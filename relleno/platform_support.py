"""Small operating-system integrations shared by the desktop client."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


IS_WINDOWS = os.name == "nt"


def data_root() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RellenoCliente"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "RellenoCliente"


def desktop_path() -> Path:
    if IS_WINDOWS:
        return Path.home() / "Desktop"
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "user-dirs.dirs"
    if config.is_file():
        for line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                return Path(value).expanduser()
    for name in ("Escritorio", "Desktop"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return Path.home()


def open_path(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(str(path))
        return
    subprocess.Popen(
        ["xdg-open", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def browser_launch_kwargs(headless: bool = False) -> dict:
    if IS_WINDOWS:
        return {"channel": "msedge", "headless": headless}
    configured = os.environ.get("RELLENO_CHROMIUM", "").strip()
    executable = configured or next(
        (path for name in ("google-chrome-stable", "chromium", "google-chrome") if (path := shutil.which(name))),
        "",
    )
    if not executable:
        raise RuntimeError("Instale chromium o google-chrome para consultar HikCentral.")
    return {"executable_path": executable, "headless": headless}


def worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--agent-worker"]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "main.py"), "--agent-worker"]


def detached_process_kwargs() -> dict:
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "close_fds": True}
    return {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
        "close_fds": True,
    }

