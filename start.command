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
if [[ -z "$PY" ]];then
  print 'No suitable Python found. Installing a free local Python automatically…'
  TOOL_DIR="$PWD/.therapy_tools"
  mkdir -p "$TOOL_DIR" || fail 'Cannot create local runtime folder'
  curl -fLsS --retry 3 'https://astral.sh/uv/install.sh' -o "$TOOL_DIR/uv_install.sh" || fail 'Could not download free Python installer; check Internet access'
  UV_INSTALL_DIR="$TOOL_DIR" UV_NO_MODIFY_PATH=1 /bin/sh "$TOOL_DIR/uv_install.sh" || fail 'Could not install local Python manager'
  export UV_PYTHON_INSTALL_DIR="$TOOL_DIR/managed_python"
  [[ -x "$TOOL_DIR/uv" ]] || fail 'Local Python manager installation did not produce an executable'
  "$TOOL_DIR/uv" python install 3.12 || fail 'Could not download managed Python 3.12'
  PY="$("$TOOL_DIR/uv" python find 3.12 --managed-python --python-preference only-managed 2>/dev/null)"
  [[ -x "$PY" ]] || fail 'Managed Python 3.12 was installed but could not be found'
fi
print "Python: $PY"
if [[ ! -x .venv/bin/python ]];then
 print 'Creating a clean local Python environment…'
 "$PY" -m venv .venv || fail 'Python could not create .venv. Check permissions and free storage.'
fi
source .venv/bin/activate || fail 'Local Python environment could not be activated'
if ! python -c 'import fastapi,uvicorn,requests,bs4,playwright,shapely,pyproj,PIL,pytest,httpx,shapefile' >/dev/null 2>&1;then
 print 'Installing free Python dependencies (first run only)…'
 python -m pip install --disable-pip-version-check --prefer-binary -r requirements.txt || fail 'Python dependency installation failed. Read the error above.'
fi
print 'Checking free Firefox automation browser…'
python -m playwright install firefox || fail 'Firefox installation failed. Check Internet access and retry.'
print 'Running startup preflight checks…'
python -m finder.selfcheck || fail 'One of the startup checks failed. Read the error above.'
# Test the actual files being launched on every startup. A version-only
# marker could skip testing after a changed or partially updated download.
print 'Testing the actual source, census, dashboard, interruption and ranking code on this Mac…'
python -m pytest -q || fail 'Local integration tests failed. The dashboard was not started with failing code. Report the test error above.'
print 'All bundled local code tests passed on this Mac.'
print '\nLaunching fresh dashboard. Keep this Terminal window open.\n'
python -m finder.server
code=$?
print "\nDashboard stopped (exit code $code). Saved research remains in the data folder."
read -k 1 'x?Press any key to exit…'
