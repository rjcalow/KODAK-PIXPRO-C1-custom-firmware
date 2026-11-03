# How to change the Pixpro C1 firmware

Recipes for retuning films, adding features, verifying and flashing. Facts and addresses are
in [FINDINGS.md](FINDINGS.md). Run everything from `C1_v1.04/`.

## 0. Setup
```bash
python3 -m venv ~/.venv-pixpro && ~/.venv-pixpro/bin/pip install numpy scipy pillow capstone unicorn
PY=~/.venv-pixpro/bin/python
```
Inputs:
- `C110.bin`: the stock v1.04 image. **Never modify it.** It is also the recovery file.
- `../lut examples/*.cube`: film LUTs.

All output goes to `build/`.

## 1. Rebuild, verify, preview
```bash
$PY tools/build_films.py C110.bin build/C110.bin      # ~30 s (fits every LUT)
$PY tools/verify_build.py C110.bin build/C110.bin     # must end with ALL CHECKS PASSED
$PY tools/preview.py C110.bin build/film_preview.png  # stock / LUT / camera approximation
$PY tools/test_exif.py C110.bin build/C110.bin       # needs unicorn; must end with ALL EXIF TESTS PASSED
$PY tools/test_ae.py C110.bin build/C110.bin         # needs unicorn; must end with ALL AE TESTS PASSED
$PY tools/test_focus.py C110.bin build/C110.bin      # needs unicorn; must end with ALL FOCUS TESTS PASSED
```
Bump `FW_PATCH` in `build_films.py` for every build you hand over. It goes into the EXIF Software tag.
Read `build/film_preview.png` (it is an image) before handing a build over.

## 2. Retune an existing film
- **Different LUT:** put the `.cube` in `../lut examples/` and change `lut=` for that entry in
  `FILMS` (`tools/build_films.py`).
