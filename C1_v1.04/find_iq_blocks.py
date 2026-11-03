#!/usr/bin/env python3
import os, re

path = 'C110.bin'
with open(path, 'rb') as f:
    data = f.read()

keys = [
    b'iq_color',
    b'iq_contrast',
    b'iq_edge',
    b'iq_3dnr',
    b'iq_post_sharpen',
    b'iq_ycurve',
]

positions = []
for key in keys:
    off = 0
    while True:
        idx = data.find(key, off)
        if idx < 0:
            break
        positions.append((idx, key.decode('latin1','ignore')))
        off = idx + 1

# unique sorted offsets for all matches
hits = sorted(set(pos for pos, _ in positions))
print('candidate iq symbol offsets:')
for pos in hits:
    print(f'  0x{pos:x}')
print('')

# print nearest blocks around each symbol pair, using previous/next hits in sorted list
for idx, pos in enumerate(hits):
    prev = hits[idx-1] if idx > 0 else pos - 0x100
    nxt = hits[idx+1] if idx + 1 < len(hits) else pos + 0x100
    block_start = max(0, min(prev, pos) - 0x40)
    block_end = min(len(data), max(nxt, pos) + 0x40)
    print(f'BLOCK 0x{pos:x} range 0x{block_start:x}-0x{block_end:x}')
    # print a few ASCII labels in block to help confirm grouping
    snippet = data[block_start:block_end]
    # only show 2 lines of ASCII around a leading symbol if present
    for key in keys:
        kidx = snippet.find(key)
        if kidx >= 0:
            print(f'  key {key.decode()} at 0x{block_start + kidx:x}')
            break
    print('')
