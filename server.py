"""Local web API for the Yoto card library."""

import json
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import gdrive
from extractor import extract_urls, sync_recovery_list

_jobs_lock = threading.Lock()
_jobs = {}
_active_job_id = None


def _read_card(folder):
    path = os.path.join(folder, "card.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not data.get("cardId"):
        return None
    return data


def _track_titles(card):
    titles = []
    for chapter in card.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        if chapter.get("title"):
            titles.append(str(chapter["title"]))
        for track in chapter.get("tracks") or []:
            if isinstance(track, dict) and track.get("title"):
                titles.append(str(track["title"]))
    return titles


_ZIP_CARD_ID = re.compile(r"\[([^\[\]]+)\]\s*\(")


def _backed_up_ids(backup_dir):
    found = set()
    if not backup_dir or not os.path.isdir(backup_dir):
        return found
    try:
        names = os.listdir(backup_dir)
    except OSError:
        return found
    for name in names:
        if not name.lower().endswith(".zip"):
            continue
        match = _ZIP_CARD_ID.search(name)
        if match:
            found.add(match.group(1))
    return found


def list_cards():
    settings = config.load_config()
    library = settings["library_dir"]
    backed_up = _backed_up_ids(settings.get("backup_dir"))
    cards = []
    if not os.path.isdir(library):
        return cards
    for name in os.listdir(library):
        if name.startswith("."):
            continue
        folder = os.path.join(library, name)
        if not os.path.isdir(folder):
            continue
        try:
            card = _read_card(folder)
        except (OSError, json.JSONDecodeError):
            continue
        if card is None:
            continue
        cards.append({
            "cardId": card["cardId"],
            "title": card.get("title") or card["cardId"],
            "author": card.get("author") or "",
            "category": card.get("category"),
            "languages": card.get("languages") or [],
            "trackTitles": _track_titles(card),
            "trackCount": card.get("trackCount") or 0,
            "readableDuration": card.get("readableDuration"),
            "cover": card.get("cover"),
            "backedUp": card["cardId"] in backed_up,
        })
    cards.sort(key=lambda item: item["title"].casefold())
    return cards


def get_card(card_id):
    if os.path.basename(card_id) != card_id or card_id.startswith("."):
        return None
    folder = os.path.join(config.load_config()["library_dir"], card_id)
    if not os.path.isdir(folder):
        return None
    try:
        return _read_card(folder)
    except (OSError, json.JSONDecodeError):
        return None


def card_file(card_id, relative):
    if os.path.basename(card_id) != card_id or card_id.startswith("."):
        raise HTTPException(status_code=404)
    library = os.path.realpath(config.load_config()["library_dir"])
    root = os.path.realpath(os.path.join(library, card_id))
    if os.path.commonpath([library, root]) != library:
        raise HTTPException(status_code=404)
    target = os.path.realpath(os.path.join(root, relative))
    if os.path.commonpath([root, target]) != root or not os.path.isfile(target):
        raise HTTPException(status_code=404)
    return target


class SettingsBody(BaseModel):
    library_dir: str
    backup_dir: str


class DriveSettingsBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""
    folder_name: str


class JobBody(BaseModel):
    urls: str
    replace_existing: bool = False
    confirm_ownership: bool = False


def _apply_event(job, event):
    kind = event.get("type")
    if kind == "log":
        job["logs"].append({"level": event.get("level", "info"), "message": event.get("message", "")})
        if len(job["logs"]) > 2000:
            del job["logs"][:-2000]
    elif kind == "status":
        job["total"] = event.get("total", job["total"])
        job["finished"] = event.get("finished", job["finished"])
        job["currentUrl"] = event.get("url") or ""
    elif kind == "result":
        if event.get("status") == "ok":
            job["succeeded"].append({
                "cardId": event.get("cardId"),
                "title": event.get("title"),
                "url": event.get("url"),
                "backup": event.get("backup"),
            })
        elif event.get("status") == "skipped":
            job["skipped"].append({
                "cardId": event.get("cardId"),
                "title": event.get("title") or event.get("cardId"),
                "url": event.get("url"),
            })
        else:
            job["failed"].append({
                "url": event.get("url"),
                "error": event.get("error") or "Download failed.",
            })


def _run_job(job_id, urls, replace_existing):
    global _active_job_id
    settings = config.load_config()

    def on_event(event):
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                _apply_event(job, event)

    try:
        extract_urls(
            urls,
            settings["library_dir"],
            settings["backup_dir"],
            on_event,
            replace_existing=replace_existing,
        )
    except Exception as ex:
        on_event({"type": "log", "level": "error", "message": f"Download stopped: {ex}"})
    finally:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["currentUrl"] = ""
            if _active_job_id == job_id:
                _active_job_id = None


def _public_job(job):
    return {
        "id": job["id"],
        "status": job["status"],
        "total": job["total"],
        "finished": job["finished"],
        "currentUrl": job["currentUrl"],
        "logs": list(job["logs"]),
        "succeeded": list(job["succeeded"]),
        "skipped": list(job.get("skipped") or []),
        "failed": list(job["failed"]),
    }


@asynccontextmanager
async def lifespan(_app):
    settings = config.load_config()
    for folder in (settings["library_dir"], settings["backup_dir"]):
        try:
            os.makedirs(folder, exist_ok=True)
        except PermissionError as ex:
            raise SystemExit(
                f"YotoLib cannot write to {folder}. The app runs as user {os.getuid()}. "
                "Give that user write access to the data folder, for example: "
                "chown -R 1000:1000 <host folder>, or run the container with "
                "--user $(id -u):$(id -g), or use a named Docker volume."
            ) from ex
    try:
        sync_recovery_list(settings["library_dir"], settings["backup_dir"])
    except OSError:
        pass
    yield


DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "[::1]")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
HOST_CHECK_EXEMPT = {"/api/health"}


