#!/bin/sh
# darkroom-agent installer for Claude Code.
# Checks Python 3 + numpy + Pillow (installs them for your user if missing), puts the skill in
# ~/.claude/skills/darkroom-agent if it isn't there yet, and runs a smoke test.
set -e
DEST="${DARKROOM_DEST:-$HOME/.claude/skills/darkroom-agent}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. On macOS run:  xcode-select --install   then rerun this script." >&2
  exit 1
fi

if python3 -c "import numpy, PIL" 2>/dev/null; then
  echo "python deps ok: $(python3 -c 'import numpy, PIL; print("numpy", numpy.__version__, "Pillow", PIL.__version__)')"
else
  echo "installing numpy and Pillow for your user..."
  python3 -m pip install --quiet --user numpy pillow 2>/dev/null \
    || python3 -m pip install --quiet --user --break-system-packages numpy pillow \
    || { echo "pip install failed. Try by hand:  python3 -m pip install --user numpy pillow" >&2; exit 1; }
  python3 -c "import numpy, PIL" || { echo "numpy/Pillow still not importable" >&2; exit 1; }
fi

if [ "$HERE" != "$DEST" ]; then
  if [ -e "$DEST" ]; then
    echo "$DEST already exists; leaving it alone. Update it with:  git -C \"$DEST\" pull"
  else
    mkdir -p "$DEST"
    # copy the skill only: no git history, eval photos or scratch renders
    (cd "$HERE" && tar -cf - --exclude .git --exclude evals --exclude work --exclude __pycache__ --exclude .DS_Store .) | tar -xf - -C "$DEST"
    echo "copied skill to $DEST"
  fi
else
  echo "skill is at $DEST"
fi

python3 "$DEST/scripts/grade.py" --list-looks >/dev/null
echo "darkroom-agent ready. Start a new Claude Code session and ask it to make a photo dark and moody."
