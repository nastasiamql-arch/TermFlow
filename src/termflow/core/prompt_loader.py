from hashlib import sha256
from pathlib import Path

from termflow.core.errors import TermFlowError


def load_prompt(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise TermFlowError(f"ไม่พบไฟล์ Prompt ต้นฉบับ: {path}")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise TermFlowError(f"ไฟล์ Prompt ว่าง: {path}")
    return text, sha256(text.encode("utf-8")).hexdigest()
