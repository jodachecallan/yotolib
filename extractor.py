"""Download a Yoto card into a library folder and write a zip backup."""

import ipaddress
import json
import os
import re
import socket
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DOWNLOAD_TIMEOUT_SECONDS = 120
MAX_REDIRECTS = 5
CARD_HOSTS = {"yoto.io", "www.yoto.io"}
MAX_ATTEMPTS = 10
RECOVERY_NAME = "recovery.json"
DISCOVER_RE = re.compile(r"(Discover\: [0-9]+ track[s]?)")

AUDIO_EXTENSIONS = {
    "audio/mpeg": "mp3",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "audio/mp4": "m4a",
    "audio/flac": "flac",
    "audio/x-m4a": "m4a",
}

IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


class ExtractFail(Exception):
    """This URL cannot be completed. Move on to the next one."""


class ExtractRetry(Exception):
    """Something unexpected failed. The same URL can be tried again."""


def clean_filename(filename):
    filename = re.sub(r"[\t]", "", filename or "")
    return re.sub(r'[<>:"/\\|?*]', "", filename).strip()


def convert_seconds(seconds):
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return "%d:%02d:%02d" % (hours, minutes, seconds)


def convert_bytes(num):
    num = float(num)
    for unit in ["", "K", "M", "G"]:
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}B".strip()
        num /= 1024.0
    return f"{num:.1f} YiB"


def extension_from_content_type(content_type, mapping):
    if not content_type:
        raise ValueError("Error: contentType provided is unknown to the codebase.")
    mime = content_type.split(";", 1)[0].strip().lower()
    try:
        return mapping[mime]
    except KeyError as ex:
        raise ValueError(
            f"Error: contentType provided is unknown to the codebase: {content_type}"
        ) from ex


def _lookup(data, *path):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _emit(on_event, **event):
    if on_event is not None:
        on_event(event)


def _log(on_event, level, message):
    _emit(on_event, type="log", level=level, message=message)


class UnsafeUrl(requests.RequestException):
    """The URL points somewhere this app will not download from."""


