"""Local reuse of strictly validated responses; never stores credentials."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from termflow.storage.paths import LOCAL

CACHE_VERSION = 1


def cache_key(request, provider) -> str:
    request_values = request.model_dump()
    request_values.pop("reuse_result", None)
    values = {"schema": CACHE_VERSION, "request": request_values,
              "provider": provider.kind, "model": provider.model, "base_url": provider.base_url}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cache_path(key: str) -> Path:
    return LOCAL / "result-cache" / f"{key}.json"


def read_result(key: str) -> str | None:
    try:
        value = json.loads(cache_path(key).read_text("utf-8"))
        return value["raw"] if isinstance(value.get("raw"), str) else None
    except (OSError, ValueError, TypeError):
        return None


def write_result(key: str, raw: str) -> None:
    path = cache_path(key)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps({"raw": raw}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # Cache availability must not turn a successful run into a failure.
    finally:
        temporary.unlink(missing_ok=True)
