from __future__ import annotations

from pathlib import Path
from typing import Any

from cache import cache
from config import BASE_DIR, Config, ensure_data_dirs
from runtime_state import runtime_state
from tools import detect_privacy


MAX_RESUME_PDF_BYTES = 8 * 1024 * 1024


def upload_pdf(filename: str, content: bytes) -> dict[str, Any]:
    if not filename.lower().endswith(".pdf"):
        raise ValueError("仅支持 PDF 简历")
    if len(content) > MAX_RESUME_PDF_BYTES:
        raise ValueError("PDF 文件不能超过 8MB")
    ensure_data_dirs()
    Path(Config.original_resume_pdf_name).write_bytes(content)
    extracted = extract_pdf_text(Path(Config.original_resume_pdf_name))
    Path(Config.extracted_resume_name).write_text(extracted, encoding="utf-8")
    markdown = normalize_markdown(extracted)
    Path(Config.resume_name).write_text(markdown, encoding="utf-8")
    cache.load()
    generate_resume_image()
    runtime_state.log("PDF 简历已上传并提取")
    return get_resume()


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf 依赖，请先执行 pip install -r requirements.txt") from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text.strip())
    extracted = "\n\n".join(parts).strip()
    if not extracted:
        raise ValueError("未能从 PDF 提取文字，请确认不是扫描件，或手动填写简历内容")
    return extracted


def normalize_markdown(text: str) -> str:
    cleaned_lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(cleaned_lines).strip()
    if cleaned.startswith("#"):
        return cleaned + "\n"
    return "# 我的简历\n\n" + cleaned + "\n"


def generate_resume_image() -> None:
    pdf_path = Path(Config.original_resume_pdf_name)
    jpg_path = Path(str(Config.resume_image_path))
    jpg_path = jpg_path if jpg_path.is_absolute() else BASE_DIR / jpg_path
    if not pdf_path.exists():
        runtime_state.log(f"PDF 不存在，跳过生成简历图片: {pdf_path}")
        return
    try:
        import fitz
    except ImportError:
        runtime_state.log("缺少 PyMuPDF 依赖，跳过简历图片生成", source="error")
        return
    jpg_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    pix.save(str(jpg_path))
    doc.close()
    runtime_state.log(f"简历图片已生成: {jpg_path}")


def save_resume(markdown: str) -> dict[str, Any]:
    cache.save_resume(markdown)
    return get_resume()


def get_resume() -> dict[str, Any]:
    extracted_path = Path(Config.extracted_resume_name)
    resume_text = cache.resume
    extracted = extracted_path.read_text(encoding="utf-8") if extracted_path.exists() else ""
    privacy = detect_privacy(resume_text)
    return {
        "markdown": resume_text,
        "extracted_text": extracted,
        "status": cache.status(),
        "privacy_findings": privacy,
    }
