"""Layout checks for phone and desktop widths."""

import pytest

from conftest import LONG_TITLE_ID, MOBILE, TRACKS_ID

VIEWS = ["home", "library", "add", "cloud", "settings"]


def open_view(page, name):
    if name != "home":
        page.click(f'.nav-btn[data-view="{name}"]')
    page.wait_for_load_state("networkidle")
    if name == "library":
        page.wait_for_selector(".card-tile, .empty")


def open_card(page, card_id=None):
    open_view(page, "library")
    selector = f'.card-tile[data-id="{card_id}"]' if card_id else ".card-tile"
    page.locator(selector).first.click()
    page.wait_for_selector(".detail-layout")


def horizontal_overflow(page):
    # Compare with the device width, not innerWidth: a phone widens its
    # layout viewport to fit content that is too wide.
    width = page.viewport_size["width"]
    return page.evaluate(
        "Math.max(document.documentElement.scrollWidth, window.innerWidth)"
    ) - width


def box(page, selector):
    return page.locator(selector).first.bounding_box()


@pytest.fixture
def local_only(remote):
    if remote:
        pytest.skip("Needs the made-up test library.")


@pytest.mark.parametrize("name", VIEWS)
def test_no_horizontal_overflow(page, shot, name):
    open_view(page, name)
    shot(name)
    assert horizontal_overflow(page) <= 0


def test_card_detail_has_no_horizontal_overflow(page, shot, local_only):
    open_card(page, LONG_TITLE_ID)
    shot("detail-long-title")
    assert horizontal_overflow(page) <= 0
    width = page.viewport_size["width"]
    title = box(page, ".detail-copy h2")
    assert title["x"] >= 0 and title["x"] + title["width"] <= width


def test_long_title_tile_fits(page, local_only):
    open_view(page, "library")
    width = page.viewport_size["width"]
    tile = box(page, f'.card-tile[data-id="{LONG_TITLE_ID}"]')
    assert tile["x"] + tile["width"] <= width


@pytest.mark.devices(MOBILE)
def test_bottom_nav(page):
    viewport = page.viewport_size
    nav = box(page, ".nav")
    assert abs(nav["y"] + nav["height"] - viewport["height"]) <= 1
    assert nav["width"] == pytest.approx(viewport["width"], abs=1)
    buttons = page.locator(".nav-btn")
    assert buttons.count() == 5
    for index in range(5):
        item = buttons.nth(index).bounding_box()
        assert item["x"] >= 0 and item["x"] + item["width"] <= viewport["width"] + 0.5
        assert item["height"] >= 48
    assert page.locator(".nav-short").first.is_visible()
    assert not page.locator(".nav-long").first.is_visible()
    assert not page.locator(".eyebrow").is_visible()


@pytest.mark.devices(["desktop"])
def test_desktop_sidebar_nav(page):
    assert page.locator(".nav-long").first.is_visible()
    assert not page.locator(".nav-short").first.is_visible()
    assert page.locator(".eyebrow").is_visible()
    nav = box(page, ".nav")
    assert nav["x"] < 256


@pytest.mark.devices(MOBILE)
@pytest.mark.parametrize("name", VIEWS)
def test_content_clears_bottom_nav(page, name):
    open_view(page, name)
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(100)
    nav_top = box(page, ".nav")["y"]
    last = page.evaluate(
        """() => {
            const nodes = [...document.querySelectorAll('#view *')]
                .filter((el) => el.offsetParent !== null && el.getClientRects().length);
            return Math.max(...nodes.map((el) => el.getBoundingClientRect().bottom));
        }"""
    )
    assert last <= nav_top + 0.5


@pytest.mark.devices(MOBILE)
def test_touch_targets(page, local_only):
    assert page.evaluate("matchMedia('(pointer: coarse)').matches")
    assert box(page, ".home .primary")["height"] >= 44
    open_view(page, "library")
    assert box(page, ".chip")["height"] >= 44
    open_card(page, TRACKS_ID)
    assert box(page, ".back")["height"] >= 44
    for selector in ("#player-prev", "#player-next"):
        item = box(page, selector)
        assert item["height"] >= 44 and item["width"] >= 44


def test_back_restores_library_scroll(page):
    open_view(page, "library")
    room = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
    if room < 200:
        pytest.skip("The library is too short to scroll.")
    target = min(room, 600)
    page.evaluate(f"window.scrollTo(0, {target})")
    page.wait_for_timeout(100)
    before = page.evaluate("window.scrollY")
    # Open a tile that is on screen at this scroll position.
    visible_id = page.evaluate(
        """() => [...document.querySelectorAll('.card-tile')]
            .find((el) => {
                const r = el.getBoundingClientRect();
                const middle = (r.top + r.bottom) / 2;
                return middle > 100 && middle < window.innerHeight - 120;
            })?.dataset.id"""
    )
    assert visible_id, "No card tile is on screen."
    page.click(f'.card-tile[data-id="{visible_id}"]')
    page.wait_for_selector(".detail-layout")
    assert page.evaluate("window.scrollY") == 0
    page.click("#back")
    page.wait_for_selector(".card-tile")
    page.wait_for_function(f"Math.abs(window.scrollY - {before}) <= 2", timeout=3000)


@pytest.mark.devices(MOBILE)
def test_player_sticks_under_header(page, shot, local_only):
    open_card(page, TRACKS_ID)
    page.evaluate("window.scrollTo(0, 900)")
    page.wait_for_timeout(100)
    shot("detail-scrolled")
    player = box(page, ".player")
    header = box(page, ".sidebar")
    assert player["y"] >= header["y"] + header["height"] - 1
    assert player["y"] <= header["y"] + header["height"] + 16
