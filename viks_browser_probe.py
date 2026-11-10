#!/usr/bin/env python3
"""Observe public Viks TV player network traffic in Chromium; no DRM/auth bypass."""
import asyncio
import json
import os

from playwright.async_api import async_playwright
from viks_parser import CATALOG_URL, HEADERS, discover_channels, get_text

TARGETS = [x.strip() for x in os.getenv("VIKS_PROBE_PAGES", "").split(",") if x.strip()]
MAX_PAGES = max(1, int(os.getenv("VIKS_BROWSER_MAX_PAGES", "12")))
WAIT_MS = max(5000, int(os.getenv("VIKS_BROWSER_WAIT_MS", "25000")))

def interesting(url, resource_type=""):
    low = url.lower()
    return (any(x in low for x in (".m3u8", ".mpd", ".m4s", ".ts?", ".ts/", "manifest", "playlist", "master", "chunklist"))
            or resource_type in ("media", "manifest"))

async def main():
    if not TARGETS:
        catalog, _, _ = get_text(CATALOG_URL)
        if catalog:
            pages = discover_channels(catalog)
            prioritized = sorted(pages.items(), key=lambda item: (0 if "ani" in (item[0] + " " + item[1]).lower() else 1, item[1].lower()))
            TARGETS.extend(url for url, _ in prioritized[:MAX_PAGES])
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        for page_url in TARGETS[:MAX_PAGES]:
            page = await browser.new_page(user_agent=HEADERS["User-Agent"])
            events, seen = [], set()
            def add(kind, url, resource_type="", status=None, content_type=""):
                key = (kind, url, status)
                if key not in seen:
                    seen.add(key)
                    events.append({"kind": kind, "url": url, "resource_type": resource_type,
                                   "status": status, "content_type": content_type})
            page.on("request", lambda req: add("request", req.url, req.resource_type)
                    if interesting(req.url, req.resource_type) else None)
            page.on("response", lambda res: add("response", res.url, res.request.resource_type,
                                                  res.status, res.headers.get("content-type", ""))
                    if interesting(res.url, res.request.resource_type) else None)
            try:
                response = await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(WAIT_MS)
                # Click only a visible, ordinary play control; do not evade site controls.
                for selector in (".play", ".jw-icon-playback", "[aria-label*='Play']", "[title*='Play']"):
                    try:
                        loc = page.locator(selector).first
                        if await loc.count() and await loc.is_visible():
                            await loc.click(timeout=1200)
                            break
                    except Exception:
                        pass
                await page.wait_for_timeout(5000)
                video = await page.locator("video").evaluate_all(
                    "(els) => els.map(v => ({src:v.currentSrc || v.src, readyState:v.readyState, paused:v.paused}))"
                )
                results[page_url] = {"page_status": response.status if response else None,
                                     "title": await page.title(), "video": video, "network": events}
                print(f"[BROWSER] {page_url}: {len(events)} media/network events")
            except Exception as exc:
                results[page_url] = {"error": str(exc), "network": events}
                print(f"[BROWSER ERROR] {page_url}: {exc}")
            finally:
                await page.close()
        await browser.close()
    with open("viks_browser_debug.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[SAVED] viks_browser_debug.json: {len(results)} pages")

if __name__ == "__main__":
    asyncio.run(main())
