"""Small statistics helpers (no scipy): median, Spearman's rho with average ranks, bootstrap CI."""
from __future__ import annotations

import math
import random
import statistics


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs, ys):
    """Spearman's rho (Pearson on average ranks). None when undefined (n < 3 or a constant side)."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    rx, ry = _ranks([p[0] for p in pairs]), _ranks([p[1] for p in pairs])
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def bootstrap_ci(xs, ys, stat=spearman, n_resamples=2000, seed=7, alpha=0.05):
    """Percentile bootstrap CI over (x, y) rows; resamples where the statistic is undefined are skipped."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n_resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        v = stat([p[0] for p in sample], [p[1] for p in sample])
        if v is not None:
            vals.append(v)
    if len(vals) < n_resamples // 2:
        return None
    vals.sort()
    lo = vals[int(alpha / 2 * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return lo, hi
