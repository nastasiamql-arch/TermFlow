from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from termflow.core.errors import TermFlowError


def load_prompt(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise TermFlowError(f"ไม่พบไฟล์ Prompt ต้นฉบับ: {path}")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise TermFlowError(f"ไฟล์ Prompt ว่าง: {path}")
    return text, sha256(text.encode("utf-8")).hexdigest()


def import_prompt_text(path: Path) -> str:
    """Extract DOCX paragraphs without rephrasing; preserve tabs and line breaks."""
    if path.suffix.lower() in {".md", ".txt"}:
        return load_prompt(path)[0]
    if path.suffix.lower() != ".docx":
        raise ValueError("รองรับ .md, .txt และ .docx")
    with ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs = []
    for paragraph in root.iter(ns + "p"):
        chunks = []
        for node in paragraph.iter():
            if node.tag == ns + "t":
                chunks.append(node.text or "")
            elif node.tag == ns + "tab":
                chunks.append("\t")
            elif node.tag in {ns + "br", ns + "cr"}:
                chunks.append("\n")
        paragraphs.append("".join(chunks))
    text = "\n".join(paragraphs)
    if not text.strip():
        raise ValueError("ไฟล์ Prompt ว่าง")
    return text
