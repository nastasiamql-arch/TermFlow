import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from termflow.storage.paths import APPDATA, PROMPTS

BUILTINS = {
    "builtin-search": ("VOCAB Extractor V3", "Search", PROMPTS / "search" / "vocab_extractor_v3.md"),
    "builtin-polish": ("Polish Glossary", "Polish", PROMPTS / "polish" / "polish_glossary.md"),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _custom_path() -> Path:
    return APPDATA / "prompts.json"


def _read_custom() -> list[dict]:
    try:
        values = json.loads(_custom_path().read_text("utf-8"))
        return [x for x in values if x.get("is_builtin") is False]
    except (OSError, ValueError, TypeError):
        return []


def _write_custom(values: list[dict]) -> None:
    path = _custom_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def list_prompts() -> list[dict]:
    builtins = []
    for prompt_id, (name, category, path) in BUILTINS.items():
        text = path.read_bytes().decode("utf-8-sig")
        builtins.append(
            {
                "id": prompt_id,
                "name": name,
                "category": category,
                "content": text,
                "created_at": "2026-10-05T00:00:00+00:00",
                "updated_at": "2026-10-05T00:00:00+00:00",
                "is_builtin": True,
                "version": "1",
            }
        )
    return builtins + _read_custom()


def create_prompt(name: str, category: str, content: str = "") -> dict:
    if category not in {"Search", "Polish"} or not name.strip():
        raise ValueError("Prompt name and valid category are required")
    now = _now()
    item = {
        "id": str(uuid4()),
        "name": name.strip(),
        "category": category,
        "content": content,
        "created_at": now,
        "updated_at": now,
        "is_builtin": False,
        "version": "1",
    }
    values = _read_custom()
    values.append(item)
    _write_custom(values)
    return item


def save_prompt(prompt_id: str, *, name: str, content: str) -> dict:
    values = _read_custom()
    for item in values:
        if item["id"] == prompt_id:
            item["name"] = name.strip()
            item["content"] = content
            item["updated_at"] = _now()
            item["version"] = str(int(item.get("version", "1")) + 1)
            _write_custom(values)
            return item
    raise KeyError(prompt_id)


def delete_prompt(prompt_id: str) -> None:
    _write_custom([x for x in _read_custom() if x["id"] != prompt_id])
