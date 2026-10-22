"""Select Chinese novel chapters from a directory without modifying source files."""
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChapterFile:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


def _natural_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.stem.casefold())
    key = tuple((0, int(part)) if part.isdecimal() else (1, part) for part in parts)
    return (key, path.name.casefold())


def find_chapters(folder: Path) -> list[ChapterFile]:
    """List only immediate TXT/MD chapter files, sorted by chapter number."""
    if not folder.is_dir():
        raise ValueError(f"Not a readable directory: {folder}")
    files = [
        p for p in folder.iterdir()
        if p.is_file() and (p.suffix.lower() in {".txt", ".md"} or (not p.suffix and p.name.isdecimal()))
    ]
    return [ChapterFile(p) for p in sorted(files, key=_natural_key)]


def join_chapters(chapters: list[ChapterFile]) -> str:
    """Keep every selected chapter intact and mark chapter boundaries."""
    if not chapters:
        raise ValueError("ยังไม่ได้เลือกบทนิยาย")
    parts: list[str] = []
    for chapter in chapters:
        try:
            text = chapter.path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"อ่านบท {chapter.name} ไม่สำเร็จ: {exc}") from exc
        if not text.strip():
            raise ValueError(f"ไฟล์บท {chapter.name} ว่างเปล่า")
        parts.append(f"===== SOURCE FILE: {chapter.name} =====\n{text}")
    return "\n\n".join(parts)
