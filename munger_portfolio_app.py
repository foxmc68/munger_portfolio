"""
Munger Toll Bridge Portfolio Monitor
=====================================
Streamlit dashboard for 28 quality stocks across three tiers.
Valuation signals (DREAM / FAIR / WAIT) based on trailing P/E (or P/B for BRK.B)
and a four-factor quality gate.  Red flags are persisted in red_flags.json.

Run:  streamlit run munger_portfolio_app.py
Data: Yahoo Finance via yfinance — no API key required.
"""

import json
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────

RED_FLAGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags.json")

FLAG_NAMES = [
    "Accounting Issues",
    "Mgmt Turnover",
    "Regulatory Threat",
    "Moat Deteriorating",
]

# ── Portfolio definition ───────────────────────────────────────────────────────

PORTFOLIO: dict[str, dict] = {
    "Tier 1": {
        "tickers": ["V", "MCO", "SPGI", "MSFT", "GOOGL", "COST", "RMS.PA", "ASML", "RMBS"],
        "fair_pe": 25,
    },
    "Tier 2": {
        "tickers": [
            "ADP", "FICO", "AXP", "BRK-B", "CME", "DHR",
            "IDXX", "ODFL", "VRSN", "CNI", "BAM", "WM", "AZO",
        ],
        "fair_pe": 20,
    },
    "Tier 3": {
        "tickers": ["JPM", "WFC", "SCHW", "CVX", "COP", "EPD", "ASR"],
        "fair_pe": 16,
    },
}

ALL_TICKERS: list[str] = [t for td in PORTFOLIO.values() for t in td["tickers"]]

# Special valuation / debt rules
USES_PB: set[str] = {"BRK-B"}
FAIR_PB: dict[str, float] = {"BRK-B": 1.35}
BANKS: set[str] = {"JPM", "WFC", "SCHW"}   # skip ROIC; D/E ≤ 1.5
MLPS: set[str] = {"EPD"}                    # D/E ≤ 2.5
# all others: D/E ≤ 0.5

DEFAULT_MOS_PCT = 30

# ── Tier / rank lookup (built once) ──────────────────────────────────────────

_TICKER_META: dict[str, dict] = {}
for _tier, _td in PORTFOLIO.items():
    for _rank, _tk in enumerate(_td["tickers"], start=1):
        _TICKER_META[_tk] = {
            "tier": _tier,
            "rank": _rank,
            "base_fair": FAIR_PB.get(_tk, _td["fair_pe"]),
        }


def de_threshold(ticker: str) -> float:
    if ticker in BANKS:
        return 1.5
    if ticker in MLPS:
        return 2.5
    return 0.5


# ── Red-flag persistence ──────────────────────────────────────────────────────

def _default_flags() -> dict:
    return {t: {f: False for f in FLAG_NAMES} for t in ALL_TICKERS}


def load_red_flags() -> dict:
    base = _default_flags()
    if os.path.exists(RED_FLAGS_FILE):
        try:
            with open(RED_FLAGS_FILE) as fh:
                stored: dict = json.load(fh)
            for tk in ALL_TICKERS:
                if tk not in stored:
                    stored[tk] = base[tk]
                else:
                    for fl in FLAG_NAMES:
                        stored[tk].setdefault(fl, False)
            return stored
        except Exception:
            pass
    save_red_flags(base)
    return base


def save_red_flags(flags: dict) -> None:
    with open(RED_FLAGS_FILE, "w") as fh:
        json.dump(flags, fh, indent=2)


# ── yfinance data layer ───────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def fetch_info(ticker: str) -> dict:
    """
    Fetch the full yfinance .info dict for a ticker.
    Cached indefinitely — cleared only by the Refresh button.
    """
    try:
        data = yf.Ticker(ticker).info
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ── Core computation ──────────────────────────────────────────────────────────

def _float(info: dict, key: str) -> Optional[float]:
    """Safe float extraction from an info dict."""
    v = info.get(key)
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _pos_float(info: dict, key: str) -> Optional[float]:
    """Like _float but returns None for zero or negative values."""
    v = _float(info, key)
    return v if (v is not None and v > 0) else None


