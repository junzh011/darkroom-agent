# Grading guide

## Order of operations (fixed)

exposure + white balance (linear light) → highlights/shadows → blacks/whites → brightness → contrast → fade → white anchor → curves
→ HSL → vibrance/saturation → colour grade → LUT → skin protect → clarity → sharpen → halation → vignette → grain

## Parameters

All optional; omitted = neutral. Ranges are the useful range, not hard limits.

| key | range | what it does |
|---|---|---|
| `exposure_ev` | −2…2 | Stops. Moves everything, highlights included. |
| `brightness` | −1.5…1 | Mid-tones only: black and white stay put. The author's main darkening tool (≈ −0.35). Darkening this way also deepens colour a little. |
| `auto_exposure` | `{median, strength, max_ev}` | Pushes every photo's median toward one target. **Not used in calibrated looks**: the author darkens dark scenes further rather than normalising them. Only for neutral "fix my exposure" requests. |
| `wb.temp` / `wb.tint` | −1…1 | + warmer / + magenta. ±1 ≈ half a stop of red/blue shift. Luminance preserved. |
| `highlights` | −1…1 | − pulls bright regions down (uses neighbourhood brightness, so it behaves like Lightroom's slider, not a curve). |
| `shadows` | −1…1 | + opens dark regions. Use it to keep texture in black clothing. |
| `blacks` | −1…1 | − crushes the black point (sets it to ~`0.12×|blacks|`); + opens the deepest tones. |
| `whites` | −1…1 | + raises the white point; − compresses the brightest tones. |
| `contrast` | −1…1 | S-curve around `contrast_pivot` (default 0.5). Lower pivot (0.35–0.45) = same contrast but darker mids. |
| `fade` | 0…0.1 | Lifts output blacks for a matte/film look. |
| `white_anchor` | `{target, strength, max_median_lift}` | Lifts the brightest ~1% toward `target` with a curve that barely touches mids, capped so the median rises ≤ `max_median_lift` (default 0.10). Keeps specular punch in a dark grade. |
| `curves` | `{master, r, g, b}` | Lists of `[x, y]` points in 0…1, monotone cubic. E.g. cool shadows: `"b": [[0,0.06],[0.5,0.5],[1,1]]`. |
| `hsl.<band>` | `{hue, sat, lum}` each −1…1 | Bands: red, orange, yellow, green, aqua, blue, purple, magenta. `hue` ±1 = ±30°. Ignores near-grey pixels. Skin lives in orange (and a bit of red). |
| `vibrance` | −1…1 | Saturation boost weighted toward muted colours; skin hues get 60% less. |
| `saturation` | −1…1 | Global saturation multiplier. |
| `color_grade` | `{shadows, midtones, highlights}` each `{hue°, sat 0…1, lum −1…1}`, `balance` −1…1, `blend` 0…1 | Three-way colour wheels. Shadow sat above ~0.3 starts tinting neutral dark clothing visibly. |
| `lut` | `{path, strength}` | 3D `.cube` LUT, path relative to the skill root or absolute. |
| `skin_protect` | 0…1 (default 0.6) | Pulls the hue of detected skin back toward the original after colour work. Raise for portraits, lower for stylised looks. |
| `clarity` | −1…1 | Midtone local contrast. Exaggerates compression artifacts on re-saved images. |
| `sharpen` | −1…1 | Fine detail; negative softens. Phone files are already sharpened. |
| `halation` | `{amount 0…0.3, threshold, radius, color}` | Warm glow around bright areas (film halation). `radius` is a fraction of the long edge. |
| `vignette` | `{amount −1…1, midpoint, feather}` | − darkens edges. |
| `grain` | `{amount 0…1, size, seed}` | Luminance grain, strongest in mids. |

Hue reference: 0 red · 30 orange · 60 yellow · 120 green · 180 teal/cyan · 205 steel blue · 240 blue · 280 purple · 320 magenta.

## Scenes (measured from the author's own edits)

Pick the scene by looking at the photo, then pass `--scene`. Values are in `looks/dark-larp.json`.
Each scene comes from only 1–3 example edits, so treat the numbers as a starting point and use your eyes.

| scene | when | what changes vs. the base | from |
|---|---|---|---|
| `night` | The default. Night/indoor scenes lit by lamps, candles, LED strips, and also most landscapes | Base signature: `brightness −0.33`, `exposure −0.14`, `wb.temp +0.19`, `saturation +0.07`. Lights stay bright. | 8 edits; scored on photos it wasn't built from, error 0.070 → 0.029 |
| `lit-subject-in-dark` | A lit person/outfit/watches against near-black | Adds `contrast +0.2`, `shadows +0.2`, opens deep blacks a little so the subject keeps texture | 1 edit |
| `daylight` | Daytime street, cars, architecture, hard sun | Much darker: `exposure −0.55`, `contrast +0.17`, `blacks −0.23`; little extra saturation | 1 edit |
| `cool-muted` | **Opt-in only**, when the user asks for a cold, washed-out look | Muted (`saturation −0.5`), cooler, clouds kept bright with `highlights +0.9`, no brightness drop | 1 edit. Tested on 3 landscapes and was wrong for them, so never pick it just because a photo is a landscape |

If a photo fits none of these, use `night` and adjust. Say which scene you treated it as.

**How much to darken is your call, from what's in frame** (each seen once in the author's edits):
- Already moody (heavy grey sky, dim scene): darken less (`brightness ≈ −0.1`) and add `contrast +0.15` instead.
- Snow, white peaks, bright sky against dark rock: keep the brights (`highlights +0.35`) and deepen blacks (`blacks −0.25`).
- Bright, flat daylight: darken more (see `daylight`).

