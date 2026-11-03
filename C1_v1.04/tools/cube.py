"""Minimal .cube 3D LUT loader / trilinear sampler."""
import numpy as np

def load(path):
    n, rows = None, []
    dmin, dmax = np.zeros(3), np.ones(3)
    with open(path) as f:
        for line in f:
            t = line.split()
            if not t or t[0].startswith('#'):
                continue
            if t[0] == 'LUT_3D_SIZE':
                n = int(t[1])
            elif t[0] == 'DOMAIN_MIN':
                dmin = np.array(t[1:4], float)
            elif t[0] == 'DOMAIN_MAX':
                dmax = np.array(t[1:4], float)
            elif t[0][0] in '-.0123456789' and len(t) == 3:
                rows.append(t)
    a = np.array(rows, float)
    assert n and len(a) == n ** 3, (n, len(a))
    # .cube order: red varies fastest -> index [b, g, r]
    return dict(n=n, lut=a.reshape(n, n, n, 3), dmin=dmin, dmax=dmax)

def apply(c, rgb):
    """rgb: (..., 3) in the LUT domain -> (..., 3), trilinear."""
    n, lut = c['n'], c['lut']
    x = (np.clip(rgb, c['dmin'], c['dmax']) - c['dmin']) / (c['dmax'] - c['dmin']) * (n - 1)
    i0 = np.clip(np.floor(x).astype(int), 0, n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                w = (fr if dr else 1 - fr) * (fg if dg else 1 - fg) * (fb if db else 1 - fb)
                out = out + w * lut[b0 + db, g0 + dg, r0 + dr]
    return out
