# Kodak PIXPRO C1 firmware v1.04 (`C110.bin`): reverse-engineering reference

Notes from reverse engineering the Kodak PIXPRO C1's stock firmware v1.04, and from building a
patched firmware on top of it. The patched firmware adds film simulations on the Color Effect menu,
a "Snap" shooting mode (fixed shutter floor, fixed hyperfocal focus), lighter sharpening, retuned
noise reduction and EXIF tags that name the film used. How to build, verify and flash it is in
[HOWTO.md](HOWTO.md).

> **Unofficial.** Not affiliated with or endorsed by Kodak or JK Imaging. Flashing modified
> firmware can brick the camera. Keep a copy of the stock `C110.bin` so you can flash it back.
> No Kodak firmware is included: the tools patch your own copy of the stock image.

**Confidence tags**
- **[camera]**: confirmed on a real camera.
- **[code]**: proven from code or data.
- **[manual]**: from the C1 user manual.
- **[inferred]**: plausible, not proven.

All RTOS addresses are virtual (load base 0x10000). File offset in the decompressed image =
address − 0x10000. "Flash N" is the Nth patched build tested on the camera (§8).

**Contents:** 1 Platform · 2 Container · 3 RTOS image · 4 ISP DTB · 5 Colour effects, menus,
EXIF, file naming, SD update · 6 Free space · 7 Current patch set · 8 Build history · 9 Shooting
modes, AE, focus, Snap · 10 Screen flip (open)

---

## 1. Platform
- SoC **Novatek NA51089** (Cortex-A9), RTOS (not Linux). Sensor **OmniVision OV13B10**.
- 16 MB SPI NOR.
- The ISP is driven through Novatek HDAL `vendor_isp_get_iq/set_iq(IQT_ITEM, buf)`.
- Lens: 3.57 mm f/2.0, VCM focus (driver FP5510). LCD: ST7789V panel, 8-bit parallel.

## 2. Container (NVTPACK_FW_HDR2) [code]

| off | field |
|---|---|
| 0x00 | GUID `D6012E07-10BC-4F91-B28A-352F82261A50` (constant, not a hash) |
| 0x10 | version `0x16071515` |
| 0x14 | header size `0x80` |
| 0x18 | partition count `5` |
| 0x1C | total file size |
| 0x20 | check method `0` |
| 0x24 | check value (u16) |
| 0x80 | partition table, `{u32 offset, u32 size, u32 id}` × 5 |

- Every partition start, and the file end, sits at `offset % 0x40 == 0x3C`. The gaps are zero
  padding.
- **Checksum (used at every level):** `Σ (u16_le[i] + i) ≡ 0 (mod 0x10000)` over the whole
  item. The check field is solved with itself zeroed. `tools/nvtfw.py` and
  `tools/bcl1patch.py` implement it.

| id | stock offset | size | content | flash partition |
|---|---|---|---|---|
| 1 | 0x000BC | 0x0457E | system DTB | `fdt` @0x10000, 0x40000 |
| **3** | 0x0463C | 0x3CC18 | **ISP DTB: all AE/AWB/IQ tuning** | `fdt.app` @0xC0000, **0x40000 max** |
| 4 | 0x4127C | 0x5BD34 | u-boot | `uboot` @0x100000, 0x70000 |
| **6** | 0x9CFBC | 0x60EF7C | **RTOS app, BCL1-compressed** | `rtos` @0x1B0000, 0xD50000 |
| 8 | 0x6ABF3C | 0x0040F | `fwver.bin` (`OTAVERNUM:1.04;`) | `usr` |

The loader partition (flash 0x0) is **not** in the package, so an update never rewrites it.

## 3. RTOS image [code]
- **BCL1 header** (big-endian): `"BCL1", u16 chk, u16 algo=9, u32 out_size=0xB12368, u32 in_size`.
  - `chk` is the Novatek sum16 that makes the whole blob sum to 0.
  - Payload: Marcus Geelnard BCL `LZ_Uncompress`, marker byte `0xA6`. Tokens: literal byte;
    `A6 00` (an escaped literal A6); `A6 <varlen len> <varlen offset>`, 7-bit big-endian with
    a continuation bit. Offsets count output positions.
- Decompressed image checksum: tag `0x55AA` at 0x26C, value at **0x26E**.
- CODEINFO at file 0x3F0: contiguous sections 0x10000 → 0xB22368; BSS ends 0xD11498.
- ARM mode (not Thumb) up to about 0x790000; rodata/data after that.
- **The UI/app code is position-independent.** Strings are reached as
  `ldr rX,[pc,#lit]; add rX, pc, rX`. GOT-style accesses go through base 0x2B980.
  A plain pointer search finds almost nothing; use `tools/armdis.py`, which resolves these.
- The patcher **never recompresses** the stream: edited literals are rewritten in place, and copy
  tokens that touch an edit become literals (`tools/bcl1patch.py`).

## 4. ISP DTB (partition id 3) [code]
- `/isp/sensor@0` binds:
  - `ae_path` /isp/ae/ov13b10_ae_0
  - `awb_path` /isp/awb/ov13b10_awb
  - `iq_path` /isp/iq/ov13b10_iq (live/movie)
  - `iq_cap_path` /isp/iq/ov13b10_iq_0_cap (stills)
  - `iq_shading_path` /isp/iq/ov13b10_iq_shading
- Each IQ profile node (~26 KB) has 18 sub-nodes. Each sub-node holds `size` (LE u32) and
  `data`, a **raw little-endian C struct**:
  `iq_ob, iq_nr, iq_cfa, iq_va, iq_gamma, iq_ccm, iq_color, iq_contrast, iq_edge, iq_3dnr,
  iq_wdr, iq_shdr, iq_rgbir, iq_companding, iq_rgbir_enh, iq_post_sharpen, iq_ycurve,
  iq_shdr_ext`.
- `ov13b10_iq_shading_1` (67 KB) has no reference anywhere in the firmware or the DTB.
  The patched builds remove it to make room.

### Block layouts
| block | bytes | layout | conf. |
|---|---|---|---|
| `iq_ccm` | 576 | `u32 mode` (0 = auto) + `manual_param` + `auto_param[3]`, each param 0x8C B after a `u32 ct` (auto: 6500/3700/2800): `s16 coef[9]` Q8 (0x100 = 1.0, rows = output R,G,B, stock rows sum 256); `u8 hue_tab[24]` (0x80 = 1.0); 2 pad; `s32 huesat_tab[24]`. Names from the param dump (0x30f658). The hue-bin angle convention is **unknown**. | code |
| `iq_color` | 1772 | `u32 hdr` + 17 per-ISO records × 104 B. **Byte 0 of each record = saturation** (0x80 = 1.0). The rest is not decoded. | code |
| `iq_gamma` | 3732 | 933 × u32. Three **129-point curves, 0..1023**, at word ranges **544–672**, **674–802** and **804–932**. Words 673 and 803 (`6`, `5`) look like LV thresholds. Input index = linear 0..1. Curve 1 is roughly sRGB in the mids, with a steeper toe. Words 85–543 hold 65-point 0..4095 curves (WDR/tone?) with prefixes 25/50/75/100; not decoded. | code / inferred |
| `iq_ycurve` | 520 | `u32 mode` + 129-point Y LUT, 0..255 (identity = `min(255, 2i)`) | code |
| `iq_ob` | 344 | `u32 mode` + 17 ISO × {R, Gr, Gb, B, IR}; black level 256 (12-bit) | code |
| `iq_edge` | 1504 | 19-word header + 17 records × 21 words (record 0 = manual, 1–16 = auto; see below). Header: `u32 enable=1, mode=0 (auto), th_overshoot=128, th_undershoot=64; u8 edge_map_lut[16], es_map_lut[16], edge_tab[24] (0x80); u32 reduce_ratio=64`. Record: `edge_enh_p, edge_enh_n` (**sharpening strength**, clamped 0..1023), `thin_freq, robust_freq, wt_low, wt_high, th_flat_low, th_flat_high, th_edge_low, th_edge_high, u8 str_flat, u8 str_edge (+2 pad), overshoot_str, undershoot_str, edge_ethr_low/high, edge_etab_low/high, es_ethr_low/high, es_etab_low/high`. Field names and offsets from the param dump (strings 0x31405c, code 0x30f9b8: `manual_param` at +0x4C, `auto_param[i]` at +0xA0 + 0x54·i). Stock capture enh_p/n: manual 128; ISO 100…: 90, 90, 90, 80, 42, 60, 80, 110, 50, 40, 30, 90… | code |
| `iq_nr` | 4852 | header 0x18 = `u32 outl_enable, gbal_enable, filter_enable, lca_enable, dbcs_enable` (all 1), `mode` (0 = auto); then 17 records × 0x11C (0 = manual, 1–16 = auto). Record offsets: `+0 u16 outl_ord_protect_th, +2 u8 outl_ord_blend_w, +4 outl_avg_mode, +8 outl_sel, +0xC outl_bright_th[5], +0x20 [5] (dark?), +0x34 u16 gbal_diff_th_str, +0x36 u16 gbal_edge_protect_th,` **`+0x38 filter_th[6], +0x50 filter_lut[17], +0x94 filter_th_b[6], +0xAC filter_lut_b[17]`** (raw-domain range filters A/B = the main spatial NR; th = difference thresholds, lut = threshold against brightness, square-root shaped), `+0xF0 filter_blend_w, +0xF4 filter_clamp_th, +0xF8 filter_clamp_mul, +0xFC lca_sub_center_filter_y/c, +0x104 lca_sub_filter_y/c, +0x10C lca_out_y_wt, +0x110 lca_out_c_wt` (LCA = chroma NR), `+0x114 dbcs_step_y/c`. Offsets from the param dump (strings 0x312c9c, code 0x30ece4). Stock filter_th_b by ISO 100…1600: max 5, 15, 30, 40, 91 (NR ramps steeply at 1600). | code |
| `iq_3dnr` | 8036 | `u32 enable=1, fcvg_enable, mode, …` + manual/auto records (fields in the dump at 0x31479c). Temporal NR; not decoded further, and whether stills use it is unknown. | code |
| `iq_post_sharpen` | 588 | `u32 enable, u32 mode` + 17 × 34 B (`u8 noise_level, noise_curve[17]`, then edge weight/threshold/strength/halo-clip fields) + 2 pad. **enable = 0** in every stock profile, so it does no sharpening. | code |
| `iq_contrast` | 176 | per-ISO table, not decoded | – |

