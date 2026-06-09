"""Smoke test for the Bureau Veritas (BV) ticker fix.

BV must fetch yfinance data under the Paris listing "BVI.PA" while still
displaying as "BV" — the same fetch≠display indirection already used for
"LSEG.L" → "LSEG".

1. Source wiring: "BVI.PA" is the fetch symbol in _SAT_FETCH_TICKERS, the bare
   "BV" fetch entry is gone, _SAT_STORE_KEY maps "BVI.PA" → "BV" (and still
   maps "LSEG.L" → "LSEG"), and the satellite row keeps display "BV" with the
   red-font / ethics-flag / off-limits note intact.
2. Live fetch: BVI.PA returns a healthy metric bundle from yfinance.
3. AppTest: the app (which fetches BVI.PA on load) renders without exceptions.
"""
import re
import sys

import munger_portfolio_app as app
from smoke_test_satellite import fetch_bundle, METRIC_FIELDS

SRC = open("munger_portfolio_app.py", encoding="utf-8").read()


def test_source_wiring() -> bool:
    ok = True

    # ── Auto-fetch ticker list — fetch under BVI.PA, no bare "BV" entry ──
    # Capture the list body: from the assignment "= [" to its closing "]".
    # (Anchor on "= [" so the [ ] inside the `list[tuple[...]]` annotation is
    # skipped; list items contain no "]" so the non-greedy stop is correct.)
    fetch_block = re.search(
        r"_SAT_FETCH_TICKERS[^\n]*=\s*\[(.*?)\]", SRC, re.S
    ).group(1)
    if '("BVI.PA", False)' not in fetch_block:
        print("  ✗ ('BVI.PA', False) not in _SAT_FETCH_TICKERS")
        ok = False
    if re.search(r'\(\s*"BV"\s*,', fetch_block):
        print("  ✗ a bare ('BV', …) fetch entry still exists in _SAT_FETCH_TICKERS")
        ok = False

    # ── _SAT_STORE_KEY map — BVI.PA → BV, LSEG.L → LSEG ──
    if '"BVI.PA": "BV"' not in SRC:
        print('  ✗ _SAT_STORE_KEY is missing "BVI.PA": "BV"')
        ok = False
    if '"LSEG.L": "LSEG"' not in SRC:
        print('  ✗ _SAT_STORE_KEY lost the "LSEG.L": "LSEG" mapping')
        ok = False

    # ── Satellite stock list — display stays "BV" (the BV row tuple) ──
    if not re.search(r'\(\s*"BV",\s+"BV",', SRC):
        print('  ✗ satellite row no longer shows ("BV", "BV", …) — display changed')
        ok = False

    # ── Red font + ethics flag + off-limits note unchanged ──
    if 'is_bv = disp == "BV"' not in SRC:
        print('  ✗ red-font / ethics driver `is_bv = disp == "BV"` missing')
        ok = False
    if "Off limits until resolved" not in SRC:
        print("  ✗ BV off-limits ethics note missing")
        ok = False

    if ok:
        print("  ✓ BVI.PA is the fetch symbol; store key BVI.PA→BV (LSEG.L→LSEG "
              "intact); display 'BV' + red font + ethics note unchanged")
    return ok


def test_live_fetch() -> bool:
    b = fetch_bundle("BVI.PA")
    got = [k for k in METRIC_FIELDS if b[k] is not None]
    n = len(got)
    print(f"  [fetch] BVI.PA: {n}/8 metrics → {got}")
    if n >= 6:
        vals = ", ".join(f"{k}={b[k]:.3g}" for k in got)
        print(f"          values: {vals}")
        print("  ✓ BVI.PA resolves to a live Bureau Veritas quote (≥6/8 metrics)")
        return True
    print(f"  ✗ BVI.PA fetched only {n}/8 metrics (need ≥6) — wrong/dead symbol?")
    return False


def test_apptest() -> bool:
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("munger_portfolio_app.py", default_timeout=180)
    at.run()
    if at.exception:
        print("  ✗ AppTest raised exceptions:")
        for ex in at.exception:
            print("    ", ex)
        return False
    blob = " ".join(str(getattr(m, "value", "")) for m in at.markdown)
    has_satellite = "Munger Satellite" in blob
    print(f"  AppTest ran cleanly (fetched BVI.PA on load). "
          f"Satellite header rendered: {has_satellite}")
    return has_satellite


if __name__ == "__main__":
    print("=== Test 1: source wiring (fetch list + store key + display/ethics) ===")
    t1 = test_source_wiring()

    print("\n=== Test 2: BVI.PA live yfinance fetch ===")
    try:
        t2 = test_live_fetch()
    except Exception:
        import traceback
        traceback.print_exc()
        t2 = False

    print("\n=== Test 3: AppTest — app loads after fetching BVI.PA ===")
    try:
        t3 = test_apptest()
    except Exception:
        import traceback
        traceback.print_exc()
        t3 = False

    print("\n=== RESULT ===")
    print(f"  source wiring (BVI.PA / store key / display): {'PASS' if t1 else 'FAIL'}")
    print(f"  BVI.PA live fetch ≥6/8:                       {'PASS' if t2 else 'FAIL'}")
    print(f"  app loads cleanly:                            {'PASS' if t3 else 'FAIL'}")
    sys.exit(0 if (t1 and t2 and t3) else 1)
