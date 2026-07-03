from __future__ import annotations

import json
import queue
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import Config
from runtime_state import runtime_state


DEFAULT_MODEL_OPTIONS = {
    "temperature": 0.2,
    "top_p": 0.8,
    "num_ctx": 10240,
}

MODEL_CALL_TIMEOUT_SECONDS = 180
MODEL_MAX_RETRIES = 3

JOB_SCORE_EARLY_STOP_LABELS = {"计算职位匹配度"}


class ModelRepetitionError(RuntimeError):
    pass


def get_value(value: Any, key: str, default: Any = "") -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def message_value(response: Any, key: str, default: Any = "") -> Any:
    message = get_value(response, "message", None)
    if message is not None:
        found = get_value(message, key, None)
        if found is not None:
            return found
    return get_value(response, key, default)


def message_content(response: Any) -> str:
    return str(message_value(response, "content", "") or "")


def message_thinking(response: Any) -> str:
    for key in ("thinking", "reasoning_content", "reasoning", "reasoning_text"):
        value = message_value(response, key, "")
        if value:
            return str(value)
    return ""


def response_done(response: Any) -> bool:
    return bool(get_value(response, "done", False))


def make_ollama_client() -> Any:
    try:
        from ollama import Client
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 Python 依赖 ollama，请先运行: pip install -r requirements.txt") from exc
    return Client(host=Config.ollama_host)


def openai_chat_url() -> str:
    return Config.openai_api_base.rstrip("/") + "/chat/completions"


def ollama_chat_url() -> str:
    return Config.ollama_host.rstrip("/") + "/api/chat"


def configured_model_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "temperature": Config.model_temperature,
        "top_p": Config.model_top_p,
        "num_ctx": 10240,
        "repeat_penalty": Config.model_repeat_penalty,
        "repeat_last_n": Config.model_repeat_last_n,
        "frequency_penalty": Config.model_frequency_penalty,
        "presence_penalty": Config.model_presence_penalty,
    }
    merged.update(options or {})
    return merged


def retry_model_options(options: dict[str, Any], repetition_retry_count: int) -> dict[str, Any]:
    if repetition_retry_count <= 0:
        return dict(options)
    updated = dict(options)
    temperature = float(updated.get("temperature", Config.model_temperature))
    updated["temperature"] = max(0.1, temperature - 0.05 * repetition_retry_count)
    repeat_penalty = float(updated.get("repeat_penalty", Config.model_repeat_penalty))
    updated["repeat_penalty"] = min(1.35, repeat_penalty + 0.08 * repetition_retry_count)
    frequency_penalty = float(updated.get("frequency_penalty", Config.model_frequency_penalty))
    updated["frequency_penalty"] = min(1.0, frequency_penalty + 0.2 * repetition_retry_count)
    presence_penalty = float(updated.get("presence_penalty", Config.model_presence_penalty))
    updated["presence_penalty"] = min(0.6, presence_penalty + 0.15 * repetition_retry_count)
    return updated


def ollama_payload_options(options: dict[str, Any] | None) -> dict[str, Any]:
    options = options or {}
    allowed = {
        "temperature",
        "top_p",
        "num_ctx",
        "num_predict",
        "repeat_penalty",
        "repeat_last_n",
    }
    payload = {key: options[key] for key in allowed if key in options}
    if "max_tokens" in options and "num_predict" not in payload:
        payload["num_predict"] = options["max_tokens"]
    return payload


def openai_payload_options(options: dict[str, Any] | None) -> dict[str, Any]:
    options = options or {}
    payload: dict[str, Any] = {}
    if "temperature" in options:
        payload["temperature"] = options["temperature"]
    if "top_p" in options:
        payload["top_p"] = options["top_p"]
    if "frequency_penalty" in options:
        payload["frequency_penalty"] = options["frequency_penalty"]
    if "presence_penalty" in options:
        payload["presence_penalty"] = options["presence_penalty"]
    if "num_predict" in options:
        payload["max_tokens"] = options["num_predict"]
    if "max_tokens" in options:
        payload["max_tokens"] = options["max_tokens"]
    return payload


