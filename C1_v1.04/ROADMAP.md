# Pixpro C1 custom firmware: roadmap

Last updated 2026-10-30. Current camera-confirmed build: **flash 15**
(`build/C110_flash15_confirmed.bin`): 8 films (T-Max, Tri-X, Tri-X Red, Kodachrome, Portra,
VSCO J3, T-Max Red, VSCO A5), 25 % less sharpening, NR +15 % at ISO 100–400 and half at ISO ≥ 800,
Snap mode (ISO 200 floor, 1/100 hold, fixed hyperfocal focus), films keep each mode's exposure.
Flash 16 (T-Max Red on Sepia with a deep red, A5 on Partial Color-Blue) runs on the camera, but
T-Max Red = T-Max. Flash 17 moves the red filters into the RGB→YCC luma row; built, awaiting the
camera test (§1 step 8).

Each step ends the usual way: build → `verify_build.py` + emulator tests → preview → flash → the
user tests → FINDINGS §8. Steps marked **research** produce findings, not a flash.

## 1. Film lineup

Goal: eight films on the Colour Effect menu (nine since flash 18).

| film | LUT (`lut examples/`) | status |
|---|---|---|
| Tri-X | `kodak_tri-x_400.cube` | done (Colored Pencil) |
| Kodachrome | `kodakchrome.cube` | done (Sketch) |
| VSCO J3 | `J3_64.cube` | done (Partial Color-Green since flash 15; Negative before), renamed in flash 13 |
| VSCO A5 | `A5_64.cube` | done (Partial Color-Blue since flash 16; Partial Color-Yellow before), renamed in flash 13 |
| Portra | `kodak_portra_160_nc.cube` | done (Partial Color-Red), flash 13 |
| T-Max | `kodak_t-max_3200.cube` | flash 14 (Black and White; Movie menu too) |
| Tri-X Red | Tri-X fit + red-filter channel mix | flash 14 (Partial Color-Green); Negative since flash 15, next to Tri-X |
| T-Max Red | T-Max fit + deep red channel mix | flash 14 (Partial Color-Blue); Sepia with a deep red since flash 16, next to T-Max |
| VSCO A6 | `A6_64.cube` + shadow lift 32 (as A5) | flash 18 (Partial Color-Yellow, next to A5) |

A red filter on B&W film darkens blue sky and foliage and lightens skin and red. Here that means
the same tone curve as the film with a channel mix weighted heavily to red, set in the CCM.

### Limits after flash 14 (flash 18: Retro and Vivid are the only free slots; 360 B free code
= 4 stubs; DTB 0x3794C; string areas full, more strings spill into dead code. FINDINGS §6)
- **Menu slots:** Normal, Retro, Sepia and Vivid are still stock. Retro, Sepia and Vivid may be
  replaced (user); they are Movie menu entries too, where a film is loaded over the movie profile.
- **DTB space:** film nodes are partial profiles (6.8 KB). 40 KB free = about 5 more films.
- **Code and strings:** 248 B of free code since flash 16 (one more stub; the stock Sepia and
  Partial Color-Blue bodies could be proven dead for more). Strings: ~30 B left. More
  needs the 0x77F864 debug format or strings in free code (FINDINGS §6).

### Steps
1. **Flash 13: renames + Portra**: done, camera-confirmed 2026-10-29.
2. **Research: room for the rest**: done 2026-10-29 (FINDINGS §4 "Profile loading", §5, §6).
   - *Partial profiles:* yes. `iqt_dtsi_load` skips blocks a node lacks (stock profiles already
     lack 6 of its 24 blocks), and `PhotoExe_OnColor` always loads a full profile first.
   - *Code:* the stock bodies of cases 2, 6, 8–11 are dead once redirected (only the jump table
     enters them). A table-driven loader was not needed.
   - *Strings:* two more debug-only formats in `PhotoExe_OnColor`.
   - *Movie:* the Movie menu runs the same `PhotoExe_OnColor`; it loads the movie profile, then
     the case. A film on a shared slot therefore applies to movies too, over the movie profile.
3. **Flash 14: B&W set**, built 2026-10-29: T-Max on Black and White (so movies get plain B&W
   film), Tri-X Red on Partial Color-Green, T-Max Red on Partial Color-Blue. J3, A5 and Portra are
   now partial nodes too (same photo parameters as flash 13). To test on the camera:
   - all 8 films still give their look (J3/A5/Portra unchanged from flash 13);
   - the red filters: blue sky darker, skin lighter, more grain than plain Tri-X/T-Max;
   - Movie mode: "T-Max" entry records B&W video.
4. **Flash 15: feedback on flash 14**, built 2026-10-30. The user: grain too much, and Tri-X /
   Tri-X Red should be adjacent. NR × 1.15 at ISO 100–400; Tri-X Red ↔ VSCO J3 slots swapped.
   Menu now: Normal, Retro, T-Max, Sepia, Vivid, Tri-X, Tri-X Red, Kodachrome, Portra, VSCO J3,
   T-Max Red, VSCO A5. **Camera-confirmed 2026-10-30.**
