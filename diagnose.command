#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]];then
  echo 'Installation is not complete. Send the last lines from the start.command Terminal instead.'
else
  .venv/bin/python -m finder.diagnostics
  echo 'Open the output folder to find diagnostics_*.zip. Inspect it before sharing.'
fi
read -k 1 'x?Press any key to close…'
