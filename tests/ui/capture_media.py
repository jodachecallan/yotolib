"""Make the README and website screenshots and the demo clip.

Runs YotoLib against a made-up showcase library (no real cards), then saves:
  docs/images/library.png         desktop library, 1120x720
  docs/images/library-mobile.png  phone library (iPhone 13)
  docs/images/demo.mp4 / demo.gif a short walk through the app

    pip install -r requirements-dev.txt imageio-ffmpeg
    python tests/ui/capture_media.py
"""

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import ROOT, run_app  # noqa: E402

OUT = ROOT / "docs" / "images"
SIZE = {"width": 1120, "height": 720}

# Made-up cards. Colours are the cover gradient, shape is the cover motif.
SHOWCASE = [
    ("The Sleepy Owl", "Mara Finch", "Sleep", ("#3b3f8f", "#8a6fd1"), "moon"),
    ("Space Pirates Ahoy", "Theo Quill", "Stories", ("#0f4c75", "#00b4d8"), "star"),
    ("Rainy Day Songs", "The Puddle Band", "Music", ("#f77f00", "#fcbf49"), "note"),
    ("Dinosaur Facts", "Dr. Ada Stone", "Learning", ("#2d6a4f", "#95d5b2"), "leaf"),
    ("The Brave Little Boat", "Mara Finch", "Stories", ("#d62828", "#f77f00"), "wave"),
    ("Counting with Croc", "Dr. Ada Stone", "Learning", ("#006d77", "#83c5be"), "dots"),
    ("Ocean Lullabies", "The Puddle Band", "Sleep", ("#023e8a", "#48cae4"), "wave"),
    ("Jungle Jamboree", "The Puddle Band", "Music", ("#6a994e", "#f2e8cf"), "note"),
    ("Tales from the Tower", "Theo Quill", "Stories", ("#7b2cbf", "#e0aaff"), "star"),
    ("Planets for Beginners", "Dr. Ada Stone", "Learning", ("#14213d", "#fca311"), "moon"),
]

MOTIFS = {
    "moon": '<circle cx="270" cy="330" r="120" fill="#fff" opacity=".9"/><circle cx="320" cy="290" r="110" fill="url(#g)"/>',
    "star": '<path d="M270 190l38 92 99 6-77 63 25 96-85-54-85 54 25-96-77-63 99-6z" fill="#fff" opacity=".9"/>',
    "note": '<path d="M230 420V230l140-30v190" fill="none" stroke="#fff" stroke-width="22" stroke-linejoin="round" opacity=".9"/>'
            '<circle cx="205" cy="425" r="38" fill="#fff" opacity=".9"/><circle cx="345" cy="395" r="38" fill="#fff" opacity=".9"/>',
    "leaf": '<path d="M150 450C150 260 290 190 400 190c0 150-80 260-250 260z" fill="#fff" opacity=".85"/>'
            '<path d="M160 440L360 230" stroke="url(#g)" stroke-width="10"/>',
    "wave": '<path d="M90 360q45-50 90 0t90 0 90 0 90 0M90 430q45-50 90 0t90 0 90 0 90 0" fill="none" stroke="#fff" stroke-width="20" stroke-linecap="round" opacity=".9"/>',
    "dots": "".join(
        f'<circle cx="{170 + 100 * (i % 3)}" cy="{230 + 100 * (i // 3)}" r="34" fill="#fff" opacity=".9"/>'
        for i in range(6)
    ),
}


def cover_svg(title, colours, motif):
    words, lines = title.split(), [""]
    for word in words:
        if len(lines[-1]) + len(word) > 14:
            lines.append("")
        lines[-1] = (lines[-1] + " " + word).strip()
    text = "".join(
        f'<text x="270" y="{640 + i * 62}" text-anchor="middle">{line}</text>' for i, line in enumerate(lines)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 540 856">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{colours[0]}"/>'
        f'<stop offset="1" stop-color="{colours[1]}"/></linearGradient></defs>'
        '<rect width="540" height="856" rx="36" fill="url(#g)"/>'
        f"{MOTIFS[motif]}"
        '<g fill="#fff" font-family="Verdana, sans-serif" font-weight="700" font-size="50">'
        f"{text}</g></svg>"
    )


def tone(path, frequency, seconds=20, rate=8000):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = bytearray()
        for n in range(seconds * rate):
            fade = min(1.0, n / rate, (seconds * rate - n) / rate)
            frames += struct.pack("<h", int(6000 * fade * math.sin(2 * math.pi * frequency * n / rate)))
        out.writeframes(bytes(frames))


