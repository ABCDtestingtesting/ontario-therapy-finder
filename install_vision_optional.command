#!/bin/zsh
cd "${0:A:h}" || exit 1
print 'Optional FREE local housing-photo classifier, about 3+ GB download.'
if ! command -v ollama >/dev/null 2>&1;then
 if command -v brew >/dev/null 2>&1;then
  brew install ollama || { print 'Ollama installation failed';read -k 1 'x?Press any key to exit…';exit 1;}
 else
  print 'Install Ollama free from https://ollama.com/download/mac then run this file again.'
  read -k 1 'x?Press any key to exit…';exit 1
 fi
fi
if command -v brew >/dev/null 2>&1;then brew services start ollama >/dev/null 2>&1 || true;fi
ollama pull qwen2.5vl:3b
print 'If model install succeeded, enable local photo classification in the dashboard.'
read -k 1 'x?Press any key to exit…'
