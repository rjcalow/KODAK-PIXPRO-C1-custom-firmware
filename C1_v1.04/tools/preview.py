#!/usr/bin/env python3
"""Render a test chart for every film in build_films.FILMS: stock camera output,
the LUT itself, and the in-camera approximation that the build will produce.

Usage: preview.py C110.bin out.png [lut_dir]      (needs numpy, scipy, pillow)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
import cube, fit_lut as F, nvtfw as nf
import build_films as BF

# ColorChecker sRGB patches (8-bit)
CC = np.array([[115, 82, 68], [194, 150, 130], [98, 122, 157], [87, 108, 67], [133, 128, 177], [103, 189, 170],
               [214, 126, 44], [80, 91, 166], [193, 90, 99], [94, 60, 108], [157, 188, 64], [224, 163, 46],
               [56, 61, 150], [70, 148, 73], [175, 54, 60], [231, 199, 31], [187, 86, 149], [8, 133, 161],
               [243, 243, 242], [200, 200, 200], [160, 160, 160], [122, 122, 121], [85, 85, 85], [52, 52, 52]]) / 255

def chart(W=600, H=330):
    img = np.zeros((H, W, 3))
    for i, c in enumerate(CC):
        r, col = divmod(i, 6)
        img[10 + r * 50:55 + r * 50, 10 + col * 98:103 + col * 98] = c
    hx = np.linspace(0, 1, W)
    hue = np.stack([np.clip(np.abs((hx * 6 + k) % 6 - 3) - 1, 0, 1) for k in (0, 4, 2)], 1)
    for j in range(40):
        img[215 + j] = hue * (0.35 + 0.6 * j / 40) + 0.05
    img[262:300] = np.linspace(0, 1, W)[:, None]
    img[300:330] = (np.linspace(0, 1, W) ** 2.2)[:, None]
    return img

def approx(fit, mono, flat, x, y):
    l = F.linearise(flat, x, y)
    if 'luma' in fit:                        # filter in the luma row, after the tone curve
        v = F.tone(fit['curve'], l) @ (fit['luma']['row'] / 256)
        return np.stack([v] * 3, 1)
    if mono:
        v = F.tone(fit['curve'], l @ fit['w'])
        return np.stack([v] * 3, 1)
    v = F.tone(fit['curve'], l @ fit['M'].T)
    Y = v @ F.LUMA
    return Y[:, None] + fit['sat'] * (v - Y[:, None])

def main(src, out, lut_dir=BF.LUT_DIR):
    d = open(src, 'rb').read()
    root, _ = nf.fdt_parse(nf.isp_part(nf.parse_pack(d))['data'])
    P = lambda s: dict(nf.find(root, '/isp/iq/ov13b10_iq_0_cap/' + s).props)['data']
    g = struct.unpack('<933I', P('iq_gamma'))
    yc = struct.unpack('<130I', P('iq_ycurve'))[1:]
    x, y = F.stock_tone(g[544:673], yc)
    img = chart(); H, W, _ = img.shape
    flat = img.reshape(-1, 3)
    rows, names = [], []
    for node, f in BF.FILMS.items():
        lut = cube.load(os.path.join(lut_dir, f['lut']))
        fit = BF.film_fit(f, x, y, lut_dir)                 # with lift and B&W filter mix
        tiles = [flat, cube.apply(lut, flat), approx(fit, f['mono'], flat, x, y)]
        rows.append(np.concatenate([np.clip(t.reshape(H, W, 3), 0, 1) for t in tiles], 1))
        names.append((f['name'], 'LUT, no filter' if f.get('mix') else 'LUT target'))
    im = Image.fromarray((np.concatenate(rows, 0) * 255 + 0.5).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    for k, (n, target) in enumerate(names):
        for j, lab in enumerate(('stock camera', target, 'camera approx')):
            dr.rectangle([j * W + 4, k * H + 300, j * W + 190, k * H + 326], fill=(0, 0, 0))
            dr.text((j * W + 8, k * H + 306), f'{n}: {lab}', fill=(255, 255, 255))
    im.save(out)
    print(f'wrote {out}')

if __name__ == '__main__':
    main(*sys.argv[1:4])
