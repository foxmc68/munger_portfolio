"""
Munger Toll Bridge Portfolio Monitor
=====================================
Streamlit dashboard for quality stocks across two portfolios.
Valuation signals (DREAM / FAIR / WAIT) based on trailing P/E (or P/B for BRK.B)
and a four-factor quality gate.  Red flags are persisted in red_flags.json /
red_flags_b.json.

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

RED_FLAGS_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags.json")
RED_FLAGS_FILE_B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags_b.json")

FLAG_NAMES = [
    "Accounting Issues",
    "Mgmt Turnover",
    "Regulatory Threat",
    "Moat Deteriorating",
]

# ── Portfolio A definition ────────────────────────────────────────────────────

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

# ── Portfolio B definition (per-ticker Munger-style Fair P/E) ─────────────────
# Rationale for each fair P/E:
#   NEE  22 – regulated utility + renewables growth, premium to plain utilities
#   PGR  18 – superior underwriting discipline, best-in-class insurer
#   PG   24 – wide-moat consumer staples, durable pricing power
#   KMI  16 – midstream infrastructure, stable contracted cash flows
#   KMB  20 – global consumer staples, strong dividend history
#   KO   24 – iconic brand moat, Munger/Buffett cornerstone holding
#   PLD  28 – premier industrial REIT, logistics demand tailwind
#   TXN  22 – analog semiconductor leader, high-margin capital-light model
#   XOM  14 – integrated oil major, cyclical commodity business
#   BLK  20 – dominant asset manager, fee-based durable moat
#   BIP  18 – global infrastructure with long-dated contracted revenues
#   CHD  26 – consumer staples compounder, consistent execution
#   CB   15 – disciplined insurer, underwriting excellence over decades
#   ABBV 16 – pharma with near-term patent risk offset by strong pipeline
#   AVGO 25 – semiconductor/software hybrid, dominant switching-cost moat
#   CL   24 – global consumer staples, emerging-market distribution moat
#   FCX  14 – premier copper miner, cyclical commodity; discounted for cycle
#   JNJ  17 – healthcare conglomerate, steady multi-decade compounder
#   ITW  24 – diversified industrials, 80/20 execution and high ROIC
#   EOG  14 – best-in-class E&P, capital discipline, low breakeven costs
#   EMR  20 – automation-focused industrial compounder, recurring software

PORTFOLIO_B_TICKERS: dict[str, float] = {
    "NEE":  22.0,
    "PGR":  18.0,
    "PG":   24.0,
    "KMI":  16.0,
    "KMB":  20.0,
    "KO":   24.0,
    "PLD":  28.0,
    "TXN":  22.0,
    "XOM":  14.0,
    "BLK":  20.0,
    "BIP":  18.0,
    "CHD":  26.0,
    "CB":   15.0,
    "ABBV": 16.0,
    "AVGO": 25.0,
    "CL":   24.0,
    "FCX":  14.0,
    "JNJ":  17.0,
    "ITW":  24.0,
    "EOG":  14.0,
    "EMR":  20.0,
}

ALL_TICKERS_B: list[str] = list(PORTFOLIO_B_TICKERS.keys())

# Special valuation / debt rules (applies across both portfolios)
USES_PB: set[str] = {"BRK-B"}
FAIR_PB: dict[str, float] = {"BRK-B": 1.35}

# Skip ROE gate; use D/E ≤ 1.5 threshold
BANKS: set[str] = {"JPM", "WFC", "SCHW", "PGR", "CB", "BLK"}

# Higher D/E tolerance ≤ 2.5
MLPS: set[str] = {"EPD", "KMI", "BIP", "PLD"}

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

_TICKER_META_B: dict[str, dict] = {}
for _rank, (_tk, _fair_pe) in enumerate(PORTFOLIO_B_TICKERS.items(), start=1):
    _TICKER_META_B[_tk] = {
        "tier": "Portfolio B",
        "rank": _rank,
        "base_fair": _fair_pe,
    }


def de_threshold(ticker: str) -> float:
    if ticker in BANKS:
        return 1.5
    if ticker in MLPS:
        return 2.5
    return 0.5


# ── Red-flag persistence ──────────────────────────────────────────────────────

def _default_flags(tickers: list[str]) -> dict:
    return {t: {f: False for f in FLAG_NAMES} for t in tickers}


def _load_flags(filepath: str, tickers: list[str]) -> dict:
    base = _default_flags(tickers)
    if os.path.exists(filepath):
        try:
            with open(filepath) as fh:
                stored: dict = json.load(fh)
            for tk in tickers:
                if tk not in stored:
                    stored[tk] = base[tk]
                else:
                    for fl in FLAG_NAMES:
                        stored[tk].setdefault(fl, False)
            return stored
        except Exception:
            pass
    _save_flags(filepath, base)
    return base


def _save_flags(filepath: str, flags: dict) -> None:
    with open(filepath, "w") as fh:
        json.dump(flags, fh, indent=2)


def load_red_flags() -> dict:
    return _load_flags(RED_FLAGS_FILE, ALL_TICKERS)

def save_red_flags(flags: dict) -> None:
    _save_flags(RED_FLAGS_FILE, flags)

def load_red_flags_b() -> dict:
    return _load_flags(RED_FLAGS_FILE_B, ALL_TICKERS_B)

def save_red_flags_b(flags: dict) -> None:
    _save_flags(RED_FLAGS_FILE_B, flags)


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
    ticker_meta: dict,
) -> dict:
    meta = ticker_meta[ticker]
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
        book_a = _pos_float(info, "bookValue")
        if book_a and price and price > 0:
            current_multiple: Optional[float] = price / (book_a / 1500)
        else:
            current_multiple = None
        metric_label = "P/B"
        bvps_b = (book_a / 1500) if book_a else None
        fair_price: Optional[float] = bvps_b * fair_multiple if bvps_b else None
        dream_price: Optional[float] = bvps_b * dream_multiple if bvps_b else None
    else:
        current_multiple = _float(info, "trailingPE")
        metric_label = "P/E"
        eps = _float(info, "trailingEps")
        fair_price = eps * fair_multiple if eps is not None else None
        dream_price = eps * dream_multiple if eps is not None else None

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

    roe_raw = _float(info, "returnOnEquity")
    roic: Optional[float] = roe_raw * 100.0 if roe_raw is not None else None

    fcf = _float(info, "freeCashflow")
    mktcap = _float(info, "marketCap")
    fcfy: Optional[float] = (fcf / mktcap * 100.0) if (fcf and mktcap and mktcap > 0) else None

    rev_growth_raw = _float(info, "revenueGrowth")
    rev_growth: Optional[float] = rev_growth_raw * 100.0 if rev_growth_raw is not None else None

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
        "Fair Price": fair_price,
        "Dream Price": dream_price,
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
            "Fair Price $": fmt_price(r["Fair Price"]),
            "Dream Price $": fmt_price(r["Dream Price"]),
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


# ── Shared display helper ─────────────────────────────────────────────────────

DISPLAY_COLS = [
    "Ticker", "#", "Price", "Metric", "Current", "Fair", "Dream",
    "Fair Price $", "Dream Price $",
    "Discount", "Signal", "ROE%*", "FCFy%", "RevGr%", "D/E",
    "Quality", "Fail Reasons", "Red Flags", "Active Flags", "Decision",
]


def render_summary_metrics(df_raw: pd.DataFrame, watchlist_size: int) -> None:
    n_dream = (df_raw["Signal"] == "DREAM").sum()
    n_fair  = (df_raw["Signal"] == "FAIR").sum()
    n_wait  = (df_raw["Signal"] == "WAIT").sum()
    n_buy   = (df_raw["Decision"] == "BUY").sum()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("DREAM", n_dream, delta_color="off")
    c2.metric("FAIR",  n_fair,  delta_color="off")
    c3.metric("WAIT",  n_wait,  delta_color="off")
    c4.metric("BUY Signals", n_buy, delta_color="off")
    c5.metric("Watchlist Size", watchlist_size, delta_color="off")


def render_table(df_display: pd.DataFrame, df_raw: pd.DataFrame, tier_name: str, mos_pct: float) -> None:
    tier_mask = df_display["Tier"] == tier_name
    tier_disp = df_display[tier_mask][DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
    signals = tier_disp["_signal"]
    tier_disp = tier_disp[DISPLAY_COLS].copy()

    n_tier_buy = (df_raw[df_raw["Tier"] == tier_name]["Decision"] == "BUY").sum()

    # Build subheader — include Fair/Dream only for tiered portfolios
    raw_tier = df_raw[df_raw["Tier"] == tier_name]
    if not raw_tier.empty:
        tier_fair = raw_tier.iloc[0]["Fair"]
        tier_dream = tier_fair * (1.0 - mos_pct / 100.0)
        st.subheader(
            f"{tier_name}  ·  Fair {tier_fair:.0f}x  ·  Dream {tier_dream:.1f}x  "
            f"·  BUY signals: {n_tier_buy}"
        )
    else:
        st.subheader(f"{tier_name}  ·  BUY signals: {n_tier_buy}")

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
        ".stTabs [data-baseweb='tab-list']{gap:6px;border-bottom:2px solid #8a8b8d}"
        ".stTabs [data-baseweb='tab']{font-size:1.15rem;font-weight:700;padding:10px 28px;border-radius:8px 8px 0 0;color:#555555;background-color:#b0b1b3;border:none;letter-spacing:0.02em}"
        ".stTabs [data-baseweb='tab']:hover{background-color:#9a9b9d;color:#333333}"
        ".stTabs [data-baseweb='tab'][aria-selected='true']{background-color:#5a7f6a !important;color:#ffffff !important;border-bottom:3px solid #5a7f6a}"
        ".stTabs [data-baseweb='tab-highlight']{display:none}"
        "[data-testid='stSidebarContent'] .block-container{padding-top:0.5rem}"
        "[data-testid='stSidebar'] hr{margin:0.4rem 0}"
        "[data-testid='stSidebar'] .stSlider{padding-top:0;margin-top:0}"
        "[data-testid='stSidebar'] .stExpander{margin-bottom:2px}"
        "</style>",
        unsafe_allow_html=True,
    )

    # ── Session state ─────────────────────────────────────────────────────────
    if "red_flags" not in st.session_state:
        st.session_state.red_flags = load_red_flags()
    if "red_flags_b" not in st.session_state:
        st.session_state.red_flags_b = load_red_flags_b()
    if "raw_rows" not in st.session_state:
        st.session_state.raw_rows = None
    if "raw_rows_b" not in st.session_state:
        st.session_state.raw_rows_b = None
    if "last_fetched" not in st.session_state:
        st.session_state.last_fetched = None
    if "last_fetched_b" not in st.session_state:
        st.session_state.last_fetched_b = None

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            "<p style='font-size:1.1rem;font-weight:700;margin:0 0 4px 0;color:#333'>Controls</p>",
            unsafe_allow_html=True,
        )
        st.divider()
        mos_pct = st.slider(
            "Dream Margin of Safety %",
            min_value=10, max_value=50, value=DEFAULT_MOS_PCT, step=5,
            help="Dream threshold = Fair multiple × (1 − MoS%)  —  applies to both portfolios",
        )

        # ── Portfolio A sidebar ───────────────────────────────────────────────
        st.markdown(
            "<div style='background:#5a7f6a;color:#fff;padding:4px 10px;border-radius:4px;"
            "font-weight:700;font-size:0.85rem;margin:8px 0 4px 0'>── Portfolio A ──</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='font-size:0.8rem;font-weight:600;color:#444;margin:2px 0'>Fair Multiple Overrides</p>",
            unsafe_allow_html=True,
        )

        fair_overrides: dict[str, Optional[float]] = {}
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
                    fair_overrides[tk] = val if val != default_val else None

        st.markdown(
            "<p style='font-size:0.8rem;font-weight:600;color:#444;margin:6px 0 2px 0'>Red Flags</p>",
            unsafe_allow_html=True,
        )

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

        # ── Portfolio B sidebar ───────────────────────────────────────────────
        st.markdown(
            "<div style='background:#5a7f6a;color:#fff;padding:4px 10px;border-radius:4px;"
            "font-weight:700;font-size:0.85rem;margin:10px 0 4px 0'>── Portfolio B ──</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='font-size:0.8rem;font-weight:600;color:#444;margin:2px 0'>Fair P/E Overrides</p>",
            unsafe_allow_html=True,
        )

        fair_overrides_b: dict[str, Optional[float]] = {}
        with st.expander("All tickers", expanded=False):
            for tk, default_pe in PORTFOLIO_B_TICKERS.items():
                val = st.number_input(
                    f"{tk}  (P/E)",
                    min_value=0.1, max_value=200.0,
                    value=float(default_pe), step=0.5,
                    key=f"ov_b_{tk}",
                )
                fair_overrides_b[tk] = val if val != default_pe else None

        st.markdown(
            "<p style='font-size:0.8rem;font-weight:600;color:#444;margin:6px 0 2px 0'>Red Flags</p>",
            unsafe_allow_html=True,
        )

        flags_b_changed = False
        with st.expander("All tickers", expanded=False):
            for tk in ALL_TICKERS_B:
                st.markdown(f"**{tk}**")
                for fl in FLAG_NAMES:
                    cur = st.session_state.red_flags_b.get(tk, {}).get(fl, False)
                    new = st.checkbox(fl, value=cur, key=f"rf_b_{tk}_{fl}")
                    if new != cur:
                        st.session_state.red_flags_b[tk][fl] = new
                        flags_b_changed = True

        if flags_b_changed:
            save_red_flags_b(st.session_state.red_flags_b)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Munger Toll Bridge Portfolio")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_a, tab_b = st.tabs(["Portfolio A", "Portfolio B"])

    # ══════════════════════════════════════════════════════════════════════════
    # PORTFOLIO A
    # ══════════════════════════════════════════════════════════════════════════
    with tab_a:
        col_refresh_a, col_ts_a = st.columns([1, 4])
        with col_refresh_a:
            if st.button("Refresh Data", key="refresh_a", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.raw_rows = None

        if st.session_state.raw_rows is None:
            progress = st.progress(0, text="Fetching market data…")
            raw_rows: list[dict] = []
            for i, tk in enumerate(ALL_TICKERS):
                override = fair_overrides.get(tk)
                raw_rows.append(
                    compute_row(tk, override, mos_pct, st.session_state.red_flags, _TICKER_META)
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
        with col_ts_a:
            st.caption(
                f"Last fetched: **{fetched_str}**  ·  "
                f"Data: Yahoo Finance (yfinance)"
            )

        df_raw = pd.DataFrame(raw_rows)
        df_display = build_display_df(raw_rows)

        render_summary_metrics(df_raw, len(ALL_TICKERS))
        st.divider()

        for tier_name in PORTFOLIO:
            render_table(df_display, df_raw, tier_name, mos_pct)

        st.divider()
        csv_bytes = df_display[["Tier"] + DISPLAY_COLS].to_csv(index=False).encode()
        st.download_button(
            label="Download Portfolio A as CSV",
            data=csv_bytes,
            file_name=f"portfolio_a_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

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
""")

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

    # ══════════════════════════════════════════════════════════════════════════
    # PORTFOLIO B
    # ══════════════════════════════════════════════════════════════════════════
    with tab_b:
        col_refresh_b, col_ts_b = st.columns([1, 4])
        with col_refresh_b:
            if st.button("Refresh Data", key="refresh_b", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.raw_rows_b = None

        if st.session_state.raw_rows_b is None:
            progress_b = st.progress(0, text="Fetching market data…")
            raw_rows_b: list[dict] = []
            for i, tk in enumerate(ALL_TICKERS_B):
                override = fair_overrides_b.get(tk)
                raw_rows_b.append(
                    compute_row(tk, override, mos_pct, st.session_state.red_flags_b, _TICKER_META_B)
                )
                progress_b.progress((i + 1) / len(ALL_TICKERS_B), text=f"Fetching {tk}…")
            progress_b.empty()
            st.session_state.raw_rows_b = raw_rows_b
            st.session_state.last_fetched_b = datetime.now()

        raw_rows_b = st.session_state.raw_rows_b

        fetched_str_b = (
            st.session_state.last_fetched_b.strftime("%Y-%m-%d  %H:%M:%S")
            if st.session_state.last_fetched_b else "—"
        )
        with col_ts_b:
            st.caption(
                f"Last fetched: **{fetched_str_b}**  ·  "
                f"Data: Yahoo Finance (yfinance)"
            )

        df_raw_b = pd.DataFrame(raw_rows_b)
        df_display_b = build_display_df(raw_rows_b)

        render_summary_metrics(df_raw_b, len(ALL_TICKERS_B))
        st.divider()

        # Portfolio B is a single group — render one table
        tier_disp_b = df_display_b[DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
        signals_b = tier_disp_b["_signal"]
        tier_disp_b = tier_disp_b[DISPLAY_COLS].copy()
        n_buy_b = (df_raw_b["Decision"] == "BUY").sum()

        st.subheader(
            f"Portfolio B  ·  Per-ticker Fair P/E  ·  "
            f"MoS {mos_pct}%  ·  BUY signals: {n_buy_b}"
        )

        styled_b = _style_df(tier_disp_b, signals_b)
        st.dataframe(
            styled_b,
            use_container_width=True,
            hide_index=True,
            column_config={
                "#":            st.column_config.NumberColumn("#", width="small"),
                "Signal":       st.column_config.TextColumn("Signal", width="small"),
                "Decision":     st.column_config.TextColumn("Decision", width="small"),
                "Fail Reasons": st.column_config.TextColumn("Fail Reasons", width="large"),
            },
        )

        st.divider()
        csv_bytes_b = df_display_b[DISPLAY_COLS].to_csv(index=False).encode()
        st.download_button(
            label="Download Portfolio B as CSV",
            data=csv_bytes_b,
            file_name=f"portfolio_b_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        with st.expander("Fair P/E Rationale (Portfolio B)", expanded=False):
            st.markdown("""
| Ticker | Fair P/E | Reasoning |
|---|---|---|
| NEE | 22 | Regulated utility + renewables growth; premium to plain utilities |
| PGR | 18 | Superior underwriting discipline, best-in-class combined ratio |
| PG | 24 | Wide-moat consumer staples, durable global pricing power |
| KMI | 16 | Midstream infrastructure, stable fee-based contracted cash flows |
| KMB | 20 | Global consumer staples, consistent dividend compounder |
| KO | 24 | Iconic brand moat, Munger/Buffett cornerstone holding |
| PLD | 28 | Premier industrial REIT, secular logistics demand tailwind |
| TXN | 22 | Analog semiconductor leader, high-margin capital-light model |
| XOM | 14 | Integrated oil major, cyclical commodity; discounted accordingly |
| BLK | 20 | Dominant asset manager, fee-based durable business |
| BIP | 18 | Global infrastructure with long-dated contracted revenues |
| CHD | 26 | Consumer staples compounder, consistent execution record |
| CB | 15 | Disciplined insurer with decades of underwriting excellence |
| ABBV | 16 | Pharma with near-term patent risk, offset by strong pipeline |
| AVGO | 25 | Semiconductor/software hybrid with dominant switching-cost moat |
| CL | 24 | Global consumer staples, emerging-market distribution reach |
| FCX | 14 | Premier copper producer, cyclical commodity; cycle discount |
| JNJ | 17 | Healthcare conglomerate, steady multi-decade compounder |
| ITW | 24 | Diversified industrials, 80/20 execution and elite ROIC |
| EOG | 14 | Best-in-class E&P, capital discipline, low breakeven oil price |
| EMR | 20 | Automation-focused industrial compounder, growing software mix |

**BUY = Signal (DREAM or FAIR) AND Quality PASS AND no Red Flags active.**
Financial companies (PGR, CB, BLK): ROE gate skipped; D/E threshold ≤ 1.5×.
Infrastructure/MLP names (KMI, BIP, PLD): D/E threshold ≤ 2.5×.
""")

        with st.expander("Valuation Key", expanded=False):
            st.markdown(f"""
| Signal | Condition |
|---|---|
| **DREAM** | Current P/E ≤ Fair P/E × (1 − {mos_pct}%) |
| **FAIR**  | Current P/E ≤ Fair P/E |
| **WAIT**  | Current P/E > Fair P/E |

- P/E uses `trailingPE` from yfinance (true trailing 12-month, not forward).
- Each ticker in Portfolio B has its own Munger-style Fair P/E (see table above).
- Override any fair P/E in the sidebar under **Portfolio B**.
""")

        st.caption("Data: Yahoo Finance via yfinance.  Not financial advice.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
