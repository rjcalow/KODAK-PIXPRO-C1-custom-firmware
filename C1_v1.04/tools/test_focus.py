#!/usr/bin/env python3
"""Run the Snap fixed-focus helpers and the colour-effect exit helper of a built firmware in
an ARM emulator.

Each redirected site (half-press AF trigger, AF status read, lens rest calls, the entry of
PhotoExe_AFStart, PhotoExe_OnColor's common exit) is entered the way the stock code enters it.
The helpers run as real code against the image's UI table (UI 0xa2 = DC mode, UI 0x58 = macro)
and AF calibration globals (GetAFlowPos / GetAFhighPos). Only the callees are stubbed: the lens
driver (set, and get = last code written), vendor_isp_set_af / get_af and Ux_PostEvent record
their arguments.
Checks: in Snap with macro off AF never starts, the lens goes to the hyperfocal code only when it
is not already there, and PhotoExe_AFStart returns without running; in every other case the stock
call happens with the stock arguments. The colour exit posts the mode-curve event except in Movie.

Usage: test_focus.py C110.bin build/C110.bin          (needs unicorn)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *
import build_films as BF
from test_exif import rtos, B, BSS_END, STACK, UI_TABLE_GOT

GOT = 0x2b980
AF_LOW_GOT, AF_HIGH_GOT = GOT + 0x35b4, GOT + 0x41c4    # globals behind GetAFlowPos / High
RET, BUF = 0xdead0000, 0xdeac0000
STOCK_REST = 235                                        # what the stock code passes (P60 - 25)
MARK = 0x5eed5eed                                       # value at [fp, #-0x114] for the colour exit

def run(img, entry, mode, macro, p60=260, p8=750, cur=0, r0=0x29, until=RET):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM, cpu=UC_CPU_ARM_CORTEX_A9)
    uc.mem_map(B, (BSS_END - B + 0xfffff) & ~0xfffff)
    uc.mem_write(B, bytes(img))
    for a in (STACK - 0x10000, RET, BUF):
        uc.mem_map(a, 0x10000)
    word = lambda a: struct.unpack_from('<I', img, a - B)[0]
    ui = word(UI_TABLE_GOT)
    uc.mem_write(ui + 0xa4 + 4 * 0xa2, struct.pack('<I', mode))
    uc.mem_write(ui + 0xa4 + 4 * 0x58, struct.pack('<I', macro))
    uc.mem_write(word(AF_LOW_GOT), struct.pack('<I', p60))
    uc.mem_write(word(AF_HIGH_GOT), struct.pack('<I', p8))
    uc.mem_write(BUF, struct.pack('<4I', 0, 0xaaaa, 0, 0))
    calls = []
    def stub(uc, addr, size, name):
        regs = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        ret = 0
        if name == 'lens_get':
            ret = cur
        else:
            calls.append((name, *regs[:{'lens': 1, 'post': 3}.get(name, 2)]))
        if name == 'get_af':
            uc.mem_write(regs[1] + 4, struct.pack('<I', 7))          # stock status marker
        uc.reg_write(UC_ARM_REG_R0, ret)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    for addr, name in ((BF.LENS_SET, 'lens'), (BF.LENS_GET, 'lens_get'), (BF.SET_AF, 'set_af'),
                       (BF.GET_AF, 'get_af'), (BF.UX_POST, 'post')):
        uc.hook_add(UC_HOOK_CODE, stub, name, begin=addr, end=addr)
    sp = STACK - 0x1000
    fp = sp + 0x200
    uc.mem_write(fp - 0x114, struct.pack('<I', MARK))
    for reg, v in ((UC_ARM_REG_R0, r0), (UC_ARM_REG_R1, BUF), (UC_ARM_REG_R2, 0x22),
                   (UC_ARM_REG_SP, sp), (UC_ARM_REG_FP, fp), (UC_ARM_REG_LR, RET)):
        uc.reg_write(reg, v)
    uc.emu_start(entry, until, count=10000)
    out = dict(calls=calls, r0=uc.reg_read(UC_ARM_REG_R0), r3=uc.reg_read(UC_ARM_REG_R3),
               sp=uc.reg_read(UC_ARM_REG_SP) - sp,
               status=struct.unpack('<I', bytes(uc.mem_read(BUF + 4, 4)))[0],
               stack=struct.unpack('<4I', bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_SP), 16))))
    return out

def target(img, a):
    w = struct.unpack_from('<I', img, a - B)[0]
    assert w >> 24 in (0xea, 0xeb), f'{a:#x} is not b/bl'
    return a + 8 + (((w & 0xffffff) ^ 0x800000) - 0x800000) * 4

def main(stock_path, built_path):
    simg, bimg = rtos(stock_path), rtos(built_path)
    fails = []
    def check(ok, msg):
        print(('  ok   ' if ok else '  FAIL ') + msg)
        if not ok: fails.append(msg)

    start, status = target(bimg, BF.AF_TRIGGER), target(bimg, BF.AF_STATUS)
    parks = {target(bimg, a) for a in BF.LENS_PARKS}
    assert len(parks) == 1, 'lens rest sites disagree'
    park, afstart = parks.pop(), target(bimg, BF.AF_START_FN)
    k = BF.snap_k()
    print(f'entries: start {start:#x}, status {status:#x}, park {park:#x}, afstart {afstart:#x}; '
          f'K = {k}/256 (focus {BF.SNAP_FOCUS_MM} mm)')
    snap = BF.SNAP['mode']
    for p60, p8 in ((260, 750), (300, 600), (420, 700)):
        want = p60 - ((p8 - p60) * k >> 8)
        print(f'Snap, calibration P60 {p60}, P8 {p8}: hyperfocal code {want}')
        for label, entry, r0 in (('half-press AF start', start, 0x29), ('lens rest', park, STOCK_REST),
                                 ('PhotoExe_AFStart', afstart, 0)):
            o = run(bimg, entry, snap, 0, p60, p8, cur=0, r0=r0)
            check(o['calls'] == [('lens', want)] and o['r0'] == 0 and o['sp'] == 0,
                  f'{label}: lens {o["calls"]} -> {want}, returns 0, no AF')
            o = run(bimg, entry, snap, 0, p60, p8, cur=want, r0=r0)
            check(o['calls'] == [] and o['r0'] == 0 and o['sp'] == 0,
                  f'{label}, lens already there: no lens write {o["calls"]}')
        o = run(bimg, status, snap, 0, p60, p8, r0=0x2b)
        check(o['calls'] == [] and o['r0'] == 0 and o['status'] == 1 and o['sp'] == 0,
              f'AF status: focused (1), AF not queried {o["calls"]}')
    print('stock behaviour kept (Snap + macro, Auto, Program AE, Movie)')
    for mode, macro, label in ((snap, 1, 'Snap + macro'), (0, 0, 'Auto'), (1, 0, 'Program AE'), (7, 0, 'Movie')):
        o = run(bimg, start, mode, macro)
        check(o['calls'] == [('set_af', 0x29, BUF)] and o['sp'] == 0, f'{label}: AF start -> set_af(0x29, buf)')
        o = run(bimg, status, mode, macro, r0=0x2b)
        check(o['calls'] == [('get_af', 0x2b, BUF)] and o['status'] == 7, f'{label}: AF status -> get_af(0x2b, buf)')
        o = run(bimg, park, mode, macro, r0=STOCK_REST)
        check(o['calls'] == [('lens', STOCK_REST)], f'{label}: lens rest -> {STOCK_REST}')
        o = run(bimg, afstart, mode, macro, r0=0x11, until=BF.AF_START_FN + 4)
        check(o['calls'] == [] and o['sp'] == -16 and o['stack'][3] == RET and o['r0'] == 0x11,
              f'{label}: PhotoExe_AFStart continues at {BF.AF_START_FN + 4:#x} with its frame pushed')
    print('bad calibration (Snap)')
    for p60, p8, want in ((500, 500, 475), (600, 300, 575), (10, 1000, 0)):
        o = run(bimg, start, snap, 0, p60, p8, cur=999)
        check(o['calls'] == [('lens', want)], f'P60 {p60}, P8 {p8}: lens -> {want} {o["calls"]}')

    print('colour effect exit: mode AE curve re-applied')
    exit_fn = target(bimg, BF.COLOR_EXIT)
    obj = struct.unpack_from('<I', bimg, BF.PHOTO_OBJ_GOT - B)[0]
    check(struct.unpack_from('<I', simg, BF.COLOR_EXIT - B)[0] == BF.COLOR_EXIT_LDR,
          f'stock {BF.COLOR_EXIT:#x} is ldr r3, [fp, #-0x114]')
    for mode, label in ((0, 'Auto'), (1, 'Program AE'), (snap, 'Snap'), (3, 'Night Landscape')):
        o = run(bimg, exit_fn, mode, 0)
        check(o['calls'] == [('post', obj, BF.EV_AE_CURVE, 0)] and o['r3'] == MARK and o['sp'] == 0,
              f'{label}: Ux_PostEvent({obj:#x}, {BF.EV_AE_CURVE:#x}, 0), r3 = [fp-0x114]')
    o = run(bimg, exit_fn, 7, 0)
    check(o['calls'] == [] and o['r3'] == MARK and o['sp'] == 0, 'Movie: no event, r3 = [fp-0x114]')
    print('\n' + ('ALL FOCUS TESTS PASSED' if not fails else f'{len(fails)} FOCUS TEST(S) FAILED'))
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main(*sys.argv[1:3])
