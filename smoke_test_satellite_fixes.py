"""Smoke test for the three Satellite-tab fixes.

(1) Banner text now reads "K's 12 — Munger Master List" (old "6 Slots Max /
    20% Total — Tier 1 Oligopolies Only" copy removed).
(2) Filter / sort / column-menu icons are fully suppressed: sortable=False,
    filter=False, suppressMenu=True, floatingFilter=False on the defaultColDef
    AND on every individual column definition (visible + hidden helpers), with
    suppressMovableColumns=True in gridOptions — checked on all three table
    configurations (satellite grids + the BRK.B P/B anchor).
(3) Column-width persistence: saved widths are applied back onto the column
    definitions on load, and the resize-state extraction helper parses an
    AgGrid columns_state payload correctly.
"""
import sys

import pandas as pd

import munger_portfolio_app as app

# Columns produced by _build_sat_row_dict (visible) + hidden helper fields.
VISIBLE = [
    "Ticker", "Price", "Current P/E", "Dream P/E", "Fair P/E", "Fair$", "Dream$",
    "Discount", "Signal", "SMS", "R", "ROIC", "FCFy", "RevGr", "GM", "Ins%",
    "D/E", "Quality", "Red Flags", "Slot Status", "Notes",
]
HIDDEN = [
    "_notes_full", "_name", "_is_bv", "_disc_raw", "_fcfy_raw", "_roic_raw",
    "_sms_bg", "_sms_fg", "_pe_label",
]

# Per the spec: every column must have these exact values; nothing else allowed.
REQUIRED_FLAGS = (
    ("sortable", False),
    ("filter", False),
    ("suppressMenu", True),
    ("floatingFilter", False),
)


def _sample_df() -> pd.DataFrame:
    row = {c: "" for c in VISIBLE + HIDDEN}
    row["Current P/E"] = 20.0
    row["SMS"] = 25
    return pd.DataFrame([row])


def _flatten_col_defs(opts: dict) -> list:
    out = []
    for c in opts.get("columnDefs", []):
        if "children" in c:
            out.extend(c["children"])
        else:
            out.append(c)
    return out


def test_banner_text() -> bool:
    """Fix 1 — AppTest renders the new banner and not the old copy."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("munger_portfolio_app.py", default_timeout=180)
    at.run()
    if at.exception:
        print("  ✗ AppTest raised exceptions:")
        for ex in at.exception:
            print("    ", ex)
        return False
    blob = " ".join(str(getattr(m, "value", "")) for m in at.markdown)
    new_ok = "K's 12 — Munger Master List" in blob
    old_gone = ("6 Slots Max" not in blob
                and "20% Total" not in blob
                and "Tier 1 Oligopolies Only" not in blob)
    print(f"  new banner present: {new_ok}; old banner copy removed: {old_gone}")
    return new_ok and old_gone


def test_icon_suppression() -> bool:
    """Fix 2 — audit all three table configs (satellite + BRK.B P/B anchor)."""
    ok = True
    for pb in (False, True):
        opts = app._build_sat_grid_options(_sample_df(), pb=pb)
        label = "pb-anchor" if pb else "satellite"

        dcd = opts.get("defaultColDef", {})
        for k, want in REQUIRED_FLAGS:
            if dcd.get(k) != want:
                print(f"  ✗ [{label}] defaultColDef[{k}]={dcd.get(k)!r} (want {want!r})")
                ok = False

        cols = _flatten_col_defs(opts)
        for col in cols:
            field = col.get("field")
            for k, want in REQUIRED_FLAGS:
                if col.get(k) != want:
                    print(f"  ✗ [{label}] column {field!r}[{k}]={col.get(k)!r} "
                          f"(want {want!r})")
                    ok = False

        if opts.get("suppressMovableColumns") is not True:
            print(f"  ✗ [{label}] suppressMovableColumns="
                  f"{opts.get('suppressMovableColumns')!r} (want True)")
            ok = False

        print(f"  [{label}] audited {len(cols)} column defs + defaultColDef")
    if ok:
        print("  ✓ no column (or defaultColDef) has filter/sortable/suppressMenu/"
              "floatingFilter mis-set; columns immovable")
    return ok


def test_width_persistence() -> bool:
    """Fix 3 — saved widths flow into column defs; state extraction is correct."""
    ok = True

    saved = {"Price": 123, "Notes": 333, "R": 51}
    opts = app._build_sat_grid_options(_sample_df(), saved_widths=saved)
    by_field = {c.get("field"): c for c in _flatten_col_defs(opts)}
    for field, want in saved.items():
        got = by_field.get(field, {}).get("width")
        if got != want:
            print(f"  ✗ column {field!r} width={got!r} (want {want!r})")
            ok = False

    # Resize-state extraction: skip hidden helper cols + null widths, coerce int.
    columns_state = [
        {"colId": "Price", "width": 210},
        {"colId": "_name", "width": 99},      # hidden helper → skipped
        {"colId": "Notes", "width": None},    # no width → skipped
        {"colId": "R", "width": 60.0},        # float → int
    ]
    got = app._sat_widths_from_state(columns_state)
    want = {"Price": 210, "R": 60}
    if got != want:
        print(f"  ✗ _sat_widths_from_state={got!r} (want {want!r})")
        ok = False
    if app._sat_widths_from_state(None) != {}:
        print("  ✗ _sat_widths_from_state(None) should be empty dict")
        ok = False

    if ok:
        print("  ✓ saved widths applied to column defs; columns_state extraction "
              "skips hidden/null and coerces to int")
    return ok


if __name__ == "__main__":
    print("=== Fix 1: banner text ===")
    try:
        f1 = test_banner_text()
    except Exception:
        import traceback
        traceback.print_exc()
        f1 = False

    print("\n=== Fix 2: filter/sort/menu icon suppression ===")
    f2 = test_icon_suppression()

    print("\n=== Fix 3: column-width persistence ===")
    f3 = test_width_persistence()

    print("\n=== RESULT ===")
    print(f"  (1) banner text:            {'PASS' if f1 else 'FAIL'}")
    print(f"  (2) icon suppression:       {'PASS' if f2 else 'FAIL'}")
    print(f"  (3) width persistence:      {'PASS' if f3 else 'FAIL'}")
    sys.exit(0 if (f1 and f2 and f3) else 1)
