# darkroom-agent

A Claude skill that colour-grades photos in a dark, moody, cinematic style, for people who don't want to learn Lightroom.
Upload a photo, ask Claude to "make it dark and moody", and it measures the photo, adapts the look to it,
checks its own result, and hands back the edit plus a plain-English rundown of what changed.

It works from iPhone HEIC/ProRAW, camera RAW, and plain JPEGs, and adjusts for each.

## Install

**Claude Code on a Mac:** one command, then start a new Claude Code session anywhere and ask it to make a photo dark and moody.

```bash
git clone https://github.com/junzh011/darkroom-agent.git ~/.claude/skills/darkroom-agent && ~/.claude/skills/darkroom-agent/install.sh
```

`install.sh` checks for Python 3 with numpy and Pillow and installs them for your user if they're missing.
Already installed? Update with `git -C ~/.claude/skills/darkroom-agent pull`.

Needs: Claude Code and Python 3 (macOS offers to install its developer tools if `python3` is missing). HEIC photos work
out of the box on a Mac; on Windows or Linux add `pip install pillow-heif`. RAW/DNG needs `pip install rawpy` everywhere.

**claude.ai / Claude desktop:** zip the folder (without `.git`) and upload it under Settings → Capabilities → Skills
(code execution must be enabled). Not tested there yet.

## How it works

- `scripts/analyze.py` measures exposure, contrast, colour cast, skin, noise and the source device.
- `scripts/grade.py` renders a grade from a look file plus overrides (numpy + Pillow only).
- `looks/` holds the looks; `references/grading-guide.md` holds the judgment rules Claude follows.

Try it directly:

```bash
python3 scripts/grade.py photo.jpg --look dark-larp --preview --compare
```

## Status

Early. The `dark-larp` look is calibrated on 6 iPhone before/after pairs with `tools/calibrate.py`:
the night base comes from 8 edits and the daylight scene from 3; the remaining scenes come from one example each, and the two opt-in styles (`quiet-luxury`, `cool-muted`) are only used when someone asks for that feel.
Offsets for ProRAW and camera RAW are untested on real files.
Global adjustments only, with no masking or local dodge and burn yet.
Delivery defaults to a 4096 px long edge (12.6 MP), so 24 MP iPhone photos come back smaller unless `--max-size 6000` is
passed, which needs about 4 GB of RAM.

Re-calibrate after adding pairs to `evals/`:

```bash
python3 tools/calibrate.py fit evals/larp-shoot-1 --out work/fit.json
python3 tools/calibrate.py eval evals/larp-shoot-1 --look dark-larp --out-dir work/eval
```
