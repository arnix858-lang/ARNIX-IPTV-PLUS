# ARNIX IPTV Plus

Android TV + phone IPTV player modernization workspace.

## Current stage
This repository starts with an authorized-APK inspection and resource-rebranding pipeline. It is not a recovered original source project.

## Input APK
Place the authorized Halva IPTV Player Plus APK at `app/original.apk` using GitHub's web upload or git. Do not commit signing keys or credentials.

## Build
Open Actions → Build modified APK → Run workflow. The first build is a test repackage and may require a separate app installation because the original package signature differs.

## Scope
Resource-level rebranding only at first. Functional changes to the player, playlists, EPG, decoder selection, and Android TV/phone layouts require source-level implementation or verified decompilation. Preserve third-party notices and license terms.