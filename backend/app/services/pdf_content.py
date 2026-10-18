"""PDF 页面文字提取；无文字页面使用本地 Tesseract OCR。"""

from io import BytesIO
import os
from pathlib import Path
from shutil import which
from subprocess import CalledProcessError, TimeoutExpired, run
from tempfile import TemporaryDirectory

import pdfplumber

from app.config import settings
from app.schemas.content_review import ContentParagraph


MAX_PDF_PAGES = 60
MAX_PDF_PARAGRAPHS = 5000
MAX_PDF_CHARS = 100000


def extract_pdf(content: bytes) -> dict:
    """返回页面映射与连续原文；OCR 失败不将空白页报告为已审查。"""
    if not content.startswith(b"%PDF-"):
        raise ValueError("请上传有效的 PDF 文件")
    paragraphs: list[dict] = []
    total_chars = 0
    ocr_pages: list[int] = []
    with pdfplumber.open(BytesIO(content)) as pdf:
        if not pdf.pages or len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF 最多支持 {MAX_PDF_PAGES} 页")
        for page_number, page in enumerate(pdf.pages, 1):
            text = page.extract_text(layout=False) or ""
            if not text.strip():
                width = float(getattr(page, "width", 0) or 0)
                height = float(getattr(page, "height", 0) or 0)
                if width > 2000 or height > 2000 or width * height > 2_000_000:
                    raise ValueError(f"第 {page_number} 页尺寸过大，无法安全执行本地 OCR")
                text = _ocr_page(content, page_number)
                ocr_pages.append(page_number)
            for line in text.splitlines():
                normalized = line.strip()
                if normalized:
                    paragraphs.append({"index": len(paragraphs), "text": normalized, "page_number": page_number})
                    total_chars += len(normalized)
                    if len(paragraphs) > MAX_PDF_PARAGRAPHS or total_chars > MAX_PDF_CHARS:
                        raise ValueError("PDF 提取内容过长，请拆分文档后上传")
        if not paragraphs:
            raise ValueError("PDF 没有可审查文字")
        return {"page_count": len(pdf.pages), "ocr_pages": ocr_pages, "paragraphs": paragraphs}


def _ocr_page(content: bytes, page_number: int) -> str:
    renderer = which(settings.pdftoppm_command)
    engine = which(settings.tesseract_command)
    if not engine and os.name == "nt" and settings.tesseract_command == "tesseract":
        candidate = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe"
        if candidate.is_file():
            engine = str(candidate)
    if not renderer or not engine:
        raise ValueError("扫描 PDF 需要本地安装 Poppler 和 Tesseract（含简体中文语言包），并配置 PDFTOPPM_COMMAND、TESSERACT_COMMAND")
    tessdata = settings.tessdata_dir
    if not tessdata and os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "SmartFormatOCR" / "tessdata"
        if local.is_dir() and (local / "chi_sim.traineddata").is_file():
            tessdata = str(local)
    try:
        with TemporaryDirectory(prefix="sf-pdf-ocr-") as folder:
            source = Path(folder) / "source.pdf"
            image = Path(folder) / "page.png"
            source.write_bytes(content)
            run([renderer, "-f", str(page_number), "-l", str(page_number), "-r", "300", "-singlefile", "-png", str(source), str(image.with_suffix(""))], check=True, capture_output=True, timeout=45)
            command = [engine, str(image), "stdout", "-l", "chi_sim+eng", "--psm", "6"]
            if tessdata:
                command.extend(["--tessdata-dir", tessdata])
            result = run(command, check=True, capture_output=True, timeout=45)
            text = result.stdout.decode("utf-8", errors="replace")
            if not text.strip():
                raise ValueError(f"第 {page_number} 页 OCR 未识别出文字，请检查扫描质量")
            return text
    except (CalledProcessError, TimeoutExpired) as exc:
        raise ValueError(f"第 {page_number} 页 OCR 失败或超时，请检查本地 OCR 配置") from exc


def paragraphs_from_pdf(cache: dict) -> list[ContentParagraph]:
    return [ContentParagraph(index=item["index"], text=item["text"]) for item in cache.get("paragraphs", [])]


def page_map_from_pdf(cache: dict | None) -> list[int] | None:
    return [item["page_number"] for item in cache.get("paragraphs", [])] if cache else None
