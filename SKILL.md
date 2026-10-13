---
name: darkroom-agent
description: Colour-grades photos in a dark, moody style (mid-tones pulled down hard while lights stay bright, slightly richer colour, natural white balance) and adapts the grade to each photo's scene and device (iPhone HEIC/ProRAW, camera RAW, JPEG). Use when the user shares a photo and asks to edit, grade, colour-correct, or make it dark, moody, cinematic, "flex" or "larp" style, or wants a preset/LUT look applied to their photo.
---

# Darkroom Agent

You edit the user's photo by **choosing parameters** and letting `scripts/grade.py` do the pixel work.
Your job is judgment: diagnose the photo, adapt the look to it, check the result with your own eyes, and iterate.

All commands below run from this skill's directory (`cd` into it, or prefix paths with it).
Requires Python 3 with numpy and Pillow. Check once with `python3 -c "import numpy, PIL"`; if that fails, run
`python3 -m pip install --user numpy pillow` (add `--break-system-packages` if a Homebrew Python refuses) and tell the user what you installed. Optional: `pip install pillow-heif rawpy` adds
HEIC and RAW/DNG support; on a Mac, HEIC also works without it through the built-in `sips`. If a format still can't be read,
the script says so in plain words. Pass that message on (usually: export the photo as a JPEG and send that).

## Workflow

Before you start, make a fresh working folder outside the user's photo folder:
`WORK=${TMPDIR:-/tmp}/darkroom-agent/<photo-name>-$(date +%H%M%S); mkdir -p "$WORK"`. Previews, compares, detail crops
and `params.json` go there; only the final file goes next to the photo. Shells don't persist between commands, so set
`WORK` in every command (or write the full path). Never reuse a folder that already has files in it: a previous run's
`params.json` would leak into yours.

1. **Measure.** `python3 scripts/analyze.py PHOTO` → JSON with tone percentiles, clipping, colour cast,
   skin presence/brightness, noise, detected device (`meta.source_class`), and `flags`. `skin_present` comes from a crude
   colour detector that red walls, wood and amber bottles also trigger: confirm there are people before acting on the skin rows.
2. **Look.** View the photo yourself. If it isn't a directly viewable format (HEIC, DNG, RAW), render a neutral preview first:
   `python3 scripts/grade.py PHOTO --look none --preview --out $WORK/neutral.jpg` and view that.
   Note the subject, the light, what should draw the eye, and anything the numbers miss.
3. **Decide.** This is the part only you can do. Work out what the photo *is* and pick the matching scene from the look
   (`--list-looks` lists their names; `references/grading-guide.md` → Scenes says when each applies): `night` (the default, also most landscapes),
   `lit-subject-in-dark`, `daylight`. Two more are opt-in styles, used only when the user asks for that feel:
   `quiet-luxury` (warm sepia toning, no whites, old-money look) and `cool-muted` (cold, washed out). Even when asked,
   check the subject suits the style (the guide's Scenes table says what does); if it doesn't, say so and show the base
   instead of a filter-looking result. Then look at what's in frame and adjust for it: light sources and flex items
   (watches, jewellery, bottles, chrome) keep their highlights; skin stays natural; black outfits keep texture.
   Round 1 runs the scene defaults with no overrides. After that, put overrides in `$WORK/params.json` so iterations are reproducible, and only override what you can
   justify from the diagnosis or the compare. Rendering two scenes' defaults side by side to choose between them is part of
   deciding, not one of the rounds.
   **Local edits.** Not every edit should be global. When one region needs something the rest doesn't (a face in shadow, a
   sky that steals attention, a background competing with the subject, a watch or bottle that should glow), add a `masks` list
   to your params (guide → Masks). Place radial and linear masks by looking at the photo, render, and **check the
   `<out>_masks.jpg` overlay** (each mask tinted; written with `--preview` or `--compare`, never beside a delivered file) before
   judging the edit: fix placement first, amounts second. `analyze.py`'s `regions` gives the centre and size of the brightest
   blob, the skin blob and the darkest area to start from. If the user names a local problem (a dark face, a blown lamp),
   round 1 may include the mask for it on top of the scene defaults; add `--crop X,Y` on that region so you judge it at 1:1. Keep amounts
   modest (the engine clamps them) and look for halos in the detail crops. Masks ride on top of the global grade, so the
   calibrated look stays intact.
