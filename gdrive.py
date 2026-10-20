"""Google Drive backups, started by the user from the Cloud backup page.

Sign-in uses Google's device flow. The app shows a short code, the user enters
it at google.com/device in a new window, and the server receives the token.
That works when the app is served over plain http on a LAN, where Google
rejects redirect sign-in. The OAuth client must be of type
"TVs and Limited Input devices".

The token is kept in memory only. Restarting the app signs out.
"""

import hashlib
import json
import os
import threading
import time
import traceback
import uuid

import requests

import config
from extractor import RECOVERY_NAME, clean_filename, sync_recovery_list, zip_directory

SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_FOLDER = "YotoLib backups"
CHUNK_SIZE = 8 * 1024 * 1024
MAX_ATTEMPTS = 5
RETRY_STATUS = {401, 408, 429, 500, 502, 503, 504}
TIMEOUT_SECONDS = 120

_lock = threading.Lock()
_session = None
_login = None
_job = {"id": "", "status": "idle"}


class DriveError(RuntimeError):
    """A Drive step failed. The message is safe to show to the user."""


class _Cancelled(Exception):
    pass


def client():
    """Client id, secret, and whether they come from the environment."""
    env_id = os.environ.get("YOTOLIB_GOOGLE_CLIENT_ID", "").strip()
    if env_id:
        return env_id, os.environ.get("YOTOLIB_GOOGLE_CLIENT_SECRET", "").strip(), True
    settings = config.load_config()
    return settings.get("google_client_id", ""), settings.get("google_client_secret", ""), False


def folder_name():
    return config.load_config().get("drive_folder") or DEFAULT_FOLDER


def save_settings(client_id, client_secret, folder):
    folder = (folder or "").strip()
    if not folder:
        raise DriveError("Name the Google Drive folder.")
    if "/" in folder or "\\" in folder:
        raise DriveError("Use a single folder name, without slashes.")
    changes = {"drive_folder": folder}
    if not client()[2]:
        client_id = (client_id or "").strip()
        client_secret = (client_secret or "").strip()
        changes["google_client_id"] = client_id
        if client_secret:
            changes["google_client_secret"] = client_secret
        elif not client_id:
            changes["google_client_secret"] = ""
    config.save_config(changes)


def status():
    client_id, secret, from_env = client()
    with _lock:
        session = _session
        login = _login
        job = dict(_job)
    return {
        "clientId": client_id,
        "clientFromEnv": from_env,
        "secretSet": bool(secret),
        "clientConfigured": bool(client_id and secret),
        "folderName": folder_name(),
        "connected": session is not None,
        "email": session.get("email", "") if session else "",
        "login": _public_login(login),
        "backup": _public_job(job),
    }


def _public_login(login):
    if not login:
        return None
    return {
        "status": login["status"],
        "userCode": login["user_code"],
        "verificationUrl": login["verification_url"],
        "expiresIn": max(0, int(login["expires_at"] - time.time())),
        "error": login.get("error", ""),
    }


def _public_job(job):
    return {
        "status": job.get("status") or "idle",
        "total": job.get("total", 0),
        "finished": job.get("finished", 0),
        "uploaded": job.get("uploaded", 0),
        "skipped": job.get("skipped", 0),
        "message": job.get("message", ""),
        "error": job.get("error", ""),
    }


def _error_text(response, fallback="Google Drive request failed."):
    if response is None:
        return "Google could not be reached."
    try:
        data = response.json()
    except ValueError:
        return f"{fallback} (HTTP {response.status_code})"
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        return error.get("message") or fallback
    if isinstance(error, str):
        return data.get("error_description") or error
    return fallback


# Sign-in


