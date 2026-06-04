"""Smoke test for the Satellite tab restructure.

1. Replicates the Satellite metric fetch for V and MCO and asserts that at
   least 6 of the 8 quality metrics fetch successfully.
2. Runs the full Streamlit app via AppTest to confirm the Satellite tab (the
   default landing tab) renders without raising an exception.
"""
import sys

import munger_portfolio_app as app

# The 8 auto-fetched quality metrics per the spec:
#   Price, ROIC, FCFy, RevGr, GM, Ins%, D/E  (plus EPS, used for Fair$/Dream$)
METRIC_FIELDS = ["price", "roic", "fcfy", "revgr", "gm", "ins", "de", "eps"]


def fetch_bundle(yf_ticker: str) -> dict:
    """Replicate _sat_fetch_all (which lives inside main()) using the module's
    importable helpers."""
    info = app.fetch_info(yf_ticker)
    out = {k: None for k in METRIC_FIELDS}
    if not info:
        return out
    out["price"] = app._price_from_info(info)
    out["eps"] = app._float(info, "trailingEps")
    roa = app._pos_float(info, "returnOnAssets")
    if roa is not None:
        out["roic"] = roa * 100.0
    else:
        roe = app._pos_float(info, "returnOnEquity")
        if roe is not None:
            out["roic"] = roe * 100.0
    fcf = app._float(info, "freeCashflow")
    mc = app._float(info, "marketCap")
    if fcf and mc and mc > 0:
        out["fcfy"] = fcf / mc * 100.0
    rg = app._float(info, "revenueGrowth")
    if rg is not None:
        out["revgr"] = rg * 100.0
    gm = app._float(info, "grossMargins")
    if gm is not None:
        out["gm"] = gm * 100.0
    ins = app._float(info, "heldPercentInsiders")
    if ins is not None:
        out["ins"] = ins * 100.0
    de = app._float(info, "debtToEquity")
    if de is not None:
        out["de"] = de / 100.0
    return out


def test_fetch():
    ok = True
    for tk in ("V", "MCO"):
        b = fetch_bundle(tk)
        got = [k for k in METRIC_FIELDS if b[k] is not None]
        n = len(got)
        print(f"[fetch] {tk}: {n}/8 metrics → {got}")
        print(f"        values: " + ", ".join(
            f"{k}={b[k]:.3g}" for k in got))
        if n < 6:
            print(f"  ✗ {tk} fetched only {n}/8 metrics (need ≥6)")
            ok = False
        else:
            print(f"  ✓ {tk} fetched {n}/8 metrics")
    return ok


def test_apptest():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("munger_portfolio_app.py", default_timeout=180)
    at.run()
    if at.exception:
        print("  ✗ AppTest raised exceptions:")
        for ex in at.exception:
            print("    ", ex)
        return False
    # Confirm the Satellite tab content rendered (BRK.B anchor marker present).
    blob = " ".join(str(getattr(m, "value", "")) for m in at.markdown)
    has_anchor = "BRK.B ANCHOR" in blob
    has_satellite = "Munger Satellite" in blob
    print(f"  AppTest ran cleanly. BRK.B anchor rendered: {has_anchor}, "
          f"Munger Satellite header rendered: {has_satellite}")
    return has_anchor and has_satellite


if __name__ == "__main__":
    print("=== Test 1: yfinance metric fetch (V, MCO) ===")
    fetch_ok = test_fetch()
    print("\n=== Test 2: AppTest — Satellite tab renders without error ===")
    try:
        app_ok = test_apptest()
    except Exception as e:
        import traceback
        traceback.print_exc()
        app_ok = False
    print("\n=== RESULT ===")
    print(f"  fetch ≥6/8 for V & MCO: {'PASS' if fetch_ok else 'FAIL'}")
    print(f"  Satellite tab loads:    {'PASS' if app_ok else 'FAIL'}")
    sys.exit(0 if (fetch_ok and app_ok) else 1)