4. **Preview.** Round 1: `python3 scripts/grade.py PHOTO --look dark-larp --scene night --preview --compare --out $WORK/preview1.jpg`;
   later rounds add `--params $WORK/params.json`. The script prints a JSON report: before/after stats and `effective_params`,
   the values that actually ran (a scene **replaces** the base's values for the keys it sets; it doesn't add to them).
   View `$WORK/preview1_compare.jpg` for the overall mood and `$WORK/preview1_detail.jpg` (1:1 crops of the brightest, the
   darkest-textured and the skin region, before | after) for highlights, texture and skin.
5. **Critique** the before|after against this checklist, adjust, re-preview. Stop after 3 rounds or when it passes:
   - Subject reads clearly; the eye goes where it should.
   - Skin looks like skin — not grey, green, or orange — unless the user asked for a stylised look.
   - Dark clothing/gear still has texture (common in LARP shots: black outfits, leather, armour). If it's a flat blob, raise `shadows` or lower the `blacks` crush.
   - Large whites (shirts, knitwear, snow, paper; not lamps or other light sources, which go cream under the warm base by design) stay white: grey means raise `highlights` or `whites`; yellow means lower `wb.temp`.
   - No halos: a lifted face or a burned sky must not show a glow or a dark ring at the mask edge in the detail crops. If it does,
     widen `feather`, turn on `refine`, or reduce the amount.
   - Highlights have punch but aren't blown into flat white patches (report `after.clipped_highlights_frac` under ~0.02).
   - Mood is dark, not muddy: if everything sits in the mids, add `contrast` or `highlights` instead of just darkening.
   - A **lit person against black** (`lit-subject-in-dark`) doesn't need to get darker: clean blacks and a readable subject is the
     goal, and lifting the floor slightly is the author's own move there. Everything else that is dim (a bar, a restaurant, a
     lamp-lit table) gets the full `night` darkening even when much of the frame is black; the author roughly halves the median
     on those. If the user says they can't see something, lift that thing with a mask instead of lightening the frame.
6. **Deliver.** Render without `--preview` and with `--max-size 4096` (full size for 12 MP phone photos; larger files are
   downsized, and the report's `input_size` vs `size` shows it, so tell the user if their file came back smaller). Put the result where the user will find it: in Claude Code, next to the original
   as `<name>_graded.jpg` unless they name a folder; in claude.ai, `/mnt/user-data/outputs/`. If they want full size for a 24 MP
   phone photo, rerun with `--max-size 6000` (needs about 4 GB of RAM).
   Share the image and at most 2–3 short plain-language bullets on what you did ("pulled the background down", "kept the lamp
   bright"). No numbers or setting names unless asked (see below).
   Offer quick tweaks ("moodier", "warmer", "less saturated", "brighter face") and map them to parameters with the guide's phrase table.
   Keep `$WORK/params.json` for the session; if the user loves the result, offer to save it as a new look in `looks/`.
   Every delivered JPEG carries its full recipe (scene, every setting, every mask, before/after numbers) in its metadata.

**If the user asks what exactly you changed** (now or in a later session): run `python3 scripts/explain.py <delivered.jpg>`
and give them its list, value by value, in their words where it helps ("brightness −0.33: mid-tones pulled down about a
third, lights left alone"). `--json` prints the raw recipe; `--params FILE` writes the settings back out so you can re-render
the same edit with a tweak (`--params FILE` on grade.py) without redoing the work. If the file has no recipe (metadata
stripped by a messaging app, or not a file you delivered), say so rather than guessing.

**Several photos from one shoot:** settle the params on the most representative frame, then apply them to the rest,
switching scene where a frame differs (e.g. one daylight shot in a night set). Check each compare image briefly for skin and blacks.

## Honesty and limits

- Local edits are limited to masks (radial, linear, luminosity, colour range, or a supplied mask image). There is no
  retouching, object removal or generative fill; say so if a photo needs those.
- Never alter content. This is grading, not generative editing.
- The default look is an early version; if the user describes their own taste, that beats the look file.

## Files

- `scripts/analyze.py` — measurements + flags (JSON).
- `scripts/grade.py` — the renderer. `--set key.sub=value` for one-off overrides, `--params file.json` for many, `--look none` for neutral.
- `scripts/ingest.py` — format/device handling (JPEG, PNG, WebP, TIFF, HEIC, DNG, camera RAW; iPhone Display P3 → sRGB).
- `scripts/explain.py` — reads the recipe embedded in a delivered JPEG and lists exactly what changed; `--params` re-exports it.
- `looks/*.json` — named looks, each with scene variants (`--scene`). `looks/_sources.json` — small per-device offsets applied automatically (`--no-source-adjust` to skip).
- `references/grading-guide.md` — parameter reference, diagnosis table, phrase → parameter map. Read it before step 3.
