---
name: darkroom-agent
description: Colour-grades photos in a dark, moody style (mid-tones pulled down hard while lights stay bright, slightly richer colour, natural white balance) and adapts the grade to each photo's scene and device (iPhone HEIC/ProRAW, camera RAW, JPEG). Use when the user shares a photo and asks to edit, grade, colour-correct, or make it dark, moody, cinematic, "flex" or "larp" style, or wants a preset/LUT look applied to their photo.
---

# Darkroom Agent

You edit the user's photo by **choosing parameters** and letting `scripts/grade.py` do the pixel work.
Your job is judgment: diagnose the photo, adapt the look to it, check the result with your own eyes, and iterate.

All commands below run from this skill's directory (`cd` into it, or prefix paths with it).
Requires Python 3 with numpy and Pillow. Check once with `python3 -c "import numpy, PIL"`; if that fails, run
`python3 -m pip install numpy pillow` and tell the user what you installed. Optional: `pip install pillow-heif rawpy` adds
HEIC and RAW/DNG support; on a Mac, HEIC also works without it through the built-in `sips`. If a format still can't be read,
the script says so in plain words. Pass that message on (usually: export the photo as a JPEG and send that).

## Workflow

Before you start, pick a working folder outside the user's photo folder:
`WORK=${TMPDIR:-/tmp}/darkroom-agent/<photo-name>; mkdir -p "$WORK"`. Previews, compares, detail crops and `params.json`
go there; only the final file goes next to the photo.

1. **Measure.** `python3 scripts/analyze.py PHOTO` → JSON with tone percentiles, clipping, colour cast,
   skin presence/brightness, noise, detected device (`meta.source_class`), and `flags`. `skin_present` comes from a crude
   colour detector that red walls, wood and amber bottles also trigger: confirm there are people before acting on the skin rows.
2. **Look.** View the photo yourself. If it isn't a directly viewable format (HEIC, DNG, RAW), render a neutral preview first:
   `python3 scripts/grade.py PHOTO --look none --preview --out $WORK/neutral.jpg` and view that.
   Note the subject, the light, what should draw the eye, and anything the numbers miss.
3. **Decide.** This is the part only you can do. Work out what the photo *is* and pick the matching scene from the look
   (`--list-looks` shows them; `references/grading-guide.md` → Scenes says when each applies): `night` (the default, also most landscapes),
   `lit-subject-in-dark`, `daylight`. Two more are opt-in styles, used only when the user asks for that feel:
   `quiet-luxury` (warm sepia toning, no whites, old-money look) and `cool-muted` (cold, washed out). Even when asked,
   check the subject suits the style (the guide's Scenes table says what does); if it doesn't, say so and show the base
   instead of a filter-looking result. Then look at what's in frame and adjust for it: light sources and flex items
   (watches, jewellery, bottles, chrome) keep their highlights; skin stays natural; black outfits keep texture.
   Round 1 runs the scene defaults with no overrides. After that, put overrides in `$WORK/params.json` so iterations are reproducible, and only override what you can
   justify from the diagnosis or the compare.
4. **Preview.** Round 1: `python3 scripts/grade.py PHOTO --look dark-larp --scene night --preview --compare --out $WORK/preview1.jpg`;
   later rounds add `--params $WORK/params.json`. The script prints a JSON report: before/after stats and `effective_params`,
   the values that actually ran (a scene **replaces** the base's values for the keys it sets; it doesn't add to them).
   View `$WORK/preview1_compare.jpg` for the overall mood and `$WORK/preview1_detail.jpg` (1:1 crops of the brightest, the
   darkest-textured and the skin region, before | after) for highlights, texture and skin.
5. **Critique** the before|after against this checklist, adjust, re-preview. Stop after 3 rounds or when it passes:
   - Subject reads clearly; the eye goes where it should.
   - Skin looks like skin — not grey, green, or orange — unless the user asked for a stylised look.
   - Dark clothing/gear still has texture (common in LARP shots: black outfits, leather, armour). If it's a flat blob, raise `shadows` or lower the `blacks` crush.
   - Large whites (shirts, knitwear, snow, paper) stay white: grey means raise `highlights` or `whites`; yellow means lower `wb.temp`.
   - Highlights have punch but aren't blown into flat white patches (report `after.clipped_highlights_frac` under ~0.02).
   - Mood is dark, not muddy: if everything sits in the mids, add `contrast` or `highlights` instead of just darkening.
   - A **lit subject against black** (a third or more of the frame already black) doesn't need to get darker: clean blacks and a
     readable subject is the goal, and lifting the floor slightly is the author's own move there. A dim room without that (a bar,
     a restaurant at night) still gets the full `night` darkening; the author roughly halves the median on those.
6. **Deliver.** Render without `--preview` and with `--max-size 4096` (full size for 12 MP phone photos; larger files are
   downsized, and the report's `input_size` vs `size` shows it, so tell the user if their file came back smaller). Put the result where the user will find it: in Claude Code, next to the original
   as `<name>_graded.jpg` unless they name a folder; in claude.ai, `/mnt/user-data/outputs/`. If they want full size for a 24 MP
   phone photo, rerun with `--max-size 6000` (needs about 4 GB of RAM).
   Share the image and 3–5 plain-language bullets on what you did ("pulled the background down", "kept the lamp bright", "richer reds").
   Offer quick tweaks ("moodier", "warmer", "less saturated", "brighter face") and map them to parameters with the guide's phrase table.
   Keep `$WORK/params.json` for the session; if the user loves the result, offer to save it as a new look in `looks/`.

**Several photos from one shoot:** settle the params on the most representative frame, then apply them to the rest,
switching scene where a frame differs (e.g. one daylight shot in a night set). Check each compare image briefly for skin and blacks.

## Honesty and limits

- This engine does **global** adjustments only: no masks, no dodge/burn on a face, no subject/background separation, no retouching or object removal.
  If the photo really needs local work (e.g. face in deep shadow against a bright sky), say so and do the best global compromise.
- Never alter content. This is grading, not generative editing.
- The default look is an early version; if the user describes their own taste, that beats the look file.

## Files

- `scripts/analyze.py` — measurements + flags (JSON).
- `scripts/grade.py` — the renderer. `--set key.sub=value` for one-off overrides, `--params file.json` for many, `--look none` for neutral.
- `scripts/ingest.py` — format/device handling (JPEG, PNG, WebP, TIFF, HEIC, DNG, camera RAW; iPhone Display P3 → sRGB).
- `looks/*.json` — named looks, each with scene variants (`--scene`). `looks/_sources.json` — small per-device offsets applied automatically (`--no-source-adjust` to skip).
- `references/grading-guide.md` — parameter reference, diagnosis table, phrase → parameter map. Read it before step 3.
