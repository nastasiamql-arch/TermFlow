import hashlib
from pathlib import Path
from threading import Event

import httpx


def download(url: str, destination: Path, progress=None, expected_sha256: str | None = None, cancelled: Event | None = None) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            done = 0
            with temp.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 128):
                    if cancelled and cancelled.is_set():
                        raise InterruptedError("Download cancelled")
                    output.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        value = digest.hexdigest()
        if done == 0:
            raise ValueError("Downloaded installer is empty")
        if total and done != total:
            raise ValueError(f"Downloaded file size mismatch: expected {total} bytes, received {done}")
        if expected_sha256 and value.lower() != expected_sha256.lower():
            raise ValueError("SHA-256 checksum mismatch")
        temp.replace(destination)
        return value
    except Exception:
        temp.unlink(missing_ok=True)
        raise
