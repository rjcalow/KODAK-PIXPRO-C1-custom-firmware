# Kodak Pixpro C1: custom film-simulation firmware

The project patches the camera's stock firmware v1.04 (`C1_v1.04/C110.bin`; Novatek NA51089,
OV13B10 sensor) to add film simulations on reused Colour Effect menu slots. The user flashes
builds from the SD card and reports results.

- **Reference** (formats, addresses, struct layouts, what is confirmed): `C1_v1.04/FINDINGS.md`
- **Recipes** (retune, add a film, verify, flash, investigate): `C1_v1.04/HOWTO.md`

Read both before changing anything.

## Current state
In menu order (= case order):

| menu slot | label | look |
|---|---|---|
| Black and White | T-Max | `kodak_t-max_3200.cube` (flash 14; also the Movie menu's entry) |
| Sepia | T-Max Red | T-Max + deep red, luma row [255, 25, −24] in `iq_cst` (flash 17; also a Movie menu entry) |
| Colored Pencil | Tri-X | `kodak_tri-x_400.cube` |
| Negative | Tri-X Red | Tri-X + red filter, luma row [214, 61, −19] in `iq_cst` (flash 17; here since flash 15, next to Tri-X) |
| Sketch | Kodachrome | `kodakchrome.cube` |
| Partial Color-Red | Portra | `kodak_portra_160_nc.cube` (flash 13) |
| Partial Color-Green | VSCO J3 | `J3_64.cube` (on Negative until flash 14) |
| Partial Color-Blue | VSCO A5 | `A5_64.cube` + shadow lift (`lift=32`) (on Partial Color-Yellow until flash 15) |
| Partial Color-Yellow | VSCO A6 | `A6_64.cube` + shadow lift (`lift=32`, as A5) (flash 18) |

New film nodes are partial profiles (only gamma, Y curve, CCM, colour; FINDINGS §4 "Profile
loading"). Normal, Retro and Vivid are stock (the only free slots left).

EXIF: ImageDescription = "Preset: <film>" on film slots (stock text otherwise), Software =
"Ricardos custom firmware <FW_PATCH>".

- Sharpening on all still photos is 25 % below stock (`SHARPEN = 0.75` in `build_films.py`, the
  user's choice). Noise reduction is halved at ISO 800 and up (`DENOISE = 0.5`,
  `DENOISE_FROM = 4`); the user wants grain for a film look. Since flash 15 it is 15 % above
  stock at ISO 100–400 (`DENOISE_LOW = 1.15`): the user found the grain too much there.
- Shooting mode Landscape is now **Snap** (FINDINGS §9): ISO 200 floor, shutter held at 1/100
  while ISO rises to 1600, then darker. Data-only. The user wanted a 1/250 hold, but that needs
  AE-generator code (anti-flicker), and they chose data-only. Snap also has fixed hyperfocal
  focus with macro off (new code; FINDINGS §9 "Snap fixed focus"; 2.8 m via `SNAP_FOCUS_MM`,
  camera-tested ≈ 1 m–∞ in flash 11).
- Choosing a colour effect re-applies the shooting mode's AE curve (flash 12), so films keep each
  photo mode's exposure. The user asked for presets to work in every mode.
- Flash 11 crashed in Snap (take a photo, review it, press zoom-out). Flash 12 reworked the focus
  code to minimise deviation from stock (FINDINGS §9) and fixed it.
- The latest build is `C1_v1.04/build/C110.bin` (flash 18, built 2026-11-02, **not yet camera-tested**):
  flash 17 + VSCO A6 on Partial Color-Yellow. String areas are full; extra strings spill to
  `STRING_SPILL` (dead case 10/11 body). Flash 17 is kept as `C1_v1.04/build/C110_flash17.bin` (
  flash 17: Tri-X Red and T-Max Red filters in
  the RGB→YCC luma row, `iq_cst`, as stock Sepia makes mono). Built 2026-10-30; **runs on the
  camera** (T-Max Red sample, true mono); the filter's effect is not yet confirmed (no same-scene T-Max shot). Flash 16 (same layout, CCM-based filters) runs on the camera, but T-Max Red
  looked the same as T-Max (measured, FINDINGS §8); kept as `C1_v1.04/build/C110_flash16.bin`. The
  last fully confirmed build is flash 15 (`C1_v1.04/build/C110_flash15_confirmed.bin`). Next
  build: bump `FW_PATCH` to 19.
- Mono films: a channel mix in the CCM rows has no visible effect on captures (cause unknown).
  Do B&W filters with `cst=True` (HOWTO §2), not the CCM. The user is sure the colour films
  get their looks.
- **Plan of work: `C1_v1.04/ROADMAP.md`** (film lineup, screen-flip fix, the user's decisions).
- Update the history table in FINDINGS §8 whenever the user reports a flash result.
- FINDINGS.md is written for public release (GitHub): neutral wording ("on the camera", not "the
  user"), no sample-photo file names or scene details beyond what a measurement needs, no
  location hints, no local `build/` file names. The pre-public version is in
  `build archive/FINDINGS_before_public_edit_2026-11-03.md`.
- LUTs are in `lut examples/`.

## Commands (run in `C1_v1.04/`, Python with numpy, scipy, pillow, capstone, unicorn)
```bash
python tools/build_films.py C110.bin build/C110.bin      # build (config: FILMS in that file)
python tools/verify_build.py C110.bin build/C110.bin     # must print ALL CHECKS PASSED
python tools/preview.py C110.bin build/film_preview.png  # view the PNG before handing over
python tools/test_exif.py C110.bin build/C110.bin       # needs unicorn; ALL EXIF TESTS PASSED
python tools/test_ae.py C110.bin build/C110.bin         # needs unicorn; ALL AE TESTS PASSED
python tools/test_focus.py C110.bin build/C110.bin      # needs unicorn; ALL FOCUS TESTS PASSED
```

## Rules
- **Never modify `C1_v1.04/C110.bin`.** It is the input and the user's recovery image. Write
  output to `build/`.
- **Never recompress the RTOS.** Change it only through `bcl1patch.patch()`, and every word
  patch must go through `word(addr, new, expected_stock)`.
- **Every build must pass `verify_build.py`.** For new code, also disassemble it and compare
  it with the stock code it imitates.
- **Don't name a menu slot from guesswork** (fx-based guesses were wrong once). Get the
  on-screen menu order from the user, or prove the name from the effect's code.
- The ISP DTB must stay ≤ 0x40000 bytes. New code goes only in the proven-dead ranges
  (`FREE_CODE`); new strings only in debug printf formats (`STRING_AREAS`).
- **The user prefers the lowest-risk option.** Say what is untested before they flash, and
  tell them to keep the stock `C110.bin`.
- Flashing is the user's action: copy the build to the SD root as `C110.bin`.
