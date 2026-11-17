import math, os, sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pool_model import Pool, tick_to_s  # noqa: E402


def test_tick_to_price_matches_hand_check():
    # HANDCHECK_lp_fynd.md section 5: ticks -19,844,096 / -19,745,792 = $2,408.92 - $2,657.76
    assert tick_to_s(-19844096) ** 2 == pytest.approx(2408.92, abs=0.01)
    assert tick_to_s(-19745792) ** 2 == pytest.approx(2657.76, abs=0.01)


def one_range():
    p = Pool(math.sqrt(2500)); p.update("a", -19900000, -19700000, 1e16)
    return p


def test_constant_liquidity_amounts():
    p = one_range(); l = 1e16 * 1e-12
    x, y = p.move_to(math.sqrt(2490))
    assert x == pytest.approx(l * (1 / math.sqrt(2490) - 1 / math.sqrt(2500)))
    assert y == pytest.approx(l * (math.sqrt(2490) - math.sqrt(2500)))
    assert -y / x == pytest.approx(math.sqrt(2490 * 2500))          # average price = geometric mean


def test_round_trip_returns_to_start():
    p = one_range(); x, y = p.move_to(math.sqrt(2480))
    x2, y2 = p.swap_eth_in(-x)
    assert x2 == pytest.approx(-x) and y2 == pytest.approx(-y) and p.s ** 2 == pytest.approx(2500)


def test_crossing_into_a_gap_and_a_second_range():
    p = Pool(math.sqrt(2500))
    p.update("a", -19900000, -19740000, 1e16)          # up to ~$2,673
    p.update("b", -19730000, -19600000, 2e16)          # from ~$2,700
    x, y = p.move_to(math.sqrt(2750))
    s0, s1, s2, s3 = math.sqrt(2500), tick_to_s(-19740000), tick_to_s(-19730000), math.sqrt(2750)
    assert y == pytest.approx(1e4 * (s1 - s0) + 2e4 * (s3 - s2))    # nothing traded across the empty gap
    assert x == pytest.approx(1e4 * (1 / s1 - 1 / s0) + 2e4 * (1 / s3 - 1 / s2))


def test_limit_price_leaves_rest_unfilled():
    p = one_range()
    filled, y = p.swap_eth_in(-1000.0, s_limit=math.sqrt(2550))
    assert p.s == pytest.approx(math.sqrt(2550)) and -1000 < filled < 0


def test_withdrawal_removes_liquidity():
    p = one_range(); p.update("a", -19900000, -19700000, -1e16)
    assert p.liquidity() == 0.0
