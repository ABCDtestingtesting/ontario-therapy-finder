#!/bin/zsh
# Fresh self-contained Mac launcher. Retains downloaded data and resume files.
set -u
cd "${0:A:h}" || exit 1
printf '\n==============================================================\n'
printf '   ONTARIO THERAPY AREA FINDER — VERSION 5.1\n'
printf '   Free local research, no Google Places API, no billing\n'
printf '==============================================================\n\n'
fail() {
  printf '\nSETUP STOPPED: %s\n' "$1"
  printf 'Nothing has been marked complete. Diagnostic data is saved in this folder.\n'
  read -k 1 'x?Press any key to exit…'
  exit 1
}
PY=''
for candidate in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null)";do
 if [[ -n "$candidate" && -x "$candidate" ]] && "$candidate" -c 'import sys;assert sys.version_info >= (3,11)' >/dev/null 2>&1;then
   PY="$candidate";break
 fi
done
[[ -z "$PY" ]] && fail 'Python 3.11+ is required. Install it free from https://www.python.org/downloads/macos/'
print "Python: $PY"
if [[ ! -x .venv/bin/python ]];then
 print 'Creating a clean local Python environment…'
 "$PY" -m venv .venv || fail 'Python could not create .venv. Check permissions and free storage.'
fi
source .venv/bin/activate || fail 'Local Python environment could not be activated'
if ! python -c 'import fastapi,uvicorn,requests,bs4,playwright,shapely,pyproj,PIL,pytest,httpx' >/dev/null 2>&1;then
 print 'Installing free Python dependencies (first run only)…'
 python -m pip install --disable-pip-version-check --prefer-binary -r requirements.txt || fail 'Python dependency installation failed. Read the error above.'
fi
print 'Checking free Firefox automation browser…'
python -m playwright install firefox || fail 'Firefox installation failed. Check Internet access and retry.'
print 'Running startup preflight checks…'
python -m finder.selfcheck || fail 'One of the startup checks failed. Read the error above.'
if [[ ! -f .venv/.therapy_5_1_tested ]];then
  print 'Testing all bundled source, census, dashboard, interruption and ranking code on this Mac…'
  python -m pytest -q || fail 'Local integration tests failed. The dashboard was not started with failing code. Report the test error above.'
  touch .venv/.therapy_5_1_tested
  print 'All local code tests passed on this Mac.'
fi
print '\nLaunching fresh dashboard. Keep this Terminal window open.\n'
python -m finder.server
code=$?
print "\nDashboard stopped (exit code $code). Saved research remains in the data folder."
read -k 1 'x?Press any key to exit…'
