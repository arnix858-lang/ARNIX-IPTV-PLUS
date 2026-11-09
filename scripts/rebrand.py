#!/usr/bin/env python3
"""Change only the visible app label in decoded APK string resources."""
from pathlib import Path
import xml.etree.ElementTree as ET
import sys

root = Path(sys.argv[1])
target_names = {"app_name", "application_name"}
replacement = "ARNIX IPTV Plus"
updated = 0

for path in root.glob("res/values*/strings.xml"):
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        continue
    changed = False
    for node in tree.getroot().findall("string"):
        if node.get("name") in target_names:
            node.text = replacement
            changed = True
            updated += 1
    if changed:
        tree.write(path, encoding="utf-8", xml_declaration=True)

if updated == 0:
    print("No app_name/application_name string resource found; inspect decoded AndroidManifest.xml.")
    sys.exit(2)
print(f"Updated {updated} app label resource(s).")