def start_login():
    """Ask Google for a device code and wait for the user in the background."""
    global _login
    client_id, secret, _from_env = client()
    if not client_id or not secret:
        raise DriveError("Save the Google client id and secret first.")
    try:
        response = requests.post(DEVICE_URL, data={"client_id": client_id, "scope": SCOPE}, timeout=30)
    except requests.RequestException as ex:
        raise DriveError("Google could not be reached.") from ex
    if not response.ok:
        text = _error_text(response, "Google refused the sign-in.")
        if "client" in text.lower():
            text += " Use an OAuth client of type TVs and Limited Input devices."
        raise DriveError(text)
    data = response.json()
    login = {
        "id": uuid.uuid4().hex,
        "device_code": data["device_code"],
        "user_code": data["user_code"],
        "verification_url": data.get("verification_url") or data.get("verification_uri") or "https://www.google.com/device",
        "expires_at": time.time() + int(data.get("expires_in") or 1800),
        "interval": int(data.get("interval") or 5),
        "status": "pending",
    }
    with _lock:
        _login = login
    threading.Thread(target=_poll_login, args=(login, client_id, secret), daemon=True).start()
    return _public_login(login)


def _finish_login(login, status, error=""):
    with _lock:
        if _login is login:
            login["status"] = status
            login["error"] = error


def _poll_login(login, client_id, secret):
    global _session
    while True:
        with _lock:
            if _login is not login or login["status"] != "pending":
                return
            interval = login["interval"]
        if time.time() > login["expires_at"]:
            _finish_login(login, "expired", "The code expired. Sign in again.")
            return
        time.sleep(interval)
        try:
            response = requests.post(TOKEN_URL, data={
                "client_id": client_id,
                "client_secret": secret,
                "device_code": login["device_code"],
                "grant_type": DEVICE_GRANT,
            }, timeout=30)
            data = response.json()
        except (requests.RequestException, ValueError):
            continue
        if response.ok and data.get("access_token"):
            session = {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", ""),
                "expires_at": time.time() + int(data.get("expires_in") or 3600),
                "email": _fetch_email(data["access_token"]),
            }
            with _lock:
                if _login is not login:
                    return
                _session = session
                login["status"] = "done"
            return
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            with _lock:
                login["interval"] += 5
            continue
        if error == "access_denied":
            _finish_login(login, "denied", "Google sign-in was cancelled.")
        elif error == "expired_token":
            _finish_login(login, "expired", "The code expired. Sign in again.")
        else:
            _finish_login(login, "error", _error_text(response, "Google sign-in failed."))
        return


def _fetch_email(token):
    try:
        response = requests.get(
            ABOUT_URL,
            params={"fields": "user(emailAddress)"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.ok:
            return (response.json().get("user") or {}).get("emailAddress", "")
    except (requests.RequestException, ValueError):
        pass
    return ""


def cancel_login():
    global _login
    with _lock:
        _login = None


def sign_out():
    global _session, _login
    with _lock:
        session = _session
        _session = None
        _login = None
    if session:
        token = session.get("refresh_token") or session.get("access_token")
        try:
            requests.post(REVOKE_URL, data={"token": token}, timeout=15)
        except requests.RequestException:
            pass


def _access_token(force_refresh=False):
    global _session
    with _lock:
        session = _session
    if session is None:
        raise DriveError("Sign in to Google Drive first.")
    if not force_refresh and session["expires_at"] - 60 > time.time():
        return session["access_token"]
    client_id, secret, _from_env = client()
    if not session.get("refresh_token"):
        raise DriveError("Google Drive sign-in expired. Sign in again.")
    try:
        response = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": secret,
            "refresh_token": session["refresh_token"],
            "grant_type": "refresh_token",
        }, timeout=30)
    except requests.RequestException as ex:
        raise DriveError("Google could not be reached.") from ex
    if not response.ok:
        if response.status_code in (400, 401):
            with _lock:
                if _session is session:
                    _session = None
            raise DriveError("Google Drive sign-in expired. Sign in again.")
        raise DriveError(_error_text(response))
    data = response.json()
    with _lock:
        session["access_token"] = data["access_token"]
        session["expires_at"] = time.time() + int(data.get("expires_in") or 3600)
    return session["access_token"]


