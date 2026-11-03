#!/usr/bin/env python3
"""Fit a 3D LUT to what the OV13B10 IQ pipeline can actually do.

Pipeline model (all per pixel):
    l   = linear RGB after the stock CCM            (recovered from the stock output s)
    v   = T(M @ l)                                  M: 3x3 extra matrix, folded into every CCM slot
                                                    T: one tone curve shared by R, G, B (iq_gamma)
    out = Y + sat * (v - Y)                         sat: global saturation (iq_color)
with the Y curve set to identity. For mono films the model is out = T(w . l); B&W filter films
that use the luma row (iq_cst) are out = c . T(l), with the stock CCM (see luma_row).

The LUT is defined on the stock camera output s, so s is linearised through
the stock tone (ycurve o gamma).
"""
import numpy as np
from scipy.optimize import least_squares

LUMA = np.array([0.299, 0.587, 0.114])
NK = 24                                   # tone curve knots

def stock_tone(gamma1, ycurve):
    """Stock linear->display tone as (x, y) samples, x = linear 0..1."""
    x = np.linspace(0, 1, 129)
    g = np.asarray(gamma1, float) / 1023.0                  # gamma: 129 pts, linear in -> 10 bit
    yc = np.asarray(ycurve, float) / 255.0                  # ycurve: 129 pts over 0..255
    y = np.interp(g, np.linspace(0, 1, 129), yc)
    return x, y

def linearise(s, x, y):
    yy = np.maximum.accumulate(y + np.arange(len(y)) * 1e-9)
    return np.interp(s, yy, x)

def knots_to_curve(p):
    """Monotone curve on knots in sqrt-linear space: p[0] = black level, rest = log increments."""
    inc = np.exp(p[1:])
    c = p[0] + np.concatenate([[0], np.cumsum(inc)])
    return c                                                 # values at NK knots

KX = np.linspace(0, 1, NK) ** 2                              # dense knots in the shadows

def tone(c, v):
    return np.interp(np.clip(v, 0, 1), KX, c)

def lift(c, black, joint=0.153):
    """Filmic shadow lift: start the curve at `black` (0..1 output) and rise along a
    smooth toe (cubic Hermite, gentle start slope) that meets the fitted curve at linear
    `joint` with the same slope. Never darkens: returns max(curve, toe) at the knots."""
    c = np.asarray(c, float)
    cj = tone(c, joint)
    mj = (tone(c, joint + 1e-3) - tone(c, joint - 1e-3)) / 2e-3
    sec = (cj - black) / joint
    mj = min(mj, 3 * sec)                                    # keep the Hermite monotone
    m0 = 0.5 * sec
    t = np.clip(KX / joint, 0, 1)
    h = ((2 * t**3 - 3 * t**2 + 1) * black + (t**3 - 2 * t**2 + t) * joint * m0
         + (-2 * t**3 + 3 * t**2) * cj + (t**3 - t**2) * joint * mj)
    return np.where(KX < joint, np.maximum(c, h), c)

def samples(n=17):
    g = np.linspace(0, 1, n)
    s = np.stack(np.meshgrid(g, g, g, indexing='ij'), -1).reshape(-1, 3)
    ch = s.max(1) - s.min(1)
    w = 1.0 / (1.0 + 3.0 * ch)                               # favour neutrals and natural colours
    nt = np.linspace(0, 1, 65)
    s = np.concatenate([s, np.stack([nt] * 3, 1)])           # extra weight on the grey axis
    w = np.concatenate([w, np.full(65, 3.0)])
    return s, w

def fit_colour(lut_apply, x, y):
    s, w = samples()
    t = lut_apply(s)
    l = linearise(s, x, y)
    c0 = np.interp(KX, x, y)
    p0 = np.concatenate([np.eye(3).ravel(), [c0[0]], np.log(np.maximum(np.diff(c0), 1e-4)), [1.0]])
    def model(p):
        M = p[:9].reshape(3, 3); c = knots_to_curve(p[9:9 + NK]); sat = p[-1]
        v = tone(c, l @ M.T)
        Y = v @ LUMA
        return Y[:, None] + sat * (v - Y[:, None])
    def res(p):
        return ((model(p) - t) * np.sqrt(w)[:, None]).ravel()
    r = least_squares(res, p0, method='trf', max_nfev=4000)
    p = r.x
    out = model(p)
    return dict(M=p[:9].reshape(3, 3), curve=knots_to_curve(p[9:9 + NK]), sat=float(p[-1]),
                err=report(out, t, s))

def fit_mono(lut_apply, x, y):
    s, w = samples()
    t = lut_apply(s).mean(1)
    l = linearise(s, x, y)
    c0 = np.interp(KX, x, y)
    p0 = np.concatenate([LUMA, [c0[0]], np.log(np.maximum(np.diff(c0), 1e-4))])
    def model(p):
        return tone(knots_to_curve(p[3:]), l @ p[:3])
    def res(p):
        return (model(p) - t) * np.sqrt(w)
    r = least_squares(res, p0, method='trf', max_nfev=4000)
    p = r.x
    out = model(p)
    return dict(w=p[:3], curve=knots_to_curve(p[3:]),
                err=report(np.stack([out] * 3, 1), np.stack([t] * 3, 1), s))

def luma_row(curve, w, x, y, lo=-256, hi=255):
    """B&W filter in the RGB->YCC luma row (iq_cst), which works after the tone curve:
    integer Q8 weights c (sum 256, each in lo..hi) with c . T(l) / 256 closest to the
    linear-domain filter T(l . w / sum(w)). Exhaustive over the legal rows."""
    s, wt = samples()
    l = linearise(s, x, y)
    A = tone(curve, l)                                       # per channel, after the tone curve
    t = tone(curve, l @ (w / w.sum()))
    Q = A.T @ (A * wt[:, None]) / 256**2                     # |A c / 256 - t|^2 as a quadratic
    b = A.T @ (t * wt) / 256
    g = np.arange(lo, hi + 1)
    c0, c1 = np.meshgrid(g, g, indexing='ij')
    c2 = 256 - c0 - c1
    C = np.stack([c0, c1, c2], -1)[(lo <= c2) & (c2 <= hi)].astype(float)
    cost = np.einsum('ni,ij,nj->n', C, Q, C) - 2 * C @ b
    c = C[np.argmin(cost)].astype(int)
    out = A @ c / 256
    return dict(row=c, err=report(np.stack([out] * 3, 1), np.stack([t] * 3, 1), s))

def report(out, t, s):
    e = np.abs(out - t).max(1) * 255
    nat = (s.max(1) - s.min(1)) < 0.5
    return dict(mean=float(e.mean()), natural_mean=float(e[nat].mean()), p95=float(np.percentile(e, 95)))

def curve_lut(c, n=129):
    """Tone curve sampled at the gamma table's 129 linear inputs."""
    return tone(c, np.linspace(0, 1, n))
