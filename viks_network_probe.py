#!/usr/bin/env python3
"""Inspect public Viks TV player network activity without saving signed URLs or cookies."""
import asyncio
import json
import re
from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import async_playwright

PAGES = [
    "https://live.viks.tv/028622-ani.html",
    "https://live.viks.tv/1000-action.html",
]

def safe_url(raw):
    """Remove query/fragment values so temporary tokens are never written to the report."""
    p = urlsplit(raw)
    path = re.sub(r"/[A-Za-z0-9_-]{32,}(?=/|$)", "/[REDACTED]", p.path)
    return urlunsplit((p.scheme, p.netloc, path, "", ""))

async def main():
    records = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
            viewport={"width": 1365, "height": 900},
        )
        for page_url in PAGES:
            page = await context.new_page()
            page_records = {}

            def on_request(req):
                key = (req.method, req.resource_type, safe_url(req.url))
                page_records.setdefault(key, {"method": req.method, "type": req.resource_type,
                                              "url": safe_url(req.url), "status": None,
                                              "content_type": None})

            def on_response(resp):
                req = resp.request
                key = (req.method, req.resource_type, safe_url(req.url))
                item = page_records.setdefault(key, {"method": req.method, "type": req.resource_type,
                                                      "url": safe_url(req.url)})
                item["status"] = resp.status
                item["content_type"] = resp.headers.get("content-type", "").split(";")[0]

            page.on("request", on_request)
            page.on("response", on_response)
            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(15000)
                # Ask the page's own video element to start, if one is present.
                await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (v) { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
                }""")
                await page.wait_for_timeout(15000)
                title = await page.title()
                video_count = await page.locator("video").count()
                iframe_urls = await page.locator("iframe").evaluate_all(
                    "(els) => els.map(e => e.src).filter(Boolean).map(u => { const x = new URL(u); return x.origin + x.pathname; })"
                )
                records[page_url] = {
                    "title": title,
                    "video_elements": video_count,
                    "iframes": iframe_urls,
                    "requests": sorted(page_records.values(), key=lambda x: (x.get("type", ""), x.get("url", ""))),
                }
            except Exception as exc:
                records[page_url] = {"error": type(exc).__name__ + ": " + str(exc)[:300],
                                     "requests": sorted(page_records.values(), key=lambda x: x.get("url", ""))}
            await page.close()
        await browser.close()

    with open("viks-network-report.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    for page_url, data in records.items():
        print("\nPAGE:", page_url)
        if data.get("error"):
            print("ERROR:", data["error"])
        print("VIDEO ELEMENTS:", data.get("video_elements", 0))
        print("IFRAMES:", len(data.get("iframes", [])))
        for item in data.get("requests", []):
            ctype = item.get("content_type") or ""
            rtype = item.get("type") or ""
            if rtype in ("media", "xhr", "fetch") or any(x in ctype.lower() for x in ("mpegurl", "dash+xml", "video/", "audio/")):
                print(f'{item.get("status")} {rtype} {ctype} {item.get("url")}')
    print("\nSaved sanitized report: viks-network-report.json")

if __name__ == "__main__":
    asyncio.run(main())
