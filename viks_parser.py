#!/usr/bin/env python3
"""Discover public Viks TV stream candidates from pages, iframes and player scripts.

The scanner only inspects publicly served page resources. It does not bypass DRM,
authentication, access controls or CAPTCHA. Existing playlist entries are retained
when a page has no newly discovered candidate.
"""
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
REFRESH_SECONDS = max(1, float(os.getenv("REFRESH_SECONDS", "300")))
MAX_WORKERS = max(1, int(os.getenv("MAX_WORKERS", "4")))
TIMEOUT = max(5, int(os.getenv("HTTP_TIMEOUT", "20")))
MAX_SCRIPTS = max(0, int(os.getenv("MAX_PLAYER_SCRIPTS", "12")))
MAX_IFRAMES = max(0, int(os.getenv("MAX_PLAYER_IFRAMES", "6")))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Referer": BASE_URL + "/",
}
URL_RE = re.compile(
    r"""(?:(?:https?:)?//|/)[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+?\.(?:m3u8|mpd)(?:\?[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?""",
    re.I,
)
ABS_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""", re.I)
STREAM_SUFFIX_RE = re.compile(r"\.(?:m3u8|mpd)(?:$|\?)", re.I)
session = requests.Session()
session.headers.update(HEADERS)


def get_text(url, referer=None):
    headers = {"Referer": referer} if referer else None
    try:
        response = session.get(url, timeout=TIMEOUT, headers=headers)
        response.raise_for_status()
        return response.text, response.url, response.headers.get("Content-Type", "")
    except requests.RequestException as exc:
        print(f"[HTTP ERROR] {url}: {exc}")
        return None, url, ""


def is_http_url(url):
    return urlparse(url).scheme in ("http", "https")


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
        host = (urlparse(page_url).hostname or "").lower()
        base_host = (urlparse(BASE_URL).hostname or "").lower()
        if host in {base_host, "www." + base_host} and re.search(r"/\d+[-_][^/]+\.html$", path, re.I):
            channels[page_url] = name
    return channels


def normalize_embedded_text(value):
    return (html.unescape(value).replace(r"\/", "/")
            .replace(r"\u0026", "&").replace(r"\u003a", ":")
            .replace(r"\x3a", ":").replace(r"\x2f", "/"))


def extract_urls(text, base_url):
    text = normalize_embedded_text(text)
    found = set()
    for raw in URL_RE.findall(text):
        candidate = urljoin(base_url, raw)
        if is_http_url(candidate) and STREAM_SUFFIX_RE.search(candidate):
            found.add(candidate.rstrip("),;]}"))
    # Some player configs store an escaped URL in a JSON string.
    for raw in ABS_URL_RE.findall(text):
        candidate = raw.rstrip("),;]}")
        if STREAM_SUFFIX_RE.search(candidate):
            found.add(candidate)
    return found


def inspect_player_resources(page_html, page_url):
    """Inspect bounded script and iframe resources referenced by a channel page."""
    soup = BeautifulSoup(page_html, "html.parser")
    resources = []
    for tag in soup.select("script[src]")[:MAX_SCRIPTS]:
        resources.append(("script", urljoin(page_url, tag.get("src", ""))))
    for tag in soup.select("iframe[src]")[:MAX_IFRAMES]:
        resources.append(("iframe", urljoin(page_url, tag.get("src", ""))))

    candidates = set(extract_urls(page_html, page_url))
    inspected = []
    for kind, resource_url in resources:
        if not is_http_url(resource_url):
            continue
        resource_text, final_url, content_type = get_text(resource_url, referer=page_url)
        inspected.append({"type": kind, "url": resource_url, "final_url": final_url,
                          "ok": resource_text is not None, "content_type": content_type})
        if resource_text is None:
            continue
        candidates.update(extract_urls(resource_text, final_url))
        # Player scripts sometimes contain an iframe URL rather than stream URL.
        if kind == "script":
            script_soup = BeautifulSoup(resource_text, "html.parser")
            for match in re.findall(r"""(?:src|file|url|source)\s*[:=]\s*["']([^"']+)["']""",
                                    resource_text, re.I):
                embedded = urljoin(final_url, normalize_embedded_text(match))
                if is_http_url(embedded) and not STREAM_SUFFIX_RE.search(embedded):
                    # Inspect only explicit player iframe/embed URLs, not arbitrary links.
                    if any(token in embedded.lower() for token in ("player", "embed", "video", "stream")):
                        frame_text, frame_final, frame_type = get_text(embedded, referer=page_url)
                        inspected.append({"type": "embedded", "url": embedded,
                                          "final_url": frame_final, "ok": frame_text is not None,
                                          "content_type": frame_type})
                        if frame_text:
                            candidates.update(extract_urls(frame_text, frame_final))

    return sorted(candidates), inspected


def scan_channel(item):
    page_url, name = item
    page_html, final_url, _ = get_text(page_url)
    if page_html is None:
        return name, None, []
    candidates, resources = inspect_player_resources(page_html, final_url)
    return name, candidates, resources


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
    cli = argparse.ArgumentParser(description="Viks TV public-page/player-resource scanner")
    cli.add_argument("--once", action="store_true", help="scan once and exit")
    args = cli.parse_args()

    print("=== VIKS TV PLAYER RESOURCE SCANNER ===")
    print("Catalog:", CATALOG_URL)
    print(f"Workers: {MAX_WORKERS}; scripts/page: {MAX_SCRIPTS}; iframes/page: {MAX_IFRAMES}")

    catalog_html, _, _ = get_text(CATALOG_URL)
    if catalog_html is None:
        print("[FATAL] Cannot load catalog.")
        return 2

    pages = discover_channels(catalog_html)
    print("Channel pages discovered:", len(pages))
    if not pages:
        with open("debug.html", "w", encoding="utf-8") as handle:
            handle.write(catalog_html)
        print("[FATAL] No channel links found; catalog saved to debug.html.")
        return 3

    current = load_previous()
    cycle = 0
    try:
        while True:
            cycle += 1
            started = time.monotonic()
            updated = dict(current)
            debug = {}
            changed = False
            print(f"\n[SCAN #{cycle}] checking {len(pages)} pages")

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(scan_channel, item) for item in pages.items()]
                for future in as_completed(futures):
                    try:
                        name, candidates, resources = future.result()
                    except Exception as exc:
                        print("[WORKER ERROR]", exc)
                        continue
                    debug[name] = {"candidate_streams": candidates or [], "resources": resources}
                    if candidates is None:
                        continue
                    # Keep existing entries if the page exposes no stream URL.
                    if candidates and updated.get(name) != candidates:
                        updated[name] = candidates
                        changed = True
                        print(f"[CANDIDATES] {name}: {len(candidates)}")
                    elif not candidates:
                        print(f"[NO CANDIDATE] {name}; retaining previous entries")

            with open("viks_debug.json", "w", encoding="utf-8") as handle:
                json.dump(debug, handle, ensure_ascii=False, indent=2)

            if changed or not os.path.exists("playlist.m3u"):
                save_outputs(updated)
                print("[SAVED] playlist.m3u + channels.json")
            current = updated
            print(f"[DONE] cycle={cycle}; channels={len(current)}; elapsed={time.monotonic()-started:.1f}s")
            if args.once:
                break
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\n[STOP] Keeping last successfully saved playlist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
