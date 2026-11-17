"""
A minimal concentrated-liquidity model of the Fynd ETH/USDG Ekubo pool, rebuilt from its position events.

Units: price P in USDG per ETH; s = sqrt(P). A position with Ekubo liquidity L (raw) and ticks [tl, tu) holds, while
the price is inside its range, virtual reserves X = l / s ETH and Y = l * s USDG with l = L * 1e-12
(1e-12 = sqrt(1e6 / 1e18) converts raw units to ETH and USDG). Ekubo tick -> price: 1.000001**tick * 1e12.
Swaps are walked across range boundaries, so a thin region does not let a small trade move the price without limit.
Fees are not part of the curve (Fynd's fee is charged by its extension, outside the pool's own fee).
"""
import bisect
import math


def tick_to_s(tick):
    return math.sqrt(1.000001 ** tick * 1e12)


class Pool:
    def __init__(self, s):
        self.s = s
        self.pos = {}                         # key -> [s_lo, s_hi, l]
        self._dirty = True

    def update(self, key, tick_lower, tick_upper, liquidity_delta):
        p = self.pos.setdefault(key, [tick_to_s(tick_lower), tick_to_s(tick_upper), 0.0])
        p[2] += liquidity_delta * 1e-12
        if p[2] <= 1e-9:
            del self.pos[key]
        self._dirty = True

    def _build(self):
        b = sorted({p[0] for p in self.pos.values()} | {p[1] for p in self.pos.values()})
        self.bounds = b
        self.seg_l = [sum(p[2] for p in self.pos.values() if p[0] <= lo and p[1] >= hi) for lo, hi in zip(b[:-1], b[1:])]
        self._dirty = False

    def liquidity(self, s=None):
        """l at price sqrt s (left-closed segments)."""
        if self._dirty:
            self._build()
        s = self.s if s is None else s
        i = bisect.bisect_right(self.bounds, s) - 1
        return self.seg_l[i] if 0 <= i < len(self.seg_l) else 0.0

    def _seg(self, s, up):
        """Segment index the price moves through from s, and that segment's far edge."""
        b = self.bounds
        if up:
            i = bisect.bisect_right(b, s) - 1
            return i, (b[i + 1] if i + 1 < len(b) else math.inf)
        i = bisect.bisect_left(b, s) - 1
        return i, (b[i] if i >= 0 else 0.0)

    def move_to(self, s_target):
        """Move the price to s_target. Returns (eth_to_pool, usdg_to_pool)."""
        if self._dirty:
            self._build()
        s, x, y = self.s, 0.0, 0.0
        while s != s_target:
            up = s_target > s
            i, edge = self._seg(s, up)
            nxt = min(s_target, edge) if up else max(s_target, edge)
            l = self.seg_l[i] if 0 <= i < len(self.seg_l) else 0.0
            if l > 0:
                x += l * (1 / nxt - 1 / s); y += l * (nxt - s)
            s = nxt
        self.s = s
        return x, y

    def swap_eth_in(self, eth, s_limit=None):
        """Pool receives `eth` ETH (negative = pays out). Stops at sqrt price s_limit if given (the trader's limit
        price). Returns (eth_filled, usdg_to_pool)."""
        if self._dirty:
            self._build()
        s, left, y = self.s, eth, 0.0
        while left != 0.0:
            up = left < 0                          # ETH out of the pool -> price rises
            i, edge = self._seg(s, up)
            if s_limit is not None:
                edge = min(edge, s_limit) if up else max(edge, s_limit)
                if s == s_limit:
                    break
            l = self.seg_l[i] if 0 <= i < len(self.seg_l) else 0.0
            if l <= 0:
                if edge in (0.0, math.inf) or edge == s_limit:
                    if edge == s_limit:
                        s = edge
                    break                          # no liquidity left that way, or the limit: the rest is unfilled
                s = edge; continue
            den = l / s + left
            s_new = l / den if den > 0 else math.inf
            if (up and s_new >= edge) or (not up and s_new <= edge):
                used = l * (1 / edge - 1 / s)
                y += l * (edge - s); left -= used; s = edge
                if edge in (0.0, math.inf) or edge == s_limit:
                    break
                continue
            y += l * (s_new - s); left = 0.0; s = s_new
        self.s = s
        return eth - left, y