def unsupported_openai_parameter(payload: dict[str, Any], error_body: str) -> str:
    text = (error_body or "").lower()
    for key in ("frequency_penalty", "presence_penalty", "top_p", "temperature"):
        if key in payload and key.lower() in text:
            return key
    return ""


def should_disable_thinking(options: dict[str, Any] | None) -> bool:
    options = options or {}
    if "think" in options:
        return not bool(options["think"])
    if "disable_thinking" in options:
        return bool(options["disable_thinking"])
    return bool(Config.disable_model_thinking)


def apply_openai_thinking_control(payload: dict[str, Any], disable_thinking: bool) -> bool:
    if not disable_thinking:
        return False
    profile = str(getattr(Config, "external_model_profile", "generic"))
    if profile == "qwen":
        payload["enable_thinking"] = False
        return True
    if profile == "doubao":
        payload["thinking"] = {"type": "disabled"}
        return True
    if profile == "deepseek":
        payload["reasoning"] = {"enabled": False}
        return True
    return False


def iter_openai_chat_chunks(
    messages: list[dict[str, str]],
    model: str,
    options: dict[str, Any] | None = None,
) -> Any:
    if not Config.openai_api_key.strip():
        raise RuntimeError("OpenAI API Key 未配置")
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    payload.update(openai_payload_options(options))
    thinking_control_applied = apply_openai_thinking_control(payload, should_disable_thinking(options))
    request = Request(
        openai_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {Config.openai_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        reasoning_open = False
        with urlopen(request, timeout=MODEL_CALL_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    if reasoning_open:
                        yield "</think>"
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                message = choices[0].get("message") or {}
                reasoning = (
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("reasoning_text")
                    or message.get("reasoning_content")
                    or ""
                )
                content = delta.get("content") or message.get("content") or ""
                if reasoning:
                    if not reasoning_open:
                        yield "<think>"
                        reasoning_open = True
                    yield reasoning
                if content:
                    if reasoning_open:
                        yield "</think>"
                        reasoning_open = False
                    yield content
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if thinking_control_applied:
            runtime_state.emit(
                "model_thinking_control_retry",
                "OpenAI 模型不支持当前思考控制参数，已移除后重试",
                source="model",
            )
            retry_options = dict(options or {})
            retry_options["disable_thinking"] = False
            yield from iter_openai_chat_chunks(messages, model, retry_options)
            return
        unsupported_key = unsupported_openai_parameter(payload, body)
        if unsupported_key:
            runtime_state.emit(
                "model_parameter_fallback",
                f"OpenAI 模型不支持参数 {unsupported_key}，已移除后重试",
                source="model",
                detail={"parameter": unsupported_key, "model": model},
            )
            retry_options = dict(options or {})
            retry_options.pop(unsupported_key, None)
            yield from iter_openai_chat_chunks(messages, model, retry_options)
            return
        raise RuntimeError(f"OpenAI 请求失败: HTTP {exc.code} {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI 连接失败: {exc}") from exc


def iter_ollama_http_raw_chunks(payload: dict[str, Any]) -> Any:
    request = Request(
        ollama_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=MODEL_CALL_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama 请求失败: HTTP {exc.code} {body[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Ollama 连接失败: {exc}") from exc


def iter_ollama_chat_chunks(
    messages: list[dict[str, str]],
    model: str,
    options: dict[str, Any] | None = None,
    format_schema: dict[str, Any] | None = None,
) -> Any:
    raw_options = dict(options or DEFAULT_MODEL_OPTIONS)
    think = raw_options.pop("think", None)
    disable_thinking = should_disable_thinking(raw_options)
    request_options = ollama_payload_options(raw_options)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": request_options,
    }
    kwargs["think"] = bool(think) if think is not None else not disable_thinking
    if format_schema is not None:
        kwargs["format"] = format_schema
    def emit_chunks(payload: dict[str, Any]) -> Any:
        reasoning_open = False
        for chunk in iter_ollama_http_raw_chunks(payload):
            thinking = message_thinking(chunk)
            content = message_content(chunk)
            if thinking:
                if not reasoning_open:
                    yield "<think>"
                    reasoning_open = True
                yield thinking
            if content:
                if reasoning_open:
                    yield "</think>"
                    reasoning_open = False
                yield content
            if response_done(chunk) and reasoning_open:
                yield "</think>"
                reasoning_open = False

    try:
        yield from emit_chunks(kwargs)
    except RuntimeError as exc:
        error_text = str(exc).lower()
        if "think" not in kwargs or not ("think" in error_text or "unknown" in error_text or "400" in error_text):
            raise
        runtime_state.emit(
            "model_thinking_control_retry",
            "Ollama 不支持当前思考控制参数，已移除后重试",
            source="model",
        )
        kwargs.pop("think", None)
        yield from emit_chunks(kwargs)


def iter_model_chunks(
    messages: list[dict[str, str]],
    model: str,
    options: dict[str, Any] | None = None,
    format_schema: dict[str, Any] | None = None,
) -> Any:
    if Config.model_provider == "openai":
        yield from iter_openai_chat_chunks(messages, model, options)
        return
    yield from iter_ollama_chat_chunks(messages, model, options, format_schema)


def visible_model_text(content: str) -> str:
    text = content or ""
    if "<think>" in text:
        close_index = text.rfind("</think>")
        if close_index >= 0:
            text = text[close_index + len("</think>"):]
        else:
            text = text.split("<think>", 1)[0]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def parse_job_score_block(content: str) -> str | None:
    text = visible_model_text(content)
    if not text:
        return None

    # 优先尝试解析 JSON 格式（支持流式输出中的不完整 JSON）
    json_result = _parse_json_score(text)
    if json_result:
        return json_result

    # 回退到正则解析三行格式
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 3:
        return None
    pattern = re.compile(r"^(学历专业|技术栈|项目经验)[:：]\s*(100|[1-9]?\d)$")
    expected_order = ["学历专业", "技术栈", "项目经验"]
    normalized: list[str] = []
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if not match or match.group(1) != expected_order[index]:
            return None
        normalized.append(f"{match.group(1)}: {match.group(2)}")

    # 检查第三行是否完整输出，防止流式截断
    # 找到第三行在原始text中的起始位置，检查后面是否还有非空白字符
    third_line = lines[2]
    third_line_start = text.find(third_line)
    if third_line_start != -1:
        after_third_line = text[third_line_start + len(third_line):]
        # 如果第三行后面还有非空白字符，说明内容还在继续输出，不视为完整
        if after_third_line.strip():
            return None

    return "\n".join(normalized)


def _parse_json_score(text: str) -> str | None:
    """尝试从文本中解析 JSON 格式的岗位评分"""
    # 查找 JSON 对象开始位置
    json_start = text.find("{")
    if json_start == -1:
        return None

    # 从找到的 { 位置开始提取内容
    json_text = text[json_start:]

    # 检查是否包含完整的 JSON 对象（以 } 结尾）
    if "}" not in json_text:
        return None

    # 找到最后一个 } 的位置，确保是 JSON 对象的结束
    last_brace = json_text.rfind("}")
    if last_brace == -1:
        return None

    # 截取到最后一个 } 的内容
    json_text = json_text[:last_brace + 1]

    # 检查 JSON 对象后面是否还有非空白字符，防止截断不完整
    after_json = text[json_start + last_brace + 1:]
    if after_json.strip():
        return None

    # 尝试解析 JSON
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    # 验证 JSON 内容格式
    required_keys = ["学历专业", "技术栈", "项目经验"]
    if not all(key in data for key in required_keys):
        return None

    # 验证分数范围和类型
    for key in required_keys:
        value = data[key]
        if not isinstance(value, int) or not (0 <= value <= 100):
            return None

    # 转换为标准输出格式
    return f"学历专业: {data['学历专业']}\n技术栈: {data['技术栈']}\n项目经验: {data['项目经验']}"


def compact_model_text(value: str, limit: int = 120) -> str:
    text = visible_model_text(value)
    if not text and "<think>" in (value or ""):
        text = re.sub(r"</?think>", "", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class ModelProgressGuard:
    def __init__(self) -> None:
        self._last_chunk = ""
        self._same_chunk_count = 0
        self._last_visible_length = 0
        self._raw_since_visible_progress = 0

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", value or "")

    def feed(self, chunk: str, content: str) -> str:
        visible_text = visible_model_text(content)
        visible_length = len(self._normalize(visible_text))
        if visible_length > self._last_visible_length:
            self._last_visible_length = visible_length
            self._raw_since_visible_progress = 0
        else:
            self._raw_since_visible_progress += len(chunk or "")
            if "<think>" in (content or "") and self._raw_since_visible_progress >= 3500:
                return "思考段长时间无有效输出"

        normalized_chunk = self._normalize(chunk)
        if len(normalized_chunk) >= 8 and normalized_chunk == self._last_chunk:
            self._same_chunk_count += 1
            if self._same_chunk_count >= 5:
                return f"连续重复片段: {normalized_chunk[:40]}"
        elif normalized_chunk:
            self._last_chunk = normalized_chunk
            self._same_chunk_count = 1

        analysis_text = visible_model_text(content)
        if not analysis_text and "<think>" in (content or ""):
            analysis_text = re.sub(r"</?think>", "", content or "")
        text = self._normalize(analysis_text)
        if len(text) < 120:
            return ""

        tail = text[-700:]
        if len(tail) >= 240:
            unique_ratio = len(set(tail)) / max(1, len(tail))
            if unique_ratio < 0.06:
                return f"低信息增量: {tail[-40:]}"
        for size in range(12, 121):
            unit = tail[-size:]
            if len(set(unit)) <= 1:
                continue
            if tail.endswith(unit * 4):
                return f"尾部循环片段: {unit[:40]}"

        spaced_tail = re.sub(r"\s+", " ", analysis_text[-900:]).strip()
        parts = [part.strip() for part in re.split(r"[。！？!?；;\n，,]+", spaced_tail) if len(part.strip()) >= 20]
        if parts:
            last = parts[-1]
            if spaced_tail.count(last) >= 4:
                return f"重复句子: {last[:60]}"
        return ""


RepetitionDetector = ModelProgressGuard


class ModelChunkPrinter:
    def __init__(self, show_reasoning: bool = False) -> None:
        self._pending = ""
        self._show_reasoning = show_reasoning
        self._in_reasoning = False
        self._reasoning_notice_printed = False
        self._output_header_printed = False

    def feed(self, chunk: str) -> None:
        text = self._pending + chunk
        self._pending = ""
        out: list[str] = []
        index = 0
        markers = ("<think>", "</think>")
        while index < len(text):
            rest = text[index:]
            if rest.startswith("<think>"):
                self._in_reasoning = True
                if self._show_reasoning:
                    out.append("\n[模型思考]\n")
                elif not self._reasoning_notice_printed:
                    out.append("\n[模型] 正在推理，思考内容已隐藏...\n")
                    self._reasoning_notice_printed = True
                index += len("<think>")
                continue
            if rest.startswith("</think>"):
                self._in_reasoning = False
                if self._show_reasoning or not self._output_header_printed:
                    out.append("\n[模型输出]\n")
                    self._output_header_printed = True
                index += len("</think>")
                continue
            if text[index] == "<" and any(marker.startswith(rest) for marker in markers):
                self._pending = rest
                break
            if self._show_reasoning or not self._in_reasoning:
                out.append(text[index])
            index += 1
        if out:
            print("".join(out), end="", flush=True)

    def flush(self) -> None:
        if self._pending:
            print(self._pending, end="", flush=True)
            self._pending = ""


def stream_ollama_chat(
    label: str,
    messages: list[dict[str, str]],
    options: dict[str, Any] | None = None,
    model: str | None = None,
    format_schema: dict[str, Any] | None = None,
    early_stop: str | None = None,
) -> str:
    selected_model = model or Config.think_model
    total_attempts = MODEL_MAX_RETRIES + 1
    base_options = configured_model_options(options)
    early_stop = early_stop or ("job_score" if label in JOB_SCORE_EARLY_STOP_LABELS else None)

    def start_worker(
        result_queue: queue.Queue[tuple[str, Any]],
        stop_event: threading.Event,
        attempt_options: dict[str, Any],
    ) -> threading.Thread:
        def worker() -> None:
            try:
                for chunk in iter_model_chunks(messages, selected_model, attempt_options, format_schema):
                    if stop_event.is_set():
                        break
                    result_queue.put(("chunk", chunk))
                if not stop_event.is_set():
                    result_queue.put(("done", None))
            except Exception as exc:
                if not stop_event.is_set():
                    result_queue.put(("error", exc))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread

    def retry_message(reason: str, attempt: int, error: Any | None = None) -> None:
        retry_no = attempt
        if retry_no <= MODEL_MAX_RETRIES:
            message = f"模型调用{reason}: {label}，第 {retry_no}/{MODEL_MAX_RETRIES} 次重试"
            runtime_state.emit(
                "model_retry",
                message,
                source="model",
                level="error" if reason == "失败" else "info",
                detail={
                    "label": label,
                    "provider": Config.model_provider,
                    "model": selected_model,
                    "attempt": attempt,
                    "max_retries": MODEL_MAX_RETRIES,
                    "timeout_seconds": MODEL_CALL_TIMEOUT_SECONDS,
                    "error": str(error or ""),
                },
            )
            print(f"\n[模型] {message}", flush=True)

    def repetition_retry_message(reason: str, attempt: int, attempt_options: dict[str, Any]) -> None:
        if attempt <= MODEL_MAX_RETRIES:
            message = f"模型输出疑似重复循环: {label}，第 {attempt}/{MODEL_MAX_RETRIES} 次重试"
            runtime_state.emit(
                "model_repetition_retry",
                message,
                source="model",
                detail={
                    "label": label,
                    "provider": Config.model_provider,
                    "model": selected_model,
                    "attempt": attempt,
                    "max_retries": MODEL_MAX_RETRIES,
                    "reason": reason,
                    "options": attempt_options if Config.log_verbosity == "debug" else {},
                },
            )
            print(f"\n[模型] 模型疑似重复，正在重试 {attempt}/{MODEL_MAX_RETRIES}", flush=True)

    runtime_state.emit("model_started", f"{label} 开始", source="model")
    print(f"\n[模型] {label}", flush=True)
    print(f"[模型] provider={Config.model_provider} model={selected_model}", flush=True)

    last_error: Any = None
    show_reasoning = bool(Config.show_model_reasoning) or Config.log_verbosity == "debug"
    repetition_retry_count = 0

    for attempt in range(1, total_attempts + 1):
        attempt_options = retry_model_options(base_options, repetition_retry_count)
        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        stop_event = threading.Event()
        start_worker(result_queue, stop_event, attempt_options)
        content = ""
        guard = ModelProgressGuard()
        printer = ModelChunkPrinter(show_reasoning=show_reasoning)
        started_at = time.monotonic()
        has_chunk = False
        next_wait_notice = 10
        if attempt > 1:
            runtime_state.emit(
                "model_attempt_started",
                f"{label} 第 {attempt}/{total_attempts} 次调用开始",
                source="model",
                detail={
                    "label": label,
                    "provider": Config.model_provider,
                    "model": selected_model,
                    "attempt": attempt,
                    "total_attempts": total_attempts,
                },
            )
            print(f"\n[模型] {label} 第 {attempt}/{total_attempts} 次调用", flush=True)

        while True:
            seconds = int(time.monotonic() - started_at)
            if seconds >= MODEL_CALL_TIMEOUT_SECONDS:
                stop_event.set()
                printer.flush()
                print("", flush=True)
                last_error = TimeoutError(f"{label} 超过 {MODEL_CALL_TIMEOUT_SECONDS} 秒未完成")
                runtime_state.emit(
                    "model_timeout",
                    f"模型调用超时: {label}",
                    source="model",
                    level="error",
                    detail={
                        "label": label,
                        "provider": Config.model_provider,
                        "model": selected_model,
                        "attempt": attempt,
                        "max_retries": MODEL_MAX_RETRIES,
                        "timeout_seconds": MODEL_CALL_TIMEOUT_SECONDS,
                    },
                )
                retry_message("超时", attempt, last_error)
                break

            try:
                item_type, payload = result_queue.get(timeout=1)
            except queue.Empty:
                if seconds >= next_wait_notice:
                    message = "等待模型首个响应" if not has_chunk else "模型正在思考/生成"
                    print(f"\n[模型] {message}... {seconds}s", flush=True)
                    next_wait_notice += 10
                continue

            if item_type == "chunk":
                chunk = str(payload or "")
                if not chunk:
                    continue
                has_chunk = True
                content += chunk
                printer.feed(chunk)
                if early_stop == "job_score":
                    score_block = parse_job_score_block(content)
                    if score_block:
                        stop_event.set()
                        printer.flush()
                        print("", flush=True)
                        runtime_state.emit(
                            "model_early_stop",
                            f"岗位评分已取得标准三项评分，提前结束模型读取: {label}",
                            source="model",
                            detail={"label": label, "score_block": score_block},
                        )
                        if Config.log_verbosity != "debug":
                            print("[模型] 岗位评分已取得标准三项评分，提前结束模型读取", flush=True)
                        runtime_state.emit("model_finished", f"{label} 完成", source="model")
                        return score_block
                repetition_reason = guard.feed(chunk, content)
                if repetition_reason:
                    stop_event.set()
                    printer.flush()
                    print("", flush=True)
                    last_error = ModelRepetitionError(repetition_reason)
                    runtime_state.emit(
                        "model_repetition_detected",
                        f"模型输出疑似重复循环: {label}",
                        source="model",
                        level="error",
                        detail={
                            "label": label,
                            "provider": Config.model_provider,
                            "model": selected_model,
                            "attempt": attempt,
                            "reason": repetition_reason,
                            "preview": compact_model_text(content),
                        },
                    )
                    repetition_retry_count += 1
                    repetition_retry_message(repetition_reason, attempt, attempt_options)
                    break
                continue

            if item_type == "error":
                printer.flush()
                print("", flush=True)
                last_error = payload
                retry_message("失败", attempt, payload)
                break

            printer.flush()
            print("", flush=True)
            runtime_state.emit("model_finished", f"{label} 完成", source="model")
            return content

    message = f"模型调用失败: {label}，已达到最大重试次数"
    runtime_state.emit(
        "model_failed",
        f"{message}: {last_error}",
        source="model",
        level="error",
        detail={
            "label": label,
            "provider": Config.model_provider,
            "model": selected_model,
            "max_retries": MODEL_MAX_RETRIES,
            "timeout_seconds": MODEL_CALL_TIMEOUT_SECONDS,
            "error": str(last_error or ""),
        },
    )
    print(f"\n[模型] {message}", flush=True)
    raise RuntimeError(f"{message}: {last_error}")
