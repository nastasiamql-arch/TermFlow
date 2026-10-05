import os
import sys
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "TermFlow"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TermFlow"

def _prompt_candidates() -> list[Path]:
    """Return source and frozen-app locations that may contain bundled prompts."""
    candidates: list[Path] = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir) / "prompts")

    module_path = Path(__file__).resolve()
    # In a source checkout this is the repository root. In a frozen app, the
    # PyInstaller bundle directory is handled above.
    candidates.extend(parent / "prompts" for parent in module_path.parents)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "prompts")

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_prompts_dir() -> Path:
    """Find bundled prompt files in source, PyInstaller, or installed layouts."""
    candidates = _prompt_candidates()
    required = Path("search") / "vocab_extractor_v3.md"
    for candidate in candidates:
        if (candidate / required).is_file():
            return candidate
    # Keep a deterministic path so the normal prompt error can explain it.
    return candidates[0]


PROMPTS = resolve_prompts_dir()