def check_public_url(url):
    """Allow only https URLs whose host resolves to public addresses.

    Card JSON names the cover, track, and icon URLs. Without this check a
    crafted card could make the server read internal addresses (cluster
    services, cloud metadata) and save the reply where the UI can read it.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeUrl(f"Only https links can be downloaded: {url}")
    host = parsed.hostname
    if not host:
        raise UnsafeUrl(f"The link has no host name: {url}")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as ex:
        raise requests.ConnectionError(f"Could not resolve {host}.") from ex
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise UnsafeUrl(f"Refused to download from a private address: {host}")


def fetch_url(url):
    """GET a public https URL, checking every redirect hop the same way."""
    for _hop in range(MAX_REDIRECTS + 1):
        check_public_url(url)
        try:
            response = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS, allow_redirects=False)
        except requests.Timeout as ex:
            raise TimeoutError(
                f"Download took longer than {DOWNLOAD_TIMEOUT_SECONDS} seconds."
            ) from ex
        if not response.is_redirect:
            return response
        url = urljoin(url, response.headers.get("location", ""))
        response.close()
    raise UnsafeUrl(f"Too many redirects for {url}")


def ensure_https(url):
    if not url.startswith("http://") and not url.startswith("https://"):
        return "https://" + url
    return url


def card_page_url(url):
    """The https form of a Yoto card link, or None for any other link."""
    parsed = urlparse(ensure_https((url or "").strip()))
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in CARD_HOSTS:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port not in (None, 443) or parsed.username or parsed.password:
        return None
    return parsed._replace(scheme="https", netloc=parsed.hostname.lower(), fragment="").geturl()


def card_id_from_url(url):
    page = card_page_url(url)
    if page is None:
        return None
    parsed = urlparse(page)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 1:
        return None
    card_id = clean_filename(parts[0])
    if card_id in ("", ".", ".."):
        return None
    return card_id


def dedupe_urls(urls):
    cleaned = []
    seen = set()
    for url in urls:
        text = (url or "").strip()
        if not text:
            continue
        card_id = card_id_from_url(text)
        if card_id is not None:
            if card_id in seen:
                continue
            seen.add(card_id)
        cleaned.append(text)
    return cleaned


def library_has_card(library_dir, card_id):
    if not card_id or os.path.basename(card_id) != card_id or card_id.startswith("."):
        return False
    return os.path.isdir(os.path.join(library_dir, card_id))


def existing_card_result(library_dir, card_id, url):
    title = card_id
    path = os.path.join(library_dir, card_id, "card.json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and data.get("title"):
            title = str(data["title"])
    except (OSError, json.JSONDecodeError):
        pass
    return {"skipped": True, "cardId": card_id, "title": title, "url": url}


def parse_card(html):
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if script_tag is None or not script_tag.string:
        raise ExtractFail("No script found with ID '__NEXT_DATA__'.")
    try:
        payload = json.loads(script_tag.string)
    except json.JSONDecodeError as ex:
        raise ExtractFail("Card page did not contain valid JSON.") from ex
    card = _lookup(payload, "props", "pageProps", "card")
    if not isinstance(card, dict):
        raise ExtractFail("No card object found in JSON blob.")
    return card


def _safe_card_id(card_id, title):
    cleaned = clean_filename(card_id or "")
    if cleaned in ("", ".", ".."):
        cleaned = clean_filename(title or "") or "card"
    return cleaned


def _write_bytes(response, path, label, on_event):
    if response.status_code != 200:
        _log(on_event, "error", f"Failed to download {label}. Response code {response.status_code}")
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(response.content)
    return True


def _track_record(track, number, pad_length, audio_rel, icon_rel):
    duration = _optional_int(track.get("duration"))
    file_size = _optional_int(track.get("fileSize"))
    title = track.get("title")
    if not isinstance(title, str) or not title.strip():
        title = "Untitled"
    return {
        "number": number,
        "title": title,
        "file": audio_rel,
        "icon": icon_rel,
        "duration": duration,
        "readableDuration": convert_seconds(duration) if duration is not None else None,
        "fileSize": file_size,
        "readableFileSize": convert_bytes(file_size) if file_size is not None else None,
        "type": _text(track.get("type")),
        "channels": _text(track.get("channels")),
        "format": _text(track.get("format")),
    }


def _backup_filename(meta):
    category = clean_filename(meta.get("category") or "card") or "card"
    title = clean_filename(meta.get("title") or meta["cardId"]) or meta["cardId"]
    marker = "[DEMO]" if meta.get("demo") else ""
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"{category} - {title}{marker}[{meta['cardId']}] ({stamp}).zip"


def _unique_backup_path(backup_dir, filename):
    path = os.path.join(backup_dir, filename)
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime("%H-%M-%S")
    return os.path.join(backup_dir, f"{stem} {stamp}{ext}")


def load_recovery(backup_dir):
    path = os.path.join(backup_dir, RECOVERY_NAME)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list):
        return []
    return [
        item for item in cards
        if isinstance(item, dict) and item.get("cardId") and item.get("url")
    ]


def save_recovery(backup_dir, cards):
    os.makedirs(backup_dir, exist_ok=True)
    ordered = sorted(cards, key=lambda item: (item.get("title") or "").casefold())
    path = os.path.join(backup_dir, RECOVERY_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"cards": ordered}, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def sync_recovery_list(library_dir, backup_dir):
    """Refresh the backup list from the library. URLs already listed are kept."""
    by_id = {item["cardId"]: item for item in load_recovery(backup_dir)}
    if os.path.isdir(library_dir):
        for name in os.listdir(library_dir):
            if name.startswith("."):
                continue
            card_path = os.path.join(library_dir, name, "card.json")
            if not os.path.isfile(card_path):
                continue
            try:
                with open(card_path, encoding="utf-8") as handle:
                    meta = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            card_id = meta.get("cardId")
            url = meta.get("url")
            if not card_id or not url:
                continue
            by_id[card_id] = {
                "cardId": card_id,
                "title": meta.get("title") or card_id,
                "url": url,
            }
    return save_recovery(backup_dir, list(by_id.values()))


def zip_directory(folder_path, output_path):
    root_name = os.path.basename(folder_path)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for current, _dirs, files in os.walk(folder_path):
            for name in files:
                full_path = os.path.join(current, name)
                relative = os.path.relpath(full_path, folder_path)
                archive.write(full_path, os.path.join(root_name, relative))


def save_card(card, source_url, library_dir, backup_dir, on_event=None):
    title = _text(card.get("title")) or "Untitled"
    if "\n" in title:
        raise ValueError("Card title contains newline characters and cannot be stored cleanly.")

    metadata = card.get("metadata") if isinstance(card.get("metadata"), dict) else {}
    content = card.get("content") if isinstance(card.get("content"), dict) else {}
    author = _text(metadata.get("author")) or "MYO"
    description = metadata.get("description")
    if not isinstance(description, str):
        description = None
    category = _text(metadata.get("category"))
    languages = metadata.get("languages")
    if not isinstance(languages, list):
        languages = []
    languages = [str(item) for item in languages if item]
    duration = _optional_int(_lookup(metadata, "media", "duration"))
    file_size = _optional_int(_lookup(metadata, "media", "fileSize"))
    card_id = _safe_card_id(_text(card.get("cardId")), title)

    meta = {
        "cardId": card_id,
        "title": title,
        "author": author,
        "description": description,
        "version": _text(content.get("version")),
        "languages": languages,
        "slug": _text(card.get("slug")),
        "category": category,
        "playbackType": _text(content.get("playbackType")),
        "sortkey": _text(card.get("sortkey")),
        "duration": duration,
        "readableDuration": convert_seconds(duration) if duration is not None else None,
        "fileSize": file_size,
        "readableFileSize": convert_bytes(file_size) if file_size is not None else None,
        "createdAt": _text(card.get("createdAt")),
        "updatedAt": _text(card.get("updatedAt")),
        "url": source_url,
        "shareCount": card.get("shareCount") if card.get("shareCount") is not None else None,
        "availability": _text(content.get("availability")),
        "shareLinkUrl": _text(card.get("shareLinkUrl")),
        "demo": bool(description and DISCOVER_RE.search(description)),
        "audioFormats": [],
        "cover": None,
        "chapters": [],
        "trackCount": 0,
        "downloadedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }

    chapters = content.get("chapters")
    if not isinstance(chapters, list):
        raise ExtractFail("Card has no chapter list.")

    tracks = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        for track in chapter.get("tracks") or []:
            if isinstance(track, dict):
                tracks.append((chapter, track))

    pad_length = max(len(str(len(tracks))), 1)
    _log(on_event, "info", f"Title: {title}")
    _log(on_event, "info", f"Found {len(tracks)} tracks.")

    os.makedirs(library_dir, exist_ok=True)
    os.makedirs(backup_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".tmp-", dir=library_dir)
    try:
        audio_dir = os.path.join(staging, "audio")
        image_dir = os.path.join(staging, "images")
        os.makedirs(audio_dir, exist_ok=True)
        os.makedirs(image_dir, exist_ok=True)

        cover_url = _lookup(metadata, "cover", "imageL")
        if cover_url:
            try:
                cover_response = fetch_url(cover_url)
            except (TimeoutError, requests.RequestException) as ex:
                _log(on_event, "error", f"Failed to download artwork: {ex}")
                cover_response = None
            if cover_response is not None and cover_response.status_code == 200:
                try:
                    cover_ext = extension_from_content_type(
                        cover_response.headers.get("content-type"), IMAGE_EXTENSIONS
                    )
                except ValueError:
                    cover_ext = "png"
                cover_name = f"cover.{cover_ext}"
                with open(os.path.join(staging, cover_name), "wb") as handle:
                    handle.write(cover_response.content)
                meta["cover"] = cover_name
            elif cover_response is not None:
                _log(on_event, "error", f"Failed to download artwork. Response code {cover_response.status_code}")

        audio_formats = []
        saved_chapters = []
        current_chapter = None
        current_tracks = None

        for index, (chapter, track) in enumerate(tracks, start=1):
            if current_chapter is not chapter:
                current_chapter = chapter
                current_tracks = []
                saved_chapters.append({
                    "title": _text(chapter.get("title")),
                    "tracks": current_tracks,
                })

            track_title = track.get("title")
            if not isinstance(track_title, str) or not track_title.strip():
                track_title = "Untitled"
            if "\n" in track_title[:-1]:
                raise ValueError(
                    "File contains newline characters, we can't process that cleanly right now so this playlist cannot be handled."
                )
            track_title = track_title.strip()
            number = f"{index:0{pad_length}d}"
            _log(on_event, "info", f"Track {number}: {track_title}")

            audio_rel = None
            audio_url = track.get("trackUrl")
            audio_response = None
            if audio_url:
                try:
                    audio_response = fetch_url(audio_url)
                except (TimeoutError, requests.RequestException) as ex:
                    _log(on_event, "error", f"Failed to download track: {ex}")
                    audio_response = None
                if audio_response is not None and audio_response.status_code == 200:
                    content_type = audio_response.headers.get("content-type")
                    audio_ext = extension_from_content_type(content_type, AUDIO_EXTENSIONS)
                    if audio_ext not in audio_formats:
                        audio_formats.append(audio_ext)
                    audio_name = clean_filename(f"{number} - {track_title}.{audio_ext}") or f"{number}.{audio_ext}"
                    audio_path = os.path.join(audio_dir, audio_name)
                    with open(audio_path, "wb") as handle:
                        handle.write(audio_response.content)
                    audio_rel = os.path.join("audio", audio_name)
                elif audio_response is not None:
                    _log(
                        on_event,
                        "error",
                        f"Failed to download track. Response code {audio_response.status_code}",
                    )

            icon_rel = None
            track_display = track.get("display") if isinstance(track.get("display"), dict) else {}
            chapter_display = chapter.get("display") if isinstance(chapter.get("display"), dict) else {}
            icon_url = track_display.get("icon16x16") or chapter_display.get("icon16x16")
            if icon_url:
                icon_name = clean_filename(f"{number}.png")
                try:
                    icon_response = fetch_url(icon_url)
                except (TimeoutError, requests.RequestException) as ex:
                    _log(on_event, "error", f"Failed to download icon: {ex}")
                    icon_response = None
                if icon_response is not None and _write_bytes(
                    icon_response, os.path.join(image_dir, icon_name), "icon", on_event
                ):
                    icon_rel = os.path.join("images", icon_name)

            record = _track_record(track, index, pad_length, audio_rel, icon_rel)
            record["title"] = track_title
            current_tracks.append(record)

        meta["chapters"] = saved_chapters
        meta["trackCount"] = len(tracks)
        meta["audioFormats"] = audio_formats

        with open(os.path.join(staging, "card.json"), "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        final_dir = os.path.join(library_dir, card_id)
        if os.path.isdir(final_dir):
            shutil.rmtree(final_dir)
        os.rename(staging, final_dir)
        staging = None

        try:
            recovery_path = sync_recovery_list(library_dir, backup_dir)
        except OSError as ex:
            raise ExtractFail(f"Saved {title} to the library, but the recovery list failed: {ex}") from ex
        _log(on_event, "info", f"Recovery list updated: {recovery_path}")

        backup_path = _unique_backup_path(backup_dir, _backup_filename(meta))
        try:
            zip_directory(final_dir, backup_path)
        except Exception as ex:
            raise ExtractFail(f"Saved {title} to the library, but the backup zip failed: {ex}") from ex
        _log(on_event, "info", f"Backup written: {backup_path}")
        return {
            "cardId": card_id,
            "title": title,
            "url": source_url,
            "backup": backup_path,
        }
    finally:
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def extract_one(url, library_dir, backup_dir, attempt, on_event=None, replace_existing=False):
    if attempt >= MAX_ATTEMPTS:
        raise ExtractFail("URL has been tried 10 times and not able to complete.")
    _log(on_event, "info", f"Attempt {attempt} for {url}")
    url = card_page_url(url)
    if url is None:
        raise ExtractFail("Only Yoto card links (https://yoto.io/...) can be downloaded.")
    try:
        response = fetch_url(url)
    except (TimeoutError, requests.RequestException) as ex:
        raise ExtractFail(f"Network error while fetching {url}: {ex}") from ex
    if response.status_code != 200:
        raise ExtractFail(f"Failed to access the URL: {response.status_code}")
    card = parse_card(response.text)
    if not replace_existing:
        card_id = _safe_card_id(_text(card.get("cardId")), _text(card.get("title")) or "")
        if library_has_card(library_dir, card_id):
            return existing_card_result(library_dir, card_id, url)
    try:
        return save_card(card, url, library_dir, backup_dir, on_event)
    except ExtractFail:
        raise
    except (ValueError, TimeoutError) as ex:
        raise ExtractFail(str(ex)) from ex
    except Exception as ex:
        raise ExtractRetry(str(ex)) from ex


def extract_urls(urls, library_dir, backup_dir, on_event=None, replace_existing=False):
    """Download each URL. Per-URL failures are reported and do not stop the batch."""
    cleaned = dedupe_urls(urls)

    total = len(cleaned)
    _log(on_event, "info", f"Found {total} URLs.")
    index = 0
    attempts = 0
    while index < total:
        url = cleaned[index]
        card_id = card_id_from_url(url)
        if card_id is None:
            message = "Only Yoto card links (https://yoto.io/...) can be downloaded."
            _log(on_event, "error", f"Skipped {url}: {message}")
            _emit(on_event, type="result", status="fail", url=url, error=message)
            index += 1
            _emit(on_event, type="status", index=index, total=total, url="", finished=index)
            continue
        if not replace_existing and card_id and library_has_card(library_dir, card_id):
            result = existing_card_result(library_dir, card_id, url)
            _log(on_event, "info", f"Already in the library: {result['title']}")
            _emit(
                on_event,
                type="result",
                status="skipped",
                cardId=result["cardId"],
                title=result["title"],
                url=url,
            )
            index += 1
            _emit(
                on_event,
                type="status",
                index=index,
                total=total,
                url="",
                finished=index,
            )
            continue
        attempts += 1
        _emit(
            on_event,
            type="status",
            index=index + 1,
            total=total,
            url=url,
            finished=index,
        )
        try:
            result = extract_one(
                url, library_dir, backup_dir, attempts, on_event, replace_existing
            )
        except ExtractRetry as ex:
            _log(on_event, "error", f"Will retry {url}: {ex}")
            continue
        except ExtractFail as ex:
            _log(on_event, "error", f"Failed {url}: {ex}")
            _emit(on_event, type="result", status="fail", url=url, error=str(ex))
        except Exception as ex:
            _log(on_event, "error", f"Failed {url}: {ex}")
            _emit(on_event, type="result", status="fail", url=url, error=str(ex))
        else:
            if result.get("skipped"):
                _log(on_event, "info", f"Already in the library: {result['title']}")
                _emit(
                    on_event,
                    type="result",
                    status="skipped",
                    cardId=result["cardId"],
                    title=result["title"],
                    url=result["url"],
                )
            else:
                _log(on_event, "info", f"Saved {result['title']}")
                _emit(on_event, type="result", status="ok", **result)
        attempts = 0
        index += 1
        _emit(
            on_event,
            type="status",
            index=index,
            total=total,
            url="",
            finished=index,
        )

    _emit(on_event, type="status", index=total, total=total, url="", finished=total)
    _log(on_event, "info", "All downloads and processing completed.")
