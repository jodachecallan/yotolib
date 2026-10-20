"""Library and backup folders, and Google Drive settings, stored in config.json."""

import json
import os
import sys

CONFIG_NAME = "config.json"
DRIVE_KEYS = ("drive_folder", "google_client_id", "google_client_secret")


def install_dir():
    """Writable directory: next to the executable when frozen, else next to this file."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Where config.json, the library, and backups live.

    YOTOLIB_DATA_DIR points this at a mounted volume in a container.
    Unset, it stays next to the app.
    """
    raw = os.environ.get("YOTOLIB_DATA_DIR", "").strip()
    if raw:
        return os.path.abspath(os.path.expanduser(raw))
    return install_dir()


def resource_dir():
    """Bundled files. PyInstaller unpacks these into a temp folder."""
    return getattr(sys, "_MEIPASS", install_dir())


def config_path():
    return os.path.join(data_dir(), CONFIG_NAME)


def default_config():
    root = data_dir()
    return {
        "library_dir": os.path.join(root, "library"),
        "backup_dir": os.path.join(root, "backups"),
    }


def resolve_dir(path):
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ValueError("Choose a folder.")
    if not os.path.isabs(path):
        path = os.path.join(data_dir(), path)
    return os.path.abspath(path)


def _stored_config():
    path = config_path()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        stored = json.load(handle)
    return stored if isinstance(stored, dict) else {}


def load_config():
    config = default_config()
    stored = _stored_config()
    for key in ("library_dir", "backup_dir"):
        if stored.get(key):
            config[key] = resolve_dir(stored[key])
    for key in DRIVE_KEYS:
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            config[key] = value.strip()
    return config


def save_config(changes):
    """Merge changes into config.json. A key set to "" or None is removed."""
    path = config_path()
    stored = _stored_config()
    for key, value in changes.items():
        if value:
            stored[key] = value
        else:
            stored.pop(key, None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Owner-only: the file can hold the Google client secret.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(stored, handle, indent=2)
        handle.write("\n")
    if os.name == "posix":
        os.chmod(path, 0o600)
