#!/usr/bin/env python3
"""Minimal FDT dumper: prints path, prop name, offset of value in blob, length, value."""
import struct, sys

def walk(d):
    magic, tot, off_struct, off_str, _, ver, _, _, sz_str, sz_struct = struct.unpack_from('>10I', d, 0)
    assert magic == 0xd00dfeed
    p = off_struct
    path = []
    while True:
        tok = struct.unpack_from('>I', d, p)[0]; p += 4
        if tok == 1:
            e = d.index(b'\0', p); name = d[p:e].decode('latin1'); p = (e + 4) & ~3
            path.append(name)
            yield ('node', '/'.join(path) or '/', None, None, None)
        elif tok == 2:
            path.pop()
        elif tok == 3:
            ln, no = struct.unpack_from('>II', d, p); p += 8
            e = d.index(b'\0', off_str + no); name = d[off_str + no:e].decode('latin1')
            yield ('prop', '/'.join(path), name, p, d[p:p + ln])
            p = (p + ln + 3) & ~3
        elif tok == 4:
            continue
        elif tok == 9:
            return

def fmt(v):
    if v and v[-1] == 0 and all(32 <= c < 127 or c == 0 for c in v) and v[0] != 0:
        return repr(v.rstrip(b'\0').decode())
    if len(v) % 4 == 0:
        w = struct.unpack('>%dI' % (len(v) // 4), v)
        s = ' '.join('%d' % x if x < 0x10000 else '0x%x' % x for x in w[:64])
        return '<%s%s>' % (s, ' ...' if len(w) > 64 else '')
    return '[' + v[:64].hex() + ']'

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    for kind, path, name, off, val in walk(d):
        if kind == 'node':
            print(f'\n{path}')
        else:
            print(f'  {name} @0x{off:x} len={len(val)}: {fmt(val)}')
