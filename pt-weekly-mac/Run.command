#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 "$(command -v python3)"; do
  if [ -x "$p" ] && "$p" -c 'import sys,zoneinfo; assert sys.version_info >= (3,9); zoneinfo.ZoneInfo("America/Toronto")' 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then echo 'Python 3.9+ with time zone data is required. Install Python from python.org.'; exit 1; fi
"$PY" -m unittest discover -s . -p 'test_monitor.py' || exit 1
"$PY" monitor.py "$@"
code=$?
echo "Exit status: $code (3 = incomplete direct directory coverage)."
if [ -t 0 ]; then read -r -p 'Press Enter to close.' unused; fi
exit "$code"
