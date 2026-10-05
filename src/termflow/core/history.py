import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from termflow.storage.paths import APPDATA


def save_snapshot(data: dict) -> str:
    folder = APPDATA / "history"
    folder.mkdir(parents=True, exist_ok=True)
    data = {**data, "id": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat()}
    path = folder / f"{data['timestamp'][:10]}-{data['id']}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return str(path)


def list_history() -> list[dict]:
    folder = APPDATA / "history"
    if not folder.exists():
        return []
    records = []
    for path in folder.glob("*.json"):
        try:
            records.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda x: x.get("timestamp", ""), reverse=True)