def allowed_hosts():
    """Host names the app answers to, from YOTOLIB_ALLOWED_HOSTS.

    Rejecting other Host headers blocks DNS rebinding, where a website points
    its own name at this app and reads the replies. "*.example.lan" matches
    subdomains. "*" turns the check off.
    """
    raw = os.environ.get("YOTOLIB_ALLOWED_HOSTS", "")
    hosts = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if not hosts:
        hosts = set(DEFAULT_ALLOWED_HOSTS)
    bind = os.environ.get("YOTOLIB_HOST", "").strip().lower()
    if bind and bind not in ("0.0.0.0", "::"):
        hosts.add(f"[{bind}]" if ":" in bind else bind)
    return hosts


def _host_name(host):
    host = host.strip().lower()
    if host.startswith("["):
        return host[:host.find("]") + 1]
    return host.rsplit(":", 1)[0]


def _host_allowed(host, hosts):
    if "*" in hosts:
        return True
    name = _host_name(host)
    if name in hosts:
        return True
    return any(item.startswith("*.") and name.endswith(item[1:]) for item in hosts)


class RequestGuard:
    """Checks the Host header, and that writes come from this app's own pages.

    Browsers send Origin and Sec-Fetch-Site on cross-site requests. A write
    from another site is refused, so a web page cannot start a backup or sign
    out. Requests without those headers (curl, scripts) are allowed.
    """

    def __init__(self, app):
        self.app = app
        self.hosts = allowed_hosts()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        host = headers.get("host", "")
        if scope["path"] not in HOST_CHECK_EXEMPT and not _host_allowed(host, self.hosts):
            response = PlainTextResponse(
                "This host name is not allowed. Add it to YOTOLIB_ALLOWED_HOSTS.",
                status_code=400,
            )
            return await response(scope, receive, send)
        if scope["method"] in UNSAFE_METHODS and _cross_site(headers, host):
            response = PlainTextResponse("Cross-site request refused.", status_code=403)
            return await response(scope, receive, send)

        async def send_with_headers(message):
            # Card files are served with the type their extension implies.
            # nosniff stops a browser from treating one as HTML or script.
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [(b"x-content-type-options", b"nosniff")]
            await send(message)

        return await self.app(scope, receive, send_with_headers)


def _cross_site(headers, host):
    if headers.get("sec-fetch-site", "") in ("cross-site", "same-site"):
        return True
    origin = headers.get("origin")
    if origin is None:
        return False
    return urlsplit(origin).netloc.lower() != host.strip().lower()


app = FastAPI(title="YotoLib", lifespan=lifespan)
app.add_middleware(RequestGuard)


def _download_running():
    with _jobs_lock:
        return _active_job_id is not None


def _public_settings(settings):
    return {"library_dir": settings["library_dir"], "backup_dir": settings["backup_dir"]}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/settings")
def read_settings():
    return _public_settings(config.load_config())


