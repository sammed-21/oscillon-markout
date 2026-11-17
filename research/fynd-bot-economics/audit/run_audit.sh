#!/bin/sh
# Independent audit of final/il_vs_bot_capture.png. Reads data/, out/, final/data/ and ../markout-backtest; writes only into audit/.
set -e
cd "$(dirname "$0")/.."
M=../markout-backtest
python3 audit/recon.py --root . --lp $M --out audit
python3 audit/analyze.py --root . --lp $M --out audit > audit/data/analyze.log
python3 audit/replay_check.py --root . --lp $M --out audit > audit/data/replay_check.log
python3 audit/write_audit.py --root . --lp $M --out audit > /dev/null
