#!/usr/bin/env python3
"""Novatek BCL1 (BCL LZ77) decompressor. Usage: bcl1.py in.bin out.bin"""
import struct, sys

def lz_uncompress(src, outsize):
    out = bytearray()
    marker = src[0]
    i = 1
    n = len(src)
    def varsize(i):
        y = 0
        while True:
            b = src[i]; i += 1
            y = (y << 7) | (b & 0x7f)
            if not b & 0x80:
                return y, i
    while i < n and len(out) < outsize:
        c = src[i]; i += 1
        if c != marker:
            out.append(c)
        elif src[i] == 0:
            out.append(marker); i += 1
        else:
            length, i = varsize(i)
            offset, i = varsize(i)
            start = len(out) - offset
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)

d = open(sys.argv[1], 'rb').read()
assert d[:4] == b'BCL1'
crc, algo, outsize, insize = struct.unpack_from('>HHII', d, 4)
print(f'crc=0x{crc:04x} algo={algo} out=0x{outsize:x} in=0x{insize:x}')
assert algo == 9
o = lz_uncompress(d[16:16 + insize], outsize)
print(f'got 0x{len(o):x}')
open(sys.argv[2], 'wb').write(o)
