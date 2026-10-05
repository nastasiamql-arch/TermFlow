import os
import shutil
import subprocess
from pathlib import Path


def launch_installer(path: Path) -> None:
    """Launch the interactive installer only after this app process exits.

    Starting Setup directly races with QApplication.quit(): Inno Setup can see
    TermFlow.exe as still running and fail to close the executable it must
    replace. A small Windows PowerShell process waits for our PID, then starts
    the normal visible installer; it never installs silently.
    """
    powershell = shutil.which("powershell.exe") or "powershell.exe"
    installer = str(path.resolve()).replace("'", "''")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f"$installer = '{installer}'; "
        "try { "
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
        "if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'Installer file was not found.' }; "
        "Start-Process -FilePath $installer -WindowStyle Normal -ErrorAction Stop | Out-Null "
        "} catch { "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.MessageBox]::Show("
        "('TermFlow could not open the installer: ' + $_.Exception.Message + "
        "[Environment]::NewLine + [Environment]::NewLine + $installer), "
        "'TermFlow Update', [System.Windows.Forms.MessageBoxButtons]::OK, "
        "[System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null "
        "}"
    )
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen(
        [powershell, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        close_fds=True,
        creationflags=creation_flags,
    )
