#!/usr/bin/env python3
"""Monitor public Viks TV pages for direct stream URLs exposed in page HTML."""
import argparse
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = os.getenv("VIKS_BASE_URL", "https://live.viks.tv").rstrip("/")
CATALOG_URL = os.getenv("VIKS_CATALOG_URL", BASE_URL + "/tv3/")
REFRESH_SECONDS = max(1, float(os.getenv("REFRESH_SECONDS", "1")))
MAX_WORKERS = max(1, int(os.getenv("MAX_WORKERS", "4")))
TIMEOUT = max(5, int(os.getenv("HTTP_TIMEOUT", "20")))

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Referer": BASE_URL + "/",
})


def get_page(url):
    try:
        response = session.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        print(f"[HTTP ERROR] {url}: {exc}")
        return None


def is_viks_url(url):
    host = (urlparse(url).hostname or "").lower()
    base_host = (urlparse(BASE_URL).hostname or "").lower()
    return urlparse(url).scheme in ("http", "https") and host in {
        base_host, "www." + base_host
    }


def discover_channels(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    channels = {}
    for anchor in soup.select("a[href]"):
        name = anchor.get_text(" ", strip=True)
        href = anchor.get("href", "").strip()
        if not name or not href:
            continue
        page_url = urljoin(CATALOG_URL, href)
        path = urlparse(page_url).path
        if is_viks_url(page_url) and re.search(r"/\d+[-_][^/]+\.html$", path, re.I):
            channels[page_url] = name
    return channels


def extract_streams(page_html, page_url):
    found = set()
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup.select("video, source"):
        for attr in ("src", "data-src"):
            value = tag.get(attr)
            if value:
                candidate = urljoin(page_url, html.unescape(value.strip()))
                if urlparse(candidate).scheme in ("http", "https"):
                    found.add(candidate)

    text = html.unescape(page_html).replace(r"\/", "/").replace(r"\u0026", "&")
    patterns = (
        r"""https?://[^\s"'<>\\]+?\.m3u8(?:\?[^\s"'<>\\]*)?""",
        r"""https?://[^\s"'<>\\]+?\.mpd(?:\?[^\s"'<>\\]*)?""",
    )
    for pattern in patterns:
        for value in re.findall(pattern, text, re.I):
            found.add(value.rstrip("),;"))
    return sorted(found)


def scan_channel(item):
    page_url, name = item
    page_html = get_page(page_url)
    if page_html is None:
        return name, None
    return name, extract_streams(page_html, page_url)


def load_previous():
    try:
        with open("channels.json", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_outputs(channels):
    with open("playlist.m3u.tmp", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("#EXTM3U\n")
        for name, urls in sorted(channels.items()):
            safe_name = name.replace("\r", " ").replace("\n", " ").replace(",", " ")
            for stream_url in urls:
                handle.write(f"#EXTINF:-1,{safe_name}\n{stream_url}\n")
    os.replace("playlist.m3u.tmp", "playlist.m3u")

    with open("channels.json.tmp", "w", encoding="utf-8") as handle:
        json.dump(channels, handle, ensure_ascii=False, indent=2)
    os.replace("channels.json.tmp", "channels.json")


def main():
    cli = argparse.ArgumentParser(description="Viks TV public-page stream monitor")
    cli.add_argument("--once", action="store_true", help="scan once and exit")
    args = cli.parse_args()

    print("=== VIKS TV STREAM MONITOR ===")
    print("Catalog:", CATALOG_URL)
    print(f"Refresh pause: {REFRESH_SECONDS:g}s | workers: {MAX_WORKERS}")

    catalog_html = get_page(CATALOG_URL)
    if catalog_html is None:
        print("[FATAL] Cannot load catalog; check network and VIKS_CATALOG_URL.")
        return 2

    with open("debug.html", "w", encoding="utf-8") as handle:
        handle.write(catalog_html)

    pages = discover_channels(catalog_html)
    print("Channel pages discovered:", len(pages))
    if not pages:
        print("[FATAL] No channel links found. Catalog HTML saved as debug.html.")
        return 3

    current = load_previous()
    cycle = 0
    try:
        while True:
            cycle += 1
            started = time.monotonic()
            print(f"\n[SCAN #{cycle}] checking {len(pages)} channel pages")
            updated = dict(current)
            changed = False

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(scan_channel, item) for item in pages.items()]
                for future in as_completed(futures):
                    try:
                        name, urls = future.result()
                    except Exception as exc:
                        print("[WORKER ERROR]", exc)
                        continue
                    if urls is None:
                        continue
                    urls = list(dict.fromkeys(urls))
                    if urls and updated.get(name) != urls:
                        updated[name] = urls
                        changed = True
                        print(f"[UPDATED] {name}: {len(urls)} URL(s)")
                    elif not urls:
                        print(f"[NO DIRECT URL] {name}; retaining previous result")

            if changed or not os.path.exists("playlist.m3u"):
                save_outputs(updated)
                print("[SAVED] playlist.m3u + channels.json")
            current = updated

            elapsed = time.monotonic() - started
            print(f"[DONE] cycle={cycle}; channels={len(current)}; elapsed={elapsed:.1f}s")
            if args.once:
                break
            time.sleep(max(0.0, REFRESH_SECONDS - elapsed))

    except KeyboardInterrupt:
        print("\n[STOP] Saving latest results...")
        save_outputs(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
