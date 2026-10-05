import subprocess
from pathlib import Path


def launch_installer(path: Path) -> None:
    # Inno Setup displays its normal interactive confirmation and wizard.
    subprocess.Popen([str(path)], close_fds=True)
