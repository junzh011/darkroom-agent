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
| `auto_exposure` | `{median, strength, max_ev, max_lift}` | Pushes every photo's median toward one target; `max_lift 0` makes it darken-only. **Not used in calibrated looks**: the author darkens dark scenes further rather than normalising them. Only for neutral "fix my exposure" requests. |
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
| `skin_protect` | 0…1 (engine default 0.6; the moody look sets 0.5) | Pulls the hue of detected skin back toward the original after colour work. Raise for portraits, lower for stylised looks. |
| `clarity` | −1…1 | Midtone local contrast. Exaggerates compression artifacts on re-saved images. |
| `sharpen` | −1…1 | Fine detail; negative softens. Phone files are already sharpened. |
| `halation` | `{amount 0…0.3, threshold, radius, color}` | Warm glow around bright areas (film halation). `radius` is a fraction of the long edge. |
| `vignette` | `{amount −1…1, midpoint, feather}` | − darkens edges. |
| `grain` | `{amount 0…1, size, seed}` | Luminance grain, strongest in mids. |

Hue reference: 0 red · 30 orange · 60 yellow · 120 green · 180 teal/cyan · 205 steel blue · 240 blue · 280 purple · 320 magenta.

Report stats are measured at render resolution, so `--preview` and full-size numbers differ slightly (p99, clipping fractions).
Compare before and after within one report, and treat thresholds as approximate.

## Scenes (measured from the author's own edits)