**Per-ISO records [code].** The DTB blob is the param struct as-is: header, `manual_param`, then
16 `auto_param` levels (that's the "17 per-ISO records"). With mode = 0 (auto) record 0 is unused,
which is why it is the same in every profile. The IQ update (0x317410 for `iq_nr`) interpolates
field by field between two neighbouring auto records (scalar 0x31f0b4, array 0x31f1c4), so auto
ISO between steps gets a blend. Auto level i = record i+1 = ISO 100·2^i [inferred: gain-index
convention; the colour-pencil profiles retune exactly records 1–5 = the camera's ISO 100–1600, and
the Retro case changes `iq_color` levels 1–6]. The same layout probably applies to `iq_color`,
`iq_ob` and `iq_post_sharpen` [inferred].

**CCM update [code].** 0x31cb98: mode ≠ 0 copies `manual_param`. In auto it interpolates
`coef`, `hue_tab` and `huesat_tab` between the two `auto_param` slots that bracket the current CT
(`[iq_info+0x640]`), using the scalar interpolator 0x31f0b4, into the final CCM at
`iq_info+0x1a76`. Coefficients are read as 12-bit signed (`> 0x800 → −0x1000`), so ±2047 is the
range. Nothing scales the CCM by ISO. Only `iq_operation_effect` overwrites the final CCM, with a
fixed table when UI param 6 = 1 (0x31d91c, a day/night-style mono mode the camera app doesn't set).

**CCM path to the hardware [code].** Per-frame IPE update (0x335a80 area): CCM update 0x31cb90,
gamma 0x31cddc, `iq_operation_effect` 0x31cfb0, then 0x31dc2c. The alternative branch at 0x3366dc
also returns into it. `final_ipp` pointers (set at 0x33613c, `iq_info` + …):
- `ipe_eproc` 0x1a04;
- `ipe_cc_en` 0x1a48, initialised from a global default (0x3342d4 / 0x3346a0);
- `ipe_cc` 0x1a4c (0x28 B: `cc2_sel`, `cc_stab_sel`, `fstab[16]` at +8, `fdtab[16]` at +0x18, …);
- `ipe_ccm` 0x1a74 (0x14 B: `cc_range`, `cc_gamma_sel`, `s16 coef[9]` at +2);
- `ipe_cctrl_en` 0x1a88, `ipe_cctrl` 0x1a8c, `ipe_cctrl_ct` 0x1ab8.

`fstab`/`fdtab` come from `iq_color` (per-ISO record: `u8 c_con` (saturation), `fstab[16]`,
`fdtab[16]`, …, `u32 cconlut[17]` at +0x24; interpolated at 0x318110). The hardware blends the
matrix output with a second source (`cc2_sel`) by these weight tables. Capture profile (= every
film): `fstab` = 128, 64, 16, then 0 at ISO 200 and up; 32, 16, 0 … 0, 16, 32, 64, 96 at ISO 100.
So it is the same at every ISO from 200, with no high-ISO fade. The ISO 100 pattern (less in the
dark, more in highlights) reads as a suppression table, 0 = full matrix [inferred; polarity not
proven]. `iqt_dtsi_load` sets a block's pointer only when `size` = data length = table size
(0x344724), then copies it; partial nodes load `iq_ccm` the same way as full ones.

**RGB→YCC transform, `iq_cst` [code].** Loader entry 22, size 0x2c:
`u32 mode; s16 cst_coef[9]` (Y, Cb, Cr rows, Q8); `s16 y_ofs` (+0x16); `u8 cb_ofs, cr_ofs`
(+0x18/+0x19); `u8 cstp_ratio` (manual, +0x1a); `u8 cstp_ratio[16]` (auto, +0x1b); pad. Names from
the dump at 0x3116a0.
- No DTB profile has `iq_cst`, so the camera runs on the IQ library's default. 0x34B538 holds 24
  default param pointers in loader order (entries 16–20 are null), and entry 22 → 0x3480EC:
  mode 0, BT.601 (77/150/29, −43/−85/128, 128/−107/−21), offsets 0/128/128, `cstp_ratio` 2.
- IQ item 0x1C (`set_iq`, handler 0x339944) copies into the same param buffer
  (`param[id]+0x58`, table at GOT+0x325C) that `iqt_dtsi_load` fills. A film node's `iq_cst`
  therefore does exactly what stock Sepia's `set_iq(0x1C)` does.
- `iq_operation_effect` copies `y_ofs`, `cb_ofs` and `cr_ofs` into the final registers
  (0x31D610), and the per-frame update interpolates `cstp_ratio` (0x31AC3C → `iq_info+0x1C98`).
  `final_ipp.ipe_cst` sits at `iq_info+0x1C7C` (0x18 B), `ipe_cstp` at 0x1C94.
- **Hardware limit:** the IPE register writer (0x295174) packs each coefficient into a **9-bit
  signed** field (`bfi …, #9`), so the range is −256…255 (−1.0…+0.996 in Q8). The driver accepts
  only CST offset 0 or 0x80 (0x29A660).
- The CST works after the tone curve: Y = c · T(R, G, B). That is a gamma-domain channel mix,
  independent of whatever the CCM does.

**NR strength scaling [code].** After interpolation the firmware passes each `filter_th` and
`filter_lut` value through `iq_cal(ratio, v, 0, 1023, way 0)` (0x3167c8) = `clamp(v·ratio/100)`,
with the same ratio for thresholds and LUTs. Scaling all four arrays together by k is the
firmware's own way of setting NR to k.

Pipeline order [inferred]: OB → WB → CCM (linear) → gamma (per channel in hardware) →
RGB→YCC → colour control → Y curve.
- **Hardware fact [code]:** the gamma engine has separate R/G/B tables. The Negative effect writes
  all three. `iq_gamma` as stored has a single curve, so per-channel toning would need a mode
  that hasn't been found.

### IQT item IDs [code]
Matched by memcpy size in `iqt_api_set_cmd` (0x33A154, table 0x33A5A0) /
`iqt_api_get_cmd` (0x33A048).

| ID | item | ID | item |
|---|---|---|---|
| 0x03 | **RLD_DTSI** (reload a profile node by path) | 0x24 | iq_ccm |
| 0x0B | UI param (sharpness-like level) | 0x25 | iq_color |
| 0x12 | **UI image effect (fx)** | 0x26 | iq_contrast |
| 0x13 | UI CCID (colour id for partial colour) | 0x27 | iq_edge |
| 0x1C | colour-space transform (RGB→YCC matrix + Cb/Cr offset) | 0x28 | iq_3dnr |
| 0x1E | iq_ycurve | 0x2D | iq_wdr |
| 0x1F | iq_ob | 0x2F | iq_shdr |
| 0x20 | iq_nr | 0x3B | iq_post_sharpen |
| 0x21 | iq_cfa | | |
| 0x22 | iq_va | | |
| 0x23 | iq_gamma | | |

`vendor_isp_get_iq` = 0x5328AC, `vendor_isp_set_iq` = 0x5328C8, UI get = 0x442434,
UI set = 0x441DEC (colour effect = UI index 3).

### Profile loading (RLD_DTSI) [code]
- `iqt_api_set_dtsi` (0x339F70) is the only caller of `iqt_dtsi_load` (0x344068). It loads the
  node at the request path into the parameter buffers of the request id (0 for every
  `PhotoExe_OnColor` load). On success it sets the update flag of every IQ item (0x18–0x45,
  table 0xBA6948), so all items are re-applied from the buffers.
- `iqt_dtsi_load` walks a 24-entry table at 0x3448CC (`char name[0x40]; void *data; u32 size`):
  iq_ob, iq_nr, iq_cfa, iq_va, iq_gamma, iq_ccm, iq_color, iq_contrast, iq_edge, iq_3dnr,
  iq_wdr, iq_shdr, iq_rgbir, iq_companding, iq_rgbir_enh, iq_post_sharpen, iq_dpc, iq_shading,
  iq_shading_inter, iq_shading_ext, iq_ldc, iq_ycurve, iq_cst, iq_shdr_ext.
  - For each entry it looks up `<node>/<name>`. If the sub-node is missing, or its `size` is
    missing or differs from the table, it clears the data pointer (0x34416C).
  - It then copies only the blocks that still have a pointer (0x344228…). A skipped block
    keeps its current parameters. A missing `version-info` only logs a warning.
- **A node with only some blocks is a valid partial profile.** Stock relies on this: every IQ
  profile lacks 6 of the 24 blocks (dpc, the three shading blocks, ldc, cst), and
  `ov13b10_iq_shading` has only 3 blocks. `iq_shdr_ev` (capture profiles) is not in the table
  and is ignored.
- The patched film nodes (since flash 14) hold only `iq_gamma`, `iq_ccm`, `iq_color` and
  `iq_ycurve` (6.8 KB instead of 26.6 KB). The rest comes from the full profile
  `PhotoExe_OnColor` loads just before (§5). In photo mode that gives exactly the parameters of a
  full clone.

## 5. Colour-effect handling [code]

### `PhotoExe_OnColor` (0x4205D8)
1. Prelude: `UI_set(3, case)`, then reloads AE (`/isp/ae/ov13b10_ae`), AWB, and IQ
   `/isp/iq/ov13b10_iq_0_cap` via RLD_DTSI (0x4207B4–0x4208A0). Afterwards **r6 = the IQ reload
   request buffer** and r4 = GOT.
   - **Movie:** in DC mode 7 (0x4207A8), or for the "photo mode rec movie" request (0x420B84),
     it loads `/isp/ae/ov13b10_ae_0`, AWB and the movie profile `/isp/iq/ov13b10_iq` instead
     (0x420B90–0x420CA8), then takes the same switch. The Movie colour menu (cases 0–4) therefore
     runs the same case code as photo.
   - Every path to the switch passes one of the two full IQ loads. The only detour, 0x421448
     (vendor_isp_init after error −21), returns to 0x4206EC before them.
2. Switch: `cmp sb,#0xb; addls pc,pc,sb,lsl#2` at 0x4208CC. **Jump table at 0x4208D8**,
   12 × `b`.
3. Common exit 0x420B6C.

**CST save/restore in the prelude [code].** On the first call (flag `[GOT+0x3310]` ≠ 0),
0x420CD8 saves the current `iq_cst` with `get_iq(0x1C)` into a global (`[GOT+0xB80]`) and clears
the flag. Every call then writes it back with `set_iq(0x1C)` (0x420710), sets fx 0 and item 0x2A,
and only then reloads the profiles and runs the case. So whatever a case sets in the CST (Sepia:
mono luma row 77/150/29 with chroma rows 0 and Cb/Cr 116/144; Retro: Cb/Cr 114/140; in the
patched firmware, the red-filter films' `iq_cst`) lasts until the next colour-effect change.
Movie takes the same prelude.

Reload request layout (filled at r6): `{u32 id=0; char path[256]; char path2[256]="null";
u32 dtsi=bl 0x31390()}`, then `vendor_isp_set_iq(3, r6)`.

| case | stock target | effect / behaviour | menu name |
|---|---|---|---|
| 0 | 0x420D1C | fx 0 (`COLOR_EFFECT_STANDARD`) | Normal |
| 1 | 0x420D48 | items 0x2A, 0x1C (Cb 114 / Cr 140), saturation 85 on ISO levels 1–6 | Retro (warm, desaturated) |
| 2 | 0x420F54 | fx 1, manual identity CCM (item 0x24), AE item 0x20 [+4] × 0.8 | Black and White |
| 3 | 0x421000 | 0x1C = luma matrix 77/150/29, Cb 116 / Cr 144, AE × 0.8 | Sepia |
| 4 | 0x4210AC | fx 3 (sets Cb/Cr 0x80 and adjusts a level in `iq_operation_effect`) | Vivid |
| 5 | 0x42110C | short path: reload `…iq_0_colorpencil`, fx 8 | Colored Pencil |
| 6 | 0x4212E0 | fx 10 = inverted gamma (0x330E40) | Negative |
| 7 | 0x42099C | short path: reload `…iq_1_colorpencil`, fx 7 | Sketch |
| 8–11 | 0x4212F8 / 0x4213A0 / 0x420E08 / 0x420EAC | fx 11 + 0x13 colour id (ccid) 8/10/11/9 + saturation | Partial Color Red / Green / Blue / Yellow |

Menu names: the menu index equals the case number [camera] (see "Menu strings" below);
cases 8–11 are also proven from the ccid table [code].

- **Partial colour ccid table [code]:** UI param 10 = ccid (debug getter 0x311994). fx 11
  (0x31DAD0) copies record `ccid` (24 × s32 per-hue-bin saturation offsets, 96 B) from the
  table at 0x33109C. Records 1–7 add +99 to a few bins ("enhance"); 8–13 set −128 everywhere
  except a few bins ("keep"). Kept bins: 8 → 23,0,1,2; 9 → 3,4; 10 → 7,8,9; 11 → 14,15,16;
  12 → 13,14; 13 → 2,3; (enhance 7 → 20,21,22). With bin k = hue 15k° (red = 0°) this reads
  red, yellow, green, blue, cyan, orange, magenta. That is a sensible enum; the CbCr-angle reading
  is not. So case 8 = Red, 9 (ccid 10) = Green, 10 (ccid 11) = Blue, 11 (ccid 9) = Yellow.
  The labels R/Y/B/G are sids 272/273/274/275.
- Nothing outside `PhotoExe_OnColor` tests specific colour-effect values except
  `Get_QualityValue` (5, 7); other `UI_get(3)` users only test ≠ 0.
- **Do not name a case from its fx value alone.** fx 7/8 were once guessed the wrong way round.
  Confirm a name on the camera, or from the effect implementation.
- `iq_operation_effect` (dispatcher at 0x31D63C) handles fx: 1, 2, 3 → 0x31D8E4, 4, 5, 6, 7, 8,
  9 = LDC/fisheye (no case uses it), 10 = inverted gamma, 11. fx is UI param 9.
  - **fx 1 (B&W, 0x31D8A8)** only sets saturation (`+0xbad`) to 0 and Cb/Cr (`+0xbfc/0xbfd`) to
    0x80. It leaves the CCM alone.
- Short paths: case 7 0x42146C → exit 0x420B58 (`mov r3,#7`). Case 5 0x4214B4 → exit 0x4212C8
  (`mov r3,#8`). Stock takes them only when UI 0xA2 == 7.
- **`Get_QualityValue`** (0x445674) lowers JPEG quality (65/70) for effects 5 and 7.

### Menu strings [code]
- 27 language tables, each **281 × `{u32 ptr, u32 len}`** + `{0,0}`. The last table
  (Vietnamese) has no terminator.
- English table = 0xB055F4. Tables run 0xB00F74 … 0xB0F494, stride 282 × 8.
- Effect string ids:

| id | name | id | name |
|---|---|---|---|
| 24 | Normal | 32 | **Sketch** |
| 25 | Vivid | 33 | Fish Eye |
| 26 | Black and White | 34 | Punk |
| 27 | Vignetting | 35 | Retro |
| 28 | Salon | 270 | Color |
| 29 | Dreamy | 272–275 | Partial Color R/Y/B/G |
| **30** | **Negative** | **276** | **Colored Pencil** |
| 31 | Sepia | | |

- The menu → case list was **not** found statically; it is probably generated LVGL code.
- **Menu order [manual, camera]** (manual p. 39, Photo menu → Color Effect): Normal, Retro, Black
  and White, Sepia, Vivid, Colored Pencils, Negative, Sketch, Partial Color-Red/-Green/-Blue/
  -Yellow. These are cases 0–11 in order: every slot proven independently (5, 6, 7, 8–11) falls
  at the same position, and the order was checked on the camera's screen.
- The **Movie** Color Effect menu (manual p. 44) offers only Normal, Retro, Black and White,
  Sepia and Vivid (cases 0–4) [manual]. Cases 5–11 are not reachable in movie mode. In Movie a
  patched case loads the film node over the movie profile (prelude above), so movies get the
  film's tone with fx 1 [code; not camera-tested].
- "Sepia" (sid 31) and "Black and White" (sid 26) appear in the manual only in the photo and
  Movie colour menus (pp. 39, 44; no playback filter), so relabelling them affects just those
  two menus [manual].

### EXIF [code, camera]
- Every capture calls 0x415944 (IFD0), 0x415bd8 (`ExifVendor_WriteExifIFD`) and 0x416abc (Interop),
  from the photo callback (0x42ba10) and `MovieExe_UserEventCb` (0x419b04).
- IFD0 ImageDescription (0x10E) is the fixed 27-byte `"KODAK Digital Still Camera"` (0x77cca0),
  copied at 0x41594c/0x415960 with the count hardcoded (`mov r2,#0x1b` at 0x4159e8). Make
  `"JK Imaging, Ltd."`, Model `"KODAK PIXPRO C1"`, Software `"1.04"`.
- `EXIF_SetTag` (0x54dfd0) copies data longer than 4 bytes, so the source buffer can be temporary.
- **No stock tag records the colour effect.** The Exif IFD reads UI 1, 6, 7, 8, 9, 0x17, 0x18,
  0x6D and 0xA2, never UI 3. Two stock shots with different effects have identical metadata apart
  from exposure and time [camera].
- MakerNote (0x927C, 40 B) comes from the callback at 0x41571c: `u32 0`, the name
  `"KODAK PIXPRO C1  Kodak"`, u16 `UI_get(2)` at +0x1C, u16 `0xA5A5`, then zeros. Playback reads
  +0x1C, +0x20 and +0x24 back into globals (0xb28250/4), so don't repurpose it.
- `PhotoExe_OnColor` does `UI_set(3, case)`, so `UI_get(3)` (0x442434) returns the case number.
- Software comes from 0x4447c0, which copies `"1.04"` into the global 0xb49ee4 and returns it.
  Every caller refills it. The count is `mov r2,#13` at 0x415aa4.
- `EXIF_SetTag` allocates from a bounded work buffer (0x54fd28: "Exif working buffer overflow!").
- **Patch [camera]:** `bl` at 0x41594c (was `ldr lr,[pc,#0x270]`) to a helper that returns
  lr = "Preset: <film>" − 0x415968 when `UI_get(3)` is a film case, else the stock literal.
  Software is `mov r2,#27` at 0x415aa4, plus `bl` at 0x415b0c (was `bl 0x4447c0`) to a helper
  returning "Ricardos custom firmware <n>". Both are emulated by `tools/test_exif.py`; patched
  files pass `exiftool -validate` the same as stock.

### File naming [code]
- Path: `A:\DCIM\<dir>KODC1\<dir>_<file>.JPG` (e.g. `101_0102.JPG`). `DCF_MakeObjPathEx`
  (0x5df7f4) looks up the file type in a 10 × 16-byte table at 0xb1a334. If that type's file
  free chars (entry +8) are empty (stock), it uses `"%s%03d%s\%03d_%04d.%s"`; otherwise it uses
  standard DCF `"%s%03d%s\%s%04d.%s"` with the 4 free chars (set by `DCF_SetFileFreeChars`).
- Unknown: whether the scanner and playback find files whose free chars differ from the current
  setting. A per-mode filename prefix therefore risks playback and numbering; not attempted.

### SD update [code, camera]
- The updater `C110FwUpdate` reads **`A:\C110.bin`** (SD root).
- It checks the container checksum (`FW bin check failed`). No signature check and no version
  compare were found.
- On failure it falls back to a loader update mechanism.
- u-boot has `nvt_fw_update` (SD) and optional RSA secure-boot code, apparently not enabled.

## 6. Free resources in the current build (flash 18)
New code may only go into stock code proven dead; new strings only into debug printf formats.

| resource | where | free |
|---|---|---|
| dead code | 0x4212E0–0x421447 (stock case 6/8/9 bodies; stock bytes, nothing placed there since flash 18) | 360 B (4 stubs) |
| dead code | 0x420B30–0x420B57 (after the J3/A5 stubs and the Snap focus helpers) | 40 B |
| dead code | 0x4212B8–0x4212C7 (after the EXIF helpers) | 16 B |
| dead code | 0x420FF4–0x420FFF (stock case 2 body, after the case 3 stub) | 12 B |
| dead code | 0x420F4C–0x420F53 (stock case 10/11 bodies: spilled strings 0x420E08, colour helper 0x420E20, stubs of cases 11, 8, 2) | 8 B |
| string spill | `STRING_SPILL` = 0x420E08: strings that do not fit in `STRING_AREAS` go to the start of the case 10/11 body, reserved before code is allocated. Holds `/isp/iq/ov13b10_tmaxred` | – |
| candidates, not yet proven dead | stock case 3 body 0x421000–0x4210AB (directly after the case 2 range); stock case 10 body 0x420E08–0x420EAB (ends in `b 0x420B6C`, case 11 starts at 0x420EAC) | 172 B + 164 B |
| string space | `STRING_AREAS`: five debug printf formats of `PhotoExe_OnColor` ("COLOR_EFFECT_STANDARD", "movie iq", "photo iq", "COLOR on,BEAUTY set OFF" 0x77F894 and "uhSelect" 0x77F8C8) | 17 B ("photo iq") + 10 B ("uhSelect") + 3 B |
| more string space | 0x77F864 "photo mode rec movie %d" (46 B): printf-only, but also printed by 0x423E78/0x424014/0x424828. Or strings in free code (the EXIF strings already are) | not used yet |
| ISP DTB | 0x3794C of 0x40000 used | 34 KB = 5 more partial films (6.8 KB each) |
| colour-effect slots still stock | cases 0 Normal, 1 Retro, 4 Vivid (Retro and Vivid are also Movie menu entries) | – |

A reload stub is 80 bytes (`reload_stub()` in `tools/build_films.py`). Stubs without a fixed
`stub=` address and the colour-exit helper are placed first-fit in `FREE_CODE`.

**Dead stock case bodies [code].** `DEAD_CASE_CODE` lists 0x420E08–0x420F53 (cases 10, 11),
0x420F54–0x420FFF (case 2) and 0x4212E0–0x421447 (cases 6, 8, 9). A range joins `FREE_CODE` only
when all its cases are films.
- A full disassembly and a raw word scan of stock (data included) find only the jump-table
  entries branching into them. The 7 literal words with in-range values (0x6BDFA4…) are PIC
  deltas to Wi-Fi strings.
- Each range is preceded by `b 0x420B6C` and holds no literal pool.
- `verify_build.py` repeats the raw branch scan on every build. Only the jump table and the
  patched call sites may enter `FREE_CODE`.

## 7. Current patch set (`tools/build_films.py`)
In menu order. Labels replace the stock menu strings in all 27 languages.

| menu slot | label | profile node | exit / fx | status |
|---|---|---|---|---|
| Black and White (case 2, sid 26) | T-Max (`kodak_t-max_3200.cube`) | `ov13b10_tmax` | stub 0x4212E0 → 0x4212C8, fx 1 | [camera]; also the Movie menu's entry |
| Sepia (case 3, sid 31) | T-Max Red (T-Max + deep red filter in the CST luma row) | `ov13b10_tmaxred` | stub 0x421380 → 0x4212C8, fx 1 | [camera] runs, true mono; filter effect not yet confirmed; also a Movie menu entry |
| Colored Pencil (case 5, sid 276) | Tri-X | `ov13b10_iq_0_colorpencil` | 0x4212C8, fx 1 | [camera] |
| Negative (case 6, sid 30) | Tri-X Red (Tri-X + red filter in the CST luma row) | `ov13b10_trixred` | stub 0x421330 → 0x4212C8, fx 1 | [camera] runs; filter effect not yet confirmed |
| Sketch (case 7, sid 32) | Kodachrome | `ov13b10_iq_1_colorpencil` | 0x420B58, fx 0 | [camera] |
| Partial Color-Red (case 8, sid 272) | Portra (`kodak_portra_160_nc.cube`) | `ov13b10_portra` | stub 0x420F90 → 0x420B58 | [camera] |
| Partial Color-Green (case 9, sid 275) | VSCO J3 | `ov13b10_j3` | stub 0x42099C → 0x420B58 | [camera] |
| Partial Color-Blue (case 10, sid 274) | VSCO A5 (+ shadow lift `lift=32`) | `ov13b10_a5` | stub 0x4209EC → 0x420B58 | [camera] |
| Partial Color-Yellow (case 11, sid 273) | VSCO A6 (`A6_64.cube` + `lift=32`, as A5) | `ov13b10_a6` | stub 0x420E5C → 0x420B58 | not yet camera-tested (flash 18) |

Stub addresses are those of flash 18; the allocator moves the unpinned ones when `FREE_CODE`
changes. Every new node is a partial profile (§4 "Profile loading"); the two colorpencil nodes stay
full. The two red-filter films' nodes hold `iq_gamma`, `iq_color`, `iq_ycurve` and `iq_cst`, with
no `iq_ccm` (the capture profile's stock matrix stays).

RTOS edits:
- jump table entries for cases 2, 3 and 5–11;
- path literal 0x4215D8 (+0x24, so case 7 loads `_1_`);
- exit immediates 0x420B58 / 0x4212C8;
- `Get_QualityValue` `beq` → `nop` at 0x44568C / 0x44569C (films keep full JPEG quality);
- labels and node paths in the five `STRING_AREAS` debug formats and `STRING_SPILL` (§6);
- reload stubs and the colour-exit helper (0x420F54) in the dead stock case bodies (§6);
- EXIF: helpers and strings at 0x42110C–0x42128F, call sites 0x41594C / 0x415AA4 / 0x415B0C (§5 EXIF);
- string ids in all 27 tables;
- Snap (§9): mode table 0xB11C5E (Landscape AE curve 0 → 1), curve 1 at 0x77ECC4, immediates
  0x426498 / 0x42731C (`movweq #25000` → `#10000`) and 0x426C98 / 0x42759C (`mov r3,#800` →
  `#1600`), label sid 54 "Snap";
- Snap fixed focus (§9): helpers at 0x420A3C, `bl` redirects at 0x42A3F0 (half-press AF start),
  0x42A60C (AF status), 0x41A2D4, 0x4563E0, 0x45F020 (lens rest); `b` at 0x429078
  (`PhotoExe_AFStart` entry);
- colour effect keeps the mode AE curve (§9): `bl` at 0x420B6C to the colour-exit helper;
- checksum at 0x26E.

DTB edits: film nodes built from `ov13b10_iq_0_cap` plus a LUT fit (new nodes keep only the film
blocks); `ov13b10_iq_shading_1` removed. These are applied to `ov13b10_iq_0_cap` before the films
copy it, so they cover Normal, the stock effects and all films (live view `ov13b10_iq` is
untouched):
- Sharpening: `iq_edge` `edge_enh_p/n` × `SHARPEN` (0.75) on all 17 records.
- Noise reduction: `iq_nr` range filters A/B (`filter_th`, `filter_lut`, `filter_th_b`,
  `filter_lut_b`) × `DENOISE_LOW` (1.15) on records 1–3 (ISO 100–400) and × `DENOISE` (0.5) on
  records `DENOISE_FROM` (4 = ISO 800) to 16, for film-like grain at high ISO. Record 0 (manual,
  unused), chroma NR (`lca_*`), outlier/hot-pixel removal and 3DNR are stock.
  - The low-ISO values are small integers, so after rounding filter B is × 1.13–1.16 and filter A
    × 1.0–1.16. At ISO 100 filter A is all zero in stock and stays off.
  - ISO 800 smooths less than ISO 400 (filter B max 20 vs 34); auto ISO between them interpolates.

The menu has no sharpness setting (manual). The ISP library has a UI `sharpness_lv`
(`iq_sxcmd_get_ui_param`, 0x311b14, debug only), but the camera app doesn't expose it.

### Look fitting (`tools/fit_lut.py`)
- The `.cube` LUT is defined on stock camera output `s`.
- `s` is linearised through the stock tone (Y curve ∘ gamma curve 1), then fitted to
  `out = sat · (T(M · l))`. T is one curve shared by R, G and B, written into all three gamma
  curves (curves 2/3 keep their stock low-light offset). The Y curve is set to identity.
  M (3×3) is folded into all 4 CCM slots; for mono films it has identical rows (channel
  weights).

| look | fit error mean / natural colours (/255) |
|---|---|
| Kodachrome (K2) | 21.2 / 15.2 (stock baseline 37.6 / 28.9) |
| Tri-X | 8.2 / 5.6 |
| J3 | 14.1 / 10.3 |
| A5 | 17.2 / 13.0 |
| Portra | 15.5 / 10.6 |
| T-Max | 4.3 / 2.9 |

Optional `lift` (per film, black level 0..255) is applied after the fit by `fit_lut.lift()`. It
starts the curve at that black and blends a cubic Hermite toe into the fitted curve at linear
0.153, never darkening. A5 uses `lift=32`: its fit had a flat 21/255 floor below ~3 % linear,
which crushed shadows on the camera (dark areas at 16–19/255).

**Mono films: the CCM channel mix has no visible effect [camera].** The first red-filter
versions (flashes 14–16) put the filter in the CCM rows. The mix was the #25-like
(0.85, 0.20, −0.05) at first, then for T-Max Red a deep red (1.0, 0.0, −0.15), #29-like, scaled
to the sum of the film's weights so greys keep their brightness. Predicted /255 for T-Max → deep
red: blue sky 169 → 49, skin 182 → 228, red 55 → 210, grey 131 → 131. On the camera, T-Max and
T-Max Red came out the same (photo of a screen showing a red-brick house under a blue sky:
brick/render 0.21 vs 0.21, sky/render 1.06 vs 1.08). Ruled out: fx 1 (it leaves the CCM), the
partial loader (it copies `iq_ccm`), an ISO-dependent CCM fade, the film exits. The cause is
unknown. It is also not known whether the CCM rows affect colour captures; the colour films do
show their looks on the camera.

**B&W filters in the CST luma row (flash 17).** So Tri-X Red and T-Max Red (`cst=True`) now do
what stock Sepia does:
- their nodes drop `iq_ccm` (stock colour matrix) and add `iq_cst` = the firmware default with the
  luma row replaced and both chroma rows 0;
- fx 1 and saturation 0 stay; the prelude restores the default CST on the next selection.
- The row is fitted by `fit_lut.luma_row()`: an exhaustive search over integer Q8 rows (sum 256,
  each −256…255) for the closest gamma-domain match c · T(l) to the linear filter T(l · w/Σw).
- **T-Max Red [255, 25, −24]** (red pinned at the 9-bit limit; 14.2/255 from the linear deep
  red); **Tri-X Red [214, 61, −19]** (13.0/255 from the #25 mix).
- Predicted /255 on T-Max's curve, BT.601 → T-Max Red: blue sky 146 → ≈ 95, red 86 → 202,
  brick 87 → ≈ 139, skin 189 → ≈ 226, blue 66 → ≈ 28. The sky can't reach the linear deep red's
  50, because the luma row can't exceed 1.0 for red.
- Noise: a red filter amplifies sensor noise (deep red ≈ 2.3× T-Max's by row norm, #25 ≈ 1.5×)
  [inferred: per-channel noise assumed independent]. Expect more grain, as with a real filter.
- [camera] Flash 17 runs and gives true mono. In an indoor test, front-lit green leaves render
  near black (luma 56 vs a lit wall at 236), as a red filter predicts, but dark-green leaves are
  dark without a filter too, so this is consistent, not proof. A same-scene T-Max / T-Max Red
  pair is still needed.
- T-Max and Tri-X still carry their fitted weights in the CCM rows. If those have no effect, they
  render as BT.601 luma through their own tone curves; moving them to the CST would apply their
  fitted channel response [inferred; not done].

Limits:
- Brightness-dependent tints (split toning) cannot be reproduced with one shared curve.
- Per-hue tables gained little (15.2 → 14.7) and their convention is unknown.
- An `iq_ob` green pedestal would need −217 codes, which would fight AWB/AE. Rejected.

## 8. Build history
"Versus" lists exactly what changed between builds.

| build | content | result |
|---|---|---|
| flash 1 | Kodachrome/Tri-X, simple S-curve looks | **[camera] works**; labels were swapped (fixed since) |
| flash 2 | LUT-fitted looks, labels corrected | built |
| flash 3 | + J3 on Negative, `shading_1` removed | **[camera] works** |
| flash 4 | + A5 on Partial Color-Yellow (case 11) | **[camera] works**; shadows too crushed |
| flash 5 | A5 `lift=32` (DTB only, `ov13b10_a5/iq_gamma`) | **[camera] works** |
| flash 6 | EXIF ImageDescription "Preset: <film>", Software "Ricardos custom firmware 6" (RTOS only) | **[camera] works**: tags present, JPEG and thumbnail decode, `exiftool -validate` matches stock |
| flash 7 | Sharpening halved (`iq_edge` enh_p/n × 0.5 in the capture profile) | built; superseded before flashing |
| flash 8 | Sharpening 25 % below stock (`SHARPEN = 0.75`; low-ISO enh_p/n 90 → 68) | built; superseded |
| flash 9 | Flash 8 + noise reduction halved at ISO ≥ 800 (`DENOISE = 0.5`, `iq_nr` range filters) | built; images liked (confirmed with flash 10's sample) |
| flash 10 | Flash 9 + **Snap** mode on the Landscape slot (AE curve only; focus still AF). RTOS data/immediates only, no new code. `test_ae.py` emulates the program lines | **[camera] works**: 1/100 s at ISO 526 (on the emulated Snap line), Tri-X preset (colour effects work in Snap), sharp, fine grain |
| flash 11 | Flash 10 + **Snap fixed hyperfocal focus** (new code: 208 B helpers + 6 `bl` redirects). `test_focus.py` emulates the helpers | **[camera] focus works** (≈ 1 m–∞: ~1 m acceptably sharp, 2.5–3.5 m crisp, distance resolved). **Exposure was not on the Snap curve** (ISO 100–124 at 1/100, ISO 100 at 1/155): §9 "Colour effect resets the mode AE curve". **Crash:** in Snap, take a photo, review it, press zoom-out → pause and crash (§9 "Snap fixed focus") |
| flash 12 | Flash 11 reworked: `PhotoExe_AFStart` is a no-op in Snap, lens written only when not already at the hyperfocal code; **colour effect re-applies the mode AE curve** (all photo modes) | **[camera] works**: crash gone, exposure stays right when changing films, focus fast |
| flash 13 | Flash 12 + labels "VSCO J3" / "VSCO A5" + **Portra** on Partial Color-Red (case 8, full profile; DTB 0x3F8E4 of 0x40000) | **[camera] works** |
| flash 14 | Flash 13 + **T-Max** (Black and White), **Tri-X Red** (Partial Color-Green), **T-Max Red** (Partial Color-Blue), CCM-row filters. All new nodes are **partial profiles** (DTB 0x362CC). Stubs in dead stock case bodies; two more debug formats hold strings | built; low-ISO grain judged too strong → flash 15 |
| flash 15 | Flash 14 + NR × 1.15 at ISO 100–400 (`DENOISE_LOW`) + Tri-X Red moved to Negative (next to Tri-X), VSCO J3 to Partial Color-Green | **[camera] works**. T-Max and T-Max Red looked the same |
| flash 16 | Flash 15 + T-Max Red moved to Sepia (next to T-Max) with a **deep red mix** (1.0, 0.0, −0.15) + VSCO A5 moved to Partial Color-Blue + Partial Color-Yellow stock again | **[camera] runs**, true mono. **T-Max Red = T-Max** (measured; §7 "Mono films") |
| flash 17 | Flash 16 + **red filters moved from the CCM rows to the RGB→YCC luma row** (`iq_cst`; rows [214, 61, −19] and [255, 25, −24]). DTB only those two nodes; RTOS only the version digit and checksum | **[camera] runs**, true mono; filter consistent but not yet proven (§7) |
| flash 18 | Flash 17 + **VSCO A6** (`lift=32`) on Partial Color-Yellow (next to A5). Cases 10/11 both films, so their stock bodies are free code again; string areas full, so the T-Max Red node path spills to `STRING_SPILL` (DTB 0x3794C). verify_build, EXIF, AE and focus tests pass | built (2026-11-02), **not yet camera-tested** |

## 9. Shooting modes, AE program lines, focus

### DC mode [code]
- The Mode menu value is **UI 0xA2** (`UIFlowMenuDCMode_*`). UI 5 ("scene") is set only by the
  debug shell and the reset routine (0x443390); nothing handles its event 0x1400210D.
- Values (from EXIF ExposureProgram/SceneCaptureType in `ExifVendor_WriteExifIFD`, 0x416630 and
  0x41668c; order matches the manual): 0 Auto, 1 Program AE, **2 Landscape** (program 8, scene 1),
  3 Night Landscape (program 8, scene 3), 4 Children (program 6, action), 5 Beach,
  6 Backlight Portrait (program 7), 7 Movie.
- Labels: sid 46 Auto Mode, 277 Program AE, **54 Landscape**, 48 Night Landscape, 278 Children,
  49 Beach, 263 Backlight Portrait.
- **Mode table** at 0xB11BC8 (GOT 0xD54): 9 × 0x34 B, indexed by DC mode. `+0 char *name`
  ("PHOTO AUTO/PORTRAIT/SCENERY/NIGHT/SPORT/BEACH/BACKLIT_PORT/MOVIE PARAMS"), `+4 scene id`,
  then u16 overrides (0xFFFF = none), read by `FlowPhoto_InitCfgSetting` (0x462070).
  `+0x2E` = **AE curve index**, `+0x30` = WDR strength (`PhotoExe_OnWDRStrength`).
  Mode 1 → curve 3; mode 3 → curve 2, WDR 3; mode 6 → WDR 2; all others → curve 0, no overrides.
- **Landscape (mode 2) has no settings of its own** in stock: curve 0 (as Auto), normal AF, no
  overrides. It only changes the EXIF tags. The manual's "vivid greens and blues" is not
  implemented, and it does **not** lock focus.

### AE program lines [code]
- `PhotoExe_OnAECurveProcess` (0x425A3C) copies curve `[mode].+0x2E` (0xD4 B =
  `ae_curve_gen_photo`) from the array at **0x77EBF0** (GOT 0x3FBC) and sets it with AE item 0x29.
  It overrides the DTB `ae_curve_gen_photo`. Curve 1 is also chosen when the factory IQ test state
  (GOT 0x30D4, written only by `auto_ReadIQConfigFile` / `UIFlowIQSetCorrectTest`) is 5.
- Layout: `node[12] × {u32 expt_us, u32 iso, u32, u32}`, then `node_num, expt_max, iso_max,
  iso_mode, isp_gain_thres`.

| curve | addr | used by (stock) | nodes (expt µs, ISO) | expt_max, iso_max |
|---|---|---|---|---|
| 0 | 0x77EBF0 | Auto, Landscape, Children, Beach, Backlight, Movie | (1,100) (16666,200) (33333,400) (66666,1600) | 250000, 600 |
| 1 | 0x77ECC4 | factory IQ test only | (1,100) (8333,400) (16666,600) (25000,800) | 25000, 800 |
| 2 | 0x77ED98 | Night Landscape | (1,100) (100000,200) (2000000,400) (4000000,800) | 2000000, 200 |
| 3 | 0x77EE6C | Program AE | as curve 0 | 1000000, 1600 |

- Hard-coded per-curve exposure caps (curve 1: 0x61A8 = 25000 µs; 0: 250000; 3: 1 s; else 2 s) in
  `PhotoExe_CalAEandAWB` (0x426494) and `PhotoExe_Capture_CalAE` (0x427318). In
  `Capture_CalAE` they apply only with manual ISO (UI 7 = 1–4), recomputing a manual
  exposure. 0x426C90/0x427594 have an extra curve-1 branch with ISO 800 (0x320).
  These immediates equal curve 1's own `expt_max` / `iso_max`, and run only for curve index 1.
- DTB AE profiles: `ov13b10_ae_0` (sensor default) and `ov13b10_ae` (reloaded by
  `PhotoExe_OnColor`); their `ae_curve_gen_photo` differ, but the RTOS curve above replaces them.

### AE curve generator [code, emulated by `tools/test_ae.py`]
- `ae_curve_cap_generator` (0x2DE360), called at 0x2E84AC: `r1` = sb = `{u32 freq, u32 ui_iso,
  u32 flicker_idx, curve…}` (nodes at sb+0xC). Output rows (0x28 B) at 0xB9F2D8 + id·0x640:
  `{u64 expt·iso, u64 expt_us, u32 iso, …, u32 flicker flag}`, ended by 0xFFFFFFFF.
- Validation: each node's exposure and ISO must be ≥ the previous node's ("ExpTime/ISO node
  error"); equal values are allowed.
- Flicker index → {0, 55, 100, 120} Hz (table 0x2DF588), from AE UI 0 (frequency); 1 = 120 Hz,
  2 = 55 Hz, otherwise 100 Hz. No menu item; the camera runs 100 Hz (samples taken on 50 Hz
  mains: 1/50 s at ISO 112 = 2 × 10 ms).
- **Auto ISO** (ui_iso 0, `iso_mode` forced 0): row 0 = (min exposure, node0 ISO), then **one full
  flicker period at node0 ISO**. After that, within each node pair, exposure first (floored to a
  multiple of the flicker period), then ISO. After the last node, exposure extends to
  `expt_max` at `iso_max`. So node exposures below one period are rounded up to it: **an auto-ISO
  curve can't hold a shutter faster than 1/100 s (1/120 at 60 Hz) while raising ISO**, and the
  sub-period range always runs at node0 ISO.
- **Fixed ISO** (ui_iso ≠ 0, `iso_mode` 1): rows at that ISO, up to half a period, then period
  multiples up to `expt_max`.
- **Shortest exposure = one sensor row [code; not camera-tested].** The AE setup
  (0x2E8C64–0x2E8C80) raises curve node0 `expt` (curve +8) to the sensor driver's row time when it
  is smaller (log "min_expt (param) < row_time (sensor_drv), force clamp to row time", 0x2EE46C).
  Sensor mode table (0xF8C40, `sen_ov13b10`):

  | mode | size | fps | VTS (lines) | row time |
  |---|---|---|---|---|
  | full-res | 4212×3124 (out 4160×3120) | 15 | 3196 | ≈ 20.9 µs |
  | 4K | 3840×2160 | 30 | 3196 | ≈ 10.4 µs |
  | binned | 2104×1560 (out 2080×1560 / 2080×1168) | 60 | 1598 | ≈ 10.4 µs |

  If stills use the full-res mode [inferred], the shortest exposure is one row ≈ 1/48000 s, well
  past the manual's 1/10000 s spec. Not yet checked: whether `sen_set_expt_ov13b10` enforces a
  minimum line count (the Linux ov13b10 driver uses 4 lines → ≈ 1/12000). Exposure is quantised to
  whole lines, so steps near the limit are coarse (1 → 2 lines = 1 stop);
  `ae_flow_get_compensation_ratio` (≈ 0x2E4D00) appears to correct for this, unverified. Fastest
  exposure seen in a sample so far: 1/569 s.

### Snap mode [code, emulated; camera]
Snap replaces Landscape (data only): a street-photography mode with a shutter floor and fixed
focus.
- Landscape (mode 2) → curve 1 (the factory-test curve, so the factory test now also gets it).
  Curve 1 = nodes (1, 200) (10000, 200) (10000, 1600), `expt_max` 10000, `iso_max` 1600. The
  four curve-1 immediates follow (10000 µs, ISO 1600). Label sid 54 → "Snap".
- Emulated program line at 50 Hz: ISO 200 from the fastest shutter to 1/100; 1/100 held while
  ISO goes 200 → 1600; then no slower (darker). 60 Hz: the same at 1/120. Fixed ISO: slowest 1/100.
- A faster hold (e.g. 1/250) needs a code change in the AE generator (skip the flicker period for
  this curve), with a banding risk under mains lighting. The data-only 1/100 hold was chosen as
  the lower-risk option.
- The ISO 200 floor applies to every exposure shorter than 1/100 (node0 ISO). At f/2, ISO 200 a
  sunny scene (EV 15 at ISO 100) needs ≈ 1/16000 s and sand or snow (EV 16) ≈ 1/32000 s, within
  the sensor's range if the row-time limit above holds. Camera check: a sunlit Snap shot with
  EXIF ExposureTime below 1/10000; exactly 1/10000 would mean a clamp not yet found. For brighter
  scenes, lowering node0 ISO to 100 halves the exposure needed (data only).
- **Colour effect resets the mode AE curve [code; camera evidence].** Event 0x211B
  (`PhotoExe_OnAECurveProcess`, table entry 0xAFDB1C) is posted only by `FlowPhoto_InitCfgSetting`
  (0x4623D4), i.e. at mode setup. `PhotoExe_OnColor` reloads `/isp/ae/ov13b10_ae` via RLD_DTSI
  (path at 0x4207D4) on every colour-effect change. That replaces the mode curve with the DTB
  `ov13b10_ae/ae_curve_gen_photo` ((1,100) (16666,400) (33333,800) (66666,1600), iso_max 800)
  until the next mode setup. Flash 11 shots fit it exactly (ISO 109/124 at 1/100, ISO 100 at
  1/155). This is stock behaviour (Program AE and Night Landscape lose their curves the same
  way). **Fixed in flash 12**: `PhotoExe_OnColor`'s common exit (0x420B6C, `ldr r3,[fp,#-0x114]`)
  calls the colour-exit helper, which posts 0x1400211B to the PhotoExe object
  (`[GOT+0x508C]` = 0xAFDB34) unless DC mode is Movie (7), then does the load. Films therefore
  keep each photo mode's exposure. 0x429580 (`PhotoExe_OnOpen`) also reloads
  ov13b10_ae (not yet identified).
- **[camera]** Colour effects (films) work in Snap (1/100 s, ISO 526 with Tri-X). The mode menu
  icon is still the landscape icon. EXIF still says ExposureProgram/SceneCaptureType = Landscape.

### Focus [code]
- Spec: 3.57 mm f/2.0, TTL AF, 60 cm–∞ (macro 8 cm). VCM lens, driver FP5510
  (`fp5510_set_focus_position` 0x54cba0, `mdrv_set_focus_pos`).
- Factory calibration (PStore "IQI", `LoadIQInfoPstore` ~0x4846b4): `+0x2C AF_POS_8CM,
  +0x30 AF_POS_60CM`. Valid → `GetAFlowPos()` (0x4845C0) = 60 cm position, `GetAFhighPos()`
  (0x4845F0) = 8 cm position; else defaults 260 / 750.
- `PhotoExe_SetAF_MACRO` (0x429E00, event 0x2105, UI 0x58 = macro) sets the AF search window with
  0x54C9B8 (low) / 0x54CA04 (high): normal [P60 − 60 (≥ 200), P60 + 100 (≤ 750)]. It also
  saves/restores the lens with 0x54C648 (get) / **0x54C5D0 (set lens position)**.
- vendor_isp wrappers: 0x53283C `get_af` / 0x532858 `set_af` (`aft_api_get/set_cmd`, item table
  0xB17D88); 0x532804/0x532820 get/set AE; 0x5328AC/0x5328C8 get/set IQ. AF item 0x29 = start AF,
  0x2B = status `{id, exec status}` (0 running, 1 focused, else failed).
- Half-press AF (key loop "KeyStatus", 0x40FC10): 0x40F0A0, then **`PhotoExe_AFStart_Single`**
  (0x42A134), then sometimes `PhotoExe_AFStart` (0x429078 → 0x422ADC, also run on mode open by
  `PhotoExe_OnOpen`). Both are asynchronous: configure AF items, **lock AE** (item 0x2A at the
  current exposure; if that is slower than 1/40 s, AFStart_Single shortens it for AF), set IQ
  item 0x23, **start AF** (`set_af(0x29)` at 0x42A3F0 / 0x422D08), set the AF-running flag
  0xB2ACD4 = 1, return.
- Poll: the key loop calls **`PhotoExe_GetAFStatus`** (0x42A5C8) every tick (0x40F7AC). It returns 0
  while the flag is clear or status = 0. Otherwise it restores IQ 0x23 and AF item 0x25, clears the
  flag and returns 1 (status 1) or 2. The key loop stores the result in GOT 0x1420, sets GOT
  0x2B98, redraws the focus frame (0x45B1B8) and gives focus-OK feedback on 1.
- Lens rest ("non_macro_pos") = `GetAFlowPos() − 25` via `bl 0x54C5D0` at 0x41A2D4, 0x4563E0 and
  0x45F020. The last is `task_1sec_period_cb` (0x45ED68): every second while macro is off and the
  last AF failed (GOT 0x1420 == 2).
- Lens primitives: 0x54C5D0(code) writes the FP5510 DAC over I2C (5 retries) and stores the code
  in the global read by 0x54C90C ("CurPos"). 0x45DBA0 is a debug "focus move" (+2 per call).
- 0x4B9100/0x4B9384 and 0x4B7E30 are factory-test AF state machines (run only for IQ-test states).
- No continuous AF found in photo live view [inferred]. **No mode skips AF in stock firmware.**
- Hyperfocal (f = 3.57 mm, N = 2, sensor ≈ 4.7 × 3.5 mm): H ≈ 1.6 m with CoC 4.1 µm (normal
  viewing), ≈ 2.8 m with CoC 2.2 µm (2 pixels). Focus at ≈ 2.8 m → ≈ 1.4 m–∞ strict, ≈ 1.0 m–∞
  normal. If the VCM code is linear in lens extension, P(d) = P60 + (e(d) − e60)/(e8 − e60) ·
  (P8 − P60) with e(d) = f²/(d − f): P(2.8 m) ≈ P60 − 0.12 · (P8 − P60), P(∞) ≈ P60 − 0.147 ·
  (P8 − P60) [inferred; linearity untested].

### Snap fixed focus [code, emulated by `tools/test_focus.py`; camera]
- "Snap" = UI 0xA2 == 2 and UI 0x58 (macro) == 0. Snap + macro keeps normal AF.
- **Lesson from flash 11** (focus worked, ≈ 1 m–∞, but: in Snap, take a photo, review it, press
  zoom-out → pause and crash). It hooked both AF triggers (0x42A3F0 half-press, 0x422D08 inside
  `PhotoExe_AFStart`), the status read and the three rests, writing the lens on every call. Not
  reproduced in emulation. Prime suspect: `PhotoExe_AFStart` runs outside half-press (mode open,
  the key loop's periodic live-view AF every 80 idle ticks at 0x40F938, events), and the hook made
  each one a synchronous I2C lens write from the UI task plus an instant "focused" completion
  (IQ/AF restore, AWB update, AF-result state). Stock AF cannot complete without live frames, so
  stock never runs that completion around capture or review. Flash 12 deviates from stock as
  little as possible, and fixed it.
- Flash 12 helpers at 0x420A3C–0x420B2F (244 B, `snap_focus_code()`):
  - `snap_lens` (0x420A9C): writes the hyperfocal code only if `LENS_GET` (0x54C648 → 0xB187DC,
    the last code written by `lens_set`; the AF library's mover and the driver init also go through
    `lens_set`) differs. Returns 0.
  - `start` (0x420AC0), from 0x42A3F0 only: Snap → `snap_lens`, AF not started; else `set_af`.
  - `status` (0x420AD8), from 0x42A60C: Snap → exec status 1; else `get_af`.
  - `park` (0x420AFC), from the three rests: Snap → `snap_lens`; else the stock `lens_set`.
  - `afstart` (0x420B14), from `b` at 0x429078 (`PhotoExe_AFStart` entry, stock `push {r4, r5, fp,
    lr}`): Snap → `snap_lens` and return to the caller (no AF, no AF-running flag, so no
    completion); else the relocated push, then `b 0x42907C`. 0x422D08 is stock.
  - So in Snap the only fake AF completion is the half-press one, and after the first move there
    are no lens writes.
- Hyperfocal code = `usat10(P60 − K·(P8 − P60)/256)`, K = 30 for `SNAP_FOCUS_MM` = 2800. If
  P8 ≤ P60, it uses P60 − 25 (the stock rest). Default calibration 260/750 → 203.
- **[camera]** Sharp from ≈ 1 m to ∞ (~1 m acceptably sharp, 2.5–3.5 m crisp), focus is
  instant, and the review/zoom-out crash is gone. Not checked: whether the AF-assist lamp still
  fires in the dark.

## 10. Screen flip (tilt screen): open research

Goal: stop the image flipping when the tilt screen opens, so it can be a waist-level finder.

**Behaviour [camera]**
- The screen flips at about **45°** of tilt (for selfies).
- Menus, icons, live view **and playback** all flip; saved photos are **not** flipped. So it is a
  **whole-display rotation**, not a sensor flip, and a fix only has to stop the display rotating.
- The manual says nothing about an automatic flip. "Rotate" in the manual and sids 108–112 are
  playback's rotate-photo feature.

**Ruled out [code]**
- **Panel rotation.** The ST7789V driver's ops table is at 0xB187BC (`dispdev_open_if8bits`
  0x54BE90, `dispdev_read_lcd_reg` 0x54BD04, `dispdev_set_device_rotate` 0x54BBC8, 0x54BB54,
  0x54BDEC, `dispdev_get_lcd_size` 0x54BA30/0x54BA0C; rotation only through this table, no direct
  `bl`). `dispdev_set_device_rotate` is table-driven (`{rot_id, cmd list, n}`; cmd
  0x80000000/0x40000000 = delay/special, else an LCD register write via 0x54BB54), but the table
  getter 0x54B09C returns **count 0**, so the panel itself never rotates. The rotation happens
  above the panel, in the display/graphics layer.
- **Status keys.** `DrvKey_DetStatusKey` (0x4ADB20) returns 0 for attributes 0–4 and errors
  otherwise; the C1 has no status keys.
- **"Image Rotation" setting** (UI 0x29, event 0x14001110). Written by `MovieExe_OnSensorRotate`
  (0x418974, which reconfigures the capture path via 0x5A6E54 with 0xED000) and `Load_MenuInfo`;
  the event is posted by the template `Photo_MenuCallback` (0x4892D8),
  `UIFlowWndMovie_Initparam` and a debug command (0x41D090, "Image Rotation %d"), and appears in
  data only in the MovieExe handler table. `PhotoExe_OnOpen` (0x4297C4): UI 0x29 == 1 →
  `0x61C290(0x10, {0, 0x10000000})`, a pipeline flip flag; also read at 0x41B9F8 (a config
  builder: `[r6+0x9C] = (UI 0x29 == 1)`). No link to the hinge found; it looks like a template
  menu setting the C1 menus don't show.
- Not related: `rotate90/180/270focus*Pos` tables (0x493694) are the digital-zoom overlay.

**Leads [code]**
- Display control: `disp_set_disp1_device_ctrl` (0x4CDF64, 31 commands, called only through the
  display object at 0xB13380). Commands 4, 8, 9 (backlight), 10 (power) and 11 (LCD mode) call
  the device object's +8, a generic control entry. Panel ops getter 0x54C3C0 → 0xB187B4 (entry +8
  = `dispdev_set_device_rotate`), reached via GOT+0x301C from `panel_init`/`lcd_ctrl` (0x54B5D8).
- `vdodisp` has a flip parameter (HDAL param 0x20000002; debug commands `x_vdodisp_cmd_set_flip` /
  `dump_flip` at 0x516E64 / 0x516BAC); `vendor_videoout_set` (0x17A058) handles 0x20000002. App
  callers of `vendor_videoout_set` (`System_AttachDisplay`, `UI_ShowJPG`, `DrvLCD_SleepLeave`,
  `_DL_BufferSwitch` 0x4B3170, `vout_status_cb`, `ImageApp_Play_Close_Module`,
  `lv_gpu_nvt_dma2d_rotate`) pass params 1/3/4/5/8; none is obviously the flip yet.
- **GPIO API:** 0xA4A28 set direction (0xF0070020), 0xA4A8C set (0x40), 0xA4ABC clear (0x60),
  **0xA4AEC read pin**. App pin reads: buttons in `DrvKey_DetNormalKey` (0x4ACA8C: pins 4, 6, 7,
  0x11–0x14, 0x16, 0x2A, 0x44, 0x45, plus 0x2B shutter elsewhere), USB detection (5, 0x21, 0x25,
  0x27, 0x2C), SD card (pin 9 via 0x4AA6C8, `DrvCARDState`), DPC (0). **No dedicated hinge pin
  read found.** Candidates: one of the key-decoder pins mapped to a key event, an
  interrupt-driven GPIO (`gpio_drv_do_tasklet`), or the second ADC channel set up at 0x4B6388.
- The sensor driver has flip/mirror (`sen_set_flip_ov13b10`, string 0xFB608), not used for this.
- "GSENSOR" and gsensor power/park strings exist (dashcam template); unclear if fitted.
- A "Rotate 180" menu string exists in all languages (English 0x9C7698); probably playback rotate.

**Next steps**
1. Map `DrvKey_DetNormalKey`'s pins to key bits and key events, and look for an event whose
   handler rotates the display (whole-UI rotation plus video-layer flip).
2. Find app code that sets a display/OSD direction (vdodisp flip 0x20000002 via ImageApp /
   hd_videoout, or the LVGL display rotation), and work back to its trigger.
3. Find who calls the display object's method at 0xB13380 with commands 4/8 (rotation
   candidates), and the periodic code (`task_100ms_period_cb` / `task_1sec_period_cb` / detection
   tasks) that reads the hinge input.
4. Fix: ignore the hinge (always "normal"), optionally switchable from an existing hidden setting
   or from the shooting mode, since a new menu item is hard (LVGL menus).
