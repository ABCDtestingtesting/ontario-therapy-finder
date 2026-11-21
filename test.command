#!/bin/zsh
cd "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]];then
 echo 'First run start.command to install free dependencies.'
 read -k 1 'x?Press any key to close…';exit 1
fi
.venv/bin/python -m pytest -q
read -k 1 'x?Press any key to close…'
