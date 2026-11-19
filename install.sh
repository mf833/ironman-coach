#!/bin/bash
# One-time setup on your Mac: ./install.sh
# Needs Python 3.12+ (the Garmin library requires it). Uses one if you have it,
# otherwise creates one with uv, Homebrew or conda, whichever is available.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
rm -rf .venv

PY=""
for c in python3.13 python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -n "$PY" ]; then
  echo "Using $PY"
  "$PY" -m venv .venv
elif command -v uv >/dev/null 2>&1; then
  echo "Creating a Python 3.12 environment with uv"
  uv venv --python 3.12 --seed .venv
elif command -v brew >/dev/null 2>&1; then
  echo "Installing Python 3.12 with Homebrew"
  brew install python@3.12
  "$(brew --prefix)/bin/python3.12" -m venv .venv
elif command -v conda >/dev/null 2>&1; then
  echo "Creating a Python 3.12 environment with conda (takes a minute)"
  conda create -y -q -p "$DIR/.venv" python=3.12 pip
else
  echo "Couldn't find a way to get Python 3.12. Install it from python.org, then rerun ./install.sh"
  exit 1
fi

.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]" 2>&1 | grep -v -i "warning\|editable\|careful\|wheel\|\*\*\*\|^ *!!" || true

NAME="${IRONMAN_ALIAS:-ironman}"
if grep -q "alias $NAME=" ~/.zshrc 2>/dev/null; then
  echo "Note: you already have an '$NAME' command. Run this one as $DIR/.venv/bin/ironman,"
  echo "or reinstall with a different name: IRONMAN_ALIAS=coach ./install.sh"
else
  echo "alias $NAME=\"$DIR/.venv/bin/ironman\"" >> ~/.zshrc
fi
echo ""
echo "Installed. Open a new terminal tab (or run: source ~/.zshrc), then: $NAME demo"