def compute_row(
    ticker: str,
    fair_override: Optional[float],
    mos_pct: float,
    red_flags: dict,
) -> dict:
    meta = _TICKER_META[ticker]
    fair_multiple = fair_override if fair_override is not None else meta["base_fair"]
    dream_multiple = fair_multiple * (1.0 - mos_pct / 100.0)

    info = fetch_info(ticker)

    # ── Price ────────────────────────────────────────────────────────────────
    price: Optional[float] = (
        _float(info, "currentPrice") or _float(info, "regularMarketPrice")
    )

    # ── Valuation multiple ───────────────────────────────────────────────────
    if ticker in USES_PB:
        # BRK-B: yfinance stores bookValue as the Class-A equivalent (~$498k).
        # Each B share is economically 1/1500th of an A share, so the correct
        # B-share book value per share is bookValue / 1500.
        # priceToBook from yfinance divides B-share price by the raw A-share
        # book value, producing ~0.001 — useless.  We always compute manually.
        book_a = _pos_float(info, "bookValue")   # Class A book value per share
        if book_a and price and price > 0:
            current_multiple: Optional[float] = price / (book_a / 1500)
        else:
            current_multiple = None
        metric_label = "P/B"
    else:
        # True trailing P/E from yfinance (calculated from trailing 12-month EPS)
        current_multiple = _float(info, "trailingPE")
        metric_label = "P/E"

    # ── Valuation signal ─────────────────────────────────────────────────────
    if current_multiple and current_multiple > 0:
        discount_pct: Optional[float] = (1.0 - current_multiple / fair_multiple) * 100.0
        if current_multiple <= dream_multiple:
            signal = "DREAM"
        elif current_multiple <= fair_multiple:
            signal = "FAIR"
        else:
            signal = "WAIT"
    else:
        signal = "N/A"
        discount_pct = None

    # ── Quality metrics ──────────────────────────────────────────────────────

    # ROIC proxy: yfinance does not expose ROIC directly; returnOnEquity (ROE)
    # is used as a proxy.  Values are decimals (0.35 = 35 %) — convert to %.
    roe_raw = _float(info, "returnOnEquity")
    roic: Optional[float] = roe_raw * 100.0 if roe_raw is not None else None

    # FCF yield = freeCashflow / marketCap
    fcf = _float(info, "freeCashflow")
    mktcap = _float(info, "marketCap")
    fcfy: Optional[float] = (fcf / mktcap * 100.0) if (fcf and mktcap and mktcap > 0) else None

    # Revenue growth: yfinance returns as decimal (0.08 = 8 %) — convert to %
    rev_growth_raw = _float(info, "revenueGrowth")
    rev_growth: Optional[float] = rev_growth_raw * 100.0 if rev_growth_raw is not None else None

    # D/E ratio: yfinance returns as a percentage (50.0 = 0.5×) — divide by 100
    de_raw = _float(info, "debtToEquity")
    de_ratio: Optional[float] = de_raw / 100.0 if de_raw is not None else None
    de_limit = de_threshold(ticker)

    # ── Quality gate ─────────────────────────────────────────────────────────
    fails: list[str] = []

    if ticker not in BANKS:
        if roic is None:
            fails.append("ROE N/A")
        elif roic < 15.0:
            fails.append(f"ROE {roic:.1f}% < 15%")

    if fcfy is None:
        fails.append("FCFy N/A")
    elif fcfy < 3.5:
        fails.append(f"FCFy {fcfy:.1f}% < 3.5%")

    if rev_growth is None:
        fails.append("RevGr N/A")
    elif rev_growth < 0.0:
        fails.append(f"RevGr {rev_growth:.1f}% < 0%")

    if de_ratio is None:
        fails.append("D/E N/A")
    elif de_ratio > de_limit:
        fails.append(f"D/E {de_ratio:.2f} > {de_limit}")

    quality = "PASS" if not fails else "FAIL"

    # ── Red flags ────────────────────────────────────────────────────────────
    ticker_flags: dict = red_flags.get(ticker, {})
    active_flags = [f for f, v in ticker_flags.items() if v]
    has_red_flag = bool(active_flags)

    # ── Final decision ───────────────────────────────────────────────────────
    buy = (signal in ("DREAM", "FAIR")) and (quality == "PASS") and (not has_red_flag)

    return {
        "Ticker": ticker,
        "Tier": meta["tier"],
        "Rank": meta["rank"],
        "Price": price,
        "Metric": metric_label,
        "Current": current_multiple,
        "Fair": fair_multiple,
        "Dream": dream_multiple,
        "Discount%": discount_pct,
        "Signal": signal,
        "ROE%": roic,
        "FCFy%": fcfy,
        "RevGr%": rev_growth,
        "D/E": de_ratio,
        "D/E Lim": de_limit,
        "Quality": quality,
        "Fail Reasons": "; ".join(fails) if fails else "",
        "Red Flags": "YES" if has_red_flag else "NO",
        "Active Flags": ", ".join(active_flags) if active_flags else "—",
        "Decision": "BUY" if buy else "WAIT",
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt_price(v: Optional[float]) -> str:
    return f"${v:,.2f}" if v is not None else "—"

def fmt_mult(v: Optional[float]) -> str:
    return f"{v:.2f}" if v is not None else "—"

def fmt_pct(v: Optional[float], plus: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}%" if plus else f"{v:.1f}%"


def build_display_df(rows: list[dict]) -> pd.DataFrame:
    records = []
    for r in rows:
        records.append({
            "Ticker":       r["Ticker"],
            "Tier":         r["Tier"],
            "#":            r["Rank"],
            "Price":        fmt_price(r["Price"]),
            "Metric":       r["Metric"],
            "Current":      fmt_mult(r["Current"]),
            "Fair":         fmt_mult(r["Fair"]),
            "Dream":        fmt_mult(r["Dream"]),
            "Discount":     fmt_pct(r["Discount%"], plus=True),
            "Signal":       r["Signal"],
            "ROE%*":        fmt_pct(r["ROE%"]),
            "FCFy%":        fmt_pct(r["FCFy%"]),
            "RevGr%":       fmt_pct(r["RevGr%"], plus=True),
            "D/E":          fmt_mult(r["D/E"]),
            "Quality":      r["Quality"],
            "Fail Reasons": r["Fail Reasons"],
            "Red Flags":    r["Red Flags"],
            "Active Flags": r["Active Flags"],
            "Decision":     r["Decision"],
            "_signal":      r["Signal"],
        })
    return pd.DataFrame(records)


# ── Row styling ───────────────────────────────────────────────────────────────

_SIGNAL_STYLE: dict[str, str] = {
    # Muted, light-theme-friendly traffic-light palette
    "DREAM": "background-color:#b7d4b0;color:#1a3a1f",   # sage green
    "FAIR":  "background-color:#f0d080;color:#3d2800",   # amber / gold
    "WAIT":  "background-color:#dfa898;color:#3d0f00",   # dusty terracotta
    "N/A":   "background-color:#d0d0d2;color:#555555",   # neutral grey
}


def _style_df(display_df: pd.DataFrame, signal_series: pd.Series) -> object:
    styles = pd.DataFrame("", index=display_df.index, columns=display_df.columns)
    for idx in display_df.index:
        css = _SIGNAL_STYLE.get(signal_series.iloc[idx], "")
        styles.iloc[idx, :] = css
    return display_df.style.apply(lambda _: styles, axis=None)


# ── Streamlit app ─────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Munger Toll Bridge Portfolio",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Light-theme CSS overrides ─────────────────────────────────────────────
    st.markdown(
        "<style>"
        ".stApp,[data-testid='stAppViewContainer']{background-color:#BDBDBF}"
        "[data-testid='stSidebar'],[data-testid='stSidebarContent']{background-color:#CACBCD}"
        "[data-testid='metric-container']{background-color:#c8c9cb;border-radius:6px;padding:8px}"
        "[data-testid='stSidebar'] [data-testid='stExpander'] summary{background-color:#6e9b82;color:#ffffff;border-radius:6px;padding:6px 10px}"
        "[data-testid='stSidebar'] [data-testid='stExpander'] summary:hover{background-color:#5a7f6a}"
        "[data-testid='stSidebar'] [data-testid='stExpander'] summary svg{fill:#ffffff}"
        "</style>",
        unsafe_allow_html=True,
    )

    # ── Session state ─────────────────────────────────────────────────────────
    if "red_flags" not in st.session_state:
        st.session_state.red_flags = load_red_flags()
    if "raw_rows" not in st.session_state:
        st.session_state.raw_rows = None
    if "last_fetched" not in st.session_state:
        st.session_state.last_fetched = None

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("Controls")

        if st.button("Refresh Data", type="primary", use_container_width=True):
            fetch_info.clear()
            st.session_state.raw_rows = None

        st.divider()
        mos_pct = st.slider(
            "Dream Margin of Safety %",
            min_value=10, max_value=50, value=DEFAULT_MOS_PCT, step=5,
            help="Dream threshold = Fair multiple × (1 − MoS%)",
        )

        st.divider()
        st.subheader("Fair Multiple Overrides")
        st.caption("Leave at default to use tier standard. Change to override per-ticker.")

        fair_overrides: dict[str, float] = {}
        for tier_name, td in PORTFOLIO.items():
            with st.expander(tier_name, expanded=False):
                for tk in td["tickers"]:
                    default_val = float(FAIR_PB.get(tk, td["fair_pe"]))
                    label = f"{tk}  ({'P/B' if tk in USES_PB else 'P/E'})"
                    val = st.number_input(
                        label,
                        min_value=0.1, max_value=200.0,
                        value=default_val, step=0.5,
                        key=f"ov_{tk}",
                    )
                    fair_overrides[tk] = val if val != default_val else None  # type: ignore[assignment]

        st.divider()
        st.subheader("Red Flags")
        st.caption("Toggling a flag saves immediately to red_flags.json.")

        flags_changed = False
        for tier_name, td in PORTFOLIO.items():
            with st.expander(tier_name, expanded=False):
                for tk in td["tickers"]:
                    st.markdown(f"**{tk}**")
                    for fl in FLAG_NAMES:
                        cur = st.session_state.red_flags.get(tk, {}).get(fl, False)
                        new = st.checkbox(fl, value=cur, key=f"rf_{tk}_{fl}")
                        if new != cur:
                            st.session_state.red_flags[tk][fl] = new
                            flags_changed = True

        if flags_changed:
            save_red_flags(st.session_state.red_flags)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Munger Toll Bridge Portfolio")

    # ── Fetch & compute (runs on first load and after Refresh button) ─────────
    if st.session_state.raw_rows is None:
        progress = st.progress(0, text="Fetching market data…")
        raw_rows: list[dict] = []
        for i, tk in enumerate(ALL_TICKERS):
            override = fair_overrides.get(tk)
            raw_rows.append(
                compute_row(tk, override, mos_pct, st.session_state.red_flags)
            )
            progress.progress((i + 1) / len(ALL_TICKERS), text=f"Fetching {tk}…")
        progress.empty()
        st.session_state.raw_rows = raw_rows
        st.session_state.last_fetched = datetime.now()

    raw_rows = st.session_state.raw_rows

    fetched_str = (
        st.session_state.last_fetched.strftime("%Y-%m-%d  %H:%M:%S")
        if st.session_state.last_fetched else "—"
    )
    st.caption(
        f"Last fetched: **{fetched_str}**  ·  "
        f"Use **Refresh Data** in the sidebar to reload.  ·  "
        f"Data: Yahoo Finance (yfinance)"
    )

    df_raw = pd.DataFrame(raw_rows)
    df_display = build_display_df(raw_rows)

    # ── Summary counters ──────────────────────────────────────────────────────
    n_dream = (df_raw["Signal"] == "DREAM").sum()
    n_fair  = (df_raw["Signal"] == "FAIR").sum()
    n_wait  = (df_raw["Signal"] == "WAIT").sum()
    n_buy   = (df_raw["Decision"] == "BUY").sum()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("DREAM", n_dream,  delta_color="off")
    c2.metric("FAIR",  n_fair,   delta_color="off")
    c3.metric("WAIT",  n_wait,   delta_color="off")
    c4.metric("BUY Signals", n_buy, delta_color="off")
    c5.metric("Watchlist Size", len(ALL_TICKERS), delta_color="off")

    st.divider()

    # ── Per-tier tables ───────────────────────────────────────────────────────
    display_cols = [
        "Ticker", "#", "Price", "Metric", "Current", "Fair", "Dream",
        "Discount", "Signal", "ROE%*", "FCFy%", "RevGr%", "D/E",
        "Quality", "Fail Reasons", "Red Flags", "Active Flags", "Decision",
    ]

    for tier_name in PORTFOLIO:
        tier_mask = df_display["Tier"] == tier_name
        tier_disp = df_display[tier_mask][display_cols + ["_signal"]].reset_index(drop=True)
        signals = tier_disp["_signal"]
        tier_disp = tier_disp[display_cols].copy()

        tier_fair = PORTFOLIO[tier_name]["fair_pe"]
        tier_dream = tier_fair * (1.0 - mos_pct / 100.0)
        n_tier_buy = (
            df_raw[df_raw["Tier"] == tier_name]["Decision"] == "BUY"
        ).sum()

        st.subheader(
            f"{tier_name}  ·  Fair {tier_fair}x  ·  Dream {tier_dream:.1f}x  "
            f"·  BUY signals: {n_tier_buy}"
        )

        styled = _style_df(tier_disp, signals)
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#":            st.column_config.NumberColumn("#", width="small"),
                "Signal":       st.column_config.TextColumn("Signal", width="small"),
                "Decision":     st.column_config.TextColumn("Decision", width="small"),
                "Fail Reasons": st.column_config.TextColumn("Fail Reasons", width="large"),
            },
        )

    # ── CSV download ──────────────────────────────────────────────────────────
    st.divider()
    csv_df = df_display[["Tier"] + display_cols].copy()
    csv_bytes = csv_df.to_csv(index=False).encode()

    st.download_button(
        label="Download full table as CSV",
        data=csv_bytes,
        file_name=f"munger_portfolio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

    # ── Quality gate key ─────────────────────────────────────────────────────
    with st.expander("Quality Gate Rules", expanded=False):
        st.markdown("""
| Check | Threshold | Exceptions | Source |
|---|---|---|---|
| ROE%\\* | ≥ 15 % | Skipped for banks (JPM, WFC, SCHW) | `returnOnEquity` proxy for ROIC |
| FCF Yield | ≥ 3.5 % | — | `freeCashflow / marketCap` |
| Revenue Growth | ≥ 0 % | — | `revenueGrowth` |
| Debt / Equity | ≤ 0.5× | Banks ≤ 1.5×; EPD ≤ 2.5× | `debtToEquity ÷ 100` |

**BUY = Signal (DREAM or FAIR) AND Quality PASS AND no Red Flags active.**

\\* yfinance does not expose ROIC directly. ROE (`returnOnEquity`) is used as a proxy.
For capital-light businesses with low equity bases the two track closely; for asset-heavy
or leveraged names ROE will overstate true ROIC.
""")

    # ── Valuation key ────────────────────────────────────────────────────────
    with st.expander("Valuation Key", expanded=False):
        st.markdown(f"""
| Signal | Condition |
|---|---|
| **DREAM** | Current multiple ≤ Fair × (1 − {mos_pct}%) |
| **FAIR**  | Current multiple ≤ Fair multiple |
| **WAIT**  | Current multiple > Fair multiple |

- P/E uses `trailingPE` from yfinance (true trailing 12-month, not forward).
- BRK-B uses **P/B** (`priceToBook`), fair P/B = 1.35.
- Fair P/E defaults: Tier 1 = 25, Tier 2 = 20, Tier 3 = 16.
- Override any fair multiple in the sidebar.
""")

    st.caption("Data: Yahoo Finance via yfinance.  Not financial advice.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
