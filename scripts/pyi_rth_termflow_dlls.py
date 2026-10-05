"""Keep Windows from resolving Qt dependencies from unrelated PATH folders."""
import os
import sys
from pathlib import Path

root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
_dll_directory_handles = []
for directory in (root, root / "PySide6", root / "shiboken6"):
    if directory.is_dir():
        _dll_directory_handles.append(os.add_dll_directory(str(directory)))

clean_path = []
for entry in os.environ.get("PATH", "").split(os.pathsep):
    if not entry:
        continue
    folder = Path(entry)
    try:
        has_system_api_shims = any(folder.glob("api-ms-win-*.dll")) or any(folder.glob("ext-ms-win-*.dll"))
    except OSError:
        has_system_api_shims = False
    if not has_system_api_shims:
        clean_path.append(entry)
os.environ["PATH"] = os.pathsep.join(clean_path)