def _api(method, url, **kwargs):
    """Call the Drive API with the session token, refreshing it once on 401."""
    headers = dict(kwargs.pop("headers", None) or {})
    for attempt in range(2):
        headers["Authorization"] = f"Bearer {_access_token(force_refresh=attempt > 0)}"
        try:
            response = requests.request(method, url, headers=headers, timeout=TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException as ex:
            raise DriveError("Google Drive could not be reached.") from ex
        if response.status_code != 401:
            break
    if not response.ok:
        raise DriveError(_error_text(response))
    return response


# Drive files


def _quote(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _find_or_create_folder(name):
    """The app only sees folders it created (drive.file), so a match is ours."""
    query = f"mimeType='{FOLDER_MIME}' and name='{_quote(name)}' and trashed=false"
    found = _api("GET", FILES_URL, params={
        "q": query,
        "fields": "files(id)",
        "orderBy": "createdTime",
        "pageSize": 1,
    }).json().get("files") or []
    if found:
        return found[0]["id"]
    created = _api("POST", FILES_URL, params={"fields": "id"}, json={
        "name": name,
        "mimeType": FOLDER_MIME,
    })
    return created.json()["id"]


def _list_folder(folder_id):
    files = []
    token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,appProperties)",
            "pageSize": 1000,
        }
        if token:
            params["pageToken"] = token
        data = _api("GET", FILES_URL, params=params).json()
        files.extend(data.get("files") or [])
        token = data.get("nextPageToken")
        if not token:
            return files


def _put_chunk(session_url, chunk, content_range):
    try:
        response = requests.put(session_url, data=chunk, headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Range": content_range,
        }, timeout=TIMEOUT_SECONDS)
    except requests.RequestException:
        return None
    if response.status_code == 401:
        _access_token(force_refresh=True)
    return response


def _next_offset(response):
    """Bytes Google has stored, from the Range header on a 308 reply."""
    received = response.headers.get("Range", "")
    if not received:
        return 0
    return int(received.rsplit("-", 1)[-1]) + 1


def _upload(path, name, folder_id, file_id, app_properties, mime, on_progress=None):
    """Resumable upload. Replaces file_id when given, else creates a file."""
    size = os.path.getsize(path)
    metadata = {"name": name, "appProperties": app_properties}
    if file_id:
        method, url = "PATCH", f"{UPLOAD_URL}/{file_id}"
    else:
        method, url = "POST", UPLOAD_URL
        metadata["parents"] = [folder_id]
        metadata["mimeType"] = mime
    started = _api(method, url, params={"uploadType": "resumable", "fields": "id"}, json=metadata, headers={
        "X-Upload-Content-Type": mime,
        "X-Upload-Content-Length": str(size),
    })
    session_url = started.headers["Location"]
    offset = 0
    failures = 0
    with open(path, "rb") as handle:
        while True:
            handle.seek(offset)
            chunk = handle.read(CHUNK_SIZE)
            if chunk:
                content_range = f"bytes {offset}-{offset + len(chunk) - 1}/{size}"
            else:
                content_range = f"bytes */{size}"
            response = _put_chunk(session_url, chunk, content_range)
            if response is not None and response.status_code in (200, 201):
                return response.json()["id"]
            if response is not None and response.status_code == 308:
                offset = _next_offset(response)
                failures = 0
                if on_progress:
                    on_progress(offset, size)
                continue
            failures += 1
            if failures > MAX_ATTEMPTS or (response is not None and response.status_code not in RETRY_STATUS):
                raise DriveError(f"Upload of {name} failed: {_error_text(response)}")
            time.sleep(min(2 ** failures, 30))
            probe = _put_chunk(session_url, b"", f"bytes */{size}")
            if probe is not None and probe.status_code in (200, 201):
                return probe.json()["id"]
            if probe is not None and probe.status_code == 308:
                offset = _next_offset(probe)


# Backup


