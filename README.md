# darkroom-agent

A Claude skill that colour-grades photos in a dark, moody, cinematic style, for people who don't want to learn Lightroom.
Upload a photo, ask Claude to "make it dark and moody", and it measures the photo, adapts the look to it,
checks its own result, and hands back the edit plus a plain-English rundown of what changed.

It works from iPhone HEIC/ProRAW, camera RAW, and plain JPEGs, and adjusts for each.

## Install

- **claude.ai / Claude desktop:** zip the `darkroom-agent` folder and upload it under Settings → Capabilities → Skills
  (code execution must be enabled).
- **Claude Code:** copy the folder to `~/.claude/skills/darkroom-agent`.

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
the night base is solid (3 consistent edits), while the other scenes come from one edit each.
Offsets for ProRAW and camera RAW are untested on real files.
Global adjustments only, with no masking or local dodge and burn yet.

Re-calibrate after adding pairs to `evals/`:

```bash
python3 tools/calibrate.py fit evals/larp-shoot-1 --out work/fit.json
python3 tools/calibrate.py eval evals/larp-shoot-1 --look dark-larp --out-dir work/eval
```
