#!/usr/bin/env python3
"""Check configured IPTV HLS URLs and write a diagnostic report.

This checks reachability from the GitHub-hosted runner only. It does not use
proxies, change region, bypass access controls, or remove channels.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent
CHANNELS_FILE = ROOT / "channels.json"
REPORT_FILE = ROOT / "stream_status.json"
TIMEOUT = 12
HEADERS = {"User-Agent": "ARNIX-IPTV-Monitor/1.0", "Accept": "*/*"}


def check_channel(channel):
    url = str(channel.get("url", "")).strip()
    result = {
        "name": channel.get("name", "Unknown"),
        "url": url,
        "status": "ERROR",
        "http_status": None,
        "detail": "",
    }
    if not url.startswith(("https://", "http://")):
        result["detail"] = "Invalid HTTP(S) URL"
        return result

    try:
        response = requests.get(
            url, headers=HEADERS, timeout=TIMEOUT, stream=True,
            allow_redirects=True,
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        sample = next(response.iter_content(chunk_size=4096), b"")
        response.close()

        # HLS manifests are text and normally contain #EXTM3U.
        if b"#EXTM3U" not in sample:
            result["status"] = "UNCONFIRMED"
            result["detail"] = (
                "HTTP reachable, but response does not look like an HLS manifest"
                + (f" (Content-Type: {content_type})" if content_type else "")
            )
            return result

        result["status"] = "ONLINE"
        result["detail"] = "HLS manifest returned successfully"
    except requests.RequestException as exc:
        result["status"] = "UNAVAILABLE"
        result["detail"] = str(exc).splitlines()[0][:240]
    return result


def main():
    channels = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checker_location": "GitHub-hosted runner (not the viewer's device)",
        "results": [check_channel(channel) for channel in channels],
    }
    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    lines = [
        "## ARNIX IPTV — stream check",
        "",
        f"Checked: {report['checked_at']}",
        "",
        "> Results describe access from GitHub's runner. A regional restriction or "
        "network policy may make a stream fail here even when it works for you, "
        "or vice versa. Channels are never deleted or rewritten automatically.",
        "",
        "| Channel | Result | HTTP | Details |",
        "|---|---|---:|---|",
    ]
    for item in report["results"]:
        details = item["detail"].replace("|", "\\|")
        lines.append(
            f"| {item['name']} | {item['status']} | "
            f"{item['http_status'] or '—'} | {details} |"
        )
    rendered = "\n".join(lines) + "\n"
    if summary:
        Path(summary).write_text(rendered, encoding="utf-8")
    print(rendered)
    # Monitoring is informational; a failed stream must not fail the workflow.
    return 0


if __name__ == "__main__":
    sys.exit(main())