## Diagnosis → adjustment

| analyze.py says | and you see | do |
|---|---|---|
| `underexposed` | subject hard to read | Usually intentional in this style: keep it dark but add `shadows +0.2` so the subject reads. |
| `overexposed` / `highlights_clipped` | blown sky/lights | `highlights −0.5`, `whites −0.3`; lower `white_anchor.target` to ~0.8. Clipped data can't be recovered, only toned down. |
| `low_contrast_flat` | hazy, grey | `contrast +0.15…0.3`, `blacks −0.1`. Usual for camera RAW and ProRAW. |
| `shadows_already_crushed` | black clothing is a blob | `shadows +0.3`, `blacks 0` or `+0.1`, `fade 0`. |
| `warm_cast` / `cool_cast` (confidence > 0.05) | cast isn't intentional (tungsten room, shade) | `wb.temp` opposite by about `temp_stops` (e.g. temp_stops 0.4 → `wb.temp −0.6`). Leave golden hour/neon alone. |
| `skin_present` + `skin_dark` | face lost in shadow | `shadows +0.3`, `skin_protect 0.8`, less vignette. Mention local dodge would do better. |
| `noisy` | night/indoor | `grain` up to cover noise, `sharpen 0`, `clarity ≤ 0.1`. |
| `no_exif_maybe_recompressed` | blocky JPEG | `sharpen 0`, `clarity 0`, `grain 0.2–0.4` (hides blocks). |

## Phrase → parameters (for tweak requests)

- "darker" / "moodier": `brightness −0.15` (keeps lights bright); if it's still too light overall, `exposure_ev −0.2`.
- "brighter face" / "can't see me": `shadows +0.3`, `exposure_ev +0.2`, `skin_protect 0.8`.
- "punchier": `contrast +0.15`, `white_anchor.target 0.92`, `clarity +0.1`.
- "crushed blacks": `blacks −0.3`, `fade 0`. "matte" / "faded": `fade 0.05`, `blacks 0`.
- "more teal" / "colder": `color_grade.shadows.sat +0.1`, `wb.temp −0.2`. "warmer": `wb.temp +0.3`.
- "skin too orange": `hsl.orange.sat −0.2`, `hsl.orange.hue −0.1`.
- "more film": `grain.amount 0.5`, `halation.amount 0.2`, `fade 0.04`. "cleaner": grain 0, halation 0.
- "less green": `hsl.green.sat −0.3`, `hsl.green.hue +0.3` (toward teal).

## Device notes (detected as `meta.source_class`)

- **phone_processed** (iPhone/Android HEIC or JPEG): Smart HDR lifts shadows and flattens contrast; heavy sharpening and noise reduction. The looks are calibrated on these files, so no offsets apply. Skin can look waxy; don't add clarity on faces.
- **phone_raw** (iPhone ProRAW DNG): decoded linear with camera white balance, without Apple's tone mapping, so it starts flatter and darker than the Photos app shows. Auto exposure does more work. Needs `rawpy`.
- **camera_raw**: flattest starting point; needs contrast and some sharpening. Needs `rawpy`.
- **camera_jpeg**: already rendered by the camera; neutral.
- **unknown** (no EXIF): screenshot or social-media re-save. Be gentle with sharpening and clarity.
