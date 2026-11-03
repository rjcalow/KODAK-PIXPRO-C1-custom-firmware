#!/usr/bin/env python3
"""Run the EXIF IFD0 setup code (0x415944) from stock and built firmware in an ARM
emulator and compare the ImageDescription and Software tag entries it builds.

For every colour-effect value 0-11 it executes 0x41594c..0x415b68 (both patched call
sites, up to the next call) with UI_get(3) returning that value, then reads the
{ifd, tag, type, count, ptr, size} entries that are later passed to EXIF_SetTag.
Nothing is stubbed: UI_get and the new helpers run as real code.

Usage: test_exif.py C110.bin build/C110.bin          (needs unicorn)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_SP
import nvtfw as nf
import bcl1patch as bp
import build_films as BF

B = BF.BASE
BSS_END = 0xd11498
STACK = 0x1000000
UI_TABLE_GOT = 0x2b980 + 0x2b4c          # UI_get: [[GOT+0x2b4c] + 0xa4 + 4*idx]

def rtos(path):
    pk = nf.parse_pack(open(path, 'rb').read())
    return bp.decompress(next(p for p in pk['parts'] if p['id'] == BF.RTOS_ID)['data'])[0]

def machine(img):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    size = (BSS_END - B + 0xfffff) & ~0xfffff
    uc.mem_map(B, size)
    uc.mem_write(B, bytes(img))
    uc.mem_map(STACK - 0x10000, 0x10000)
    return uc

ENTRY_DESC, ENTRY_SW = -0xec, -0x60          # fp offsets of the two tag entries

def ifd0(img, effect):
    uc = machine(img)
    ui = struct.unpack_from('<I', img, UI_TABLE_GOT - B)[0]
    uc.mem_write(ui + 0xa4 + 4 * 3, struct.pack('<I', effect))
    sp = STACK - 0x800 - 4                    # after the 9-register push: sp = 4 mod 8
    uc.reg_write(UC_ARM_REG_SP, sp)
    uc.emu_start(0x41594c, 0x415b68)
    fp = sp + 0x20
    assert uc.reg_read(UC_ARM_REG_SP) == sp - 0x17c, 'stack not balanced'
    out = {}
    for name, off in (('desc', ENTRY_DESC), ('sw', ENTRY_SW)):
        ifd, tag, typ, count, ptr, size = struct.unpack('<IHHIII', bytes(uc.mem_read(fp + off, 20)))
        out[name] = dict(ifd=ifd, tag=tag, type=typ, count=count, size=size,
                         data=bytes(uc.mem_read(ptr, size)))
    return out

def main(stock_path, built_path):
    simg, bimg = rtos(stock_path), rtos(built_path)
    films = {f['case']: BF.PRESET.format(f['name']) for f in BF.FILMS.values()}
    fails = []
    def check(ok, msg):
        print(('  ok   ' if ok else '  FAIL ') + msg)
        if not ok: fails.append(msg)

    stock = ifd0(simg, 0)
    sd, ss = stock['desc'], stock['sw']
    check((sd['tag'], sd['type'], sd['count'], sd['data']) == (0x10e, 2, 27, b'KODAK Digital Still Camera\0'),
          f'stock ImageDescription entry {sd}')
    check((ss['tag'], ss['type'], ss['count'], ss['data'][:5]) == (0x131, 2, 13, b'1.04\0'),
          f'stock Software entry {ss}')

    print('ImageDescription (0x10e) by colour effect')
    for eff in range(12):
        s, b = ifd0(simg, eff), ifd0(bimg, eff)
        want = films[eff].encode().ljust(27, b'\0') if eff in films else sd['data']
        d = b['desc']
        check(s['desc'] == sd and d['data'] == want and
              {k: d[k] for k in ('ifd', 'tag', 'type', 'count', 'size')} ==
              {k: sd[k] for k in ('ifd', 'tag', 'type', 'count', 'size')},
              f"effect {eff:2d}: {d['data'].rstrip(bytes(1)).decode()!r}")

    print('Software (0x131)')
    w = ifd0(bimg, 0)['sw']
    want = BF.FIRMWARE.encode() + b'\0'
    check(w['data'] == want and w['count'] == w['size'] == len(want) and
          (w['ifd'], w['tag'], w['type']) == (ss['ifd'], 0x131, 2), f'built Software entry {w}')

    print('\n' + ('ALL EXIF TESTS PASSED' if not fails else f'{len(fails)} TEST(S) FAILED'))
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main(*sys.argv[1:3])
