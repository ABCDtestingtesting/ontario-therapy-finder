#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3)"; do
  if [ -x "$p" ] && "$p" -c 'import sys,zoneinfo; assert sys.version_info >= (3,9); zoneinfo.ZoneInfo("America/Toronto")' 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then echo 'Python 3.9+ with time zone data is required. Install Python from python.org.'; exit 1; fi
"$PY" -m unittest discover -s . -p 'test_keyless.py' || exit 1
if [ "${1:-}" = "--self-test" ]; then exit 0; fi
"$PY" weekly_keyless.py "$@"
code=$?
# Independent directory-statistic survey; preserve historical evidence when unavailable.
OUT="$HOME/Library/Application Support/PT Weekly Index Survey/$(TZ=America/Toronto date +%F)-directory"
"$PY" directory_index.py --out "$OUT"
dircode=$?
if [ "$dircode" -ne 0 ]; then code=3; fi
echo "Weekly approximation with this week\047s indexed profile evidence is in the week-start folder printed above. The directory-only report is a secondary cross-check."
echo "Exit status: $code (0 = completed index survey, 3 = incomplete; neither certifies an exact competitor ranking)."
if [ -t 0 ]; then read -r -p 'Press Enter to close.' unused; fi
exit "$code"
