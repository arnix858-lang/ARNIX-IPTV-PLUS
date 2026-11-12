#!/usr/bin/env python3
"""Check user-supplied, authorized proxies; does not scan or harvest public proxies."""
import argparse
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

TEST_URL = "https://www.cloudflare.com/cdn-cgi/trace"
ALLOWED_SCHEMES = {"http", "https", "socks5", "socks5h"}


def check(proxy_url: str, timeout: float) -> tuple[bool, str, float]:
    parsed = urlparse(proxy_url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        return False, "invalid proxy URL (expected http(s):// or socks5(h)://)", 0.0
    proxies = {"http": proxy_url, "https": proxy_url}
    started = time.perf_counter()
    try:
        response = requests.get(
            TEST_URL, proxies=proxies, timeout=timeout,
            headers={"User-Agent": "ARNIX-IPTV-ProxyCheck/1.0"},
        )
        elapsed = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        return True, f"HTTPS test passed; HTTP {response.status_code}", elapsed
    except requests.RequestException as exc:
        elapsed = (time.perf_counter() - started) * 1000
        return False, str(exc).splitlines()[0][:180], elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check only proxy URLs you own or are authorized to use."
    )
    parser.add_argument("file", nargs="?", default="proxies.txt")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"Proxy list not found: {path}")
    urls = [
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not urls:
        raise SystemExit("No proxy URLs found.")
    for url in urls:
        ok, message, ms = check(url, args.timeout)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {url} — {message} ({ms:.0f} ms)")


if __name__ == "__main__":
    main()
