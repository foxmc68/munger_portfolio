"""Smoke test for the Bull/Bear Debate prompt system.

(1) The LIVE DASHBOARD DATA block is built and injected for V and WTKWY.
(2) The BV path generates a conduct risk assessment, not a bull/bear debate.
(3) The full app runs under AppTest with no exceptions.
"""
import sys

import munger_portfolio_app as app


def _row(ticker, name, pe_label="P/E", is_bv=False, **over):
    """Minimal AgGrid-style row dict (formatted strings + hidden fields)."""
    base = {
        "Ticker": ticker, "_name": name, "_pe_label": pe_label, "_is_bv": is_bv,
        "Price": "$320.62", "Current P/E": 28.4, "Dream P/E": 15, "Fair P/E": 20,
        "Fair$": "$230.00", "Dream$": "$172.00", "Discount": "-36%",
        "Signal": "WAIT", "SMS": 26, "R": "R1", "ROIC": "19.2%", "FCFy": "3.5%",
        "RevGr": "17.1%", "GM": "98%", "Ins%": "0.1%", "D/E": "0.67",
        "Quality": "PASS", "Red Flags": "NO", "Slot Status": "○ Watching — Slot Open",
        "Notes": "x", "_notes_full": "Greatest legal monopoly. Buy at Fair.",
        "_fcfy_raw": 3.5,
    }
    base.update(over)
    return base


def _data_from_row(row):
    """Mirror _open_debate_from_row's data-dict assembly (without the dialog)."""
    def _num(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    def _clean(v):
        if v is None:
            return "—"
        return str(v).replace(" ⚠", "").replace("ᵉ", "").strip() or "—"
    ticker = row.get("Ticker", "")
    return {
        "ticker": ticker, "name": row.get("_name") or ticker,
        "tier": app._debate_tier(ticker),
        "slot_status": _clean(row.get("Slot Status", "—")),
        "signal": row.get("Signal", "WAIT"), "price": _clean(row.get("Price")),
        "current_pe": f"{_num(row.get('Current P/E')):.2f}",
        "dream_pe": _clean(row.get("Dream P/E")), "fair_pe": _clean(row.get("Fair P/E")),
        "fair_dollar": _clean(row.get("Fair$")), "dream_dollar": _clean(row.get("Dream$")),
        "discount": _clean(row.get("Discount")), "sms": _clean(row.get("SMS")),
        "r": _clean(row.get("R")), "roic": _clean(row.get("ROIC")),
        "fcfy": _clean(row.get("FCFy")), "revgr": _clean(row.get("RevGr")),
        "gm": _clean(row.get("GM")), "ins": _clean(row.get("Ins%")),
        "de": _clean(row.get("D/E")), "quality": _clean(row.get("Quality")),
        "red_flags": _clean(row.get("Red Flags")),
        "k_notes": row.get("_notes_full") or _clean(row.get("Notes", "")),
        "pe_label": row.get("_pe_label", "P/E"),
        "is_bv": bool(row.get("_is_bv")) or ticker == "BV",
        "fcfy_raw": row.get("_fcfy_raw"),
    }


def test_data_block():
    ok = True
    for tk, name, tier in [("V", "Visa", "Tier 1 Pure Toll"),
                           ("WTKWY", "Wolters Kluwer", "Tier 2 Embedded Infrastructure")]:
        data = _data_from_row(_row(tk, name))
        block = app._build_data_block(data)
        sys_p, user_p = app._build_debate_user_prompt(data)
        checks = {
            "header present": "LIVE DASHBOARD DATA (use these figures" in block,
            "ticker line": f"Ticker: {tk}" in block,
            "company name": f"Company Name: {name}" in block,
            "tier correct": f"Tier: {tier}" in block,
            "all metrics": all(k in block for k in
                               ["Price:", "Current P/E:", "Dream P/E:", "Fair P/E:",
                                "Fair$:", "Dream$:", "Discount:", "Signal:", "SMS:",
                                "R:", "ROIC:", "FCFy:", "RevGr:", "GM:", "Ins%:",
                                "D/E:", "Quality:", "Red Flags:", "Slot Status:",
                                "K's Notes:"]),
            "do-not-substitute instruction": "do not substitute training data" in block,
            "block injected into prompt": "LIVE DASHBOARD DATA" in user_p,
            "gate table present": "| Gate | Threshold | Current | Pass? |" in user_p,
            "no 'Munger would'": "Munger would" not in user_p and "Would Munger" not in user_p,
            "Munger framework framing": "Applying Munger's framework" in user_p,
            "R defs hard-coded": "rate beneficiary" in sys_p and "rate sensitive" in sys_p,
            "tiered FCF gate": "Tier 1 Pure Toll quality gate: FCFy 3.0-3.5%" in sys_p,
            "signal restated": "**WAIT**" in user_p,
        }
        bad = [k for k, v in checks.items() if not v]
        print(f"[{tk}] tier={data['tier']}  {'✓' if not bad else '✗ FAIL: ' + str(bad)}")
        if bad:
            ok = False
    return ok


def test_bv_path():
    data = _data_from_row(_row("BV", "BV", is_bv=True,
                               Signal="WAIT", SMS=20, FCFy="-3.6%",
                               Slot_Status="○ Watch ⚠",
                               **{"_notes_full": "Ethics investigation — CEO refused to disclose. Off limits until resolved."}))
    sys_p, user_p = app._build_debate_user_prompt(data)
    checks = {
        "uses BV system prompt": "conduct risk assessment" in sys_p,
        "top off-limits instruction": "currently off limits due to an active ethics" in user_p,
        "no standard bull/bear sections": "## 1. BULL CASE" not in user_p and "BEAR CASE" not in user_p,
        "section 1 off limits": "## 1. Why BV Is Off Limits" in user_p,
        "section 2 resolution": "## 2. What Resolution Would Look Like" in user_p,
        "section 3 rank preserved": "## 3. Analytical Rank Preserved" in user_p,
        "section 4 re-entry": "## 4. Conditions For Re-Entry Analysis" in user_p,
        "data block present": "LIVE DASHBOARD DATA" in user_p,
        "rank #10 referenced": "#10" in user_p,
    }
    bad = [k for k, v in checks.items() if not v]
    print(f"[BV] {'✓' if not bad else '✗ FAIL: ' + str(bad)}")
    return not bad


def test_apptest():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("munger_portfolio_app.py", default_timeout=200)
    at.run()
    if at.exception:
        print("  ✗ AppTest exceptions:", at.exception)
        return False
    print("  ✓ AppTest ran cleanly")
    return True


if __name__ == "__main__":
    print("=== Test 1: data block for V and WTKWY ===")
    t1 = test_data_block()
    print("\n=== Test 2: BV conduct-assessment path ===")
    t2 = test_bv_path()
    print("\n=== Test 3: AppTest ===")
    try:
        t3 = test_apptest()
    except Exception as e:
        import traceback
        traceback.print_exc()
        t3 = False
    print("\n=== RESULT ===")
    print(f"  data block (V, WTKWY): {'PASS' if t1 else 'FAIL'}")
    print(f"  BV conduct path:       {'PASS' if t2 else 'FAIL'}")
    print(f"  AppTest no exceptions: {'PASS' if t3 else 'FAIL'}")
    sys.exit(0 if (t1 and t2 and t3) else 1)
