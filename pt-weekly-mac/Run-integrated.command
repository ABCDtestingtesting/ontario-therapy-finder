#!/bin/bash
cd "$(dirname "$0")" || exit 1
PY=""
for p in "$(command -v python3)" /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  if [ -x "$p" ] && "$p" -c 'import sys,zoneinfo; assert sys.version_info >= (3,9); zoneinfo.ZoneInfo("America/Toronto")' 2>/dev/null; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then echo "Python 3.9+ required."; exit 1; fi
exec "$PY" -u integrated_run.py "$@"
