#!/usr/bin/env python3
"""Run the AE capture-curve generator (ae_curve_cap_generator, 0x2de360) from stock and
built firmware in an ARM emulator on the curve each shooting mode loads, and print the
resulting program lines (exposure, ISO breakpoints).

The curve is the one PhotoExe_OnAECurveProcess would copy: mode table record +0x2e indexes
the 0xd4-byte curves at 0x77ebf0. Inputs are set as the caller (0x2e84ac) sets them for
auto ISO (ae_ui ISO = 0, so iso_mode = 0) and for a fixed ISO; flicker index 2 = 100 Hz
(50 Hz mains), 3 = 120 Hz. Only printf is stubbed.

Usage: test_ae.py C110.bin build/C110.bin          (needs unicorn)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
import build_films as BF
from test_exif import rtos, B, BSS_END, STACK

GENERATOR, PRINTF = 0x2de360, 0xa6230
CURVES, CURVE = 0x77ebf0, 0xd4
TABLE = 0xb9f2d8                              # output: id * 0x640, rows of 0x28 bytes
WORK, RET = 0x2000000, 0xdead0000
MODES = ('Auto', 'Program AE', 'Landscape/Snap', 'Night Landscape')

def curve_of(img, mode):
    idx = struct.unpack_from('<H', img, BF.MODE_TABLE + BF.MODE_REC * mode + 0x2e - B)[0]
    return idx, img[CURVES + CURVE * idx - B:CURVES + CURVE * (idx + 1) - B]

def program_line(img, curve, ui_iso=0, flicker=2):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM, cpu=UC_CPU_ARM_CORTEX_A9)
    uc.reg_write(UC_ARM_REG_C1_C0_2, uc.reg_read(UC_ARM_REG_C1_C0_2) | 0xf << 20)  # VFP on
    uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    uc.mem_map(B, (BSS_END - B + 0xfffff) & ~0xfffff)
    uc.mem_write(B, bytes(img))
    for a in (STACK - 0x10000, WORK, RET):
        uc.mem_map(a, 0x10000)
    msgs = []
    def printf(uc, addr, size, _):
        msgs.append(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), 100)).split(b'\0')[0].decode(errors='replace'))
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    uc.hook_add(UC_HOOK_CODE, printf, begin=PRINTF, end=PRINTF)
    w = list(struct.unpack('<53I', curve))
    if ui_iso == 0:
        w[51] = 0                             # caller forces iso_mode 0 in auto ISO
    sb = WORK + 0xa04                         # {freq, ui ISO, flicker idx, curve...}
    uc.mem_write(sb, struct.pack('<3I53I', 50, ui_iso, flicker, *w))
    sp = STACK - 0x1000
    uc.mem_write(sp, struct.pack('<II', WORK + 0x30, WORK + 0x3904))
    for reg, v in ((UC_ARM_REG_R0, 0), (UC_ARM_REG_R1, sb), (UC_ARM_REG_R2, WORK + 0x508),
                   (UC_ARM_REG_R3, WORK + 0x38), (UC_ARM_REG_SP, sp), (UC_ARM_REG_LR, RET)):
        uc.reg_write(reg, v)
    uc.emu_start(GENERATOR, RET, count=5_000_000)
    rows = []
    for r in range(40):
        ev, _, expt, _, iso = struct.unpack_from('<5I', bytes(uc.mem_read(TABLE + 0x28 * r, 20)))
        if ev == 0xffffffff:
            break
        rows.append((expt, iso))
    return rows, msgs

def fmt(rows):
    return ' -> '.join(f'{e}us@{i}' for e, i in rows)

def main(stock_path, built_path):
    simg, bimg = rtos(stock_path), rtos(built_path)
    fails = []
    def check(ok, msg):
        print(('  ok   ' if ok else '  FAIL ') + msg)
        if not ok: fails.append(msg)

    print('program lines by mode (auto ISO, 50 Hz)')
    for m, name in enumerate(MODES):
        (si, sc), (bi, bc) = curve_of(simg, m), curve_of(bimg, m)
        srows, _ = program_line(simg, sc)
        brows, msgs = program_line(bimg, bc)
        if m == BF.SNAP['mode']:
            continue
        check((si, srows) == (bi, brows) and not msgs, f'{name}: curve {bi}, unchanged: {fmt(brows)}')

    print('snap')
    idx, cv = curve_of(bimg, BF.SNAP['mode'])
    for label, kw, want in (
            ('auto ISO, 50 Hz', {}, [(1, 200), (10000, 200), (10000, 400), (10000, 1600)]),
            ('auto ISO, 60 Hz', dict(flicker=3), [(1, 200), (8333, 200), (8333, 400), (8333, 1600)]),
            ('fixed ISO 400', dict(ui_iso=400), [(1, 400), (5000, 400), (10000, 400)])):
        rows, msgs = program_line(bimg, cv, **kw)
        check(idx == 1 and rows == want and not msgs, f'{label}: {fmt(rows)}' + (f' {msgs}' if msgs else ''))
    print('\n' + ('ALL AE TESTS PASSED' if not fails else f'{len(fails)} AE TEST(S) FAILED'))
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main(*sys.argv[1:3])