@app.put("/api/settings")
def write_settings(body: SettingsBody):
    if _download_running():
        raise HTTPException(status_code=409, detail="Wait until the current download finishes.")
    if gdrive.backup_running():
        raise HTTPException(status_code=409, detail="Wait until the Google Drive backup finishes.")
    try:
        library_dir = config.resolve_dir(body.library_dir)
        backup_dir = config.resolve_dir(body.backup_dir)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    if os.path.realpath(library_dir) == os.path.realpath(backup_dir):
        raise HTTPException(status_code=400, detail="The library and backup folders must be different.")
    try:
        os.makedirs(library_dir, exist_ok=True)
        os.makedirs(backup_dir, exist_ok=True)
    except OSError as ex:
        raise HTTPException(status_code=400, detail=f"Could not use those folders: {ex}") from ex
    if not os.path.isdir(library_dir) or not os.path.isdir(backup_dir):
        raise HTTPException(status_code=400, detail="Both paths need to be folders.")
    saved = {"library_dir": library_dir, "backup_dir": backup_dir}
    config.save_config(saved)
    return _public_settings(saved)


@app.get("/api/drive")
def read_drive():
    return gdrive.status()


@app.put("/api/drive")
def write_drive(body: DriveSettingsBody):
    if gdrive.backup_running():
        raise HTTPException(status_code=409, detail="Wait until the Google Drive backup finishes.")
    try:
        gdrive.save_settings(body.client_id, body.client_secret, body.folder_name)
    except gdrive.DriveError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    return gdrive.status()


@app.post("/api/drive/login")
def start_drive_login():
    try:
        gdrive.start_login()
    except gdrive.DriveError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    return gdrive.status()


@app.delete("/api/drive/login")
def cancel_drive_login():
    gdrive.cancel_login()
    return gdrive.status()


@app.post("/api/drive/logout")
def drive_logout():
    if gdrive.backup_running():
        raise HTTPException(status_code=409, detail="Wait until the Google Drive backup finishes.")
    gdrive.sign_out()
    return gdrive.status()


@app.post("/api/drive/backup")
def start_drive_backup():
    if _download_running():
        raise HTTPException(status_code=409, detail="Wait until the current download finishes.")
    try:
        gdrive.start_backup()
    except gdrive.DriveError as ex:
        raise HTTPException(status_code=409, detail=str(ex)) from ex
    return gdrive.status()


@app.delete("/api/drive/backup")
def cancel_drive_backup():
    gdrive.cancel_backup()
    return gdrive.status()


@app.get("/api/cards")
def read_cards():
    return list_cards()


@app.get("/api/cards/{card_id}")
def read_card(card_id: str):
    card = get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found.")
    return card


@app.get("/api/cards/{card_id}/files/{file_path:path}")
def read_card_file(card_id: str, file_path: str):
    return FileResponse(card_file(card_id, file_path))


@app.get("/api/jobs/current")
def current_job():
    with _jobs_lock:
        if _active_job_id and _active_job_id in _jobs:
            return _public_job(_jobs[_active_job_id])
        return {"status": "idle"}


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Download not found.")
        return _public_job(job)


@app.post("/api/jobs")
def start_job(body: JobBody):
    global _active_job_id
    if not body.confirm_ownership:
        raise HTTPException(
            status_code=400,
            detail="Confirm that you legally own these cards, or have permission to keep a copy, before downloading.",
        )
    urls = [line.strip() for line in body.urls.splitlines() if line.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="Paste at least one URL.")
    if gdrive.backup_running():
        raise HTTPException(status_code=409, detail="Wait until the Google Drive backup finishes.")
    with _jobs_lock:
        if _active_job_id is not None:
            raise HTTPException(status_code=409, detail="A download is already running.")
        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "running",
            "total": len(urls),
            "finished": 0,
            "currentUrl": "",
            "logs": [],
            "succeeded": [],
            "skipped": [],
            "failed": [],
        }
        _jobs[job_id] = job
        _active_job_id = job_id
        finished = [
            item_id for item_id, item in _jobs.items()
            if item["status"] == "done" and item_id != job_id
        ]
        for item_id in finished[:-2]:
            _jobs.pop(item_id, None)
        public = _public_job(job)
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, urls, body.replace_existing),
        daemon=True,
    )
    thread.start()
    return public


static_dir = os.path.join(config.resource_dir(), "static")


@app.get("/")
def index_page():
    return FileResponse(os.path.join(static_dir, "index.html"))


app.mount("/assets", StaticFiles(directory=static_dir), name="assets")
