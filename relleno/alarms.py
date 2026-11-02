"""Own the validated SDS alarm schedule without duplicating legacy tasks."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from relleno.storage import ROOT


DEFAULT_SYNC_DIR = Path(r"C:\SDSAlarmas\sync")
STATE_FILE = ROOT / "alarmas-state.json"
RETRY_SECONDS = 60 * 60


def sync_dir(config: dict) -> Path:
    configured = str((config.get("alarms") or {}).get("sync_dir") or "").strip()
    return Path(configured) if configured else DEFAULT_SYNC_DIR


def installation(config: dict) -> dict:
    folder = sync_dir(config)
    runner = folder / "EJECUTAR_SYNC_DIARIA_GENERADO.cmd"
    orchestrator = folder / "orquestador_diario.py"
    vehicles = folder / "fetch_alarmas_hikcentral.py"
    faces = folder / "fetch_alarmas_ivms_injection.py"
    centre_config = folder / "config_centro.json"
    return {
        "folder": folder,
        "runner": runner,
        "orchestrator": orchestrator,
        "vehicles": vehicles,
        "faces": faces,
        "config": centre_config,
        "ready": all(path.is_file() for path in (centre_config, runner, vehicles, faces)),
    }


def load_state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(value: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def disable_legacy_tasks(run=subprocess.run) -> list[str]:
    """Remove old schedulers; their files and configuration remain available."""
    if os.name != "nt":
        return []
    query = run(
        ["schtasks", "/Query", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        check=False,
    )
    removed = []
    for line in query.stdout.splitlines():
        name = line.split('","', 1)[0].strip().strip('"').lstrip("\\")
        if not name.casefold().startswith("sds_sync_alarmas_"):
            continue
        result = run(
            ["schtasks", "/Delete", "/TN", name, "/F"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            removed.append(name)
    return removed


def python_executable(config: dict) -> str:
    setup = installation(config)
    if setup["runner"].is_file():
        content = setup["runner"].read_text(encoding="utf-8-sig", errors="replace")
        match = re.search(r'"([^"\r\n]*python(?:w)?\.exe)"', content, flags=re.IGNORECASE)
        if match and Path(match.group(1)).is_file():
            return match.group(1)
    raise ValueError(
        "La instalación SDS no informa el Python validado. "
        "Abra una vez SDS Alarmas - Configuración y guarde el centro."
    )


def month_ranges(first: date, last: date):
    cursor = first
    while cursor <= last:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = min(last, next_month - timedelta(days=1))
        yield cursor, end
        cursor = next_month


def commands(config: dict, current: datetime) -> list[list[str]]:
    setup = installation(config)
    python = python_executable(config)
    last = current.date() - timedelta(days=1)
    first = last - timedelta(days=2)
    result = [[
        python,
        str(setup["vehicles"]),
        "--config", str(setup["config"]),
        "--dias-atras", "3",
    ]]
    for start, end in month_ranges(first, last):
        result.append([
            python,
            str(setup["faces"]),
            "--config", str(setup["config"]),
            "--from-date", start.isoformat(),
            "--to-date", end.isoformat(),
        ])
    return result


def run_now(config: dict, run=subprocess.run, now=None) -> dict:
    setup = installation(config)
    if not setup["ready"]:
        raise ValueError("No se encontró la instalación SDS Alarmas configurada en C:\\SDSAlarmas\\sync.")
    started = now or datetime.now().astimezone()
    state = load_state() | {
        "state": "running",
        "started_at": started.isoformat(timespec="seconds"),
        "message": "Extrayendo alarmas vehiculares y faciales",
    }
    save_state(state)
    try:
        results = []
        for selected in commands(config, started):
            results.append(run(
                selected,
                cwd=str(setup["folder"]),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=4 * 60 * 60,
                check=False,
            ))
        returncode = next((result.returncode for result in results if result.returncode), 0)
        finished = datetime.now().astimezone()
        state.update(
            state="completed" if returncode == 0 else "failed",
            finished_at=finished.isoformat(timespec="seconds"),
            completed_day=started.date().isoformat() if returncode == 0 else state.get("completed_day"),
            retry_after=0 if returncode == 0 else time.time() + RETRY_SECONDS,
            message=(
                "Alarmas vehiculares y faciales sincronizadas sin duplicados"
                if returncode == 0
                else f"La extracción de alarmas terminó con código {returncode}; se reintentará"
            ),
        )
        save_state(state)
        return state
    except Exception:
        state.update(
            state="failed",
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            retry_after=time.time() + RETRY_SECONDS,
            message="No se pudo iniciar la extracción de alarmas; se reintentará",
        )
        save_state(state)
        raise


class AlarmScheduler:
    def __init__(self):
        self.tasks_disabled = False
        self.worker = None

    def tick(self, config: dict, now=None) -> None:
        settings = config.get("alarms") or {}
        if not settings.get("enabled"):
            return
        setup = installation(config)
        if not setup["ready"]:
            return
        if not self.tasks_disabled:
            disable_legacy_tasks()
            self.tasks_disabled = True
        current = now or datetime.now().astimezone()
        if current.hour < int(settings.get("run_hour", 3)):
            return
        state = load_state()
        if state.get("completed_day") == current.date().isoformat():
            return
        if float(state.get("retry_after") or 0) > time.time():
            return
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(
            target=self._run_safely,
            args=(config, current),
            daemon=True,
            name="relleno-alarmas",
        )
        self.worker.start()

    @staticmethod
    def _run_safely(config: dict, current: datetime) -> None:
        try:
            run_now(config, now=current)
        except Exception:
            # run_now persists a safe status for the UI and next retry.
            return
