"""Headless browser fixtures for the YotoLib UI.

The app runs against a throwaway data folder with made-up cards, so the
tests never touch the real library. Set YOTOLIB_UI_BASE_URL to point the
tests at a running copy instead; tests that need the made-up cards skip.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "test-results" / "ui"

LONG_TITLE_ID = "UITEST-LONG"
TRACKS_ID = "UITEST-TRACKS"
NO_COVER_ID = "UITEST-NOCOVER"

CATEGORIES = ["Stories", "Music", "Sleep", "Learning"]


def _png(width, height, rgb):
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _card(card_id, title, index, chapters=1, tracks_each=3, cover=True):
    chapter_list = []
    number = 1
    for chapter in range(chapters):
        tracks = []
        for _ in range(tracks_each):
            tracks.append({
                "number": number,
                "title": f"Track {number} of {title[:20]}",
                "file": f"audio/{number:02d}.mp3",
                "duration": 120,
                "readableDuration": "2:00",
            })
            number += 1
        chapter_list.append({"title": f"Chapter {chapter + 1}", "tracks": tracks})
    return {
        "cardId": card_id,
        "title": title,
        "author": f"Test Author {index % 3 + 1}",
        "category": CATEGORIES[index % len(CATEGORIES)],
        "languages": ["en"],
        "description": "A made-up card for the UI tests.",
        "trackCount": number - 1,
        "readableDuration": f"{(number - 1) * 2} min",
        "cover": "cover.png" if cover else None,
        "chapters": chapter_list,
    }


def build_library(data_dir):
    library = data_dir / "library"
    cards = [
        _card(LONG_TITLE_ID, "Supercalifragilisticexpialidocious" * 3, 0),
        _card(TRACKS_ID, "A card with a long track list", 1, chapters=4, tracks_each=8),
        _card(NO_COVER_ID, "No cover card", 2, cover=False),
    ]
    cards += [_card(f"UITEST-{n:02d}", f"Sample story {n:02d}", n) for n in range(3, 16)]
    for index, card in enumerate(cards):
        folder = library / card["cardId"]
        folder.mkdir(parents=True)
        (folder / "card.json").write_text(json.dumps(card), encoding="utf-8")
        if card["cover"]:
            shade = 80 + (index * 37) % 150
            (folder / "cover.png").write_bytes(_png(64, 64, (shade, 120, 200)))
    (data_dir / "backups").mkdir()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def remote():
    return bool(os.environ.get("YOTOLIB_UI_BASE_URL", "").strip())


@pytest.fixture(scope="session")
def base_url(tmp_path_factory, remote):
    if remote:
        yield os.environ["YOTOLIB_UI_BASE_URL"].strip().rstrip("/")
        return
    data_dir = tmp_path_factory.mktemp("yotolib-data")
    build_library(data_dir)
    port = _free_port()
    env = {
        **os.environ,
        "YOTOLIB_DATA_DIR": str(data_dir),
        "YOTOLIB_HOST": "127.0.0.1",
        "YOTOLIB_PORT": str(port),
        "YOTOLIB_OPEN_BROWSER": "0",
    }
    log = open(data_dir / "server.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "yotolib.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                urllib.request.urlopen(url + "/api/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("YotoLib did not start in time.")
        if proc.poll() is not None:
            log.close()
            pytest.fail("YotoLib exited:\n" + (data_dir / "server.log").read_text())
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance):
    browser = playwright_instance.chromium.launch()
    yield browser
    browser.close()


def _profiles(p):
    return {
        "iphone-13": {k: v for k, v in p.devices["iPhone 13"].items() if k != "default_browser_type"},
        "pixel-7": {k: v for k, v in p.devices["Pixel 7"].items() if k != "default_browser_type"},
        "narrow-320": {
            "viewport": {"width": 320, "height": 640},
            "device_scale_factor": 2,
            "is_mobile": True,
            "has_touch": True,
        },
        "desktop": {"viewport": {"width": 1280, "height": 800}},
    }


DEVICES = ["iphone-13", "pixel-7", "narrow-320", "desktop"]
MOBILE = [name for name in DEVICES if name != "desktop"]


@pytest.fixture
def device(request):
    return request.param


@pytest.fixture
def page(browser, playwright_instance, device, base_url):
    context = browser.new_context(**_profiles(playwright_instance)[device], base_url=base_url)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("/")
    page.wait_for_selector(".home")
    yield page
    context.close()
    assert not errors, f"JavaScript errors: {errors}"


@pytest.fixture
def shot(page, device):
    RESULTS.mkdir(parents=True, exist_ok=True)

    def take(name):
        page.screenshot(path=str(RESULTS / f"{device}-{name}.png"), full_page=True)

    return take


def pytest_configure(config):
    config.addinivalue_line("markers", "devices(names): run only on these device profiles")


def pytest_generate_tests(metafunc):
    if "device" not in metafunc.fixturenames:
        return
    marker = metafunc.definition.get_closest_marker("devices")
    names = marker.args[0] if marker else DEVICES
    metafunc.parametrize("device", names, indirect=True)