def build_showcase(data_dir):
    library = data_dir / "library"
    backups = data_dir / "backups"
    backups.mkdir(parents=True)
    for index, (title, author, category, colours, motif) in enumerate(SHOWCASE):
        card_id = f"DEMO{index:02d}"
        folder = library / card_id
        (folder / "audio").mkdir(parents=True)
        (folder / "cover.svg").write_text(cover_svg(title, colours, motif), encoding="utf-8")
        tone(folder / "audio" / "tone.wav", 220 + 40 * index)
        tracks = [
            {"number": n, "title": name, "file": "audio/tone.wav", "duration": 20, "readableDuration": "0:20"}
            for n, name in enumerate(["Hello there", "The big adventure", "A quiet moment", "Goodnight"], 1)
        ]
        card = {
            "cardId": card_id,
            "title": title,
            "author": author,
            "category": category,
            "languages": ["en"],
            "description": "A made-up card for the YotoLib screenshots.",
            "trackCount": len(tracks),
            "readableDuration": "1 min",
            "cover": "cover.svg",
            "chapters": [{"title": "Side A", "tracks": tracks}],
        }
        (folder / "card.json").write_text(json.dumps(card), encoding="utf-8")
        if index % 3 != 2:
            (backups / f"{title} [{card_id}] (2026-10-24).zip").write_bytes(b"")


# A dot that follows the mouse, since recorded video has no cursor.
CURSOR = """
addEventListener('DOMContentLoaded', () => {
  const dot = document.createElement('div');
  dot.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;' +
    'border-radius:50%;background:rgba(20,20,20,.35);border:2px solid #fff;z-index:99999;' +
    'pointer-events:none;transition:transform .12s';
  document.body.append(dot);
  addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; });
  addEventListener('mousedown', () => { dot.style.transform = 'scale(.7)'; });
  addEventListener('mouseup', () => { dot.style.transform = ''; });
});
"""


def glide_click(page, selector, pause=700):
    target = page.locator(selector).first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12)
    page.wait_for_timeout(150)
    target.click()
    page.wait_for_timeout(pause)


def screenshots(browser, p, url):
    page = browser.new_page(viewport=SIZE)
    page.goto(url)
    page.click('.nav-btn[data-view="library"]')
    page.wait_for_selector(".card-tile img")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / "library.png"))
    page.close()

    phone = {k: v for k, v in p.devices["iPhone 13"].items() if k != "default_browser_type"}
    phone["device_scale_factor"] = 2
    context = browser.new_context(**phone)
    page = context.new_page()
    page.goto(url)
    page.click('.nav-btn[data-view="library"]')
    page.wait_for_selector(".card-tile img")
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(OUT / "library-mobile.png"))
    context.close()


def record(browser, url, video_dir):
    context = browser.new_context(viewport=SIZE, record_video_dir=str(video_dir), record_video_size=SIZE)
    context.add_init_script(CURSOR)
    page = context.new_page()
    page.goto(url)
    page.wait_for_selector(".home")
    page.mouse.move(700, 400)
    page.wait_for_timeout(700)

    glide_click(page, '.nav-btn[data-view="library"]', 1000)
    glide_click(page, '.chip[data-category="Music"]', 900)
    glide_click(page, '.chip[data-category=""]', 300)
    glide_click(page, "#library-search", 100)
    page.keyboard.type("owl", delay=110)
    page.wait_for_timeout(600)
    glide_click(page, ".card-tile", 800)

    glide_click(page, "#player-toggle", 1600)
    glide_click(page, "#player-next", 1300)
    glide_click(page, "#player-toggle", 300)
    glide_click(page, "#back", 500)
    page.fill("#library-search", "")
    page.wait_for_timeout(600)

    glide_click(page, '.nav-btn[data-view="add"]', 1000)
    glide_click(page, '.nav-btn[data-view="cloud"]', 1000)
    glide_click(page, '.nav-btn[data-view="home"]', 600)
    video = page.video
    context.close()
    return Path(video.path())


def convert(webm):
    try:
        import imageio_ffmpeg
    except ImportError:
        shutil.copy(webm, OUT / "demo.webm")
        print("imageio-ffmpeg is not installed, so only demo.webm was saved.")
        return
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "26", "-preset", "slow", "-movflags", "+faststart", "-an", str(OUT / "demo.mp4")],
        check=True,
    )
    palette = "fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(webm), "-vf", palette, "-loop", "0", str(OUT / "demo.gif")],
        check=True,
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "data"
        build_showcase(data_dir)
        with run_app(data_dir) as url, sync_playwright() as p:
            browser = p.chromium.launch()
            screenshots(browser, p, url)
            webm = record(browser, url, Path(tmp) / "video")
            browser.close()
            convert(webm)
    for name in ("library.png", "library-mobile.png", "demo.mp4", "demo.gif", "demo.webm"):
        path = OUT / name
        if path.exists():
            print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
