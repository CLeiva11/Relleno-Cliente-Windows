"""Configuracion administrada de HikCentral para las instalaciones del cliente."""
import os


URL = "https://127.0.0.1"
ACCOUNT = "admin"


def apply(config):
    """Fuerza el destino administrado conservando estado y huella local."""
    previous = config.get("hikcentral") or {}
    managed = previous | {"url": URL, "method": "username", "managed": True}
    changed = managed != previous
    config["hikcentral"] = managed
    return changed


def credentials():
    """Devuelve las claves incluidas durante el build, nunca desde config.json."""
    try:
        from relleno._managed_hikcentral import PASSWORDS
    except ImportError:
        PASSWORDS = tuple(
            value.strip()
            for value in os.environ.get("RELLENO_HIKCENTRAL_PASSWORDS", "").split("|")
            if value.strip()
        )
    passwords = tuple(dict.fromkeys(str(value) for value in PASSWORDS if str(value)))
    if not passwords:
        raise ValueError("Esta instalacion no incluye las credenciales administradas de HikCentral.")
    return {"method": "username", "account": ACCOUNT, "secrets": passwords}


def credential_options(values):
    passwords = values.get("secrets") or (values.get("secret"),)
    return [
        {"method": "username", "account": values["account"], "secret": password}
        for password in dict.fromkeys(passwords)
        if password
    ]