- **Manual tweaks:** edit `film_profile()`. Keep the order: copy the capture profile, fit,
  then write gamma, Y curve, CCM and saturation.
  - Saturation is byte 0 of each of the 17 `iq_color` records.
  - Tone is the three 129-point gamma curves (0..1023). For raised, filmic blacks add
    `lift=<black 0..255>` to the `FILMS` entry (A5 uses 32). `preview.py` applies it too.
  - Colour is the CCM in Q8, folded into all 4 colour-temperature slots. Keep coefficients
    inside ±2047.
  - **B&W filter** (mono films): `mix=(r, g, b)` is the filter's channel weights, scaled so
    greys keep their brightness. Add `cst=True`, as both red films have since flash 17: a mix in
    the CCM rows has no visible effect on mono captures. `cst=True` drops the node's `iq_ccm`
    and adds an `iq_cst` block whose luma row is fitted to the mix (`fit_lut.luma_row`). Each
    coefficient must fit a 9-bit signed register (−256…255 in Q8), so red can't go above 1.0.
    The build prints the row, and `verify_build` checks it against the stock default. Tri-X Red uses (0.85, 0.20, −0.05) (red, #25-like), T-Max Red
    (1.0, 0.0, −0.15) (deep red, #29-like). Skies get darker mainly through the negative blue
    weight; more red alone barely changes things once skin and reds are near white. Every step
    adds noise. `preview.py` shows the film without the filter in
    the middle tile and with it on the right.
- Retuning changes only DTB data, so the RTOS patch is identical. This is the lowest-risk kind
  of build.
- **Sharpening** (all still photos, Normal included): set `SHARPEN` in `build_films.py`
  (1.0 = stock, 0.75 = flash 8, the user's choice). It scales `edge_enh_p/n` in the capture profile's `iq_edge`
  (FINDINGS §4). `preview.py` does not simulate sharpening; judge it from camera photos.
- **Noise reduction** (all still photos): `DENOISE_LOW` (1.15 since flash 15) scales the `iq_nr`
  range filters on records 1..`DENOISE_FROM`−1 (ISO 100–400), `DENOISE` (0.5 since flash 9) those
  on records `DENOISE_FROM`..16 (record r = ISO 100·2^(r−1); 4 = ISO 800). 1.0 = stock. Chroma NR
  is not touched. Low-ISO values are small integers (ISO 100 filter B max 5), so small changes
  round unevenly. Not simulated by `preview.py` either.
- **Menu order** of the films = case order. To move a film between two new-node slots, swap
  `case` and `sid` of the two `FILMS` entries (labels follow the slot). Cases 5 and 7 are tied to
  the colorpencil nodes.
- **Snap exposure:** edit `SNAP_NODES` / `SNAP_EXPT_MAX` / `SNAP_ISO_MAX` in `build_films.py`
  (FINDINGS §9). Nodes must not decrease. In auto ISO nothing faster than one flicker period
  (1/100 s) can be held. `test_ae.py` prints the resulting program line; update its expected
  rows when you change the curve.
- **Snap focus distance:** `SNAP_FOCUS_MM` in `build_films.py` sets K (`snap_k()`). If far
  subjects are soft, raise it (focus farther; ∞ ≈ K 38). If ~1.5 m is soft, lower it.
  `test_focus.py` follows K automatically.

## 3. Add a film on another colour-effect slot
1. **Pick the case and confirm its menu name.**
   - Ask the user for the Colour Effect menu order on screen, or prove the name from the
     effect's implementation (FINDINGS §5).
   - Do not trust names guessed from fx values.
   - Find the menu's string id in the English table (FINDINGS §5).
   - Since flash 16 only cases 0 (Normal), 1 (Retro), 4 (Vivid) and 11 (Partial Color-Yellow)
     are left. Cases 1–4 are also in the Movie menu, where the film is loaded over the movie
     profile. A film on case 11 also frees the case 10/11 stock bodies again.
2. **Add a `FILMS` entry:**
   ```python
   'ov13b10_portra': dict(name='Portra', sid=<string id>, lut='portra.cube', mono=False,
                          new=True, case=<0-11>, exit=EXIT_FX0),
   ```
   - The 80-byte reload stub is allocated in `FREE_CODE` automatically (optional `stub=` pins it).
     The build stops if free code runs out (248 B left after flash 16: one more stub; FINDINGS §6
     lists two stock case bodies that could be proven dead for more).
   - A stock case body becomes free code only when all cases sharing it are films
     (`DEAD_CASE_CODE`); cases 0, 1, 3 and 4 have no entry there yet.
     Moving a film off a slot can also take a range out of `FREE_CODE` (flash 16, case 11); the
     allocator then moves the unpinned stubs, and `verify_build` checks the result. Prove a new one dead first
     (FINDINGS §6).
   - `exit`: `EXIT_FX0` for colour films, `EXIT_FX1` to also apply the B&W effect (all mono films).
   - The node is cloned from `ov13b10_iq_0_cap` and keeps only `FILM_BLOCKS`, a partial profile
     of 6.8 KB (FINDINGS §4). The DTB has room for ~5 more (40 KB free after flash 14).
3. **String space.** Labels and the `/isp/iq/<node>` path must fit in `STRING_AREAS` (five
   debug printf formats, full since flash 18). Strings that do not fit spill to `STRING_SPILL`
   (the dead case 10/11 body, flash 18). The script asserts each area ends in
   `\x1b[0m\0` and refuses to overflow. Candidates for more: FINDINGS §6.
4. Rebuild, verify and preview (§1). `verify_build` checks:
   - each new case points to a stub in `FREE_CODE` that matches the stock short path, loads
     `/isp/iq/<node>` and `"null"`, and exits with fx 1 for mono films, fx 0 otherwise;
   - only the jump table and the patched call sites branch into `FREE_CODE`;
   - the label shows in all 27 tables;
   - the node holds only `FILM_BLOCKS`, with the capture profile's sizes and version-info.
5. Disassemble the stub (its address is in `verify_build`'s jump-table list) and compare it
   with the stock short path:
   ```bash
   $PY tools/nvtfw.py unpack build/C110.bin /tmp/built
   $PY tools/armdis.py /tmp/built/part_id6_rtos_base0x10000.bin 0x4209EC 0x420A3C   # A5 stub
   $PY tools/armdis.py /tmp/built/part_id6_rtos_base0x10000.bin 0x42146C 0x4214B4
   ```
   The `add r1, pc, r1` lines must resolve to your path and to `"null"`.

## 4. Other kinds of change (patterns)
- **Word patch in the RTOS:** inside `rtos_edits()`, use `word(addr, new, expected_old)`. It
  asserts the stock value, so a wrong address fails loudly. `bcl1patch.patch()` handles
  compression and `fix_rtos_checksum()` the image checksum. Never recompress the stream.
- **New code:** place it only in `FREE_CODE`, and prove first that nothing branches into the
  range (scan the disassembly for branch targets). The code is PIC: build addresses as
  `ldr rX,[pc,#lit]; add rX,pc,rX` with `lit = target − (add_addr + 8)`. Use
  `bl_insn` / `b_insn`.
- **New strings:** use debug-only printf formats (FINDINGS §6). Never touch a string that is
  used as data.
- **DTB edits:** use the `nvtfw` tree API (`find`, `clone`, remove from `children`). The ISP
  DTB must stay ≤ 0x40000. Node names are free; the firmware reaches nodes by path.
- **Labels:** repoint `{ptr,len}` for the string id in **all 27** tables. `language_tables()`
  finds them, including the unterminated last one.

## 5. Investigating something new
- Unpack: `$PY tools/nvtfw.py unpack C110.bin /tmp/stock`. You get partitions, the
  decompressed RTOS (`part_id6_rtos_base0x10000.bin`) and DTB text dumps.
- Full annotated disassembly (~45 s):
  `$PY tools/armdis.py <rtos.bin> 0x10000 0x7e0000 > full.txt`. Then grep for a string; its
  references show as `; =0xADDR "text"`.
- Strings are reached by PIC `add rX, pc, rX`. A raw pointer search only finds data tables.
- `__func__` strings name functions, e.g. `"PhotoExe_OnColor"`. Logs look like
  `\x1b[1;31mERR:%s() ...`.
- IQ struct meaning: match a memcpy size in an `iqt_api_*` handler against the DTB blob size,
  then compare stock values across profiles and ISO levels.

## 6. Flashing (the user does this)
1. Charge the battery fully. The updater refuses on low battery.
2. Copy `build/C110.bin` to the **SD card root** as `C110.bin`. Run the update the same way
   as Kodak's official update.
3. Keep stock `C110.bin` for recovery. Flashing it the same way restores stock. If the
   camera won't boot, u-boot / the loader have an SD update path (not tested).
4. After flashing, the user checks:
   - **Normal** looks unchanged apart from intended changes (since flash 8: sharpening 25 % below stock);
   - each film label gives the expected look;
   - JPEG quality is normal.

Record the result in FINDINGS §8.

## 7. Pitfalls already hit
- Effect names inferred from fx values were swapped (fx 7 = Sketch, fx 8 = Colored Pencil).
  Confirm names on the camera.
- Some patch bytes sit inside LZ copy tokens. That is why `bcl1patch` splits tokens instead
  of patching literals only.
- `str.replace` on `"""` corrupted every docstring in a script once. Edit docstrings
  precisely.
- `dis.py` as a script name shadows Python's stdlib `dis` and breaks capstone. Run scripts
  with `python -I`.
- The `ldr r1,[pc,#x]` annotations in `armdis` show raw deltas (sometimes as false strings).
  The following `add rX, pc, rX` line shows the real target.
