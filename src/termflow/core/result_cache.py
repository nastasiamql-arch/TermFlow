"""Small exact-identity cache for validated generation results."""

import json
import os
from hashlib import sha256
from pathlib import Path

from termflow.storage.paths import APPDATA

CACHE_VERSION = 1


def cache_key(*, workflow: str, provider: str, base_url: str, model: str, prompt: str,
              source: str = "", vocab: str = "", user_input: str = "", validator_version: str = "1") -> str:
    identity = {
        "cache_schema": CACHE_VERSION,
        "workflow": workflow,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "source_sha256": sha256(source.encode("utf-8")).hexdigest(),
        "vocab_sha256": sha256(vocab.encode("utf-8")).hexdigest(),
        "user_input_sha256": sha256(user_input.encode("utf-8")).hexdigest(),
        "validator_version": validator_version,
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


class ResultCache:
    def __init__(self, path: Path | None = None):
        self.path = path or APPDATA / "result_cache.json"

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def get(self, key: str, validator) -> str | None:
        raw = self._read().get(key)
        if not isinstance(raw, str):
            return None
        try:
            validator(raw)
        except Exception:
            self.delete(key)
            return None
        return raw

    def put(self, key: str, raw: str, validator) -> bool:
        try:
            validator(raw)
        except Exception:
            return False
        try:
            values = self._read()
            values[key] = raw
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
            return True
        except OSError:
            return False

    def delete(self, key: str) -> None:
        values = self._read()
        if key in values:
            del values[key]
            try:
                self.path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
