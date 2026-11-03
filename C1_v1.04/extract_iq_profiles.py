#!/usr/bin/env python3
import os
import struct

path = 'C110.bin'
if not os.path.exists(path):
    raise SystemExit(f'Firmware file not found: {path}')

with open(path, 'rb') as f:
    data = f.read()

keys = [
    b'iq_color',
    b'iq_contrast',
    b'iq_edge',
    b'iq_3dnr',
    b'iq_post_sharpen',
    b'iq_ycurve',
    b'ov13b10_iq_0_colorpencil',
    b'ov13b10_iq_1_colorpencil',
    b'PORTRAIT',
    b'SCENERY',
    b'Black and White',
    b'Custom1',
]

seen = []
for key in keys:
    off = 0
    while True:
        idx = data.find(key, off)
        if idx < 0:
            break
        if idx not in [x[0] for x in seen]:
            seen.append((idx, key))
        off = idx + 1

for idx, key in sorted(seen):
    name = key.decode('latin1', 'ignore')
    start = max(0, idx - 64)
    end = min(len(data), idx + 512)
    chunk = data[start:end]
    print(f'=== {name} @ 0x{idx:x} ===')
    for i in range(0, len(chunk), 16):
        row = chunk[i:i+16]
        words = []
        for j in range(0, min(len(row), 16), 4):
            part = row[j:j+4]
            if len(part) < 4:
                words.append('??')
            else:
                words.append(f'{struct.unpack_from("<I", part)[0]:08x}')
        hexs = ' '.join(words)
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f'{start + i:08x}: {hexs:<47} {asc}')
    print()
