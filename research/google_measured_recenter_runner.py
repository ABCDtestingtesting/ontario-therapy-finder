"""Measured Google Maps recentering for targeted Ontario FSA recovery.

Never accept a search whose map centre differs materially from its requested
tile. No verification challenges are bypassed.
"""
import math
import re

from finder.common import SourceUnavailable


def refresh(page, lat, lon):
    checkbox = page.get_by_role("checkbox", name="Update results when map moves")
    requested = (float(lat), float(lon))

    def enable():
        if not checkbox.count() or not checkbox.first.is_visible():
            raise SourceUnavailable("Google map-area search control is missing")
        state = checkbox.first.get_attribute("aria-checked")
        if state == "false":
            checkbox.first.click(timeout=5000)
            page.wait_for_timeout(500)
        elif state != "true":
            raise SourceUnavailable("Google map-area control has unknown state")
        if checkbox.first.get_attribute("aria-checked") != "true":
            raise SourceUnavailable("Google map-area control is disabled")

    def position(url):
        match = re.search(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),([\d.]+)z", url)
        if not match:
            raise SourceUnavailable("Google map URL lacks coordinates or zoom")
        return tuple(map(float, match.groups()))

    def km(url):
        a, b, _ = position(url)
        radians = math.pi / 180
        delta = math.sin((a - lat) * radians / 2)**2 + (
            math.cos(lat * radians) * math.cos(a * radians) *
            math.sin((b - lon) * radians / 2)**2)
        return 12742 * math.asin(min(1, math.sqrt(delta)))

    enable()
    initial_url = page.url
    match = re.search(r"/@-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?,", initial_url)
    if not match:
        raise SourceUnavailable("Google map request cannot be geographically anchored")
    exact_url = initial_url[:match.start()] + (
        f"/@{lat:.6f},{lon:.6f},") + initial_url[match.end():]
    viewport = page.viewport_size or {"width": 1400, "height": 960}
    x = int(viewport["width"] * 0.72)
    y = int(viewport["height"] * 0.52)

    def pan(dx, dy):
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + dx, y + dy, steps=12)
        page.mouse.up()
        page.wait_for_timeout(1900)
        enable()
        return page.url

    refreshed = pan(22, 7)
    offset = km(refreshed)
    if offset > 0.7 or refreshed == initial_url:
        page.goto(exact_url, wait_until="domcontentloaded", timeout=35000)
        page.wait_for_timeout(1300)
        enable()
        refreshed = pan(-22, -7)
        offset = km(refreshed)

    for attempt in range(8):
        if offset <= 0.7 and refreshed != initial_url:
            return {"refreshed_url": refreshed, "map_center_offset_km": round(offset, 4)}
        current_lat, current_lon, zoom = position(refreshed)
        metres_per_pixel = (
            156543.03392 * max(0.2, math.cos(math.radians(current_lat))) / 2**zoom
        )
        east_m = (current_lon - lon) * 111100 * math.cos(math.radians(lat))
        north_m = (current_lat - lat) * 111100
        dx = max(-130, min(130, round(east_m / metres_per_pixel)))
        dy = max(-130, min(130, round(-north_m / metres_per_pixel)))
        if abs(dx) < 12 and abs(dy) < 12:
            dx, dy = 22, 7
        previous = offset
        refreshed = pan(dx, dy)
        offset = km(refreshed)
        if offset >= previous - 0.03 and attempt in (2, 5):
            page.goto(exact_url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(1300)
            enable()
            refreshed = pan(22, 7)
            offset = km(refreshed)

    if offset > 0.7 or refreshed == initial_url:
        raise SourceUnavailable(
            f"Google map centre remained {offset:.2f} km from the requested tile"
        )
    return {"refreshed_url": refreshed, "map_center_offset_km": round(offset, 4)}


def main():
    import runpy
    import finder.google_browser as browser

    browser._refresh_map_area_results = refresh
    runpy.run_module("research.recheck_google_contenders", run_name="__main__")


if __name__ == "__main__":
    main()