def _library_cards(library_dir):
    cards = []
    if not os.path.isdir(library_dir):
        return cards
    for name in os.listdir(library_dir):
        if name.startswith("."):
            continue
        folder = os.path.join(library_dir, name)
        path = os.path.join(folder, "card.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and meta.get("cardId"):
            cards.append((folder, meta))
    cards.sort(key=lambda item: str(item[1].get("title") or item[1]["cardId"]).casefold())
    return cards


def _fingerprint(folder):
    """Changes when any file in the card folder is added, removed, or rewritten."""
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(current, name)
            info = os.stat(full)
            digest.update(f"{os.path.relpath(full, folder)}\0{info.st_size}\0{info.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _zip_name(meta):
    category = clean_filename(meta.get("category") or "card") or "card"
    title = clean_filename(meta.get("title") or meta["cardId"]) or meta["cardId"]
    marker = "[DEMO]" if meta.get("demo") else ""
    return f"{category} - {title}{marker}[{meta['cardId']}].zip"


def backup_running():
    with _lock:
        return _job.get("status") == "running"


def start_backup():
    global _job
    with _lock:
        if _session is None:
            raise DriveError("Sign in to Google Drive first.")
        if _job.get("status") == "running":
            raise DriveError("A Google Drive backup is already running.")
        _job = {
            "id": uuid.uuid4().hex,
            "status": "running",
            "total": 0,
            "finished": 0,
            "uploaded": 0,
            "skipped": 0,
            "message": "Starting Google Drive backup.",
            "error": "",
            "cancel": False,
        }
        job = _job
    threading.Thread(target=_run_backup, args=(job,), daemon=True).start()
    return _public_job(job)


def cancel_backup():
    with _lock:
        if _job.get("status") == "running":
            _job["cancel"] = True


def _update(job, **fields):
    with _lock:
        if job.get("cancel"):
            raise _Cancelled()
        job.update(fields)


def _run_backup(job):
    try:
        summary = _backup(job)
    except _Cancelled:
        status, message, error = "cancelled", "Backup stopped. Cards uploaded so far are on Google Drive.", ""
    except DriveError as ex:
        status, message, error = "error", "", str(ex)
    except OSError as ex:
        status, message, error = "error", "", f"Google Drive backup failed: {ex}"
    except Exception:
        traceback.print_exc()
        status, message, error = "error", "", "Google Drive backup failed. See the app log."
    else:
        status, message, error = "done", summary, ""
    with _lock:
        job.update(status=status, message=message, error=error)


def _backup(job):
    settings = config.load_config()
    library_dir = settings["library_dir"]
    backup_dir = settings["backup_dir"]
    os.makedirs(backup_dir, exist_ok=True)
    sync_recovery_list(library_dir, backup_dir)

    folder = folder_name()
    _update(job, message=f"Opening {folder} on Google Drive.")
    folder_id = _find_or_create_folder(folder)
    existing = _list_folder(folder_id)
    by_card = {}
    recovery_id = None
    for item in existing:
        props = item.get("appProperties") or {}
        if props.get("yotolibCard"):
            by_card[props["yotolibCard"]] = item
        elif item.get("name") == RECOVERY_NAME:
            recovery_id = item["id"]

    cards = _library_cards(library_dir)
    total = len(cards)
    _update(job, total=total)
    for index, (card_folder, meta) in enumerate(cards):
        card_id = meta["cardId"]
        title = str(meta.get("title") or card_id)
        fingerprint = _fingerprint(card_folder)
        prior = by_card.get(card_id)
        if prior and (prior.get("appProperties") or {}).get("yotolibFingerprint") == fingerprint:
            _update(job, finished=index + 1, skipped=job["skipped"] + 1, message=f"{title} is already on Google Drive.")
            continue
        _update(job, message=f"Zipping {title}")
        staging = os.path.join(backup_dir, f".drive-{card_id}.zip.part")
        try:
            zip_directory(card_folder, staging)

            def progress(sent, size, title=title):
                percent = int(sent * 100 / size) if size else 100
                _update(job, message=f"Uploading {title} ({percent}%)")

            _update(job, message=f"Uploading {title}")
            _upload(
                staging,
                _zip_name(meta),
                folder_id,
                prior["id"] if prior else None,
                {"yotolibCard": card_id, "yotolibFingerprint": fingerprint},
                "application/zip",
                progress,
            )
        finally:
            if os.path.exists(staging):
                os.remove(staging)
        _update(job, finished=index + 1, uploaded=job["uploaded"] + 1, message=f"Uploaded {title}")

    _update(job, message="Uploading recovery.json")
    _upload(
        os.path.join(backup_dir, RECOVERY_NAME),
        RECOVERY_NAME,
        folder_id,
        recovery_id,
        {},
        "application/json",
    )
    uploaded = job["uploaded"]
    skipped = job["skipped"]
    summary = f"Uploaded {uploaded} {'card' if uploaded == 1 else 'cards'} to {folder} on Google Drive."
    if skipped:
        summary += f" {skipped} {'was' if skipped == 1 else 'were'} already up to date."
    return summary
