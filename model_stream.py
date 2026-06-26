from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config import Config
from runtime_state import runtime_state


DEFAULT_MODEL_OPTIONS = {
    "temperature": 0.6,
    "num_ctx": 10240,
}


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


def openai_payload_options(options: dict[str, Any] | None) -> dict[str, Any]:
    options = options or {}
    payload: dict[str, Any] = {}
    if "temperature" in options:
        payload["temperature"] = options["temperature"]
    if "num_predict" in options:
        payload["max_tokens"] = options["num_predict"]
    if "max_tokens" in options:
        payload["max_tokens"] = options["max_tokens"]
    return payload


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
        with urlopen(request, timeout=60) as response:
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
        with urlopen(request, timeout=300) as response:
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
    request_options = dict(options or DEFAULT_MODEL_OPTIONS)
    think = request_options.pop("think", None)
    disable_thinking = should_disable_thinking(options)
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
) -> str:
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
    selected_model = model or Config.think_model

    def worker() -> None:
        try:
            for chunk in iter_model_chunks(messages, selected_model, options or DEFAULT_MODEL_OPTIONS, format_schema):
                result_queue.put(("chunk", chunk))
            result_queue.put(("done", None))
        except Exception as exc:
            result_queue.put(("error", exc))

    runtime_state.emit("model_started", f"{label} 开始", source="model")
    print(f"\n[模型] {label}", flush=True)
    print(f"[模型] provider={Config.model_provider} model={selected_model}", flush=True)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    content = ""
    show_reasoning = bool(Config.show_model_reasoning) or Config.log_verbosity == "debug"
    printer = ModelChunkPrinter(show_reasoning=show_reasoning)
    started_at = time.monotonic()
    has_chunk = False
    next_wait_notice = 10

    while True:
        seconds = int(time.monotonic() - started_at)
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
            continue

        if item_type == "error":
            printer.flush()
            print("", flush=True)
            runtime_state.emit("model_failed", f"{label} 失败: {payload}", source="model", level="error")
            raise payload

        printer.flush()
        print("", flush=True)
        runtime_state.emit("model_finished", f"{label} 完成", source="model")
        return content