Pick the scene by looking at the photo, then pass `--scene`. Values are in `looks/moody.json`.
A scene's values **replace** the base's for the keys it sets (they don't add to them), so read `effective_params` in the
report to see what actually ran.
Each scene comes from only 1–3 example edits, so treat the numbers as a starting point and use your eyes.

| scene | when | what changes vs. the base | from |
|---|---|---|---|
| `night` | The default. Night/indoor scenes lit by lamps, candles, LED strips, and also most landscapes | Base signature: `brightness −0.33`, `exposure −0.14`, `wb.temp +0.19`, `saturation +0.07`. Lights stay bright. | 8 edits; scored on photos it wasn't built from, error 0.070 → 0.029 |
| `lit-subject-in-dark` | A lit **person**, outfit or watches against near-black (a third or more of the frame already black). People only: a lit table, food, drinks or objects against black stays on `night` (the author's own lamp-table edit, 06, went to mids 0.011); answer a visibility complaint about the food with a mask on top of `night`, not by switching scene | Effective values: `exposure +0.04` (base is −0.14), `contrast 0.19`, `shadows +0.19`, `blacks +0.28`. It deliberately **lifts** the black floor and the median a little: the author's edit of a near-black car interior opened the blacks so the subject reads. Don't "fix" that by darkening. On an already-dark input, dark and moody means clean blacks and a readable subject, not less light | 1 edit (05). The scene default scored 0.015 against the author's edit; a darkening override scored 0.026 |
| `daylight` | Bright daytime (input mids above ~0.38): street, cars, architecture, sunlit mountains | Not a fixed darkening: normalises exposure toward mids ≈0.35 (`auto_exposure` median 0.48 before the brightness drop, lift capped at +0.1 EV), then `contrast +0.12`, `blacks −0.15`. Dim or overcast daytime (mids below ~0.38) stays on `night` | 3 edits (04, 07, 10); error vs the author's edits 0.020, versus 0.070 for the old fixed −0.55 EV version |
| `cool-muted` | **Opt-in only**, when the user asks for a cold, washed-out look | Muted (`saturation −0.5`), cooler, clouds kept bright with `highlights +0.9`, no brightness drop | 1 edit. Tested on 3 landscapes and was wrong for them, so never pick it just because a photo is a landscape |
| `quiet-luxury` | **Opt-in only, and only when the subject suits it:** classic or old stone architecture, vintage cars, candlelit or wood interiors, autumn streets, muted natural materials. It does **not** suit modern glass and steel, coloured lighting (LED strips, a red bar wall), strong single-colour subjects or blue-hour skies; there it reads as a filter. If the photo doesn't fit, say so and show `night` instead | A different kind of look: the whole frame is toned warm (`color_grade` at hue 25), weak colours are muted while strong subject colours survive (`vibrance −0.55`), whites are capped at ~0.8, and exposure is normalised dark (`auto_exposure` median 0.18, darken-only). Skin protection is off on purpose. | Measured from 8 online reference photos, not the author's edits. Tried on the author's modern-city, bar and table photos and rejected: the subjects didn't fit, at any strength. Fit matters more than strength |

If a photo fits none of these, use `night` and adjust. Say which scene you treated it as.

**How much to darken is your call, from what's in frame** (each seen once in the author's edits):
- Already moody **daytime** (heavy grey sky, overcast, flat light): set `brightness −0.1` and `contrast 0.15` (absolute values,
  not added to the base) instead of the full darkening. This came from an overcast mountain edit and does **not** apply to dim
  night interiors: on bars and restaurants the author still roughly halves the median (03: 0.086 → 0.036), so the `night`
  default is right there.
- Snow, white peaks, bright sky against dark rock: keep the brights (`highlights +0.35`) and deepen blacks (`blacks −0.25`).
- Bright, flat daylight: darken more (see `daylight`).
- **Dark subject in daylight** (open water, dark hillsides or forest, a dark interior with a bright window, a marina at dusk): this is a dark scene even if the phone's HDR made the input bright. Use `night` (darken relative) rather than `daylight`, and let the water or hills go deep while the few highlights stay bright. Measured from reference edits at mids 0.07–0.23 with highlights 0.67–0.84.
- **Open daylight street scenes** in the reference edits sit at mids 0.39–0.43, a touch lighter than the author's own 0.34–0.37; if a daylight result looks heavy, `exposure_ev +0.1` is within taste.
- **Low-key inputs** (a third or more of the frame already black): the median barely moves whatever you do, so judge the lit
  subject areas in the compare, not `p50`.

## Masks (local edits)

Masks ride on top of the finished global grade, so they never disturb the calibrated look. Put a `masks` list in your params;
each entry is `{"name", "type", ...placement, "invert", "opacity", "refine", "adjust": {...}}`. Coordinates are fractions of
the image (x right, y down, 0…1) in the displayed frame, the same one you see in the previews; `radius` is a fraction of the
long edge. `analyze.py` → `regions` gives `center` and `size` for the brightest blob, the skin blob and the darkest area:
start a mask at that centre with radius ≈ half the larger size. Every render with masks also writes
`<out>_masks.jpg` with each mask tinted (red, cyan, yellow, green in order): **check it before judging the edit.**
The report lists each mask's `coverage` (share of the frame above 50% weight); near-zero coverage means it missed.

| type | placement fields | typical use |
|---|---|---|
| `radial` | `center [x,y]`, `radius`, `aspect` (>1 taller), `feather` 0…1 | lift a face or subject; inverted, burn everything else |
| `linear` | `from [x,y]` (full strength) → `to [x,y]` (zero) | pull a sky down from the top edge; darken a foreground |
| `luminosity` | `lo`, `hi`, `feather` (luma 0…1, measured on the graded image) | tame the brightest 10%; lift only deep shadows |
| `color` | `hue`°, `width`°, `feather`°, `min_sat` | mute a distracting colour; deepen one |
| `image` | `path` to a mask image (white = selected) | person or sky masks from an external tool |

`adjust` takes: `exposure_ev`, `brightness`, `contrast`, `highlights`, `shadows`, `whites`, `blacks`, `saturation`, `vibrance`, `wb`,
`clarity`, `sharpen`. Amounts are clamped (exposure ±1 EV, brightness ±0.6, most others ±0.5) and anything else is ignored with
a warning. `refine: true` snaps the mask to real edges in the image (a guided filter), which is what keeps a face lift from
looking like a spotlight; use it on radials over people and objects, not on skies.

Geometry: a `radial` is at full strength inside `radius × (1 − feather)` and fades to zero at `radius`; `aspect` multiplies the
vertical radius (>1 = taller). With feather 0.5 the full-strength core is only half the radius, so size the radius to the whole
subject, not its centre. Masks apply in list order, each on the result of the previous one; `luminosity` and `color` masks
measure the image as it is when they run. Where masks overlap the later one wins, so list the mask that must have the final
say last (a lamp burn after a table lift).

**When to reach for a mask** (judgment, not rules; each from the author's photos or references):
- Face or subject darker than the author would leave it (`skin_dark`, or you can see it): radial over the subject,
  `exposure_ev +0.2…+0.4`, `shadows +0.2`, `refine: true`, feather ≥ 0.5. Pair it with an inverted radial at
  `exposure_ev −0.2…−0.4` so the subject reads by contrast rather than by brightness alone.
- A sky or bright background that pulls the eye off the subject: linear from the top edge, `exposure_ev −0.3…−0.6`;
  on a flat white sky add `saturation −0.1` so it goes grey, not blue.
- Flex items (watch faces, jewellery, bottle labels, chrome) lost in a dark grade: small radial, `exposure_ev +0.2`, `clarity +0.2`.
- A blown practical light (lamp shade, candle, neon): small radial on it, `highlights −0.3…−0.5`, `exposure_ev −0.1…−0.2`,
  feather ≈ 0.35 (tight is fine, `highlights` only touches bright pixels). A clipped centre can only be toned down, not
  recovered; tell the user.
- Something the user says they can't see (food, a drink, a detail): lift that thing with a radial on top of the scene the
  photo calls for; don't lighten the whole frame or switch scene to get it. If the complaint was about the original, expect
  the upper half of the lift range (+0.3…+0.4), because `night`'s darkening has to be overcome first.
- One colour shouting (a green exit sign, a red traffic light): `color` mask with `saturation −0.3`.
- Don't mask what the global grade already handles; two masks is usually plenty. Start at the low end of every range.

**Halo check:** with `--compare`, every mask adds a detail-crop row (`mask N edge`) centred where its boundary crosses the
strongest picture edge, which is where a halo would show (chosen at a fixed working size, so preview and final agree);
`--crop X,Y` adds a crop anywhere else you want to look, and the report's `detail.points` says where every crop was taken. A glow or a
dark ring there means the feather is too tight or the amount too high; fix that before anything else.

## Diagnosis → adjustment

| analyze.py says | and you see | do |
|---|---|---|
| `underexposed` | subject hard to read | Usually intentional in this style: keep it dark but add `shadows +0.2` so the subject reads. |
| `overexposed` / `highlights_clipped` | blown sky or lights | Whole frame: `highlights −0.5`, `whites −0.3`. One blown lamp or candle: a small radial mask instead (Masks). Clipped data can't be recovered, only toned down. |
| `low_contrast_flat` | hazy, grey | `contrast +0.15…0.3`, `blacks −0.1`. Usual for camera RAW and ProRAW. |
| `shadows_already_crushed` | black clothing is a blob | If `lit-subject-in-dark` applies, its `blacks +0.28` already handles this. Otherwise `shadows +0.3`, `blacks +0.1`, `fade 0`. |
| `warm_cast` / `cool_cast` (confidence > 0.05; confidence is the share of the frame that was near-neutral and usable for the estimate, not the strength of the cast, which is `temp_stops`) | cast isn't intentional (tungsten room, shade) | `wb.temp` opposite by about `temp_stops` (e.g. temp_stops 0.4 → `wb.temp −0.6`). Leave golden hour/neon alone. |
| `skin_present` + `skin_dark` | face lost in shadow | `shadows +0.3`, `skin_protect 0.8`, less vignette. Mention local dodge would do better. |
| `skin_mask_unreliable` | warm stone, wood, autumn leaves, or an already sepia-toned photo | The detector is reading the scene as skin. Coverage above 25% raises this flag; above 40% `skin_protect` is also reduced automatically (`skin_protect_reduced` in the report). Red walls and amber bottles trigger it too. Judge skin by eye; don't raise `skin_protect` to compensate. |
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
- "old money" / "quiet luxury" / "sepia" / "vintage warm": use `--scene quiet-luxury` rather than hand-tuning. On top of it, "less brown": `color_grade.midtones.sat 0.2`, `wb.temp 0.15`; "keep the sky blue": `hsl.blue.sat 0`.

## Device notes (detected as `meta.source_class`)

- **phone_processed** (iPhone/Android HEIC or JPEG): Smart HDR lifts shadows and flattens contrast; heavy sharpening and noise reduction. The looks are calibrated on these files, so no offsets apply. Skin can look waxy; don't add clarity on faces.
- **phone_raw** (iPhone ProRAW DNG): decoded linear with camera white balance, without Apple's tone mapping, so it starts flatter and darker than the Photos app shows. Auto exposure does more work. Needs `rawpy`.
- **camera_raw**: flattest starting point; needs contrast and some sharpening. Needs `rawpy`.
- **camera_jpeg**: already rendered by the camera; neutral.
- **unknown** (no EXIF): screenshot or social-media re-save. Be gentle with sharpening and clarity.
