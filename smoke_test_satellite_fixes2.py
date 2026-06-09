"""Smoke test for the second round of Satellite-tab fixes.

(1) Column headers use SHORT labels (so AG Grid never truncates to an ellipsis),
    while every column keeps a headerTooltip carrying the full label.
(2) The Munger Satellite banner bubble is dynamic — "X of 12 at FAIR or better
    — Y DREAM" computed from the live row signals (no stale "1 of 6 Filled /
    slots held as SGOV" copy).
(3) The debate modal renders the API response via st.markdown(_md_safe(...)):
    bare '$' (LaTeX-math trigger) is escaped to '\\$' so dollar figures and the
    surrounding *italic* / **bold** markers render correctly, and no other
    markdown construct is altered.
"""
import sys

import pandas as pd

import munger_portfolio_app as app

VISIBLE = [
    "Ticker", "Price", "Current P/E", "Dream P/E", "Fair P/E", "Fair$", "Dream$",
    "Discount", "Signal", "SMS", "R", "ROIC", "FCFy", "RevGr", "GM", "Ins%",
    "D/E", "Quality", "Red Flags", "Slot Status", "Notes",
]
HIDDEN = ["_notes_full", "_name", "_is_bv", "_sms_bg", "_sms_fg", "_pe_label"]

# Expected short header label per field (per the spec).
EXPECTED_HEADERS = {
    "Ticker": "Ticker", "Price": "Price", "Current P/E": "P/E",
    "Dream P/E": "Dream", "Fair P/E": "Fair", "Fair$": "Fair$",
    "Dream$": "Dream$", "Discount": "Disc%", "Signal": "Signal", "SMS": "SMS",
    "R": "R", "ROIC": "ROIC", "FCFy": "FCFy", "RevGr": "RevGr", "GM": "GM",
    "Ins%": "Ins%", "D/E": "D/E", "Quality": "Qual", "Red Flags": "Flags",
    "Slot Status": "Status", "Notes": "Notes",
}
# Long labels that must NOT appear as a header (would truncate to an ellipsis).
FORBIDDEN_HEADERS = {"Current P/E", "Dream P/E", "Fair P/E", "Discount",
                     "Quality", "Red Flags", "Slot Status", "K's Notes"}


def _sample_df() -> pd.DataFrame:
    row = {c: "" for c in VISIBLE + HIDDEN}
    row["Current P/E"] = 20.0
    row["SMS"] = 25
    return pd.DataFrame([row])


def _cols(opts: dict) -> dict:
    out = {}
    for c in opts.get("columnDefs", []):
        if "field" in c:
            out[c["field"]] = c
    return out


def test_short_headers() -> bool:
    """Fix 1 — short labels on both the satellite grid and the BRK.B P/B anchor."""
    ok = True
    # Satellite grid (pb=False): every column uses the short label + keeps a tip.
    cols = _cols(app._build_sat_grid_options(_sample_df(), pb=False))
    for field, want in EXPECTED_HEADERS.items():
        got = cols[field].get("headerName")
        if got != want:
            print(f"  ✗ {field!r} headerName={got!r} (want {want!r})")
            ok = False
        if not cols[field].get("headerTooltip"):
            print(f"  ✗ {field!r} lost its headerTooltip")
            ok = False
    for field, c in cols.items():
        if c.get("headerName") in FORBIDDEN_HEADERS:
            print(f"  ✗ {field!r} still shows long header {c.get('headerName')!r}")
            ok = False

    # BRK.B anchor (pb=True): the three valuation cols relabel to P/B; the rest
    # still use the short labels.
    pb_cols = _cols(app._build_sat_grid_options(_sample_df(), pb=True))
    for field, want in {"Current P/E": "Current P/B", "Dream P/E": "Dream P/B",
                        "Fair P/E": "Fair P/B"}.items():
        if pb_cols[field].get("headerName") != want:
            print(f"  ✗ [pb] {field!r} headerName="
                  f"{pb_cols[field].get('headerName')!r} (want {want!r})")
            ok = False
    if pb_cols["Discount"].get("headerName") != "Disc%":
        print("  ✗ [pb] Discount should still be 'Disc%'")
        ok = False

    if ok:
        print("  ✓ all headers short, tooltips intact, no long labels remain "
              "(satellite + P/B anchor)")
    return ok


def test_md_safe() -> bool:
    """Fix 3 — $ escaped (math disabled); other markdown untouched; idempotent."""
    ok = True

    s = "Fair value of $52 vs price $44 — **bold**, *italic*, and `code` stay."
    out = app._md_safe(s)
    if "\\$52" not in out or "\\$44" not in out:
        print(f"  ✗ dollar signs not escaped: {out!r}")
        ok = False
    for token in ("**bold**", "*italic*", "`code`", "—"):
        if token not in out:
            print(f"  ✗ markdown token {token!r} was altered: {out!r}")
            ok = False

    # Headings, tables, lists pass through unchanged.
    table = "## 4. SIGNAL VERDICT\n| Gate | Pass? |\n| --- | --- |\n- bullet"
    if app._md_safe(table) != table:
        print(f"  ✗ table/heading markdown altered: {app._md_safe(table)!r}")
        ok = False

    # Already-escaped \$ is not double-escaped.
    _esc_in = "already \\$5"
    _esc_out = app._md_safe(_esc_in)
    if _esc_out != _esc_in:
        print("  ✗ already-escaped dollar double-escaped: " + repr(_esc_out))
        ok = False

    if app._md_safe("") != "" or app._md_safe(None) is not None:
        print("  ✗ empty/None handling wrong")
        ok = False

    if ok:
        print("  ✓ $ escaped, math disabled; bold/italic/code/tables/headings "
              "untouched; no double-escape")
    return ok


def test_app_renders() -> bool:
    """Fixes 1 & 2 in situ — AppTest renders the new bubble; old copy is gone."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("munger_portfolio_app.py", default_timeout=180)
    at.run()
    if at.exception:
        print("  ✗ AppTest raised exceptions:")
        for ex in at.exception:
            print("    ", ex)
        return False
    blob = " ".join(str(getattr(m, "value", "")) for m in at.markdown)

    new_bubble = ("at FAIR or better" in blob and "DREAM" in blob
                  and "of 12 at FAIR or better" in blob)
    old_gone = ("Filled" not in blob and "slots held as SGOV" not in blob)
    print(f"  dynamic bubble present: {new_bubble}; old 6-slot copy removed: "
          f"{old_gone}")
    return new_bubble and old_gone


if __name__ == "__main__":
    print("=== Fix 1: short column headers (no ellipsis) ===")
    f1 = test_short_headers()

    print("\n=== Fix 3: debate markdown rendering (_md_safe) ===")
    f3 = test_md_safe()

    print("\n=== Fixes 1 & 2: AppTest (banner bubble + render) ===")
    try:
        f2 = test_app_renders()
    except Exception:
        import traceback
        traceback.print_exc()
        f2 = False

    print("\n=== RESULT ===")
    print(f"  (1) short headers:          {'PASS' if f1 else 'FAIL'}")
    print(f"  (2) dynamic banner bubble:  {'PASS' if f2 else 'FAIL'}")
    print(f"  (3) markdown rendering:     {'PASS' if f3 else 'FAIL'}")
    sys.exit(0 if (f1 and f2 and f3) else 1)
