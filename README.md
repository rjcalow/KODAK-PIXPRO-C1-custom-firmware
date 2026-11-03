# Kodak PIXPRO C1 custom firmware

Unofficial firmware mod for the **Kodak PIXPRO C1** (stock firmware v1.04). It turns the camera's
Color Effect menu into a set of film simulations, adds a "Snap" street-shooting mode, and tunes
sharpening and noise reduction for a more film-like look. It works by patching your own copy of
the stock firmware; no Kodak firmware is included here.

> **Use at your own risk.** This is not affiliated with or endorsed by Kodak or JK Imaging.
> Flashing modified firmware can brick the camera. Keep a copy of the stock `C110.bin` so you
> can flash it back.

## Features

**Film simulations** on the Color Effect menu (the menu still shows them in the stock slots):

| menu slot | film |
|---|---|
| Black and White | Kodak T-Max |
| Sepia | T-Max with a deep red filter |
| Colored Pencil | Kodak Tri-X |
| Negative | Tri-X with a red filter |
| Sketch | Kodachrome |
| Partial Color-Red | Kodak Portra |
| Partial Color-Green | VSCO J3 |
| Partial Color-Blue | VSCO A5 |
| Partial Color-Yellow | VSCO A6 |

Normal, Retro and Vivid stay stock. Each look is fitted from a `.cube` LUT onto the camera's own
image processor (tone curve, colour matrix, saturation), so it is applied in-camera to every JPEG
at no speed cost. The black-and-white films are true monochrome. The films work in every photo
mode and keep that mode's exposure; T-Max and T-Max Red are also on the Movie menu.

**Snap mode** (replaces Landscape): a street-photography mode.
- ISO 200 floor; the shutter holds at 1/100 s while ISO rises to 1600, then the image gets darker
  rather than blurry.
- Fixed hyperfocal focus (about 1 m to infinity), so there is no autofocus delay. Turning macro on
  brings autofocus back.

**Image tuning** (all still photos):
- Sharpening 25 % below stock.
- Noise reduction halved at ISO 800 and above, for grain; slightly stronger at ISO 100–400.

**EXIF:** photos taken with a film record it in ImageDescription (`Preset: Portra`, etc.).

## Status

Every feature has been tested on a real camera except VSCO A6 (the newest addition). The red
filters run and give true monochrome, but their effect has not been confirmed with a side-by-side
test yet. Full details, including what is confirmed and what is not, are in
[FINDINGS.md](C1_v1.04/FINDINGS.md).

## Building

You need the stock v1.04 firmware (`C110.bin`, from Kodak) and Python 3 with numpy, scipy,
pillow, capstone and unicorn.

```bash
python3 -m venv ~/.venv-pixpro
~/.venv-pixpro/bin/pip install numpy scipy pillow capstone unicorn
```

The film LUTs are not included (they are third-party). Put your own `.cube` files in
`lut examples/` with the names listed in `FILMS` in
[tools/build_films.py](C1_v1.04/tools/build_films.py), or point the films at your own LUTs.

Then, from `C1_v1.04/` with the stock `C110.bin` in that folder:

```bash
python tools/build_films.py C110.bin build/C110.bin      # build
python tools/verify_build.py C110.bin build/C110.bin     # must print ALL CHECKS PASSED
python tools/preview.py C110.bin build/film_preview.png  # preview the looks
python tools/test_exif.py C110.bin build/C110.bin        # emulated EXIF test
python tools/test_ae.py C110.bin build/C110.bin          # emulated exposure test
python tools/test_focus.py C110.bin build/C110.bin       # emulated focus test
```

The build never touches the input file and never recompresses the firmware: it patches only the
bytes it changes, and `verify_build.py` checks every change against the stock image.

## Flashing

1. Charge the battery fully.
2. Copy `build/C110.bin` to the root of the SD card, named `C110.bin`.
3. Follow the camera's firmware update procedure (see the C1 manual).

To go back to stock, flash the original `C110.bin` the same way.

## Documentation

- [FINDINGS.md](C1_v1.04/FINDINGS.md): reverse-engineering reference (firmware format, image
  processor structures, colour effects, exposure, focus, with addresses).
- [HOWTO.md](C1_v1.04/HOWTO.md): how to retune a film, add a new one, and verify a build.

## Hardware

Novatek NA51089 SoC (Cortex-A9, RTOS), OmniVision OV13B10 13 MP sensor, 3.57 mm f/2.0 lens.
