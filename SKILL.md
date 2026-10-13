---
name: darkroom-agent
description: Colour-grades photos in a dark, moody style (mid-tones pulled down hard while lights stay bright, slightly richer colour, natural white balance) and adapts the grade to each photo's scene and device (iPhone HEIC/ProRAW, camera RAW, JPEG). Use when the user shares a photo and asks to edit, grade, colour-correct, or make it dark, moody, cinematic, "flex" or "larp" style, or wants a preset/LUT look applied to their photo.
---

# Darkroom Agent

You edit the user's photo by **choosing parameters** and letting `scripts/grade.py` do the pixel work.
Your job is judgment: diagnose the photo, adapt the look to it, check the result with your own eyes, and iterate.

All commands below run from this skill's directory (`cd` into it, or prefix paths with it).
Only numpy + Pillow are required. Optional, if you can install packages: `pip install pillow-heif rawpy`
(HEIC and RAW/DNG support). Without them, HEIC/RAW fail with a message telling the user to export a JPEG — pass that on.

## Workflow

1. **Measure.** `python scripts/analyze.py PHOTO` → JSON with tone percentiles, clipping, colour cast,
   skin presence/brightness, noise, detected device (`meta.source_class`), and `flags`.
2. **Look.** View the photo yourself. If it isn't a directly viewable format (HEIC, DNG, RAW), render a neutral preview first:
   `python scripts/grade.py PHOTO --look none --preview --out neutral.jpg` and view that.
   Note the subject, the light, what should draw the eye, and anything the numbers miss.
3. **Decide.** This is the part only you can do. Work out what the photo *is* and pick the matching scene from the look
   (`--list-looks` shows them; `references/grading-guide.md` → Scenes says when each applies): `night` (the default, also most landscapes),
   `lit-subject-in-dark`, `daylight`. Two more are opt-in styles, used only when the user asks for that feel:
   `quiet-luxury` (warm sepia toning, no whites, old-money look) and `cool-muted` (cold, washed out). Even when asked,
   check the subject suits the style (the guide's Scenes table says what does); if it doesn't, say so and show the base
   instead of a filter-looking result. Then look at what's in frame and adjust for it: light sources and flex items
   (watches, jewellery, bottles, chrome) keep their highlights; skin stays natural; black outfits keep texture.
   Put any overrides in a small JSON file (e.g. `work/params.json`) so iterations are reproducible. Only override what you can justify.
4. **Preview.** `python scripts/grade.py PHOTO --look dark-larp --scene night --params work/params.json --preview --compare --out work/preview.jpg`
   The script prints a JSON report (before/after stats, effective params). View `work/preview_compare.jpg`.
5. **Critique** the before|after against this checklist, adjust, re-preview. Stop after 3 rounds or when it passes:
   - Subject reads clearly; the eye goes where it should.
   - Skin looks like skin — not grey, green, or orange — unless the user asked for a stylised look.
   - Dark clothing/gear still has texture (common in LARP shots: black outfits, leather, armour). If it's a flat blob, raise `shadows` or lower the `blacks` crush.
   - Highlights have punch but aren't blown into flat white patches (report `after.clipped_highlights_frac` under ~0.02).
   - Mood is dark, not muddy: if everything sits in the mids, add `contrast` or `highlights` instead of just darkening.
6. **Deliver.** Render without `--preview` (`--out` to wherever the user can download files, e.g. `/mnt/user-data/outputs/` if that exists).
   Share the image and 3–5 plain-language bullets on what you did ("pulled the background down", "kept the lamp bright", "richer reds").
   Offer quick tweaks ("moodier", "warmer", "less saturated", "brighter face") and map them to parameters with the guide's phrase table.
   Keep `work/params.json`; if the user loves it, offer to save it as a new look in `looks/`.

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
