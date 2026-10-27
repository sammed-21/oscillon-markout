"""
Oscillon gap-fee and exposure-cap maths, imported from oscillon-spec (the single source of truth).

On import it checks every case in oscillon-spec/vectors.json and refuses to load if any disagrees, so the backtest
can never run on maths that has drifted from the spec. Override the spec location with OSCILLON_SPEC_DIR.

  python3 fee_spec.py        # just runs the vector check
"""
import importlib.util
import json
import os
import sys

SPEC_DIR = os.environ.get("OSCILLON_SPEC_DIR",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../oscillon-spec"))
_spec = importlib.util.spec_from_file_location("oscillon_fee_spec", os.path.join(SPEC_DIR, "fee_spec.py"))
_ref = importlib.util.module_from_spec(_spec)
sys.modules["oscillon_fee_spec"] = _ref
_spec.loader.exec_module(_ref)

Params, gap_bp, market_price, gap_fees, holdings_cap, max_in, Q96, E18 = (
    _ref.Params, _ref.gap_bp, _ref.market_price, _ref.gap_fees, _ref.holdings_cap, _ref.max_in, _ref.Q96, _ref.E18)


def check_vectors(path: str = os.path.join(SPEC_DIR, "vectors.json")) -> int:
    cases = json.load(open(path))["cases"]
    for c in cases:
        p = Params(**c["params"]); i = c["input"]; e = c["expected"]
        if c["kind"] == "fee":
            got = gap_fees(int(i["sqrtPool"]), i["crossRateSources"], int(i["now"]), p)
            want = (int(e["fee0to1"]), int(e["fee1to0"]))
        else:
            got = max_in(i["pegSources0"], i["pegSources1"], int(i["Hnormal0"]), int(i["Hnormal1"]),
                         int(i["holdings0"]), int(i["holdings1"]), int(i["now"]), p)
            want = (int(e["maxIn0to1"]), int(e["maxIn1to0"]))
        if got != want:
            raise RuntimeError(f"vectors.json mismatch in '{c['name']}': got {got}, expected {want}")
    return len(cases)


N_VECTORS = check_vectors()

if __name__ == "__main__":
    print(f"oscillon-spec/vectors.json: {N_VECTORS} cases pass")
