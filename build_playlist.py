#!/usr/bin/env python3
"""Build an M3U playlist from channels.json."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNELS = ROOT / "channels.json"
OUTPUT = ROOT / "playlist.m3u"


def main() -> None:
    channels = json.loads(CHANNELS.read_text(encoding="utf-8"))
    lines = ["#EXTM3U"]
    for channel in channels:
        name = str(channel["name"]).replace("\n", " ").replace("\r", " ")
        url = str(channel["url"]).strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"Unsupported URL for {name}")
        tvg_id = str(channel.get("tvg_id", "")).replace('"', "")
        group = str(channel.get("group", "Без категории")).replace('"', "")
        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" group-title="{group}",{name}'
        )
        lines.append(url)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Written {len(channels)} channels to {OUTPUT.name}")


if __name__ == "__main__":
    main()