5. **Open: T-Max / T-Max Red** (user, 2026-10-30): far apart in the menu, and they look the same.
   - The data differs a lot on sky, skin, reds and blues, but not on greys or foliage (FINDINGS §7).
     Fx 1 leaves the CCM alone (FINDINGS §5), so the filter should reach the image. Asked for a
     colourful test pair (sky + red/skin) to confirm on the camera.
   - Adjacency: T-Max sits on Black and White (case 2, the Movie entry), and cases 1/3 are stock.
     Options put to the user:
     (a) T-Max Red → Sepia (case 3); Sepia leaves the photo and Movie menus, and Movie gets
     T-Max Red. Case 10 then needs a 9th film, or a film moves there and Partial Color-Yellow
     (case 11) returns to stock at the end. Its dead body then becomes live, and the allocator
     moves the colour helper and stubs; that fits in the remaining free code.
     (b) T-Max next to T-Max Red, with a colour film on Black and White; Movie loses B&W.
     (c) Drop or replace T-Max Red.
   - **User chose (a) + a deeper red** (2026-10-30). Their "2 yes" was taken as fine either way,
     since (a) already makes the two adjacent.
6. **Flash 16**, built 2026-10-30: T-Max Red on Sepia with a deep red mix (1.0, 0.0, −0.15), VSCO A5
   on Partial Color-Blue, Partial Color-Yellow stock again. Menu: Normal, Retro, T-Max, T-Max Red,
   Vivid, Tri-X, Tri-X Red, Kodachrome, Portra, VSCO J3, VSCO A5, Partial Color-Yellow. To test:
   T-Max Red vs T-Max on sky / red / skin; A5 still right; Partial Color-Yellow behaves as stock;
   Movie "T-Max Red" entry records B&W video.
   **Camera (2026-10-30): runs, but T-Max Red = T-Max** (measured, FINDINGS §8). The CCM channel
   mix does not reach the photo.
7. **Open: does the CCM reach captures at all?** It decides whether B&W filters can work through
   the CCM, and whether the colour films' matrices ever applied. Static analysis found no cause
   (FINDINGS §4 "CCM path to the hardware"). Next: a no-flash photo test, with the camera rested
   and the same colourful scene shot as Normal, T-Max, T-Max Red, Tri-X, Tri-X Red and a colour
   film (J3 or Portra). It compares:
   - Tri-X (full node) vs Tri-X Red (partial, same tone curve): partial loading vs CCM in mono;
   - the colour film vs Normal: whether the colour matrix M applies.
   If the CCM never applies, the fallback for B&W filters is the RGB→YCC luma weights (IQ item
   0x1C / `iq_cst`, as stock Sepia does it).
   - User (2026-10-30): the colour films clearly get their looks, so the problem is how mono
     works. No test photos taken.
8. **Flash 17: B&W filters in the CST luma row**, built 2026-10-30. Data only: the red films' nodes
   carry `iq_cst` (rows [214, 61, −19] / [255, 25, −24]) and no `iq_ccm`. It works like stock Sepia,
   and the prelude restores the default CST on the next selection (FINDINGS §4/§5/§7). To test:
   - T-Max Red vs T-Max (and Tri-X Red vs Tri-X) on sky, red and skin: should now differ clearly;
   - after T-Max Red, Normal and the colour films look normal (CST restored);
   - Movie "T-Max Red" entry.
   - Optional later: move T-Max and Tri-X to CST weights too, so their fitted channel response
     applies.

## 2. Screen flip (waist-level finder)

Goal: tilting the screen up no longer flips the image, so it can be used as a waist-level finder.
**User: in every mode; an on/off option would be nice. Research first** (findings: FINDINGS §10).
Status (3 research rounds): the screen flips at ~45°. It is a **whole-display rotation** (menus,
live view, playback); saved photos are not flipped. The panel driver itself never rotates, so the
flip is in the display/graphics layer. The hinge input is not yet identified (not a polled GPIO by
number; likely a key-decoder input or an interrupt). Next: FINDINGS §10 "Next steps".

What the firmware shows so far:
- The OV13B10 sensor driver can flip and mirror the readout (`sen_set_flip_ov13b10`).
- Movie mode keeps a flip state in UI 0x29 and reconfigures the sensor path on event 0x14001110
  (`MovieExe_OnSensorRotate`). That event is also posted by `Photo_MenuCallback` and a debug
  command.
- The LCD driver has a get/set state call (`DrvLCDState`).
- **Not found yet:** the hinge-switch detection and what it calls in photo mode (sensor flip,
  display rotation, or both).

Steps:
1. **Research:** find the hinge detection (GPIO/key-detection tasks) and its handler. Check
   whether saved photos are also rotated when the screen is flipped (sensor flip) or only the
   live view (display).
2. **Flash:** ignore the hinge, so the screen always shows the normal orientation, either
   everywhere or only in Snap. **Decision needed** (see end). Moderate risk: it touches detection
   and display code, so it gets its own flash.

## 3. Later / optional
- Snap: true 1/250 hold (AE-generator code change to skip the anti-flicker period for the Snap
  curve; banding risk under mains lighting).
- Extra looks already in `lut examples/`: Fuji Superia 400, Kodak Elite Extracolor 100,
  GR3 "Plady". Since flash 14 there is DTB and code room; they would go on Retro / Sepia / Vivid
  (Movie menu too) and need more string space.
- Snap cosmetics: EXIF still says "Landscape", and the menu still shows the landscape icon.

## Decisions (user, 2026-10-29)
1. **Film slots:** Retro, Black and White, Sepia and Vivid may all be replaced.
2. **Screen flip:** remove it in every mode; an option would be nice. Research first.
3. **Labels:** "VSCO J3", "VSCO A5", "Portra", "T-Max", "Tri-X Red", "T-Max Red" approved.
4. **(2026-10-30)** Pairs side by side: Tri-X / Tri-X Red, T-Max / T-Max Red. Sepia may go
   (photo and Movie) for T-Max Red. T-Max Red gets a deeper red. Partial Color-Yellow back to
   stock at the end of the list.
