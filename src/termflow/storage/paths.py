import os
from pathlib import Path

APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "TermFlow"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TermFlow"
PROMPTS = Path(__file__).resolve().parents[3] / "prompts"
