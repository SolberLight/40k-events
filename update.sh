#!/usr/bin/env bash
# Refresh both sources and rebuild the site. Needs only python3 (standard library).
set -euo pipefail
cd "$(dirname "$0")"
echo "== Best Coast Pairings (API) =="
python3 scrape_bcp.py "$@"
echo "== MiniHeadQuarters (HTML) =="
python3 scrape_mhq.py
echo "== Build =="
python3 build.py
echo "Done. Open site/index.html or run: python3 -m http.server 8040 -d site"
