#!/usr/bin/env python3
"""Kodak Pixpro C1 (Novatek NA51089) firmware tool.

  nvtfw.py info    C110.bin
  nvtfw.py unpack  C110.bin outdir          # partitions, decompressed rtos, DTB text dumps
  nvtfw.py ls      C110.bin [path-prefix]   # list ISP DTB (partition id 3) nodes/props
  nvtfw.py clone   C110.bin out.bin SRC DST # duplicate an ISP DTB node under a new name
  nvtfw.py delete  C110.bin out.bin PATH    # remove an ISP DTB node
  nvtfw.py setprop C110.bin out.bin PATH PROP blob.bin   # replace a property value
  nvtfw.py getprop C110.bin PATH PROP out.bin

Every write re-serialises the ISP DTB, rebuilds the NVTPACK container
(offsets / total size) and fixes the container checksum. Nothing here touches
the compressed RTOS partition.
"""
import struct, sys, os

FDT_MAGIC = 0xd00dfeed
ISP_DTB_ID = 3                  # NVTPACK partition id of 'fdt.app' (application.bin)
ISP_DTB_FLASH_SIZE = 0x40000    # flash partition size from the system DTB

# ---------------------------------------------------------------- checksum

def nvt_sum(b):
    """Novatek 16-bit checksum: sum(u16[i] + i). A valid image sums to 0."""
    n = len(b) // 2
    w = struct.unpack('<%dH' % n, b[:n * 2])
    return (sum(w) + n * (n - 1) // 2) & 0xffff

# ---------------------------------------------------------------- container

def parse_pack(d):
    ver, hdr, cnt, total, method, chk = struct.unpack_from('<6I', d, 0x10)
    parts = [struct.unpack_from('<III', d, hdr + 12 * i) for i in range(cnt)]
    return dict(ver=ver, hdr=hdr, method=method, chk=chk, total=total,
                parts=[dict(off=o, size=s, id=t, data=d[o:o + s]) for o, s, t in parts])

def build_pack(orig, parts):
    hdr = struct.unpack_from('<I', orig, 0x14)[0]
    first = struct.unpack_from('<I', orig, hdr)[0]
    out = bytearray(orig[:first])
    def pad():                                # stock images place every partition (and
        while (len(out) + 4) % 0x40:          # the end of file) at offset = 0x3c mod 0x40
            out.append(0)
    for i, p in enumerate(parts):
        pad()
        struct.pack_into('<III', out, hdr + 12 * i, len(out), len(p['data']), p['id'])
        out += p['data']
    pad()
    struct.pack_into('<I', out, 0x1c, len(out))
    struct.pack_into('<I', out, 0x24, 0)
    struct.pack_into('<I', out, 0x24, (-nvt_sum(out)) & 0xffff)
    assert nvt_sum(out) == 0
    return bytes(out)

# ---------------------------------------------------------------- FDT

class Node:
    def __init__(self, name):
        self.name, self.props, self.children = name, [], []

    def child(self, name):
        return next((c for c in self.children if c.name == name), None)

def fdt_parse(d):
    magic, tot, o_st, o_str, o_rsv, ver, lcv, cpu, sz_str, sz_st = struct.unpack_from('>10I', d, 0)
    assert magic == FDT_MAGIC
    meta = dict(ver=ver, lcv=lcv, cpu=cpu, rsv=d[o_rsv:o_st])
    p, stack, root = o_st, [], None
    while True:
        tok = struct.unpack_from('>I', d, p)[0]; p += 4
        if tok == 1:
            e = d.index(b'\0', p); n = Node(d[p:e].decode()); p = (e + 4) & ~3
            if stack: stack[-1].children.append(n)
            else: root = n
            stack.append(n)
        elif tok == 2:
            stack.pop()
        elif tok == 3:
            ln, no = struct.unpack_from('>II', d, p); p += 8
            e = d.index(b'\0', o_str + no)
            stack[-1].props.append([d[o_str + no:e].decode(), d[p:p + ln]])
            p = (p + ln + 3) & ~3
        elif tok == 4:
            continue
        elif tok == 9:
            return root, meta

def fdt_build(root, meta):
    st, strs, stoff = bytearray(), bytearray(), {}
    def sname(s):
        if s not in stoff:
            stoff[s] = len(strs); strs.extend(s.encode() + b'\0')
        return stoff[s]
    def emit(n):
        st.extend(struct.pack('>I', 1)); st.extend(n.name.encode() + b'\0')
        while len(st) & 3: st.append(0)
        for k, v in n.props:
            st.extend(struct.pack('>III', 3, len(v), sname(k))); st.extend(v)
            while len(st) & 3: st.append(0)
        for c in n.children: emit(c)
        st.extend(struct.pack('>I', 2))
    emit(root); st.extend(struct.pack('>I', 9))
    o_rsv = 0x28
    o_st = o_rsv + len(meta['rsv'])
    o_str = o_st + len(st)
    tot = o_str + len(strs)
    hdr = struct.pack('>10I', FDT_MAGIC, tot, o_st, o_str, o_rsv, meta['ver'], meta['lcv'],
                      meta['cpu'], len(strs), len(st))
    return hdr + meta['rsv'] + bytes(st) + bytes(strs)

def find(root, path):
    n = root
    for part in [x for x in path.split('/') if x]:
        n = n.child(part)
        if n is None:
            raise SystemExit(f'node not found: {path}')
    return n

def walk(n, path=''):
    p = path + '/' + n.name if n.name else path
    yield p or '/', n
    for c in n.children:
        yield from walk(c, p)

def clone(n, name):
    m = Node(name)
    m.props = [[k, bytes(v)] for k, v in n.props]
    m.children = [clone(c, c.name) for c in n.children]
    return m

# ---------------------------------------------------------------- BCL1

def bcl1_decompress(d):
    assert d[:4] == b'BCL1'
    _, algo, outsize, insize = struct.unpack_from('>HHII', d, 4)
    assert algo == 9, 'only LZ (9) supported'
    src, out, marker, i = d[16:16 + insize], bytearray(), d[16], 1
    def var(i):
        y = 0
        while True:
            b = src[i]; i += 1; y = (y << 7) | (b & 0x7f)
            if not b & 0x80: return y, i
    while i < len(src) and len(out) < outsize:
        c = src[i]; i += 1
        if c != marker: out.append(c)
        elif src[i] == 0: out.append(marker); i += 1
        else:
            ln, i = var(i); off, i = var(i); s = len(out) - off
            for k in range(ln): out.append(out[s + k])
    return bytes(out)

# ---------------------------------------------------------------- commands

def load(path):
    d = open(path, 'rb').read()
    pk = parse_pack(d)
    if nvt_sum(d) != 0:
        print('warning: container checksum does not verify', file=sys.stderr)
    return d, pk

def isp_part(pk):
    return next(p for p in pk['parts'] if p['id'] == ISP_DTB_ID)

def save(orig, pk, root, meta, out):
    blob = fdt_build(root, meta)
    if len(blob) > ISP_DTB_FLASH_SIZE:
        raise SystemExit(f'ISP DTB 0x{len(blob):x} exceeds flash partition 0x{ISP_DTB_FLASH_SIZE:x}')
    isp_part(pk)['data'] = blob
    img = build_pack(orig, pk['parts'])
    open(out, 'wb').write(img)
    print(f'wrote {out}: ISP DTB 0x{len(blob):x} / 0x{ISP_DTB_FLASH_SIZE:x} '
          f'({ISP_DTB_FLASH_SIZE - len(blob)} bytes free), checksum 0x{struct.unpack_from("<I", img, 0x24)[0]:04x}')

def fmt(v):
    if len(v) == 4: return '<0x%x> (le %d)' % (struct.unpack('>I', v)[0], struct.unpack('<I', v)[0])
    if v and v[-1] == 0 and all(32 <= c < 127 for c in v[:-1]): return repr(v[:-1].decode())
    return f'[{len(v)} bytes] {v[:24].hex()}...'

def main(a):
    cmd = a[0]
    if cmd == 'info':
        d, pk = load(a[1])
        print(f'NVTPACK ver=0x{pk["ver"]:08x} total=0x{pk["total"]:x} chk=0x{pk["chk"]:04x} '
              f'(verifies: {nvt_sum(d) == 0})')
        for p in pk['parts']:
            kind = {1: 'system DTB', 3: 'ISP DTB (fdt.app)', 4: 'u-boot', 6: 'rtos (BCL1)', 8: 'usr / fwver'}.get(p['id'], '?')
            print(f'  id{p["id"]}  off=0x{p["off"]:07x} size=0x{p["size"]:07x}  {kind}')
    elif cmd == 'unpack':
        d, pk = load(a[1]); os.makedirs(a[2], exist_ok=True)
        for p in pk['parts']:
            fn = os.path.join(a[2], f'part_id{p["id"]}.bin'); open(fn, 'wb').write(p['data']); print(fn)
            if p['data'][:4] == b'BCL1':
                fn = os.path.join(a[2], f'part_id{p["id"]}_rtos_base0x10000.bin')
                open(fn, 'wb').write(bcl1_decompress(p['data'])); print(fn)
            if p['data'][:4] == struct.pack('>I', FDT_MAGIC):
                root, _ = fdt_parse(p['data'])
                fn = os.path.join(a[2], f'part_id{p["id"]}.txt')
                with open(fn, 'w') as f:
                    for path, n in walk(root):
                        f.write(path + '\n')
                        for k, v in n.props: f.write(f'  {k} = {fmt(v)}\n')
                print(fn)
    elif cmd == 'ls':
        _, pk = load(a[1]); root, _ = fdt_parse(isp_part(pk)['data'])
        pre = a[2] if len(a) > 2 else ''
        for path, n in walk(root):
            if path.startswith(pre):
                print(path, ' '.join(f'{k}:{len(v)}' for k, v in n.props))
    elif cmd in ('clone', 'delete', 'setprop'):
        d, pk = load(a[1]); root, meta = fdt_parse(isp_part(pk)['data'])
        if cmd == 'clone':
            src = find(root, a[3]); parent = find(root, a[4].rsplit('/', 1)[0])
            name = a[4].rsplit('/', 1)[1]
            if parent.child(name): raise SystemExit('destination exists')
            parent.children.append(clone(src, name))
        elif cmd == 'delete':
            parent = find(root, a[3].rsplit('/', 1)[0]); n = find(root, a[3]); parent.children.remove(n)
        else:
            n = find(root, a[3]); v = open(a[5], 'rb').read()
            prop = next((p for p in n.props if p[0] == a[4]), None)
            if prop is None: raise SystemExit('property not found')
            if len(prop[1]) != len(v): raise SystemExit(f'size mismatch: {len(prop[1])} vs {len(v)}')
            prop[1] = v
        save(d, pk, root, meta, a[2])
    elif cmd == 'getprop':
        _, pk = load(a[1]); root, _ = fdt_parse(isp_part(pk)['data'])
        v = next(v for k, v in find(root, a[2]).props if k == a[3]); open(a[4], 'wb').write(v)
        print(f'{len(v)} bytes -> {a[4]}')
    else:
        print(__doc__)

if __name__ == '__main__':
    main(sys.argv[1:] or ['help'])
