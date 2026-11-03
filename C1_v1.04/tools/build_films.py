#!/usr/bin/env python3
"""Build a Pixpro C1 v1.04 firmware with eight film simulations on reused
colour-effect slots (menu order confirmed on the camera):

  Black and White (case 2)       -> "T-Max"       new node ov13b10_tmax, fx 1 (Movie menu too)
  Sepia (case 3)                 -> "T-Max Red"   new node ov13b10_tmaxred, fx 1 (Movie menu too)
  Colored Pencil (case 5)        -> "Tri-X"       stock node ov13b10_iq_0_colorpencil, fx 1 (B&W)
  Negative (case 6)              -> "Tri-X Red"   new node ov13b10_trixred, fx 1
  Sketch (case 7)                -> "Kodachrome"  stock node ov13b10_iq_1_colorpencil, fx 0
  Partial Color-Red (case 8)     -> "Portra"      new node ov13b10_portra, fx 0
  Partial Color-Green (case 9)   -> "VSCO J3"     new node ov13b10_j3, fx 0
  Partial Color-Blue (case 10)   -> "VSCO A5"     new node ov13b10_a5, fx 0
Partial Color-Yellow (case 11) is stock again.

New nodes hold only the film blocks (FILM_BLOCKS); everything else stays as the full
profile PhotoExe_OnColor loads just before them. The unreferenced ov13b10_iq_shading_1
node is removed.

Each look is fitted from a .cube LUT (tools/fit_lut.py) onto the CCM, gamma,
Y curve and saturation blocks. Tri-X Red and T-Max Red keep the stock CCM and put their
B&W filter in the RGB->YCC luma row (iq_cst) instead.

The Landscape shooting mode becomes "Snap": its own AE program line (ISO 200 floor,
shutter held at 1/100 while ISO rises to 1600, then no slower), and fixed hyperfocal
focus while macro is off. See SNAP and snap_focus_code below.

Usage: build_films.py C110.bin out/C110.bin [lut_dir]
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvtfw as nf
import bcl1patch as bp

BASE = 0x10000                    # RTOS load address
RTOS_ID = 6

# --------------------------------------------------------------- film looks

LUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lut examples')

EXIT_FX0 = 0x420b58     # "image effect = none" exit (was case 7's fx 7 exit)
EXIT_FX1 = 0x4212c8     # "image effect = B&W" exit (was case 5's fx 8 exit)

FILMS = {
    # Existing colorpencil nodes are reached through stock short paths (see rtos_edits).
    # A new node also needs: case = PhotoExe_OnColor switch case to take over,
    # exit = EXIT_FX0/EXIT_FX1, and optionally stub = a fixed free dead-code address for its
    # 80-byte reload stub (otherwise one is allocated in FREE_CODE).
    # Optional lift = black level (0..255) for a filmic shadow toe on top of the LUT fit.
    # case is also the colour-effect UI value that the EXIF preset text is keyed on.
    # Menu order = case order. Entry order here only sets where strings and stubs are placed.
    'ov13b10_iq_0_colorpencil': dict(name='Tri-X',      sid=276, lut='kodak_tri-x_400.cube', mono=True,  case=5),
    'ov13b10_iq_1_colorpencil': dict(name='Kodachrome', sid=32,  lut='kodakchrome.cube',     mono=False, case=7),
    # case 9 = Partial Color-Green (sid 275); on Negative (case 6) until flash 14
    'ov13b10_j3':               dict(name='VSCO J3',    sid=275, lut='J3_64.cube',           mono=False,
                                     new=True, case=9, stub=0x42099c, exit=EXIT_FX0),
    # case 10 = Partial Color-Blue (sid 274); on Partial Color-Yellow (case 11, sid 273) until
    # flash 15. Case 11 is stock again, so its stock body (DEAD_CASE_CODE 10/11) is live.
    'ov13b10_a5':               dict(name='VSCO A5',    sid=274, lut='A5_64.cube',           mono=False, lift=32,
                                     new=True, case=10, stub=0x4209ec, exit=EXIT_FX0),
    # case 11 = Partial Color-Yellow (sid 273; A5's slot until flash 15), next to A5, same lift.
    # With cases 10 and 11 both films, their stock bodies (DEAD_CASE_CODE) are free code again.
    'ov13b10_a6':               dict(name='VSCO A6',    sid=273, lut='A6_64.cube',           mono=False, lift=32,
                                     new=True, case=11, exit=EXIT_FX0),
    # case 8 = Partial Color-Red (ccid 8, sid 272)
    'ov13b10_portra':           dict(name='Portra',     sid=272, lut='kodak_portra_160_nc.cube', mono=False,
                                     new=True, case=8, exit=EXIT_FX0),
    # case 2 = Black and White (sid 26). The Movie colour menu offers it too, and in Movie
    # PhotoExe_OnColor loads this node over the movie profile (ov13b10_iq).
    'ov13b10_tmax':             dict(name='T-Max',      sid=26,  lut='kodak_t-max_3200.cube', mono=True,
                                     new=True, case=2, exit=EXIT_FX1),
    # case 6 = Negative (sid 30), next to Tri-X (Partial Color-Green until flash 14);
    # case 3 = Sepia (sid 31), next to T-Max, Movie menu too (Partial Color-Blue until flash 15).
    # mix = B&W filter: channel weights on the film's tone curve. Tri-X Red: red (#25-like).
    # T-Max Red: deep red (#29-like, flash 16; was the #25 mix), no green and some blue taken away.
    # cst = apply the filter in the RGB->YCC luma row (iq_cst), as stock Sepia makes its mono,
    # with the stock CCM: a mix in the CCM rows had no effect on mono captures (flash 15/16).
    'ov13b10_trixred':          dict(name='Tri-X Red',  sid=30,  lut='kodak_tri-x_400.cube', mono=True,
                                     mix=(0.85, 0.20, -0.05), cst=True, new=True, case=6, exit=EXIT_FX1),
    'ov13b10_tmaxred':          dict(name='T-Max Red',  sid=31,  lut='kodak_t-max_3200.cube', mono=True,
                                     mix=(1.0, 0.0, -0.15), cst=True, new=True, case=3, exit=EXIT_FX1),
}
NEW_NODES = tuple(n for n, f in FILMS.items() if f.get('new'))   # cloned from ov13b10_iq_0_cap
# New film nodes keep only these blocks. iqt_dtsi_load (0x344068) skips blocks a node lacks
# and leaves those parameters as they were (stock profiles already lack 6 of its 24 blocks),
# and PhotoExe_OnColor reloads the full capture profile (in Movie: the movie profile) just
# before the film node, so the rest comes from there.
FILM_BLOCKS = ('iq_gamma', 'iq_ycurve', 'iq_ccm', 'iq_color')
# cst films: no iq_ccm (the capture profile's stays), plus iq_cst, which no profile has. The camera
# runs on the IQ library's default (pointer table IQ_DEFAULTS, loader order). PhotoExe_OnColor saves
# that once and writes it back (set_iq 0x1c, 0x420710) before every colour effect, so a film's
# iq_cst lasts only until the next selection, as with stock Sepia.
CST_BLOCKS = ('iq_gamma', 'iq_ycurve', 'iq_color', 'iq_cst')
IQ_LOAD_TABLE = 0x3448cc                      # iqt_dtsi_load: 24 x {char name[0x40]; void *; u32 size}
IQ_DEFAULTS = 0x34b538                        # 24 default param pointers, same order
CST_INDEX = 22                                # iq_cst: u32 mode; s16 coef[9] (Y, Cb, Cr rows, Q8); ...
CST_COEF = (-256, 255)                        # 9-bit signed register fields (writer 0x295174)
DROP_NODES = ('ov13b10_iq_shading_1',)        # unreferenced by firmware, frees 67 KB

def film_blocks(f):
    return CST_BLOCKS if f.get('cst') else FILM_BLOCKS

def iq_default(img, index):
    """(name, default param bytes) of iqt_dtsi_load table entry `index`."""
    a = IQ_LOAD_TABLE + 0x48 * index
    name = img[a - BASE:a - BASE + 0x40].split(b'\0')[0].decode()
    size = struct.unpack_from('<I', img, a + 0x44 - BASE)[0]
    ptr = struct.unpack_from('<I', img, IQ_DEFAULTS + 4 * index - BASE)[0]
    return name, img[ptr - BASE:ptr - BASE + size]

def cst_block(default, row):
    """iq_cst data: the default with the luma row set to `row` and both chroma rows 0 (mono)."""
    assert len(default) == 0x2c and struct.unpack_from('<9h', default, 4) == (77, 150, 29, -43, -85, 128, 128, -107, -21)
    assert sum(row) == 256 and all(CST_COEF[0] <= c <= CST_COEF[1] for c in row)
    b = bytearray(default)
    struct.pack_into('<9h', b, 4, *row, 0, 0, 0, 0, 0, 0)
    return bytes(b)

# Still-photo tuning in the capture profile (Normal, stock effects, and every film, which
# copies it). Per-ISO blocks hold record 0 = manual_param (unused, mode = auto) and records
# 1-16 = auto levels, record r = ISO 100 << (r - 1); the firmware interpolates between them.
# Sharpening: edge_enh_p/edge_enh_n of every iq_edge record are scaled.
SHARPEN = 0.75                                # 1.0 = stock
EDGE_HDR, EDGE_REC, EDGE_LVLS = 19, 21, 17    # iq_edge words: header, record, records
# Noise reduction: the range filters A/B (filter_th, filter_lut, filter_th_b, filter_lut_b)
# of iq_nr are scaled, as the firmware's own NR ratio does (0x3167c8): records
# 1..DENOISE_FROM-1 by DENOISE_LOW, records DENOISE_FROM..16 by DENOISE.
DENOISE_LOW = 1.15                            # ISO 100-400; 1.0 = stock
DENOISE = 0.5                                 # ISO 800 and up; 1.0 = stock
DENOISE_FROM = 4                              # record 4 = ISO 800
NR_HDR, NR_REC, NR_LVLS = 0x18, 0x11c, 17     # iq_nr bytes: header, record, records
NR_FILTERS = ((0x38, 6), (0x50, 17), (0x94, 6), (0xac, 17))   # (offset in record, u32 count)

# PhotoExe_OnColor jump table (12 x `b`) and the stock target of each case
JUMP_TABLE = 0x4208d8
STOCK_CASES = (0x420d1c, 0x420d48, 0x420f54, 0x421000, 0x4210ac, 0x42110c,
               0x4212e0, 0x42099c, 0x4212f8, 0x4213a0, 0x420e08, 0x420eac)
# Stock case bodies that are dead once every listed case goes to a film: only the jump table
# branches into them, nothing falls through (the instruction before each is `b 0x420b6c`) and
# they hold no literal pools. The first two FREE_CODE ranges are dead since cases 5 and 7 go
# to their short paths.
DEAD_CASE_CODE = (((0x420e08, 0x420f54), (10, 11)),
                  ((0x420f54, 0x421000), (2,)),
                  ((0x4212e0, 0x421448), (6, 8, 9)))   # 0x421448 is a shared tail: live
FREE_CODE = ((0x42099c, 0x420b58), (0x42110c, 0x4212c8)) + tuple(
    r for r, cases in DEAD_CASE_CODE if set(cases) <= {f['case'] for f in FILMS.values()})
# debug-only printf formats used as string storage: (start, last usable byte)
STRING_AREAS = ((0x77f9e0, 0x77fa0b),         # "COLOR_EFFECT_STANDARD"
                (0x77f930, 0x77f96c),         # "movie iq"
                (0x77f9a0, 0x77f9dc),         # "photo iq"
                (0x77f894, 0x77f8c5),         # "COLOR on,BEAUTY set OFF ..."
                (0x77f8c8, 0x77f8e9))         # "uhSelect=%d"
# strings that do not fit there go to the start of the dead case 10/11 body (when both are films)
STRING_SPILL = DEAD_CASE_CODE[0][0][0]

# EXIF: IFD0 ImageDescription = "Preset: <film>" on film slots (stock text otherwise),
# Software = FIRMWARE. Helpers live in the second FREE_CODE range.
FW_PATCH = 18                                 # bump for every flash
FIRMWARE = f'Ricardos custom firmware {FW_PATCH}'
PRESET = 'Preset: {}'
EXIF_CODE = 0x42110c
UI_GET = 0x442434                             # UI_get(idx); idx 3 = colour effect = case
DESC_LDR = 0x41594c                           # ldr lr,[pc,#0x270]: ImageDescription offset
DESC_BASE = 0x415968                          # ...added to pc at 0x415960
DESC_LEN = 27                                 # count hardcoded at 0x4159e8
SW_LEN_MOV = 0x415aa4                         # mov r2,#13: Software count/size
SW_CALL = 0x415b0c                            # bl 0x4447c0 -> "1.04"

# Snap mode on the Landscape slot (DC mode UI 0xa2 = 2, label sid 54, which has no settings of
# its own). Its AE curve index (u16 at +0x2e of its mode-table record) goes to curve 1, the
# factory IQ-test curve, rewritten as the snap program line. In auto ISO the AE generator
# always runs the first node's ISO up to one flicker period (1/100 s at 50 Hz) before raising
# ISO, so the hold is 1/100, not faster.
SNAP = dict(name='Snap', sid=54, mode=2)
SNAP_NODES = ((1, 200), (10000, 200), (10000, 1600))   # (exposure us, ISO)
SNAP_EXPT_MAX, SNAP_ISO_MAX = 10000, 1600
MODE_TABLE, MODE_REC = 0xb11bc8, 0x34          # 9 records, indexed by DC mode
AE_CURVE1 = 0x77ecc4                           # ae_curve_gen_photo layout, 53 words
STOCK_CURVE1 = ((1, 100), (8333, 400), (16666, 600), (25000, 800)), (25000, 800, 1, 1000)
# curve 1's exposure and ISO limits repeated as immediates in the capture AE code
# (PhotoExe_CalAEandAWB, PhotoExe_Capture_CalAE); executed only for curve index 1
CURVE1_EXPT_MOVW = ((0x426498, 6), (0x42731c, 5))      # movweq rN, #25000
CURVE1_ISO_MOV = (0x426c98, 0x42759c)                  # mov r3, #800

# Snap fixed focus (macro off). Half-press AF (PhotoExe_AFStart_Single) does not start AF: the
# lens goes to the hyperfocal code and the AF status reads "focused". PhotoExe_AFStart (mode open,
# periodic live-view AF, events) does nothing but make sure the lens is there: no AF, no AF-running
# flag, no completion. The stock rest position (60 cm position - 25) becomes the hyperfocal one.
# The lens is written only when it is not already at that code.
# Position = P60 - K * (P8 - P60) / 256 from the camera's own AF calibration (60 cm and 8 cm VCM
# codes), K from lens extension f^2/(d - f) at SNAP_FOCUS_MM, assuming the VCM code is linear in
# extension. Camera-tested at 2800 (flash 11): ~1 m to infinity.
SNAP_FOCUS_MM = 2800                          # ~1.4 m to infinity at a 2-pixel circle of confusion
SNAP_CODE = 0x420a3c                          # in the first FREE_CODE range, after the A5 stub
LENS_SET = 0x54c5d0                           # set VCM code (FP5510 over I2C), r0 = code
LENS_GET = 0x54c648                           # last code written by LENS_SET (0xb187dc)
AF_LOW, AF_HIGH = 0x4845c0, 0x4845f0          # GetAFlowPos / GetAFhighPos: 60 cm / 8 cm codes
SET_AF, GET_AF = 0x532858, 0x53283c           # vendor_isp_set_af / vendor_isp_get_af
AF_TRIGGER = 0x42a3f0                         # bl set_af(0x29) in PhotoExe_AFStart_Single
AF_STATUS = 0x42a60c                          # bl get_af(0x2b) in PhotoExe_GetAFStatus
AF_START_FN = 0x429078                        # PhotoExe_AFStart: push {r4, r5, fp, lr}
AF_START_PUSH = 0xe92d4830
LENS_PARKS = (0x41a2d4, 0x4563e0, 0x45f020)   # bl LENS_SET(GetAFlowPos() - 25)

# Colour effect keeps the mode's AE curve: PhotoExe_OnColor reloads the DTB AE profile, which
# replaces the curve the shooting mode set. At its common exit (ldr r3,[fp,#-0x114]) call a
# helper that posts the mode-curve event again, as FlowPhoto_InitCfgSetting does (not in Movie).
COLOR_EXIT = 0x420b6c
COLOR_EXIT_LDR = 0xe51b3114                   # ldr r3, [fp, #-0x114]
UX_POST = 0x557738                            # Ux_PostEvent(obj, event, nparams, ...)
PHOTO_OBJ_GOT = 0x2b980 + 0x508c              # GOT slot holding the PhotoExe event object
EV_AE_CURVE = 0x1400211b                      # -> PhotoExe_OnAECurveProcess
MOVIE_MODE = 7

def snap_k(focus_mm=SNAP_FOCUS_MM, f=3.57):
    e = lambda d: f * f / (d - f)                       # lens extension (mm) focused at d
    return round(256 * (e(600) - e(focus_mm)) / (e(80) - e(600)))

def u32s(b):
    return list(struct.unpack('<%dI' % (len(b) // 4), b))

def soften_edges(root, k=SHARPEN):
    p = next(p for p in nf.find(root, '/isp/iq/ov13b10_iq_0_cap/iq_edge').props if p[0] == 'data')
    w = u32s(p[1])
    assert len(w) == EDGE_HDR + EDGE_REC * EDGE_LVLS
    for lv in range(EDGE_LVLS):
        o = EDGE_HDR + EDGE_REC * lv              # edge_enh_p, edge_enh_n (0..1023)
        w[o:o + 2] = [round(v * k) for v in w[o:o + 2]]
    p[1] = struct.pack('<%dI' % len(w), *w)

def nr_scale(lv):
    """NR factor of iq_nr record lv (record 0 = manual_param, unused in auto mode)."""
    return 1.0 if lv == 0 else DENOISE_LOW if lv < DENOISE_FROM else DENOISE

def tune_nr(root):
    p = next(p for p in nf.find(root, '/isp/iq/ov13b10_iq_0_cap/iq_nr').props if p[0] == 'data')
    b = bytearray(p[1])
    assert len(b) == NR_HDR + NR_REC * NR_LVLS
    for lv in range(1, NR_LVLS):
        k = nr_scale(lv)
        for off, n in NR_FILTERS:
            o = NR_HDR + NR_REC * lv + off
            v = struct.unpack_from('<%dI' % n, b, o)
            struct.pack_into('<%dI' % n, b, o, *[min(1023, round(x * k)) for x in v])
    p[1] = bytes(b)

def film_fit(f, x, ys, lut_dir=LUT_DIR):
    """LUT fit for a film, with its optional shadow lift and B&W filter mix (the mix replaces
    the fitted channel weights, scaled to their sum so mid-grey stays put)."""
    import numpy as np
    import cube, fit_lut
    lut = cube.load(os.path.join(lut_dir, f['lut']))
    fit = (fit_lut.fit_mono if f['mono'] else fit_lut.fit_colour)(lambda s: cube.apply(lut, s), x, ys)
    if f.get('lift'):
        fit['curve'] = fit_lut.lift(fit['curve'], f['lift'] / 255)
    if f.get('mix') is not None:
        assert f['mono'], 'mix is a B&W filter'
        mix = np.array(f['mix'], float)
        fit['w'] = mix / mix.sum() * fit['w'].sum()
    if f.get('cst'):
        assert f['mono'], 'cst is a B&W filter'
        fit['luma'] = fit_lut.luma_row(fit['curve'], fit['w'], x, ys, *CST_COEF)
    return fit

def film_profile(root, node, f, lut_dir, cst_default=None):
    import numpy as np
    import fit_lut
    cap = nf.find(root, '/isp/iq/ov13b10_iq_0_cap')
    dst = nf.find(root, '/isp/iq/' + node)
    # start from the stock still-capture tuning, change the film blocks; new nodes then keep
    # only those
    for c, e in zip(cap.children, dst.children):
        assert c.name == e.name
        e.props = [[k, bytes(v)] for k, v in c.props]
    def blob(sub):
        return next(p for p in nf.find(dst, sub).props if p[0] == 'data')

    gp, yp, cp, colp = blob('iq_gamma'), blob('iq_ycurve'), blob('iq_ccm'), blob('iq_color')
    g = u32s(gp[1]); yc = u32s(yp[1])
    G1 = slice(544, 673)                                    # 129-pt gamma curves (0..1023);
    CURVES = (G1, slice(674, 803), slice(804, 933))         # 2 and 3 follow LV thresholds
    x, ys = fit_lut.stock_tone(g[G1], yc[1:])
    fit = f['fit'] = film_fit(f, x, ys, lut_dir)

    # tone -> all three gamma curves; curves 2/3 keep their stock offset from curve 1
    c1 = np.array(g[G1], float)
    c1m = np.maximum.accumulate(c1 + np.arange(129) * 1e-6)
    for sl in CURVES:
        lin = np.interp(np.array(g[sl], float), c1m, np.linspace(0, 1, 129))
        v = np.clip(np.round(fit_lut.tone(fit['curve'], lin) * 1023), 0, 1023)
        g[sl] = list(np.maximum.accumulate(v).astype(int))
    gp[1] = struct.pack('<933I', *g)
    # the fitted tone already includes the stock Y curve: make the Y curve identity
    yc[1:] = [min(255, 2 * i) for i in range(129)]
    yp[1] = struct.pack('<130I', *yc)

    # colour matrix folded into each of the 4 colour-temperature CCM slots (Q8); cst films keep
    # the stock matrix (their node has no iq_ccm) and get the filter in the luma row instead
    if not f.get('cst'):
        M = np.tile(fit['w'], (3, 1)) if f['mono'] else fit['M']
        b = bytearray(cp[1])
        for slot in range(4):
            o = slot * 0x90 + 4
            C = np.array(struct.unpack_from('<9h', b, o), float).reshape(3, 3)
            N = np.clip(np.round(M @ C), -2047, 2047).astype(int)
            struct.pack_into('<9h', b, o, *N.ravel())
        cp[1] = bytes(b)

    # saturation: byte 0 of each of the 17 per-ISO records in iq_color
    sat = 0.0 if f['mono'] else fit['sat']
    b = bytearray(colp[1])
    for lv in range(17):
        o = 4 + 104 * lv
        b[o] = max(0, min(255, round(b[o] * sat)))
    colp[1] = bytes(b)

    if f.get('new'):
        dst.children = [c for c in dst.children if c.name in film_blocks(f)]
    if f.get('cst'):
        assert f.get('new') and cst_default is not None
        data = cst_block(cst_default, fit['luma']['row'])
        cst = nf.Node('iq_cst')
        cst.props = [['size', struct.pack('<I', len(data))], ['data', data]]
        dst.children.insert([c.name for c in dst.children].index('iq_ycurve') + 1, cst)   # loader order

# --------------------------------------------------------------- RTOS patch

def b_insn(src, dst):
    return 0xea000000 | (((dst - src - 8) >> 2) & 0xffffff)

NOP = 0xe320f000

def bl_insn(src, dst):
    return 0xeb000000 | (((dst - src - 8) >> 2) & 0xffffff)

def reload_stub(at, path_addr, exit_addr):
    """Relocated copy of the stock case-7 short path (0x42146c): fill the
    {id, path[256], "null"[256], dtsi} reload request, vendor_isp_set_iq(3, ...),
    then branch to an exit that sets the image effect."""
    NULL_STR = 0x77d2e8
    code = [
        0xe59f1040,                         # ldr  r1, [pc, #0x40]   -> path literal
        0xe3a03000,                         # mov  r3, #0
        0xe1a00006,                         # mov  r0, r6
        0xe3a02c01,                         # mov  r2, #0x100
        0xe4803004,                         # str  r3, [r0], #4
        0xe08f1001,                         # add  r1, pc, r1
        bl_insn(at + 0x18, 0xd5944),        # bl   strncpy
        0xe59f1028,                         # ldr  r1, [pc, #0x28]   -> "null" literal
        0xe3a02c01,                         # mov  r2, #0x100
        0xe2860f41,                         # add  r0, r6, #0x104
        0xe08f1001,                         # add  r1, pc, r1
        bl_insn(at + 0x2c, 0xd5944),        # bl   strncpy
        bl_insn(at + 0x30, 0x31390),        # bl   get dtsi
        0xe1a01006,                         # mov  r1, r6
        0xe5860204,                         # str  r0, [r6, #0x204]
        0xe3a00003,                         # mov  r0, #3            (IQT_ITEM_RLD_DTSI)
        bl_insn(at + 0x40, 0x5328c8),       # bl   vendor_isp_set_iq
        b_insn(at + 0x44, exit_addr),       # b    exit
        (path_addr - (at + 0x14 + 8)) & 0xffffffff,
        (NULL_STR - (at + 0x28 + 8)) & 0xffffffff,
    ]
    return struct.pack('<%dI' % len(code), *code)

def exif_code(at, img):
    """Two helpers plus their strings:
    desc: called in place of `ldr lr,[pc,#0x270]` at DESC_LDR. Returns in lr the
          ImageDescription offset (string - DESC_BASE): "Preset: <film>" when
          UI_get(3) is a film's case, else the stock literal. Clobbers r0, r2, r3.
    sw:   called in place of `bl 0x4447c0`; returns r0 = FIRMWARE.
    Returns (code bytes, address of the sw helper)."""
    films = sorted((f['case'], PRESET.format(f['name'])) for f in FILMS.values())
    stock_lit = struct.unpack_from('<I', img, DESC_LDR + 8 + 0x270 - BASE)[0]
    assert stock_lit == 0x77cca0 - DESC_BASE
    n = len(films)
    code_words = 4 + 2 * n + 1                         # push, mov, bl, ldr, n*(cmp, ldreq), pop
    lits = at + 4 * code_words                         # default literal, then one per film
    sw = lits + 4 * (n + 1)                            # sw helper: ldr, add, bx, literal
    strs = sw + 16
    desc_strs, a = [], strs
    for _, t in films:
        assert len(t) < DESC_LEN, f'{t!r} longer than {DESC_LEN - 1} characters'
        desc_strs.append(a); a += 28
    fw_str = a
    def ldr_lr(pc_at, lit):
        off = lit - (pc_at + 8)
        assert 0 <= off < 0x1000
        return 0xe59fe000 | off
    w = [0xe92d4010,                                   # push {r4, lr}
         0xe3a00003,                                   # mov  r0, #3
         bl_insn(at + 8, UI_GET),                      # bl   UI_get
         ldr_lr(at + 12, lits)]                        # ldr  lr, =stock text
    for k, (case, _) in enumerate(films):
        assert 0 <= case < 12
        w += [0xe3500000 | case,                       # cmp  r0, #case
              ldr_lr(at + 4 * len(w) + 4, lits + 4 * (k + 1)) & 0x0fffffff]   # ldreq lr, =film
    w.append(0xe8bd8010)                               # pop  {r4, pc}
    assert at + 4 * len(w) == lits
    w.append(stock_lit)
    w += [(s - DESC_BASE) & 0xffffffff for s in desc_strs]
    w += [0xe59f0004,                                  # ldr  r0, [pc, #4]
          0xe08f0000,                                  # add  r0, pc, r0
          0xe12fff1e,                                  # bx   lr
          (fw_str - (sw + 12)) & 0xffffffff]
    out = struct.pack('<%dI' % len(w), *w)
    for _, t in films:
        out += t.encode().ljust(28, b'\0')
    out += FIRMWARE.encode() + b'\0'
    return out, sw

def snap_focus_code(at, k=None):
    """Snap fixed-focus helpers. Returns (code bytes, {'start', 'status', 'park', 'afstart'}).
    start:   in place of `bl vendor_isp_set_af` (item 0x29) in PhotoExe_AFStart_Single. In Snap:
             lens to the hyperfocal code, return 0, AF not started. Else: tail-call the stock.
    status:  in place of `bl vendor_isp_get_af` (item 0x2b). In Snap: exec status (+4) = 1
             (focused), return 0. Else: tail-call the stock.
    park:    in place of `bl LENS_SET` with the stock rest position. In Snap: the hyperfocal code.
    afstart: branched to from the first instruction of PhotoExe_AFStart. In Snap: lens to the
             hyperfocal code and return (no AF, no flag). Else: its push, then continue there.
    The lens is only written when LENS_GET differs from the hyperfocal code.
    Snap = UI_get(0xa2) == SNAP['mode'] and UI_get(0x58) (macro) == 0."""
    k = snap_k() if k is None else k
    assert 0 < k < 256
    def bcond(src, dst, cond):                          # b<cond> to an absolute address
        return (b_insn(src, dst) & 0x0fffffff) | cond << 28
    EQ, NE = 0, 1
    w = []
    def emit(*ins):                                     # callables get their own address
        for i in ins:
            w.append(i(at + 4 * len(w)) if callable(i) else i)
    pc = lambda: at + 4 * len(w)
    is_snap = pc()
    emit(0xe92d4010,                                    # push {r4, lr}
         0xe3a000a2,                                    # mov  r0, #0xa2      (DC mode)
         lambda a: bl_insn(a, UI_GET),                  # bl   UI_get
         0xe2504000 | SNAP['mode'],                     # subs r4, r0, #mode
         0x1a000002,                                    # bne  1f
         0xe3a00058,                                    # mov  r0, #0x58      (macro)
         lambda a: bl_insn(a, UI_GET),                  # bl   UI_get
         0xe1a04000,                                    # mov  r4, r0
         0xe3540000,                                    # 1: cmp r4, #0
         0x03a00001,                                    # moveq r0, #1
         0x13a00000,                                    # movne r0, #0
         0xe8bd8010)                                    # pop  {r4, pc}
    snap_pos = pc()
    emit(0xe92d4010,                                    # push {r4, lr}
         lambda a: bl_insn(a, AF_LOW),                  # bl   GetAFlowPos   (60 cm code)
         0xe1a04000,                                    # mov  r4, r0
         lambda a: bl_insn(a, AF_HIGH),                 # bl   GetAFhighPos  (8 cm code)
         0xe0500004,                                    # subs r0, r0, r4    (span)
         0xe3a01000 | k,                                # mov  r1, #k
         0xe0000091,                                    # mul  r0, r1, r0
         0xe1a00440,                                    # asr  r0, r0, #8
         0xd3a00019,                                    # movle r0, #25      (bad calibration)
         0xe0440000,                                    # sub  r0, r4, r0
         0xe6ea0010,                                    # usat r0, #10, r0
         0xe8bd8010)                                    # pop  {r4, pc}
    snap_lens = pc()                                    # lens to the hyperfocal code; returns 0
    emit(0xe92d4010,                                    # push {r4, lr}
         lambda a: bl_insn(a, snap_pos),                # bl   snap_pos
         0xe1a04000,                                    # mov  r4, r0
         lambda a: bl_insn(a, LENS_GET),                # bl   lens_get      (last code written)
         0xe1500004,                                    # cmp  r0, r4
         0xe1a00004,                                    # mov  r0, r4
         lambda a: (bl_insn(a, LENS_SET) & 0x0fffffff) | NE << 28,   # blne lens_set
         0xe3a00000,                                    # mov  r0, #0
         0xe8bd8010)                                    # pop  {r4, pc}
    def prologue():                                     # Z set when not Snap; r0-r2, lr kept
        emit(0xe92d4007,                                # push {r0, r1, r2, lr}
             lambda a: bl_insn(a, is_snap),             # bl   is_snap
             0xe3500000,                                # cmp  r0, #0
             0xe8bd4007)                                # pop  {r0, r1, r2, lr}
    start = pc()
    prologue()
    emit(lambda a: bcond(a, SET_AF, EQ),                # beq  vendor_isp_set_af
         lambda a: b_insn(a, snap_lens))                # b    snap_lens
    status = pc()
    prologue()
    emit(lambda a: bcond(a, GET_AF, EQ),                # beq  vendor_isp_get_af
         0xe3a00001,                                    # mov  r0, #1
         0xe5810004,                                    # str  r0, [r1, #4]  (exec status)
         0xe3a00000,                                    # mov  r0, #0
         0xe12fff1e)                                    # bx   lr
    park = pc()
    prologue()
    emit(lambda a: bcond(a, LENS_SET, EQ),              # beq  lens_set      (stock position)
         lambda a: b_insn(a, snap_lens))                # b    snap_lens
    afstart = pc()
    prologue()
    emit(lambda a: bcond(a, snap_lens, NE),             # bne  snap_lens     (Snap: no AF)
         AF_START_PUSH,                                 # push {r4, r5, fp, lr}  (relocated)
         lambda a: b_insn(a, AF_START_FN + 4))          # b    PhotoExe_AFStart + 4
    return struct.pack('<%dI' % len(w), *w), dict(start=start, status=status, park=park, afstart=afstart)

def color_code(at):
    """Called in place of `ldr r3,[fp,#-0x114]` at PhotoExe_OnColor's common exit: unless in
    Movie, post EV_AE_CURVE to the PhotoExe object (re-applies the mode's AE curve after the
    DTB AE reload), then do the replaced load. Clobbers r0-r2, ip."""
    w = []
    def emit(*ins):
        for i in ins:
            w.append(i(at + 4 * len(w)) if callable(i) else i)
    lit = at + 4 * 14
    emit(0xe92d4010,                                    # push {r4, lr}
         0xe3a000a2,                                    # mov  r0, #0xa2      (DC mode)
         lambda a: bl_insn(a, UI_GET),                  # bl   UI_get
         0xe3500000 | MOVIE_MODE,                       # cmp  r0, #7
         0x0a000006,                                    # beq  1f
         lambda a: 0xe59f0000 | (lit - (a + 8)),        # ldr  r0, [pc, #lit]
         0xe08f0000,                                    # add  r0, pc, r0    (GOT slot)
         0xe5900000,                                    # ldr  r0, [r0]      (PhotoExe object)
         0xe3000000 | (EV_AE_CURVE >> 12 & 0xf) << 16 | 1 << 12 | (EV_AE_CURVE & 0xfff),          # movw r1, #ev
         0xe3400000 | (EV_AE_CURVE >> 28) << 16 | 1 << 12 | (EV_AE_CURVE >> 16 & 0xfff),          # movt r1, #ev>>16
         0xe3a02000,                                    # mov  r2, #0
         lambda a: bl_insn(a, UX_POST),                 # bl   Ux_PostEvent
         COLOR_EXIT_LDR,                                # 1: ldr r3, [fp, #-0x114]
         0xe8bd8010,                                    # pop  {r4, pc}
         lambda a: (PHOTO_OBJ_GOT - (at + 4 * 6 + 8)) & 0xffffffff)   # literal for the add at +0x18
    assert at + 4 * 14 == lit
    return struct.pack('<%dI' % len(w), *w)

def curve_words(nodes, tail):
    w = [0] * 53
    for i, (expt, iso) in enumerate(nodes):
        w[4 * i], w[4 * i + 1] = expt, iso
    w[48:53] = [len(nodes), *tail]
    return w

def movw(cond_rd, imm):                       # movw with the cond/Rd of an existing one
    return (cond_rd & 0xfff0f000) | (imm >> 12) << 16 | (imm & 0xfff)

def rtos_edits(img):
    e = {}
    def word(addr, val, expect):
        o = addr - BASE
        cur = struct.unpack_from('<I', img, o)[0]
        assert cur == expect, f'{addr:#x}: {cur:#010x} != {expect:#010x}'
        for k, byte in enumerate(struct.pack('<I', val)):
            e[o + k] = byte
    def blob(addr, data):
        for k, byte in enumerate(data):
            e[addr - BASE + k] = byte

    def case_to(case, dst):
        a = JUMP_TABLE + 4 * case
        word(a, b_insn(a, dst), b_insn(a, STOCK_CASES[case]))

    # PhotoExe_OnColor switch: send cases 5 and 7 straight to their short
    # "reload colorpencil profile, set image effect, exit" paths
    case_to(5, 0x4214b4)                                      # menu: Colored Pencil
    case_to(7, 0x42146c)                                      # menu: Sketch
    # case 7 short path: load ..._iq_1_colorpencil (0x77fa30) instead of _0_ (0x77fa0c)
    word(0x4215d8, 0x35e584 + 0x24, 0x35e584)
    # image effects: case 7 -> 0 (none), case 5 -> 1 (black and white)
    word(EXIT_FX0, 0xe3a03000, 0xe3a03007)
    word(EXIT_FX1, 0xe3a03001, 0xe3a03008)
    # Get_QualityValue: drop the reduced JPEG quality used for effects 7 and 5
    word(0x44568c, NOP, 0x0a000010)
    word(0x44569c, NOP, 0x0a00000c)

    # new strings go in a debug-only printf format in PhotoExe_OnColor
    # ("\e[1;31mERR:%s() COLOR_EFFECT_STANDARD\r\n\e[0m", 43 bytes), so it just
    # logs the first label; the next string (0x77fa0c) is live and must survive
    for lo, hi in STRING_AREAS:
        assert img[hi - 4 - BASE:hi + 1 - BASE] == b'\x1b[0m\0', f'{lo:#x} is not a debug format'
    areas = [list(a) for a in STRING_AREAS]
    spill = bytearray()
    def put(s):
        for ar in areas:
            if ar[0] + len(s) <= ar[1]:
                a = ar[0]
                blob(a, s + b'\0')
                ar[0] = (a + len(s) + 1 + 3) & ~3
                return a
        if any(lo == STRING_SPILL for lo, _ in FREE_CODE):
            a = STRING_SPILL + len(spill)
            spill.extend(s + b'\0' + bytes(-(len(s) + 1) % 4))
            return a
        raise SystemExit(f'no string space left for {s!r}: add an area to STRING_AREAS')
    labels, paths = {}, {}
    for f in (*FILMS.values(), SNAP):
        labels[f['sid']] = (put(f['name'].encode()), len(f['name']))
    for node in NEW_NODES:
        paths[node] = put(('/isp/iq/' + node).encode())

    # code that became dead when cases were redirected: fixed placements first, then
    # first-fit allocation for the rest
    used = []
    def place(at, code, what):
        lo, hi = at, at + len(code)
        assert any(a <= lo and hi <= b for a, b in FREE_CODE), f'{what} outside free code'
        assert not any(lo < b and a < hi for a, b in used), f'{what} overlaps other code'
        used.append((lo, hi))
        blob(lo, code)
        return lo
    if spill:
        place(STRING_SPILL, bytes(spill), 'spilled strings')
    def alloc(size):
        for lo, hi in FREE_CODE:
            a = lo
            for ulo, uhi in sorted(u for u in used if lo <= u[0] < hi):
                if ulo - a >= size:
                    break
                a = max(a, (uhi + 3) & ~3)
            if hi - a >= size:
                return a
        raise SystemExit(f'no free code left for {size} bytes')

    # new nodes: their switch case jumps to a relocated reload stub
    def film_stub(node, at):
        f = FILMS[node]
        assert f['case'] not in (5, 7), 'cases 5 and 7 are the colorpencil films'
        place(at, reload_stub(at, paths[node], f['exit']), f'{node} stub')
        case_to(f['case'], at)
    for node in NEW_NODES:
        if FILMS[node].get('stub'):
            film_stub(node, FILMS[node]['stub'])

    # EXIF preset/firmware strings
    code, sw_helper = exif_code(EXIF_CODE, img)
    place(EXIF_CODE, code, 'EXIF code')
    word(DESC_LDR, bl_insn(DESC_LDR, EXIF_CODE), 0xe59fe270)
    word(SW_LEN_MOV, 0xe3a02000 | (len(FIRMWARE) + 1), 0xe3a0200d)
    word(SW_CALL, bl_insn(SW_CALL, sw_helper), bl_insn(SW_CALL, 0x4447c0))

    # Snap: mode record +0x2c holds u16 +0x2c (0xffff = no override) and u16 +0x2e (AE curve)
    word(MODE_TABLE + MODE_REC * SNAP['mode'] + 0x2c, 0x0001ffff, 0x0000ffff)
    new, old = curve_words(SNAP_NODES, (SNAP_EXPT_MAX, SNAP_ISO_MAX, 1, 1000)), curve_words(*STOCK_CURVE1)
    for i, (n, o) in enumerate(zip(new, old)):
        if n != o:
            word(AE_CURVE1 + 4 * i, n, o)
    for addr, rd in CURVE1_EXPT_MOVW:
        stock = movw(0x03000000 | rd << 12, 25000)            # movweq rd, #25000
        word(addr, movw(stock, SNAP_EXPT_MAX), stock)
    for addr in CURVE1_ISO_MOV:
        word(addr, 0xe3a03d19, 0xe3a03e32)                     # mov r3, #1600 (was #800)
    assert SNAP_ISO_MAX == 1600

    # Snap fixed focus: helpers in free code; half-press AF trigger, AF status, lens rest calls
    # and the entry of PhotoExe_AFStart redirected
    code, entry = snap_focus_code(SNAP_CODE)
    place(SNAP_CODE, code, 'snap focus code')
    word(AF_TRIGGER, bl_insn(AF_TRIGGER, entry['start']), bl_insn(AF_TRIGGER, SET_AF))
    word(AF_STATUS, bl_insn(AF_STATUS, entry['status']), bl_insn(AF_STATUS, GET_AF))
    for a in LENS_PARKS:
        word(a, bl_insn(a, entry['park']), bl_insn(a, LENS_SET))
    word(AF_START_FN, b_insn(AF_START_FN, entry['afstart']), AF_START_PUSH)

    # colour effect: re-apply the shooting mode's AE curve after OnColor's DTB AE reload
    at = alloc(len(color_code(0)))
    place(at, color_code(at), 'colour exit code')
    word(COLOR_EXIT, bl_insn(COLOR_EXIT, at), COLOR_EXIT_LDR)

    # reload stubs without a fixed address
    for node in NEW_NODES:
        if not FILMS[node].get('stub'):
            film_stub(node, alloc(len(reload_stub(0, 0, 0))))

    # repoint the replaced string IDs in every language table
    for tbl in language_tables(img):
        for sid, (ptr, ln) in labels.items():
            a = tbl + 8 * sid
            for k, byte in enumerate(struct.pack('<II', ptr, ln)):
                e[a - BASE + k] = byte
    return e

def language_tables(img):
    """String tables: 281 {ptr,len} entries + {0,0}; English starts at 0xb055f4."""
    NENT, STRIDE = 281, 282 * 8
    def ok(t, terminated=True):
        o = t - BASE
        if o < 0 or o + STRIDE > len(img): return False
        p, l = struct.unpack_from('<II', img, o + NENT * 8)
        if terminated and (p, l) != (0, 0): return False
        if struct.unpack_from('<I', img, o + 4)[0] != 0: return False   # entry 0 is ""
        for i in range(1, NENT):
            p, l = struct.unpack_from('<II', img, o + 8 * i)
            if not (BASE <= p < BASE + len(img)) or l > 200: return False
        return True
    eng = 0xb055f4
    assert ok(eng)
    t = eng
    while ok(t - STRIDE): t -= STRIDE
    out = []
    while ok(t): out.append(t); t += STRIDE
    if ok(t, terminated=False):   # the last table (Vietnamese) has no terminator
        out.append(t)
    return out

def fix_rtos_checksum(edits, img):
    """Recompute the image check word at 0x26e (tag 0x55aa at 0x26c)."""
    b = bytearray(img)
    for o, v in edits.items(): b[o] = v
    assert b[0x26c:0x26e] == b'\x55\xaa'
    b[0x26e:0x270] = b'\0\0'
    c = (-bp.nvt_sum(b)) & 0xffff
    edits[0x26e], edits[0x26f] = c & 0xff, c >> 8

# --------------------------------------------------------------- main

def main(src, out, lut_dir=LUT_DIR):
    d = open(src, 'rb').read()
    pk = nf.parse_pack(d)
    assert bp.nvt_sum(d) == 0, 'input container checksum invalid'
    rt = next(p for p in pk['parts'] if p['id'] == RTOS_ID)
    img, _ = bp.decompress(rt['data'])
    assert bp.nvt_sum(img) == 0
    name, cst_default = iq_default(img, CST_INDEX)
    assert name == 'iq_cst'

    # ISP DTB
    isp = nf.isp_part(pk)
    root, meta = nf.fdt_parse(isp['data'])
    iq = nf.find(root, '/isp/iq')
    for node in DROP_NODES:
        iq.children.remove(nf.find(root, '/isp/iq/' + node))
    soften_edges(root)                            # before films copy the capture profile
    tune_nr(root)
    for node in NEW_NODES:
        assert iq.child(node) is None
        iq.children.append(nf.clone(nf.find(root, '/isp/iq/ov13b10_iq_0_cap'), node))
    for node, f in FILMS.items():
        film_profile(root, node, f, lut_dir, cst_default)
        e = f['fit']['err']
        print(f"{f['name']}: fit error mean {e['mean']:.1f}/255, natural colours {e['natural_mean']:.1f}/255"
              + (' (film LUT, before the filter mix)' if f.get('mix') else ''))
        if f.get('cst'):
            lr = f['fit']['luma']
            print(f"  luma row {[int(c) for c in lr['row']]}/256 for mix {f['mix']}: "
                  f"{lr['err']['mean']:.1f}/255 from the linear filter")
    isp['data'] = nf.fdt_build(root, meta)
    assert len(isp['data']) <= nf.ISP_DTB_FLASH_SIZE, 'ISP DTB exceeds its flash partition'
    print(f"ISP DTB: 0x{isp['size']:x} -> 0x{len(isp['data']):x} (flash partition 0x{nf.ISP_DTB_FLASH_SIZE:x})")

    # RTOS
    edits = rtos_edits(img)
    fix_rtos_checksum(edits, img)
    new_blob, new_img, stats = bp.patch(rt['data'], edits)
    assert bp.nvt_sum(new_img) == 0
    changed = sum(1 for i in range(len(img)) if img[i] != new_img[i])
    rt['data'] = new_blob

    image = nf.build_pack(d, pk['parts'])
    assert bp.nvt_sum(image) == 0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'wb').write(image)
    print(f'language tables patched: {len(language_tables(img))}')
    print(f'rtos: {changed} bytes changed, {stats}')
    print(f'wrote {out} ({len(image)} bytes, checksum 0x{struct.unpack_from("<I", image, 0x24)[0]:04x})')

if __name__ == '__main__':
    main(*sys.argv[1:4])
