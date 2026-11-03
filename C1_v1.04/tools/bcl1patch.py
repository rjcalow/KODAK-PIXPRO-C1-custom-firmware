#!/usr/bin/env python3
"""Patch bytes of a BCL1 (LZ) compressed image without recompressing it.

Edited bytes stored as literals are rewritten in place. Any back-reference
(copy token) that writes an edited byte, or reads one, is replaced by plain
literals carrying the intended output. Every other token is kept byte-for-byte,
and copy offsets are output-relative, so nothing else in the stream changes
meaning. The result is verified by full decompression, the header in_size is
updated and the BCL1 header checksum recomputed (Novatek sum16 over the blob).
"""
import struct
from array import array

def nvt_sum(b):
    n = len(b) // 2
    w = struct.unpack('<%dH' % n, b[:n * 2])
    return (sum(w) + n * (n - 1) // 2) & 0xffff

def header(blob):
    assert blob[:4] == b'BCL1'
    _, algo, outsize, insize = struct.unpack_from('>HHII', blob, 4)
    assert algo == 9
    return outsize, insize

def decompress(blob, track=False):
    """Return (output, src) where src[i] is the blob offset of output byte i if it
    was a literal, else -1."""
    outsize, insize = header(blob)
    src = blob[16:16 + insize]
    out = bytearray()
    prov = array('i') if track else None
    marker, i, n = src[0], 1, len(src)
    while i < n and len(out) < outsize:
        c = src[i]; i += 1
        if c != marker:
            out.append(c)
            if track: prov.append(16 + i - 1)
        elif src[i] == 0:
            out.append(marker); i += 1
            if track: prov.append(-1)     # escaped marker: not patchable in place
        else:
            ln = off = 0
            while True:
                b = src[i]; i += 1; ln = (ln << 7) | (b & 0x7f)
                if not b & 0x80: break
            while True:
                b = src[i]; i += 1; off = (off << 7) | (b & 0x7f)
                if not b & 0x80: break
            s = len(out) - off
            for k in range(ln): out.append(out[s + k])
            if track: prov.extend([-1] * ln)
    return bytes(out), prov

def tokens(blob):
    """Yield (in_start, in_end, out_start, out_len, copy_src) for every token;
    copy_src is -1 for literals. Offsets are into the whole blob / output."""
    outsize, insize = header(blob)
    src = blob[16:16 + insize]
    marker, i, n, o = src[0], 1, len(src), 0
    while i < n and o < outsize:
        s = i
        c = src[i]; i += 1
        if c != marker:
            yield 16 + s, 16 + i, o, 1, -1; o += 1
        elif src[i] == 0:
            i += 1; yield 16 + s, 16 + i, o, 1, -1; o += 1
        else:
            ln = off = 0
            while True:
                b = src[i]; i += 1; ln = (ln << 7) | (b & 0x7f)
                if not b & 0x80: break
            while True:
                b = src[i]; i += 1; off = (off << 7) | (b & 0x7f)
                if not b & 0x80: break
            yield 16 + s, 16 + i, o, ln, o - off; o += ln

def patch(blob, edits):
    """edits: {decompressed_offset: new_byte}. Returns (new_blob, new_image, stats)."""
    img, _ = decompress(blob)
    marker = blob[16]
    want = bytearray(img)
    for off, val in edits.items():
        want[off] = val
    dirty = sorted(o for o in edits if img[o] != want[o])
    import bisect
    def hits(a, ln):
        j = bisect.bisect_left(dirty, a)
        return j < len(dirty) and dirty[j] < a + ln
    def lit(bs):
        out = bytearray()
        for b in bs:
            out += bytes([marker, 0]) if b == marker else bytes([b])
        return out
    repl = []                       # (in_start, in_end, new_bytes)
    n_lit = n_copy = 0
    for s, e, o, ln, cs in tokens(blob):
        if cs < 0:
            if hits(o, 1):
                repl.append((s, e, lit(want[o:o + 1]))); n_lit += 1
        elif hits(o, ln) or hits(cs, ln):
            repl.append((s, e, lit(want[o:o + ln]))); n_copy += 1
    nb = bytearray(blob[:16]); pos = 16
    for s, e, b in repl:
        nb += blob[pos:s]; nb += b; pos = e
    _, insize = header(blob)
    nb += blob[pos:16 + insize]
    struct.pack_into('>I', nb, 12, len(nb) - 16)
    if len(nb) & 1:                 # keep the blob 16-bit aligned for the checksum
        nb.append(0)
    got, _ = decompress(bytes(nb))
    if got != bytes(want):
        diff = [hex(i) for i in range(len(got)) if got[i] != want[i]][:10]
        raise ValueError('verification failed at ' + ', '.join(diff))
    struct.pack_into('<H', nb, 4, 0)
    struct.pack_into('<H', nb, 4, (-nvt_sum(nb)) & 0xffff)
    assert nvt_sum(nb) == 0
    return bytes(nb), got, dict(literals=n_lit, copies_split=n_copy, growth=len(nb) - len(blob))

def literal_ok(blob, offsets):
    """Which decompressed offsets are stored as patchable literals."""
    _, prov = decompress(blob, track=True)
    return {o: prov[o] >= 0 for o in offsets}
