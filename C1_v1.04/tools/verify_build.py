#!/usr/bin/env python3
"""Check a built firmware against stock, independently of build_films.py.

Usage: verify_build.py C110.bin build/C110.bin
Exits non-zero if any check fails. Prints the jump table, every RTOS change
region, the replaced menu labels and the ISP DTB node changes for review.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nvtfw as nf
import bcl1patch as bp
import build_films as BF

B = BF.BASE
fails = []

def check(ok, msg):
    print(('  ok   ' if ok else '  FAIL ') + msg)
    if not ok:
        fails.append(msg)

def main(stock_path, built_path):
    sd, bd = open(stock_path, 'rb').read(), open(built_path, 'rb').read()
    sp, bpk = nf.parse_pack(sd), nf.parse_pack(bd)
    print('container')
    check(bp.nvt_sum(bd) == 0, 'container checksum')
    check([p['id'] for p in sp['parts']] == [p['id'] for p in bpk['parts']], 'same partition ids/order')
    for p in bpk['parts']:
        check((p['off'] + 4) % 0x40 == 0, f'id{p["id"]} offset alignment 0x{p["off"]:x}')
    check((len(bd) + 4) % 0x40 == 0, 'file length alignment')
    s_parts = {p['id']: p['data'] for p in sp['parts']}
    b_parts = {p['id']: p['data'] for p in bpk['parts']}
    for pid in (1, 4, 8):
        check(s_parts[pid] == b_parts[pid], f'id{pid} identical to stock')

    print('rtos')
    blob = b_parts[BF.RTOS_ID]
    check(bp.nvt_sum(blob) == 0, 'BCL1 blob checksum')
    simg, _ = bp.decompress(s_parts[BF.RTOS_ID])
    bimg, _ = bp.decompress(blob)
    check(len(simg) == len(bimg), 'decompressed size unchanged')
    check(bp.nvt_sum(bimg) == 0, 'decompressed image checksum (0x26e)')
    diffs, i = [], 0
    while i < len(simg):
        if simg[i] != bimg[i]:
            j = i
            while j < len(simg) and simg[j:j + 4] != bimg[j:j + 4]:
                j += 1
            diffs.append((i + B, j - i)); i = j
        i += 1
    print('  changed regions:', ', '.join(f'{a:#x}+{n}' for a, n in diffs))
    print('  jump table (PhotoExe_OnColor cases 0-11):')
    for c in range(12):
        a = BF.JUMP_TABLE + 4 * c
        w = struct.unpack_from('<I', bimg, a - B)[0]
        tgt = a + 8 + (((w & 0xffffff) ^ 0x800000) - 0x800000) * 4
        mark = '' if tgt == BF.STOCK_CASES[c] else '   <- patched'
        check(w >> 24 == 0xea, f'case {c:2d} -> {tgt:#x}{mark}')

    print('menu labels (all language tables)')
    tables = BF.language_tables(simg)
    check(len(tables) == 27, f'{len(tables)} language tables')
    for f in (*BF.FILMS.values(), BF.SNAP):
        got = set()
        for t in tables:
            p, l = struct.unpack_from('<II', bimg, t - B + 8 * f['sid'])
            got.add(bimg[p - B:p - B + l])
        check(got == {f['name'].encode()}, f'string id {f["sid"]} -> {sorted(got)}')

    print('snap mode (Landscape slot)')
    u16 = lambda im, a: struct.unpack_from('<H', im, a - B)[0]
    idx = [u16(bimg, BF.MODE_TABLE + BF.MODE_REC * m + 0x2e) for m in range(9)]
    check(idx == [0, 3, 1, 2, 0, 0, 0, 0, 0], f'AE curve index by DC mode {idx} (mode 2 -> 1)')
    sc = struct.unpack_from('<53I', simg, BF.AE_CURVE1 - B)
    bc = struct.unpack_from('<53I', bimg, BF.AE_CURVE1 - B)
    nodes = [(bc[4 * i], bc[4 * i + 1]) for i in range(bc[48])]
    check(sc[48:] == (4, 25000, 800, 1, 1000), f'stock curve 1 tail {sc[48:]}')
    check(nodes == list(BF.SNAP_NODES) and bc[48:] == (len(nodes), 10000, 1600, 1, 1000)
          and not any(bc[4 * len(nodes):48]) and all(bc[4 * i + 2] == bc[4 * i + 3] == 0 for i in range(12)),
          f'curve 1 = snap: nodes {nodes}, tail {bc[48:]}')
    check(all(x[0] <= y[0] and x[1] <= y[1] for x, y in zip(nodes, nodes[1:])),
          'snap nodes: exposure and ISO non-decreasing (AE generator rule)')
    for a in (0x77ebf0, 0x77ed98, 0x77ee6c):
        check(simg[a - B:a - B + 0xd4] == bimg[a - B:a - B + 0xd4], f'AE curve at {a:#x} unchanged')
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    dis = lambda im, a: next(md.disasm(im[a - B:a - B + 4], a)).op_str
    for a, rd in BF.CURVE1_EXPT_MOVW:
        check((dis(simg, a), dis(bimg, a)) == (f'r{rd}, #0x61a8', f'r{rd}, #0x2710'),
              f'{a:#x} movweq {dis(simg, a)} -> {dis(bimg, a)}')
    for a in BF.CURVE1_ISO_MOV:
        check((dis(simg, a), dis(bimg, a)) == ('r3, #0x320', 'r3, #0x640'), f'{a:#x} mov {dis(simg, a)} -> {dis(bimg, a)}')

    print('snap fixed focus')
    def bl_target(im, a):
        w = struct.unpack_from('<I', im, a - B)[0]
        return a + 8 + (((w & 0xffffff) ^ 0x800000) - 0x800000) * 4 if w >> 24 in (0xea, 0xeb) else None
    word = lambda im, a: struct.unpack_from('<I', im, a - B)[0]
    code, entry = BF.snap_focus_code(BF.SNAP_CODE)
    lo, hi = BF.SNAP_CODE, BF.SNAP_CODE + len(code)
    clo = bl_target(bimg, BF.COLOR_EXIT) or 0              # allocated in FREE_CODE
    ccode = BF.color_code(clo)
    chi = clo + len(ccode)
    sites = [(BF.AF_TRIGGER, BF.SET_AF, lo, hi), (BF.AF_STATUS, BF.GET_AF, lo, hi)] + \
            [(a, BF.LENS_SET, lo, hi) for a in BF.LENS_PARKS]
    for a, stock, l, h in sites:
        t = bl_target(bimg, a)
        check(bl_target(simg, a) == stock and l <= (t or 0) < h, f'{a:#x}: bl {stock:#x} -> bl {t:#x}')
    t = bl_target(bimg, BF.AF_START_FN)
    check(word(simg, BF.AF_START_FN) == BF.AF_START_PUSH and word(bimg, BF.AF_START_FN) >> 24 == 0xea
          and lo <= (t or 0) < hi, f'{BF.AF_START_FN:#x} PhotoExe_AFStart: push {{r4, r5, fp, lr}} -> b {t:#x}')
    check(word(bimg, 0x422d08) == word(simg, 0x422d08), '0x422d08 (AF trigger inside PhotoExe_AFStart) stock')
    t = bl_target(bimg, BF.COLOR_EXIT)
    check(word(simg, BF.COLOR_EXIT) == BF.COLOR_EXIT_LDR and t == clo,
          f'{BF.COLOR_EXIT:#x} PhotoExe_OnColor exit: ldr r3, [fp, #-0x114] -> bl {t:#x}')
    for name, (l, h, c, calls) in {
            'focus helpers': (lo, hi, code, (BF.UI_GET, BF.AF_LOW, BF.AF_HIGH, BF.SET_AF, BF.GET_AF,
                                             BF.LENS_SET, BF.LENS_GET, BF.AF_START_FN + 4)),
            'colour helper': (clo, chi - 4, ccode[:-4], (BF.UI_GET, BF.UX_POST))}.items():
        check(any(a <= l and h <= b for a, b in BF.FREE_CODE) and bimg[l - B:h - B] == c[:h - l],
              f'{name} at {l:#x}-{h:#x} inside FREE_CODE')
        insns = list(md.disasm(bimg[l - B:h - B], l))
        check(len(insns) * 4 == h - l, f'{name} disassemble as {len(insns)} ARM instructions')
        ext = sorted({i.op_str for i in insns if i.mnemonic.startswith('b') and i.op_str.startswith('#')
                      and not l <= int(i.op_str.lstrip('#'), 16) < h})
        check(ext == sorted(f'#{x:#x}' for x in calls), f'{name} only branch to {ext}')
    check((word(bimg, chi - 4) + clo + 0x18 + 8) & 0xffffffff == BF.PHOTO_OBJ_GOT,
          f'colour helper literal -> GOT slot {BF.PHOTO_OBJ_GOT:#x}')

    print('film reload stubs')
    in_free = lambda l, h: any(a <= l and h <= b for a, b in BF.FREE_CODE)
    pt_free = lambda x: any(a <= x < b for a, b in BF.FREE_CODE)
    cstr = lambda im, a: im[a - B:im.index(b'\0', a - B)]
    exif, _ = BF.exif_code(BF.EXIF_CODE, simg)
    blocks = [('EXIF helpers', BF.EXIF_CODE, BF.EXIF_CODE + len(exif)),
              ('focus helpers', lo, hi), ('colour helper', clo, chi)]
    check(bimg[BF.EXIF_CODE - B:BF.EXIF_CODE - B + len(exif)] == exif and in_free(*blocks[0][1:]),
          f'EXIF helpers at {BF.EXIF_CODE:#x}-{BF.EXIF_CODE + len(exif):#x} inside FREE_CODE')
    def jt(im, case):
        a = BF.JUMP_TABLE + 4 * case
        return a + 8 + (((word(im, a) & 0xffffff) ^ 0x800000) - 0x800000) * 4
    for n in BF.NEW_NODES:
        f = BF.FILMS[n]
        t = jt(bimg, f['case'])
        path = (t + 0x14 + 8 + word(bimg, t + 0x48)) & 0xffffffff
        null = (t + 0x28 + 8 + word(bimg, t + 0x4c)) & 0xffffffff
        stub = bimg[t - B:t - B + 0x50]
        insns = list(md.disasm(stub[:0x48], t))
        calls = sorted(int(i.op_str.lstrip('#'), 16) for i in insns if i.mnemonic in ('b', 'bl'))
        exit_fx = BF.EXIT_FX1 if f['mono'] else BF.EXIT_FX0
        check(in_free(t, t + 0x50) and stub == BF.reload_stub(t, path, f['exit']) and len(insns) == 18
              and calls == sorted([0xd5944, 0xd5944, 0x31390, 0x5328c8, exit_fx]),
              f'case {f["case"]:2d} stub {t:#x}: 18 instructions, calls strncpy x2, dtsi, set_iq, b {exit_fx:#x}')
        check(cstr(bimg, path) == ('/isp/iq/' + n).encode() and cstr(bimg, null) == b'null'
              and (any(a <= path and path + len(n) + 8 <= b for a, b in BF.STRING_AREAS) or in_free(path, path + len(n) + 9)),
              f'case {f["case"]:2d} stub paths {cstr(bimg, path).decode()!r} (in STRING_AREAS or FREE_CODE), {cstr(bimg, null).decode()!r}')
        blocks.append((f'{n} stub', t, t + 0x50))
    for a, fx in ((BF.EXIT_FX0, 0), (BF.EXIT_FX1, 1)):
        check(dis(bimg, a) == f'r3, #{fx}', f'{a:#x} exit sets image effect {fx} ({dis(bimg, a)})')
    over = [(x[0], y[0]) for i, x in enumerate(blocks) for y in blocks[i + 1:] if x[1] < y[2] and y[1] < x[2]]
    check(not over, f'{len(blocks)} code blocks in FREE_CODE do not overlap {over or ""}')

    print('reused stock code is dead')
    def branches_in(im):                   # every B/BL/BLX word, data included, into FREE_CODE
        out = set()
        for o in range(0, len(im) - 3, 4):
            w = struct.unpack_from('<I', im, o)[0]
            if (w >> 25) & 7 != 5:
                continue
            src = o + B
            dst = src + 8 + (((w & 0xffffff) ^ 0x800000) - 0x800000) * 4 + (2 * (w >> 24 & 1) if w >> 28 == 0xf else 0)
            if pt_free(dst) and not pt_free(src):
                out.add(src)
        return out
    table = {BF.JUMP_TABLE + 4 * c for c in range(12)}
    sites = {BF.DESC_LDR, BF.SW_CALL, BF.AF_TRIGGER, BF.AF_STATUS, BF.AF_START_FN, BF.COLOR_EXIT, *BF.LENS_PARKS}
    s_in, b_in = branches_in(simg), branches_in(bimg)
    check(s_in <= table, f'stock: only the jump table branches into FREE_CODE ({len(s_in)} entries)')
    check(b_in <= table | sites, f'built: only the jump table and the patched call sites branch into FREE_CODE '
          f'({len(b_in & table)} + {len(b_in & sites)}){"" if b_in <= table | sites else " extra: " + str([hex(x) for x in b_in - table - sites])}')
    live = [c for c in range(12) if pt_free(BF.STOCK_CASES[c]) and jt(bimg, c) == BF.STOCK_CASES[c]]
    check(not live, f'no case still enters its stock body inside FREE_CODE {live or ""}')
    ro = [(a, n) for a, n in diffs if 0x77e000 <= a < 0x780000]
    check(all(any(l <= a and a + n <= h + 1 for l, h in BF.STRING_AREAS) or BF.AE_CURVE1 <= a < BF.AE_CURVE1 + 0xd4
              for a, n in ro), 'rodata changes only inside STRING_AREAS and AE curve 1')
    for l, h in BF.STRING_AREAS:
        check(simg[h - 4 - B:h + 1 - B] == b'\x1b[0m\0' and bimg[h - B] == 0,
              f'string area {l:#x}-{h:#x}: stock debug format, still NUL-terminated')

    print('isp dtb')
    sroot = nf.fdt_parse(s_parts[3])[0]
    broot = nf.fdt_parse(b_parts[3])[0]
    check(len(b_parts[3]) <= nf.ISP_DTB_FLASH_SIZE, f'size 0x{len(b_parts[3]):x} <= 0x{nf.ISP_DTB_FLASH_SIZE:x}')
    sw = {p: n.props for p, n in nf.walk(sroot)}
    bw = {p: n.props for p, n in nf.walk(broot)}
    top = lambda w: {p for p in w if p.startswith('/isp/') and p.count('/') == 3}
    print('  removed nodes:', sorted(top(sw) - top(bw)))
    print('  added nodes:  ', sorted(top(bw) - top(sw)))
    changed = sorted({p.rsplit('/', 1)[0] for p in sw if p in bw and sw[p] != bw[p]})
    print('  changed nodes:', changed)
    cap = '/isp/iq/ov13b10_iq_0_cap'
    expect = {'/isp/iq/' + n for n in BF.FILMS if n not in BF.NEW_NODES} | {cap}
    check(set(changed) <= expect, 'only film nodes and the capture profile changed')
    check(sorted(p for p in sw if p.startswith(cap + '/') and sw[p] != bw[p]) == [cap + '/iq_edge', cap + '/iq_nr'],
          'capture profile: only iq_edge and iq_nr changed')
    sn, bn = dict(sw[cap + '/iq_nr'])['data'], dict(bw[cap + '/iq_nr'])['data']
    nr = {0x18 + 0x11c * lv + off + 4 * i: lv for lv in range(1, 17)
          for off, n in BF.NR_FILTERS for i in range(n)}            # range filter A/B words
    check(len(sn) == len(bn) == 4852 and all(sn[i] == bn[i] for i in range(len(sn)) if (i & ~3) not in nr),
          'iq_nr: only range filters of records 1-16 changed')
    word = lambda b, o: struct.unpack_from('<I', b, o)[0]
    k = lambda lv: BF.DENOISE if lv >= BF.DENOISE_FROM else BF.DENOISE_LOW
    th_b = lambda b, lv: [word(b, 0x18 + 0x11c * lv + 0x94 + 4 * i) for i in range(6)]
    check(all(word(bn, o) == min(1023, round(word(sn, o) * k(lv))) for o, lv in nr.items()),
          f'iq_nr: range filters = stock x {BF.DENOISE_LOW} (records 1-{BF.DENOISE_FROM - 1}), '
          f'x {BF.DENOISE} (records {BF.DENOISE_FROM}-16) '
          f'(filter_th_b ISO 400 {th_b(sn, 3)} -> {th_b(bn, 3)}, ISO 1600 {th_b(sn, 5)} -> {th_b(bn, 5)})')
    se = struct.unpack('<376I', dict(sw[cap + '/iq_edge'])['data'])
    be = struct.unpack('<376I', dict(bw[cap + '/iq_edge'])['data'])
    enh = {19 + 21 * lv + k for lv in range(17) for k in (0, 1)}   # edge_enh_p / edge_enh_n
    check(all(se[i] == be[i] for i in range(376) if i not in enh), 'iq_edge: only edge_enh_p/n changed')
    check(all(be[i] == round(se[i] * BF.SHARPEN) for i in enh),
          f'iq_edge: edge_enh_p/n = stock x {BF.SHARPEN} '
          f'({[se[i] for i in sorted(enh)][2:4]} -> {[be[i] for i in sorted(enh)][2:4]} at level 1)')
    check(sorted(top(sw) - top(bw)) == ['/isp/iq/' + n for n in BF.DROP_NODES], 'only DROP_NODES removed')
    capn = nf.find(broot, cap)
    # iq_cst (cst films): size and default straight from the stock loader / default tables
    a = BF.IQ_LOAD_TABLE + 0x48 * BF.CST_INDEX
    cst_name = simg[a - B:a - B + 0x40].split(b'\0')[0]
    cst_size = struct.unpack_from('<I', simg, a + 0x44 - B)[0]
    cst_def = simg[(lambda p: slice(p - B, p - B + cst_size))(struct.unpack_from('<I', simg, BF.IQ_DEFAULTS + 4 * BF.CST_INDEX - B)[0])]
    check(cst_name == b'iq_cst' and cst_size == 0x2c and struct.unpack_from('<9h', cst_def, 4) ==
          (77, 150, 29, -43, -85, 128, 128, -107, -21) and cst_def[0x18:0x1a] == b'\x80\x80',
          f'stock iq_cst: loader entry {BF.CST_INDEX} {cst_name.decode()!r} size {cst_size:#x}, default BT.601, Cb/Cr 128')
    for n in BF.FILMS:
        node = nf.find(broot, '/isp/iq/' + n)
        check(node is not None, f'/isp/iq/{n} present')
        if n not in BF.NEW_NODES:          # stock node: full profile, still-photo tuning as the capture one
            for blk in ('iq_edge', 'iq_nr'):
                check(bw.get(f'/isp/iq/{n}/{blk}') == bw[f'{cap}/{blk}'], f'/isp/iq/{n} {blk} = capture profile')
            continue
        # new node: only the film blocks; the rest stays as the profile loaded just before it
        f = BF.FILMS[n]
        blocks = BF.film_blocks(f)
        names = [c.name for c in node.children]
        stock_order = [c.name for c in capn.children if c.name in blocks]
        check(sorted(names) == sorted(blocks) and [x for x in names if x != 'iq_cst'] == stock_order and
              ('iq_ccm' not in names) == bool(f.get('cst')),
              f'/isp/iq/{n} holds only {names}')
        sizes = [((dict(c.props)['size'] == dict(capn.child(c.name).props)['size']) if c.name != 'iq_cst' else
                  struct.unpack('<I', dict(c.props)['size'])[0] == cst_size) and
                 len(dict(c.props)['data']) == struct.unpack('<I', dict(c.props)['size'])[0] for c in node.children]
        check(all(sizes) and node.props == capn.props,
              f'/isp/iq/{n} block sizes and version-info = capture profile (iq_cst = loader table)')
        if f.get('cst'):
            d = dict(node.child('iq_cst').props)['data']
            coef = struct.unpack_from('<9h', d, 4)
            check(d[:4] == cst_def[:4] and d[0x16:] == cst_def[0x16:] and coef[3:] == (0,) * 6 and
                  sum(coef[:3]) == 256 and all(BF.CST_COEF[0] <= c <= BF.CST_COEF[1] for c in coef[:3]),
                  f'/isp/iq/{n} iq_cst: luma row {list(coef[:3])}/256 (9-bit fields), chroma rows 0, '
                  f'mode/offsets/cstp = stock default')
    print('\n' + ('ALL CHECKS PASSED' if not fails else f'{len(fails)} CHECK(S) FAILED'))
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main(*sys.argv[1:3])
