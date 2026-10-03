"""Resume file -> plain text. Stdlib, plus pypdf when installed (optional, requirements.txt). Owner: D.

    read(path) -> str
        .txt/.md as UTF-8; .docx via zipfile + word/document.xml; .pdf via pypdf.
        Raises ValueError with a user-facing reason (unsupported type, no text layer, pypdf missing).
"""
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SUFFIXES = (".txt", ".md", ".docx", ".pdf")


def _plain(path):
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # User file boundary: Windows editors often save cp1252
        try:
            return path.read_text(encoding="cp1252")
        except UnicodeDecodeError:
            raise ValueError("cannot read the text (not UTF-8 or Windows-1252); paste the text") from None


def _docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except zipfile.BadZipFile:
        raise ValueError("not a valid .docx") from None
    except KeyError:
        raise ValueError("not a valid .docx (no word/document.xml)") from None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise ValueError("not a valid .docx (unreadable document.xml)") from None
    lines = []
    for p in root.iter(f"{{{W}}}p"):
        lines.append("".join(t.text or "" for t in p.iter(f"{{{W}}}t")))
    return "\n".join(lines)


def _pdf(path):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise ValueError("PDF needs pypdf (pip install -r requirements.txt); or paste the text") from None
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except PdfReadError:
        raise ValueError("not a valid .pdf") from None
    if not text.strip():
        raise ValueError("PDF has no text layer (scanned?); paste the text")
    return text


def read(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError(f"unsupported resume type {suffix or '(none)'}; use .txt .md .docx .pdf")
    if not path.is_file():
        raise ValueError(f"resume file {path} not found")
    if suffix == ".docx":
        text = _docx(path)
    elif suffix == ".pdf":
        text = _pdf(path)
    else:
        text = _plain(path)
    text = text.strip()
    if not text:
        raise ValueError("resume is empty")
    return text
