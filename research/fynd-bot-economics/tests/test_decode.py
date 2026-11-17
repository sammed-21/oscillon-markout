"""
Tests for decode.py on three real bot transactions, with every expected number read by hand from the raw logs
(hex values quoted in the comments). Run: python3 -m pytest tests -q
"""
import json, os, sys
import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
from decode import decode, economics, s128, s256, NATIVE, USDG, WETH, CORE, PM, BOT_CONTRACT  # noqa: E402

META = json.load(open(os.path.join(HERE, "..", "data", "meta.json")))
fx = lambda n: json.load(open(os.path.join(HERE, "fixtures", n + ".json")))


def run(name):
    x = fx(name)
    d = decode(x["tx"], x["receipt"], META)
    return d, economics(d)


def test_signed_ints():
    assert s128("ffffffffffffffffffffffffe323b7a1") == -0x1cdc485f
    assert s128("000000000000000002add01d6d350d62") == 0x02add01d6d350d62
    assert s256("f" * 63 + "f") == -1


def test_sells_eth_v4():
    # 0x21baf60f... block 87,487,456, nonce 0: bot sells ETH into Fynd, buys it back on a Uniswap v4 WETH/USDG pool
    d, e = run("sells_eth_v4")
    assert d["nonce"] == 0 and d["status"] == 1 and d["value_wei"] == 0
    assert e["fynd_direction"] == "bot_sells_eth"
    assert e["fynd_eth_raw"] == 0x02add01d6d350d62 and e["fynd_usdg_raw"] == -0x1cdc485f      # Fynd got ETH, paid 484.198495 USDG
    v4 = [l for l in d["legs"] if l["venue"] == "uniswap_v4"]
    assert len(v4) == 1 and v4[0]["raw"][WETH] == -0x02ae565aaa0681c9 and v4[0]["raw"][USDG] == 0x1cdc485f
    # fee = ETH the bot paid into Fynd (bot event word 2) - Fynd swap amount
    assert e["fee_token"] == "ETH" and e["fee_raw"] == 0x02ae47d45a75918c - 0x02add01d6d350d62
    # bot keeps WETH out - ETH paid in = bot event word 3
    assert e["bot_eth_wei"] == 0x02ae565aaa0681c9 - 0x02ae47d45a75918c == 0x0e864f90f03d
    assert e["bot_event_profit_gap"] == 0 and e["bot_usdg_raw"] == 0
    assert not e["issues"], e["issues"]
    assert e["gas_eth"] == pytest.approx(387949 * 20020000 / 1e18)


def test_buys_eth_v4_fee_observed_in_usdg():
    # 0x6863b1c0...: bot buys ETH from Fynd with USDG, sells the ETH on a native-ETH Uniswap v4 pool
    d, e = run("buys_eth_v4")
    assert e["fynd_direction"] == "bot_buys_eth"
    assert e["fynd_usdg_raw"] == 309877180
    # USDG transfer bot -> Core is 309,906,951: the 29,771 above the swap amount is the Fynd fee (observed)
    assert e["fee_token"] == "USDG" and e["fee_raw"] == 309906951 - 309877180
    assert e["bot_event_w2"] == 309906951                    # the bot's event reports the same amount paid in
    assert e["bot_usdg_raw"] == 309937962 - 309906951 == e["bot_event_w3"]
    assert e["bot_eth_wei"] == 0                              # native ETH out of Fynd went straight into the v4 pool
    assert not e["issues"], e["issues"]


def test_multihop_intermediate_nets_to_zero():
    # 0x02404683...: USDG -> ETH (v4) -> token 0x6b1d... (v4) -> WETH (v3) -> unwrapped; intermediates must net to 0
    d, e = run("sells_eth_multihop")
    assert e["n_other_legs"] == 3
    assert e["intermediate_residual"] == {}
    assert e["bot_event_profit_gap"] == 0
    assert not e["issues"], e["issues"]


def test_router_and_venue_checks_flag_a_tampered_transfer():
    x = fx("sells_eth_v4")
    for l in x["receipt"]["logs"]:      # shave 1 unit off the USDG transfer into the PoolManager
        if l["topics"] and l["topics"][0].startswith("0xddf252ad") and l["topics"][2].endswith(PM[2:]):
            l["data"] = "0x" + f"{int(l['data'], 16) - 1:064x}"
    e = economics(decode(x["tx"], x["receipt"], META))
    assert any("swap/transfer gap" in s for s in e["issues"])
