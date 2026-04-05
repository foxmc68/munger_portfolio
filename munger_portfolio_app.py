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

RED_FLAGS_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags.json")
RED_FLAGS_FILE_B  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags_b.json")
CUSTOM_TICKERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_tickers.json")

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
            "IDXX", "VRSN", "CNI", "BAM", "WM", "AZO",
        ],
        "fair_pe": 20,
    },
    "Tier 3": {
        "tickers": ["JPM", "CVX", "COP", "EPD", "ASR", "PM"],
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

# ── Retired stocks ────────────────────────────────────────────────────────────

RETIRED_STOCKS: list[dict] = [
    {
        "ticker": "SCHW",
        "from_portfolio": "A",
        "date_retired": "2026-04-04",
        "removal_reason": "Financial repression victim — net interest income destroyed by compressed real rates",
    },
    {
        "ticker": "WFC",
        "from_portfolio": "A",
        "date_retired": "2026-04-04",
        "removal_reason": "Inferior to JPM in every thesis-relevant dimension — no global diversification",
    },
    {
        "ticker": "ODFL",
        "from_portfolio": "A",
        "date_retired": "2026-04-04",
        "removal_reason": "100% US domestic freight, no currency hedge, no real asset backing — wrong macro fit",
    },
    {
        "ticker": "AMT",
        "from_portfolio": "B",
        "date_retired": "2026-04-04",
        "removal_reason": "ROIC barely clears WACC, $45B debt, REIT P/E distortion — model calibration error",
    },
    {
        "ticker": "TROW",
        "from_portfolio": "B",
        "date_retired": "2026-04-04",
        "removal_reason": "Structurally declining active asset manager — secular erosion from passive indexing",
    },
    {
        "ticker": "PAYX",
        "from_portfolio": "A",
        "date_retired": "2026-04-04",
        "removal_reason": "Redundant to ADP with smaller moat, float income at risk in financial repression",
    },
    {
        "ticker": "SYY",
        "from_portfolio": "B",
        "date_retired": "2026-04-04",
        "removal_reason": "Low-margin US food distribution, no pricing power, no currency hedge",
    },
    {
        "ticker": "HRL",
        "from_portfolio": "B",
        "date_retired": "2026-04-04",
        "removal_reason": "Weakest consumer staples name, minimal international presence, low ROIC",
    },
    {
        "ticker": "PSX",
        "from_portfolio": "A",
        "date_retired": "2026-04-04",
        "removal_reason": "Refining margins volatile and mean-reverting, no durable moat",
    },
    {
        "ticker": "MDT",
        "from_portfolio": "B",
        "date_retired": "2026-04-04",
        "removal_reason": "Serial execution underperformer, pricing pressure, ROIC 8% mediocre for medical devices",
    },
]

ALL_TICKERS_RETIRED: list[str] = [s["ticker"] for s in RETIRED_STOCKS]

# ── Macro Signals configuration ───────────────────────────────────────────────
# Each signal has live-fetch or static-manual data. Direction "above" means
# exceeding the threshold is bad; "below" means falling below is bad.

MACRO_SIGNALS_CONFIG: list[dict] = [
    {
        "id": "treasury_10y",
        "name": "10-yr Treasury Yield",
        "ticker": "^TNX",
        "fetch_live": True,
        "type": "numeric",
        "format": "pct",
        "invert": False,
        "danger": 5.5,
        "crisis": 7.0,
        "direction": "above",
        "action_normal": "BUY — short-duration SGOV safe",
        "action_danger": "CAUTION — bond market stress rising",
        "action_crisis": "AVOID DURATION — fiscal/inflation crisis",
        "frequency": "Daily",
        "description": "High yields = inflation or fiscal stress. SGOV (0-3 mo T-bills) is insulated vs long bonds.",
    },
    {
        "id": "dxy",
        "name": "DXY Dollar Index",
        "ticker": "DX-Y.NYB",
        "fetch_live": True,
        "type": "numeric",
        "format": "number_2dp",
        "invert": False,
        "danger": 98.0,
        "crisis": 90.0,
        "direction": "below",
        "action_normal": "BUY — dollar strength supports SGOV",
        "action_danger": "CAUTION — dollar weakness emerging",
        "action_crisis": "AVOID USD CASH — reserve currency stress",
        "frequency": "Daily",
        "description": "Dollar falling below 98 = foreign selling of US assets. Below 90 = potential reserve-currency crisis.",
    },
    {
        "id": "real_fed_funds",
        "name": "Real Fed Funds Rate",
        "ticker": "^IRX",
        "fetch_live": True,
        "type": "computed_real_rate",
        "format": "pct",
        "invert": False,
        "danger": -1.0,
        "crisis": -3.0,
        "direction": "below",
        "action_normal": "BUY — positive real rates favor cash",
        "action_danger": "CAUTION — financial repression risk",
        "action_crisis": "AVOID SGOV — real return deeply negative",
        "frequency": "Monthly (CPI) / Daily (rate)",
        "description": "Nominal Fed Funds Rate minus CPI. Negative = savers punished. Deep negative = financial repression destroying cash holders.",
    },
    {
        "id": "gold",
        "name": "Gold Price",
        "ticker": "GC=F",
        "fetch_live": True,
        "type": "numeric",
        "format": "price",
        "invert": False,
        "danger": 5000.0,
        "crisis": 6000.0,
        "direction": "above",
        "action_normal": "BUY — no systemic monetary fear",
        "action_danger": "CAUTION — inflation/geopolitical fear elevated",
        "action_crisis": "AVOID USD CASH — safe-haven panic signal",
        "frequency": "Daily",
        "description": "Gold is the fear gauge. Above $5K signals serious monetary distrust; above $6K = systemic crisis underway.",
    },
    {
        "id": "crude_oil",
        "name": "WTI Crude Oil",
        "ticker": "CL=F",
        "fetch_live": True,
        "type": "numeric",
        "format": "price",
        "invert": False,
        "danger": 120.0,
        "crisis": 150.0,
        "direction": "above",
        "action_normal": "BUY — energy costs manageable",
        "action_danger": "CAUTION — stagflation risk rising",
        "action_crisis": "AVOID — oil shock / recession likely",
        "frequency": "Daily",
        "description": "High oil = stagflationary shock. Fed cannot cut without inflaming inflation; SGOV stays competitive.",
    },
    {
        "id": "fiscal_deficit",
        "name": "US Fiscal Deficit % GDP",
        "ticker": None,
        "fetch_live": False,
        "type": "numeric",
        "format": "pct",
        "invert": False,
        "default": 6.5,
        "danger": 8.0,
        "crisis": 10.0,
        "direction": "above",
        "action_normal": "BUY — deficit manageable",
        "action_danger": "CAUTION — bond vigilantes may act",
        "action_crisis": "AVOID LONG USD — monetization risk rising",
        "frequency": "Quarterly (CBO / OMB data)",
        "description": "US federal deficit as % of GDP. High deficits = Treasury supply flood, yields spike, dollar debasement risk.",
    },
    {
        "id": "vix",
        "name": "VIX Volatility Index",
        "ticker": "^VIX",
        "fetch_live": True,
        "type": "numeric",
        "format": "number_2dp",
        "invert": False,
        "danger": 30.0,
        "crisis": 45.0,
        "direction": "above",
        "action_normal": "BUY — market calm, SGOV safe",
        "action_danger": "CAUTION — market stress, hold dry powder",
        "action_crisis": "AVOID EQUITIES — systemic fear / liquidation risk",
        "frequency": "Daily",
        "description": "VIX above 30 = elevated fear. Above 45 = systemic panic. SGOV is safe haven but watch for credit dislocation.",
    },
    {
        "id": "msft_azure",
        "name": "MSFT Azure Growth",
        "ticker": None,
        "fetch_live": False,
        "type": "numeric",
        "format": "pct",
        "invert": False,
        "default": 33.0,
        "danger": 32.0,
        "crisis": 25.0,
        "direction": "below",
        "action_normal": "BUY — AI/cloud thesis intact",
        "action_danger": "CAUTION — cloud growth decelerating",
        "action_crisis": "AVOID MSFT heavy — growth thesis breaking",
        "frequency": "Quarterly (earnings)",
        "description": "Azure YoY growth rate. Proxy for AI/cloud infrastructure demand. Deceleration = overvaluation risk for MSFT-heavy portfolios.",
    },
    {
        "id": "yen_dollar",
        "name": "Yen / Dollar  (JPY per USD)",
        "ticker": "JPYUSD=X",
        "fetch_live": True,
        "type": "numeric",
        "format": "number_1dp",
        "invert": True,   # JPYUSD=X gives USD per JPY; invert → JPY per USD
        "danger": 140.0,
        "crisis": 125.0,
        "direction": "below",
        "action_normal": "BUY — yen stable, no carry unwind",
        "action_danger": "CAUTION — yen carry trade unwind risk",
        "action_crisis": "AVOID RISK — global deleveraging likely",
        "frequency": "Daily",
        "description": "Yen strengthening below 140/USD = carry trade unwind risk. Sharp yen moves historically trigger global liquidations.",
    },
    {
        "id": "brk_cash",
        "name": "BRK.B Cash Position",
        "ticker": None,
        "fetch_live": False,
        "type": "manual_status",
        "format": None,
        "invert": False,
        "default_note": "Cash ~$325B, no major acquisitions signaled (Q4 2024)",
        "danger": None,
        "crisis": None,
        "direction": None,
        "action_normal": "BUY — Buffett hoarding cash = patience signal",
        "action_danger": "CAUTION — Berkshire beginning acquisitions",
        "action_crisis": "AVOID EQUITIES — Buffett deploying $50B+ in one quarter",
        "frequency": "Quarterly (13-F / earnings)",
        "description": "Berkshire cash deployment is a Buffett market-valuation signal. Big acquisitions = he sees value; contrarian BUY for equities.",
    },
]

# Special valuation / debt rules (applies across both portfolios)
USES_PB: set[str] = {"BRK-B"}
FAIR_PB: dict[str, float] = {"BRK-B": 1.35}

# Skip ROE gate; use D/E ≤ 1.5 threshold
# PM has negative book equity from buybacks, making ROE meaningless — same exception as JPM
BANKS: set[str] = {"JPM", "PGR", "CB", "BLK", "PM"}

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


# ── Custom tickers persistence ────────────────────────────────────────────────

def load_custom_tickers() -> list:
    """Load custom tickers from JSON. Returns list of {ticker, portfolio, fair_pe} dicts."""
    if os.path.exists(CUSTOM_TICKERS_FILE):
        try:
            with open(CUSTOM_TICKERS_FILE) as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_custom_tickers(custom: list) -> None:
    with open(CUSTOM_TICKERS_FILE, "w") as fh:
        json.dump(custom, fh, indent=2)


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
        "Is Custom": meta.get("is_custom", False),
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


def compute_retired_row(stock: dict) -> dict:
    ticker = stock["ticker"]
    info = fetch_info(ticker)
    price: Optional[float] = (
        _float(info, "currentPrice") or _float(info, "regularMarketPrice")
    )
    pe: Optional[float] = _float(info, "trailingPE")
    return {
        "Ticker": ticker,
        "From": stock["from_portfolio"],
        "Date Retired": stock["date_retired"],
        "Price": price,
        "P/E": pe,
        "Removal Reason": stock["removal_reason"],
    }


# ── Formatting helpers ────────────────────────────────────────────────────────

def compute_macro_status(value: float, danger: float, crisis: float, direction: str) -> str:
    """Return NORMAL / DANGER / CRISIS based on thresholds and direction."""
    if direction == "above":
        if value >= crisis:
            return "CRISIS"
        if value >= danger:
            return "DANGER"
        return "NORMAL"
    else:  # "below"
        if value <= crisis:
            return "CRISIS"
        if value <= danger:
            return "DANGER"
        return "NORMAL"


_MACRO_STATUS_BG: dict[str, str] = {
    "NORMAL": "#4d8c68",
    "DANGER": "#b8860b",
    "CRISIS": "#9b3333",
    "N/A":    "#777777",
}
_MACRO_STATUS_BORDER: dict[str, str] = {
    "NORMAL": "#4d8c68",
    "DANGER": "#c8a030",
    "CRISIS": "#b85c5c",
    "N/A":    "#999999",
}


def fmt_macro_value(value: float, fmt: str) -> str:
    if fmt == "pct":
        return f"{value:.2f}%"
    if fmt == "price":
        return f"${value:,.0f}"
    if fmt == "number_1dp":
        return f"{value:.1f}"
    return f"{value:.2f}"


def fmt_macro_threshold(value: float, fmt: str) -> str:
    if fmt == "pct":
        return f"{value:.1f}%"
    if fmt == "price":
        return f"${value:,.0f}"
    return f"{value:.1f}"


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
        _is_custom = r.get("Is Custom", False)
        records.append({
            "Ticker":       ("★ " + r["Ticker"]) if _is_custom else r["Ticker"],
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
        ".stTabs [data-baseweb='tab-list']{gap:6px;border-bottom:2px solid #8a8b8d;margin-top:0}"
        ".stTabs [data-baseweb='tab']{font-size:1.15rem;font-weight:700;padding:6px 28px;border-radius:8px 8px 0 0;color:#ffffff;background-color:#b0b1b3;border:none;letter-spacing:0.02em}"
        ".stTabs [data-baseweb='tab']:nth-child(1){background-color:#6e9b82 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(1):hover{background-color:#5f8a72 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(1)[aria-selected='true']{background-color:#4d7a5f !important;color:#ffffff !important;border-bottom:3px solid #4d7a5f !important}"
        ".stTabs [data-baseweb='tab']:nth-child(2){background-color:#6e8fa0 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(2):hover{background-color:#5f7e90 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(2)[aria-selected='true']{background-color:#4d6e80 !important;color:#ffffff !important;border-bottom:3px solid #4d6e80 !important}"
        ".stTabs [data-baseweb='tab']:nth-child(3){background-color:#8e8eaa !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(3):hover{background-color:#7a7a98 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(3)[aria-selected='true']{background-color:#5a5a7f !important;color:#ffffff !important;border-bottom:3px solid #5a5a7f !important}"
        ".stTabs [data-baseweb='tab']:nth-child(4){background-color:#b88070 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(4):hover{background-color:#a87060 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(4)[aria-selected='true']{background-color:#a07060 !important;color:#ffffff !important;border-bottom:3px solid #a07060 !important}"
        ".stTabs [data-baseweb='tab-highlight']{display:none}"
        ".block-container{padding-top:0.75rem !important;padding-bottom:1rem !important}"
        "h1{margin-bottom:0.25rem !important;margin-top:0 !important}"
        ".stTabs{margin-top:0 !important}"
        ".stButton{margin-top:0 !important}"
        "[data-testid='stMetric']{margin-bottom:0 !important}"
        "hr{margin-top:0.4rem !important;margin-bottom:0.4rem !important}"
        "[data-testid='stSidebarContent'] .block-container{padding-top:0.5rem}"
        "[data-testid='stSidebar'] hr{margin:0.4rem 0}"
        "[data-testid='stSidebar'] .stSlider{padding-top:0;margin-top:0}"
        "[data-testid='stSidebar'] .stButton>button{"
        "font-size:12px;padding:3px 6px;border-radius:20px;height:auto;min-height:0;"
        "line-height:1.5;font-weight:600;background-color:#6e9b82;color:#fff;border:none;"
        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
        "[data-testid='stSidebar'] .stButton>button:hover{background-color:#5a7f6a;color:#fff}"
        "[data-testid='stSidebar'] .stButton>button:focus{box-shadow:none;outline:none}"
        ".st-key-rf_a .stButton>button{"
        "background-color:#9b6e6e !important;color:#fff !important}"
        ".st-key-rf_a .stButton>button:hover{"
        "background-color:#7f5a5a !important}"
        ".st-key-rf_b .stButton>button,.st-key-btn_b_ov .stButton>button{"
        "background-color:#6e8fa0 !important;color:#fff !important}"
        ".st-key-rf_b .stButton>button:hover,.st-key-btn_b_ov .stButton>button:hover{"
        "background-color:#5a7a8c !important}"
        ".st-key-refresh_b button{background-color:#6e8fa0 !important;border-color:#6e8fa0 !important;color:#fff !important}"
        ".st-key-refresh_b button:hover{background-color:#5a7a8c !important;border-color:#5a7a8c !important}"
        "[data-testid='stSidebar'] .pill-panel{"
        "background:#bfc0c2;border-radius:6px;padding:6px 8px;margin-bottom:4px}"
        ".st-key-btn_add_stock .stButton>button{"
        "background-color:#a07060 !important;color:#fff !important}"
        ".st-key-btn_add_stock .stButton>button:hover{"
        "background-color:#8a5e50 !important}"
        ".st-key-btn_fetch_preview .stButton>button{"
        "background-color:#7a8fa0 !important;color:#fff !important;font-size:11px !important}"
        ".st-key-btn_fetch_preview .stButton>button:hover{"
        "background-color:#627888 !important}"
        ".st-key-btn_add_to_portfolio .stButton>button{"
        "background-color:#5a7f6a !important;color:#fff !important;font-size:11px !important}"
        ".st-key-btn_add_to_portfolio .stButton>button:hover{"
        "background-color:#4a6a58 !important}"
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
    if "raw_rows_retired" not in st.session_state:
        st.session_state.raw_rows_retired = None
    if "last_fetched_retired" not in st.session_state:
        st.session_state.last_fetched_retired = None
    if "macro_last_fetched" not in st.session_state:
        st.session_state.macro_last_fetched = None
    if "macro_cpi_rate" not in st.session_state:
        st.session_state.macro_cpi_rate = 2.8
    if "macro_fiscal_deficit" not in st.session_state:
        st.session_state.macro_fiscal_deficit = 6.5
    if "macro_azure_growth" not in st.session_state:
        st.session_state.macro_azure_growth = 33.0
    if "macro_brk_status" not in st.session_state:
        st.session_state.macro_brk_status = "NORMAL"
    if "macro_brk_note" not in st.session_state:
        st.session_state.macro_brk_note = "Cash ~$325B, no major acquisitions signaled (Q4 2024)"
    if "custom_tickers" not in st.session_state:
        st.session_state.custom_tickers = load_custom_tickers()
    if "raw_rows_custom_a" not in st.session_state:
        st.session_state.raw_rows_custom_a = None
    if "raw_rows_custom_b" not in st.session_state:
        st.session_state.raw_rows_custom_b = None
    if "add_stock_preview" not in st.session_state:
        st.session_state.add_stock_preview = None

    # Ensure custom tickers have red-flag entries
    for _ct in st.session_state.custom_tickers:
        _ctk = _ct["ticker"]
        if _ct["portfolio"] == "A":
            st.session_state.red_flags.setdefault(_ctk, {f: False for f in FLAG_NAMES})
        else:
            st.session_state.red_flags_b.setdefault(_ctk, {f: False for f in FLAG_NAMES})

    # ── Pill toggle states ────────────────────────────────────────────────────
    # Accordion state: None = all closed, otherwise holds the open tier name
    for _ak in ["accordion_overrides_a", "accordion_redflags_a", "accordion_redflags_b"]:
        if _ak not in st.session_state:
            st.session_state[_ak] = None
    for _pk in ["pill_b_ov", "pill_add_stock"]:
        if _pk not in st.session_state:
            st.session_state[_pk] = False

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
            "font-weight:700;font-size:18px;margin:8px 0 4px 0;text-align:center'>── Portfolio A ──</div>",
            unsafe_allow_html=True,
        )

        # -- Fair Multiple Overrides: row of 3 pill buttons -------------------
        st.markdown(
            "<p style='font-size:0.82rem;font-weight:700;color:#333;margin:4px 0 2px 0'>"
            "Fair Multiple Overrides</p>",
            unsafe_allow_html=True,
        )
        _pc1, _pc2, _pc3 = st.columns(3)
        with _pc1:
            if st.button("Tier 1", key="btn_a_fair_t1", use_container_width=True):
                st.session_state.accordion_overrides_a = None if st.session_state.accordion_overrides_a == "Tier 1" else "Tier 1"
        with _pc2:
            if st.button("Tier 2", key="btn_a_fair_t2", use_container_width=True):
                st.session_state.accordion_overrides_a = None if st.session_state.accordion_overrides_a == "Tier 2" else "Tier 2"
        with _pc3:
            if st.button("Tier 3", key="btn_a_fair_t3", use_container_width=True):
                st.session_state.accordion_overrides_a = None if st.session_state.accordion_overrides_a == "Tier 3" else "Tier 3"

        for _tier_name in ["Tier 1", "Tier 2", "Tier 3"]:
            if st.session_state.accordion_overrides_a == _tier_name:
                _td = PORTFOLIO[_tier_name]
                with st.container():
                    st.markdown(
                        f"<p style='font-size:0.75rem;font-weight:700;color:#5a7f6a;"
                        f"margin:4px 0 2px 0'>{_tier_name}</p>",
                        unsafe_allow_html=True,
                    )
                    for _tk in _td["tickers"]:
                        _default_val = float(FAIR_PB.get(_tk, _td["fair_pe"]))
                        _label = f"{_tk}  ({'P/B' if _tk in USES_PB else 'P/E'})"
                        st.number_input(
                            _label,
                            min_value=0.1, max_value=200.0,
                            value=_default_val, step=0.5,
                            key=f"ov_{_tk}",
                        )

        # Build fair_overrides from session state (works whether panel is open or not)
        fair_overrides: dict[str, Optional[float]] = {}
        for _tier_name, _td in PORTFOLIO.items():
            for _tk in _td["tickers"]:
                _default_val = float(FAIR_PB.get(_tk, _td["fair_pe"]))
                _val = st.session_state.get(f"ov_{_tk}", _default_val)
                fair_overrides[_tk] = _val if _val != _default_val else None

        # -- Red Flags: row of 3 pill buttons ---------------------------------
        st.markdown(
            "<p style='font-size:0.82rem;font-weight:700;color:#333;margin:6px 0 2px 0'>"
            "Red Flags</p>",
            unsafe_allow_html=True,
        )
        with st.container(key="rf_a"):
            _rc1, _rc2, _rc3 = st.columns(3)
            with _rc1:
                if st.button("Tier 1", key="btn_a_rf_t1", use_container_width=True):
                    st.session_state.accordion_redflags_a = None if st.session_state.accordion_redflags_a == "Tier 1" else "Tier 1"
            with _rc2:
                if st.button("Tier 2", key="btn_a_rf_t2", use_container_width=True):
                    st.session_state.accordion_redflags_a = None if st.session_state.accordion_redflags_a == "Tier 2" else "Tier 2"
            with _rc3:
                if st.button("Tier 3", key="btn_a_rf_t3", use_container_width=True):
                    st.session_state.accordion_redflags_a = None if st.session_state.accordion_redflags_a == "Tier 3" else "Tier 3"

        flags_changed = False
        for _tier_name in ["Tier 1", "Tier 2", "Tier 3"]:
            if st.session_state.accordion_redflags_a == _tier_name:
                _td = PORTFOLIO[_tier_name]
                with st.container():
                    st.markdown(
                        f"<p style='font-size:0.75rem;font-weight:700;color:#5a7f6a;"
                        f"margin:4px 0 2px 0'>{_tier_name}</p>",
                        unsafe_allow_html=True,
                    )
                    for _tk in _td["tickers"]:
                        st.markdown(f"**{_tk}**")
                        for _fl in FLAG_NAMES:
                            _cur = st.session_state.red_flags.get(_tk, {}).get(_fl, False)
                            _new = st.checkbox(_fl, value=_cur, key=f"rf_{_tk}_{_fl}")
                            if _new != _cur:
                                st.session_state.red_flags[_tk][_fl] = _new
                                flags_changed = True

        if flags_changed:
            save_red_flags(st.session_state.red_flags)
            st.session_state.raw_rows = None
            st.session_state.raw_rows_custom_a = None
            st.rerun()

        # ── Portfolio B sidebar ───────────────────────────────────────────────
        st.markdown(
            "<div style='background:#6e8fa0;color:#fff;padding:4px 10px;border-radius:4px;"
            "font-weight:700;font-size:18px;margin:10px 0 4px 0;text-align:center'>── Portfolio B ──</div>",
            unsafe_allow_html=True,
        )

        # -- Fair P/E Overrides: single pill button ---------------------------
        st.markdown(
            "<p style='font-size:0.82rem;font-weight:700;color:#333;margin:4px 0 2px 0'>"
            "Fair P/E Overrides</p>",
            unsafe_allow_html=True,
        )
        if st.button("Overrides", key="btn_b_ov", use_container_width=False):
            st.session_state.pill_b_ov = not st.session_state.pill_b_ov

        if st.session_state.pill_b_ov:
            with st.container():
                for _tk, _default_pe in PORTFOLIO_B_TICKERS.items():
                    st.number_input(
                        f"{_tk}  (P/E)",
                        min_value=0.1, max_value=200.0,
                        value=float(_default_pe), step=0.5,
                        key=f"ov_b_{_tk}",
                    )

        fair_overrides_b: dict[str, Optional[float]] = {}
        for _tk, _default_pe in PORTFOLIO_B_TICKERS.items():
            _val = st.session_state.get(f"ov_b_{_tk}", float(_default_pe))
            fair_overrides_b[_tk] = _val if _val != _default_pe else None

        # -- Red Flags: Defensives | Growth/Infra pill buttons ----------------
        _B_DEFENSIVES = ["PG", "KMB", "KO", "CHD", "CL", "ABBV", "JNJ"]
        _B_GROWTH = [
            "NEE", "PGR", "PLD", "TXN", "XOM", "BLK", "BIP",
            "CB", "AVGO", "FCX", "ITW", "EOG", "EMR", "KMI",
        ]

        st.markdown(
            "<p style='font-size:0.82rem;font-weight:700;color:#333;margin:6px 0 2px 0'>"
            "Red Flags</p>",
            unsafe_allow_html=True,
        )
        with st.container(key="rf_b"):
            _bc1, _bc2 = st.columns(2)
            with _bc1:
                if st.button("Defensives", key="btn_b_rf_def", use_container_width=True):
                    st.session_state.accordion_redflags_b = None if st.session_state.accordion_redflags_b == "Defensives" else "Defensives"
            with _bc2:
                if st.button("Growth/Infra", key="btn_b_rf_growth", use_container_width=True):
                    st.session_state.accordion_redflags_b = None if st.session_state.accordion_redflags_b == "Growth/Infra" else "Growth/Infra"

        flags_b_changed = False
        _b_rf_panels = [
            ("Defensives", _B_DEFENSIVES),
            ("Growth/Infra", _B_GROWTH),
        ]
        for _label, _tickers in _b_rf_panels:
            if st.session_state.accordion_redflags_b == _label:
                with st.container():
                    st.markdown(
                        f"<p style='font-size:0.75rem;font-weight:700;color:#5a7f6a;"
                        f"margin:4px 0 2px 0'>{_label}</p>",
                        unsafe_allow_html=True,
                    )
                    for _tk in _tickers:
                        st.markdown(f"**{_tk}**")
                        for _fl in FLAG_NAMES:
                            _cur = st.session_state.red_flags_b.get(_tk, {}).get(_fl, False)
                            _new = st.checkbox(_fl, value=_cur, key=f"rf_b_{_tk}_{_fl}")
                            if _new != _cur:
                                st.session_state.red_flags_b[_tk][_fl] = _new
                                flags_b_changed = True

        if flags_b_changed:
            save_red_flags_b(st.session_state.red_flags_b)
            st.session_state.raw_rows_b = None
            st.session_state.raw_rows_custom_b = None
            st.rerun()

        # ── Add a Stock sidebar ───────────────────────────────────────────────
        st.markdown(
            "<div style='background:#a07060;color:#fff;padding:4px 10px;border-radius:4px;"
            "font-weight:700;font-size:18px;margin:10px 0 4px 0;text-align:center'>"
            "── Add a Stock ──</div>",
            unsafe_allow_html=True,
        )
        with st.container(key="btn_add_stock"):
            if st.button("+ Add Stock", key="btn_add_stock_toggle", use_container_width=False):
                st.session_state.pill_add_stock = not st.session_state.pill_add_stock

        if st.session_state.pill_add_stock:
            st.text_input("Ticker Symbol", key="add_ticker_input", placeholder="e.g. NVDA")
            st.selectbox(
                "Add to Portfolio",
                options=["Portfolio A", "Portfolio B"],
                key="add_portfolio_select",
            )
            st.number_input(
                "Fair P/E (or Fair P/B)",
                min_value=0.1, max_value=200.0,
                value=20.0, step=0.5,
                key="add_fair_pe_input",
            )

            _add_col1, _add_col2 = st.columns(2)
            with _add_col1:
                with st.container(key="btn_fetch_preview"):
                    if st.button("Fetch & Preview", key="btn_fetch_preview_btn", use_container_width=True):
                        _ticker_input = st.session_state.get("add_ticker_input", "").strip().upper()
                        if _ticker_input:
                            _preview_info = fetch_info(_ticker_input)
                            st.session_state.add_stock_preview = {
                                "ticker": _ticker_input,
                                "info": _preview_info,
                            }
                        else:
                            st.session_state.add_stock_preview = None

            with _add_col2:
                with st.container(key="btn_add_to_portfolio"):
                    if st.button("Add to Portfolio", key="btn_add_to_port_btn", use_container_width=True):
                        _ticker_input = st.session_state.get("add_ticker_input", "").strip().upper()
                        _portfolio_sel = st.session_state.get("add_portfolio_select", "Portfolio A")
                        _fair_pe_val = float(st.session_state.get("add_fair_pe_input", 20.0))
                        _port_key = "A" if _portfolio_sel == "Portfolio A" else "B"
                        _all_existing = (
                            set(ALL_TICKERS) | set(ALL_TICKERS_B)
                            | {_ct["ticker"] for _ct in st.session_state.custom_tickers}
                        )
                        if not _ticker_input:
                            st.warning("Enter a ticker symbol.")
                        elif _ticker_input in _all_existing:
                            st.warning(f"{_ticker_input} already in portfolios.")
                        else:
                            _new_entry = {
                                "ticker": _ticker_input,
                                "portfolio": _port_key,
                                "fair_pe": _fair_pe_val,
                            }
                            st.session_state.custom_tickers.append(_new_entry)
                            save_custom_tickers(st.session_state.custom_tickers)
                            if _port_key == "A":
                                st.session_state.red_flags[_ticker_input] = {
                                    f: False for f in FLAG_NAMES
                                }
                                save_red_flags(st.session_state.red_flags)
                                st.session_state.raw_rows_custom_a = None
                            else:
                                st.session_state.red_flags_b[_ticker_input] = {
                                    f: False for f in FLAG_NAMES
                                }
                                save_red_flags_b(st.session_state.red_flags_b)
                                st.session_state.raw_rows_custom_b = None
                            st.session_state.add_stock_preview = None
                            st.rerun()

            # Preview card
            _preview = st.session_state.add_stock_preview
            if _preview:
                _pinfo = _preview["info"]
                _pticker = _preview["ticker"]
                _pprice = _float(_pinfo, "currentPrice") or _float(_pinfo, "regularMarketPrice")
                _ppe = _float(_pinfo, "trailingPE")
                _proe_raw = _float(_pinfo, "returnOnEquity")
                _proe = _proe_raw * 100.0 if _proe_raw is not None else None
                _pfcf = _float(_pinfo, "freeCashflow")
                _pmktcap = _float(_pinfo, "marketCap")
                _pfcfy = (
                    (_pfcf / _pmktcap * 100.0)
                    if (_pfcf and _pmktcap and _pmktcap > 0) else None
                )
                _prev_raw = _float(_pinfo, "revenueGrowth")
                _prev_gr = _prev_raw * 100.0 if _prev_raw is not None else None
                _pde_raw = _float(_pinfo, "debtToEquity")
                _pde = _pde_raw / 100.0 if _pde_raw is not None else None
                _pname = _pinfo.get("shortName") or _pinfo.get("longName") or _pticker
                st.markdown(
                    f"<div style='background:#e8e4d8;border:1px solid #b0a888;border-radius:6px;"
                    f"padding:8px 10px;margin-top:6px;font-size:0.8rem;color:#333'>"
                    f"<b style='font-size:0.9rem;color:#5a3a28'>{_pticker}</b>"
                    f"<span style='font-size:0.72rem;color:#666;margin-left:6px'>{_pname}</span><br>"
                    f"<b>Price:</b> {fmt_price(_pprice)} &nbsp; <b>P/E:</b> {fmt_mult(_ppe)}<br>"
                    f"<b>ROE:</b> {fmt_pct(_proe)} &nbsp; <b>FCFy:</b> {fmt_pct(_pfcfy)}<br>"
                    f"<b>RevGr:</b> {fmt_pct(_prev_gr, plus=True)} &nbsp; <b>D/E:</b> {fmt_mult(_pde)}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Munger Toll Bridge Portfolio")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_a, tab_b, tab_r, tab_m = st.tabs(["Portfolio A", "Portfolio B", "Retired", "Macro Signals"])

    # ══════════════════════════════════════════════════════════════════════════
    # PORTFOLIO A
    # ══════════════════════════════════════════════════════════════════════════
    with tab_a:
        col_refresh_a, col_ts_a = st.columns([1, 4])
        with col_refresh_a:
            if st.button("Refresh Data", key="refresh_a", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.raw_rows = None
                st.session_state.raw_rows_custom_a = None

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

        # ── Custom tickers (Portfolio A) ──────────────────────────────────────
        _custom_a = [_ct for _ct in st.session_state.custom_tickers if _ct["portfolio"] == "A"]
        if _custom_a:
            if st.session_state.raw_rows_custom_a is None:
                _custom_rows_a: list[dict] = []
                for _ci, _ct in enumerate(_custom_a, start=1):
                    _ctk = _ct["ticker"]
                    _cmeta = {_ctk: {"tier": "Custom", "rank": _ci, "base_fair": _ct["fair_pe"], "is_custom": True}}
                    _custom_rows_a.append(
                        compute_row(_ctk, None, mos_pct, st.session_state.red_flags, _cmeta)
                    )
                st.session_state.raw_rows_custom_a = _custom_rows_a
            _df_raw_ca = pd.DataFrame(st.session_state.raw_rows_custom_a)
            _df_disp_ca = build_display_df(st.session_state.raw_rows_custom_a)
            _n_buy_ca = (_df_raw_ca["Decision"] == "BUY").sum()
            st.subheader(f"Custom Watchlist  ·  BUY signals: {_n_buy_ca}")
            _ca_disp = _df_disp_ca[DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
            _ca_signals = _ca_disp["_signal"]
            _ca_disp = _ca_disp[DISPLAY_COLS].copy()
            _ca_styled = _style_df(_ca_disp, _ca_signals)
            st.dataframe(
                _ca_styled,
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
| ROE%\\* | ≥ 15 % | Skipped for banks (JPM) | `returnOnEquity` proxy for ROIC |
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
                st.session_state.raw_rows_custom_b = None

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

        # ── Custom tickers (Portfolio B) ──────────────────────────────────────
        _custom_b = [_ct for _ct in st.session_state.custom_tickers if _ct["portfolio"] == "B"]
        if _custom_b:
            if st.session_state.raw_rows_custom_b is None:
                _custom_rows_b: list[dict] = []
                for _ci, _ct in enumerate(_custom_b, start=1):
                    _ctk = _ct["ticker"]
                    _cmeta = {_ctk: {"tier": "Portfolio B", "rank": len(ALL_TICKERS_B) + _ci, "base_fair": _ct["fair_pe"], "is_custom": True}}
                    _custom_rows_b.append(
                        compute_row(_ctk, None, mos_pct, st.session_state.red_flags_b, _cmeta)
                    )
                st.session_state.raw_rows_custom_b = _custom_rows_b
            _df_raw_cb = pd.DataFrame(st.session_state.raw_rows_custom_b)
            _df_disp_cb = build_display_df(st.session_state.raw_rows_custom_b)
            _n_buy_cb = (_df_raw_cb["Decision"] == "BUY").sum()
            st.subheader(f"Custom Watchlist  ·  BUY signals: {_n_buy_cb}")
            _cb_disp = _df_disp_cb[DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
            _cb_signals = _cb_disp["_signal"]
            _cb_disp = _cb_disp[DISPLAY_COLS].copy()
            _cb_styled = _style_df(_cb_disp, _cb_signals)
            st.dataframe(
                _cb_styled,
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

    # ══════════════════════════════════════════════════════════════════════════
    # RETIRED
    # ══════════════════════════════════════════════════════════════════════════
    with tab_r:
        st.markdown(
            "<div style='background:#5a5a7f;color:#fff;padding:10px 16px;border-radius:6px;"
            "margin-bottom:12px'>"
            "<strong>Thesis Tracking</strong> — Stocks removed from Portfolio A or B are archived "
            "here so you can verify whether the removal thesis played out correctly over time. "
            "Live price and P/E are fetched from Yahoo Finance so you can monitor performance "
            "post-removal against the stated removal rationale."
            "</div>",
            unsafe_allow_html=True,
        )

        col_refresh_r, col_ts_r = st.columns([1, 4])
        with col_refresh_r:
            if st.button("Refresh Data", key="refresh_r", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.raw_rows_retired = None

        if st.session_state.raw_rows_retired is None:
            progress_r = st.progress(0, text="Fetching market data…")
            raw_rows_retired: list[dict] = []
            for i, stock in enumerate(RETIRED_STOCKS):
                raw_rows_retired.append(compute_retired_row(stock))
                progress_r.progress((i + 1) / len(RETIRED_STOCKS), text=f"Fetching {stock['ticker']}…")
            progress_r.empty()
            st.session_state.raw_rows_retired = raw_rows_retired
            st.session_state.last_fetched_retired = datetime.now()

        raw_rows_retired = st.session_state.raw_rows_retired

        fetched_str_r = (
            st.session_state.last_fetched_retired.strftime("%Y-%m-%d  %H:%M:%S")
            if st.session_state.last_fetched_retired else "—"
        )
        with col_ts_r:
            st.caption(
                f"Last fetched: **{fetched_str_r}**  ·  "
                f"Data: Yahoo Finance (yfinance)"
            )

        # Build display dataframe
        retired_records = []
        for r in raw_rows_retired:
            retired_records.append({
                "Ticker":         r["Ticker"],
                "From":           r["From"],
                "Date Retired":   r["Date Retired"],
                "Price":          fmt_price(r["Price"]),
                "P/E":            fmt_mult(r["P/E"]),
                "Removal Reason": r["Removal Reason"],
            })
        df_retired = pd.DataFrame(retired_records)

        def color_retired_rows(row):
            if row["From"] == "A":
                return ["background-color: #d4e6dc"] * len(row)
            elif row["From"] == "B":
                return ["background-color: #d4e0e6"] * len(row)
            return [""] * len(row)

        styled_retired = df_retired.style.apply(color_retired_rows, axis=1)

        st.subheader(f"Retired Positions  ·  {len(RETIRED_STOCKS)} stocks")

        st.dataframe(
            styled_retired,
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        csv_bytes_r = df_retired.to_csv(index=False).encode()
        st.download_button(
            label="Download Retired as CSV",
            data=csv_bytes_r,
            file_name=f"retired_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

        st.caption(
            "Row color: sage green = Portfolio A · slate blue = Portfolio B.  "
            "Data: Yahoo Finance via yfinance.  Not financial advice."
        )


    # ══════════════════════════════════════════════════════════════════════════
    # MACRO SIGNALS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_m:
        st.markdown(
            "<div style='background:#a07060;color:#fff;padding:10px 16px;border-radius:6px;"
            "margin-bottom:10px'>"
            "<div><strong>Macro Signals Dashboard</strong> — 10 macro indicators for SGOV deployment decisions.</div>"
            "<div style='margin-top:4px;white-space:nowrap'>"
            "<span style='background:#5a8a5a;color:#fff;padding:1px 8px;border-radius:10px;"
            "font-size:0.85rem'>&#9679; NORMAL</span>&nbsp;"
            "deploy freely &nbsp;|&nbsp; "
            "<span style='background:#b8860b;color:#fff;padding:1px 8px;border-radius:10px;"
            "font-size:0.85rem'>&#9650; DANGER</span>&nbsp;"
            "caution &nbsp;|&nbsp; "
            "<span style='background:#8a3a3a;color:#fff;padding:1px 8px;border-radius:10px;"
            "font-size:0.85rem'>&#9888; CRISIS</span>&nbsp;"
            "avoid / reduce"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        # ── Refresh + manual inputs ───────────────────────────────────────────
        col_rm, col_tm, col_cpi = st.columns([1, 3, 2])
        with col_rm:
            if st.button("Refresh Data", key="refresh_m", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.macro_last_fetched = None

        # Force a "first fetch" timestamp so we can show it
        if st.session_state.macro_last_fetched is None:
            st.session_state.macro_last_fetched = datetime.now()

        macro_ts_str = st.session_state.macro_last_fetched.strftime("%Y-%m-%d  %H:%M:%S")
        with col_tm:
            st.caption(
                f"Last fetched: **{macro_ts_str}**  ·  "
                "Live signals via Yahoo Finance (yfinance)  ·  Static signals updated manually"
            )

        with col_cpi:
            new_cpi = st.number_input(
                "CPI Rate % (for Real Fed Funds)",
                min_value=-5.0, max_value=25.0,
                value=float(st.session_state.macro_cpi_rate),
                step=0.1, format="%.1f",
                key="macro_cpi_input",
                help="Enter latest CPI YoY % — used to compute Real Fed Funds Rate = nominal rate − CPI",
            )
            st.session_state.macro_cpi_rate = new_cpi

        # ── Manual / static signal inputs ────────────────────────────────────
        with st.expander("Update Manual Signals (Fiscal Deficit, Azure Growth, BRK.B)", expanded=False):
            st.markdown(
                "<p style='font-size:0.85rem;color:#555;margin:0 0 8px 0'>"
                "These signals are updated quarterly from public sources. "
                "Edit values here and they apply immediately to the cards below.</p>",
                unsafe_allow_html=True,
            )
            _mc1, _mc2, _mc3 = st.columns(3)
            with _mc1:
                new_deficit = st.number_input(
                    "Fiscal Deficit % GDP",
                    min_value=0.0, max_value=30.0,
                    value=float(st.session_state.macro_fiscal_deficit),
                    step=0.1, format="%.1f",
                    key="macro_deficit_input",
                    help="Source: CBO / OMB — update quarterly",
                )
                st.session_state.macro_fiscal_deficit = new_deficit
                st.caption("Source: CBO / OMB budget outlook")

            with _mc2:
                new_azure = st.number_input(
                    "MSFT Azure Growth %",
                    min_value=0.0, max_value=100.0,
                    value=float(st.session_state.macro_azure_growth),
                    step=0.5, format="%.1f",
                    key="macro_azure_input",
                    help="Azure YoY revenue growth % — from MSFT quarterly earnings",
                )
                st.session_state.macro_azure_growth = new_azure
                st.caption("Source: MSFT quarterly earnings")

            with _mc3:
                new_brk_status = st.selectbox(
                    "BRK.B Cash Status",
                    options=["NORMAL", "DANGER", "CRISIS"],
                    index=["NORMAL", "DANGER", "CRISIS"].index(st.session_state.macro_brk_status),
                    key="macro_brk_status_input",
                )
                st.session_state.macro_brk_status = new_brk_status
                new_brk_note = st.text_area(
                    "BRK.B Note",
                    value=st.session_state.macro_brk_note,
                    height=68,
                    key="macro_brk_note_input",
                )
                st.session_state.macro_brk_note = new_brk_note

        st.divider()

        # ── Summary scorecard ─────────────────────────────────────────────────
        _statuses: list[str] = []
        for _s in MACRO_SIGNALS_CONFIG:
            if _s["type"] == "manual_status":
                _statuses.append(st.session_state.macro_brk_status)
            elif _s["type"] == "computed_real_rate":
                _irx2 = fetch_info(_s["ticker"])
                _n2 = _float(_irx2, "regularMarketPrice") or _float(_irx2, "currentPrice")
                if _n2 is not None:
                    _rv = _n2 - st.session_state.macro_cpi_rate
                    _statuses.append(compute_macro_status(_rv, _s["danger"], _s["crisis"], _s["direction"]))
                else:
                    _statuses.append("N/A")
            elif _s["fetch_live"]:
                _li2 = fetch_info(_s["ticker"])
                _r2 = _float(_li2, "regularMarketPrice") or _float(_li2, "currentPrice")
                if _r2 is not None:
                    _dv2 = (1.0 / _r2) if (_s["invert"] and _r2 != 0) else _r2
                    _statuses.append(compute_macro_status(_dv2, _s["danger"], _s["crisis"], _s["direction"]))
                else:
                    _statuses.append("N/A")
            else:
                _sk2 = {"fiscal_deficit": "macro_fiscal_deficit", "msft_azure": "macro_azure_growth"}.get(_s["id"])
                if _sk2:
                    _sv2 = float(st.session_state.get(_sk2, _s.get("default", 0.0)))
                    _statuses.append(compute_macro_status(_sv2, _s["danger"], _s["crisis"], _s["direction"]))
                else:
                    _statuses.append("N/A")

        _cnt_normal  = _statuses.count("NORMAL")
        _cnt_danger  = _statuses.count("DANGER")
        _cnt_crisis  = _statuses.count("CRISIS")
        _cnt_na      = _statuses.count("N/A")

        _sum_c1, _sum_c2, _sum_c3, _sum_c4 = st.columns(4)
        _sum_c1.metric("NORMAL",  _cnt_normal,  delta_color="off")
        _sum_c2.metric("DANGER",  _cnt_danger,  delta_color="off")
        _sum_c3.metric("CRISIS",  _cnt_crisis,  delta_color="off")
        _sum_c4.metric("N/A",     _cnt_na,      delta_color="off")

        _sgov_ok = _cnt_crisis == 0 and _cnt_danger <= 2
        _sgov_label = "DEPLOY SGOV" if _sgov_ok else ("CAUTION" if _cnt_crisis == 0 else "AVOID / REDUCE")
        _sgov_color = "#4d8c68" if _sgov_ok else ("#b8860b" if _cnt_crisis == 0 else "#9b3333")
        st.markdown(
            f"<div style='background:{_sgov_color};color:#fff;padding:10px 18px;border-radius:6px;"
            f"font-size:1.05rem;font-weight:700;margin-top:8px;text-align:center'>"
            f"Overall SGOV Stance: {_sgov_label}  ·  "
            f"{_cnt_normal}/10 Normal · {_cnt_danger}/10 Danger · {_cnt_crisis}/10 Crisis"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Signal cards — 2-column grid ──────────────────────────────────────
        st.subheader("LIVE SIGNALS — fetched from Yahoo Finance")

        # Render live signals (first 7) then separator then manual signals (last 3)
        _LIVE_SIGNALS   = MACRO_SIGNALS_CONFIG[:7]
        _MANUAL_SIGNALS = MACRO_SIGNALS_CONFIG[7:]

        grid_cols_live = st.columns(2)
        for _idx, _sig in enumerate(_LIVE_SIGNALS):
            _col = grid_cols_live[_idx % 2]
            with _col:

                # ── Determine current value and status ────────────────────────
                _display_val: Optional[float] = None
                _status: str = "N/A"
                _value_str: str = "—"
                _extra_label: str = ""

                if _sig["type"] == "manual_status":
                    _status = st.session_state.macro_brk_status
                    _value_str = st.session_state.macro_brk_note

                elif _sig["type"] == "computed_real_rate":
                    _irx_info = fetch_info(_sig["ticker"])
                    _nominal = (
                        _float(_irx_info, "regularMarketPrice")
                        or _float(_irx_info, "currentPrice")
                    )
                    if _nominal is not None:
                        _display_val = _nominal - st.session_state.macro_cpi_rate
                        _status = compute_macro_status(
                            _display_val, _sig["danger"], _sig["crisis"], _sig["direction"]
                        )
                        _value_str = fmt_macro_value(_display_val, _sig["format"])
                        _extra_label = (
                            f"nominal {_nominal:.2f}% − CPI {st.session_state.macro_cpi_rate:.1f}%"
                        )
                    else:
                        _value_str = "—"

                elif _sig["fetch_live"]:
                    _live_info = fetch_info(_sig["ticker"])
                    _raw = (
                        _float(_live_info, "regularMarketPrice")
                        or _float(_live_info, "currentPrice")
                    )
                    if _raw is not None:
                        _display_val = (1.0 / _raw) if (_sig["invert"] and _raw != 0) else _raw
                        _status = compute_macro_status(
                            _display_val, _sig["danger"], _sig["crisis"], _sig["direction"]
                        )
                        _value_str = fmt_macro_value(_display_val, _sig["format"])
                    else:
                        _value_str = "—"

                else:
                    # Static numeric
                    _static_key = {
                        "fiscal_deficit": "macro_fiscal_deficit",
                        "msft_azure":     "macro_azure_growth",
                    }.get(_sig["id"])
                    if _static_key:
                        _display_val = float(st.session_state.get(_static_key, _sig.get("default", 0.0)))
                        _status = compute_macro_status(
                            _display_val, _sig["danger"], _sig["crisis"], _sig["direction"]
                        )
                        _value_str = fmt_macro_value(_display_val, _sig["format"])

                # ── Choose action label by status ─────────────────────────────
                _action_map = {
                    "NORMAL": _sig["action_normal"],
                    "DANGER": _sig["action_danger"],
                    "CRISIS": _sig["action_crisis"],
                    "N/A":    "—",
                }
                _card_action = _action_map.get(_status, "—")

                # ── Threshold display strings ─────────────────────────────────
                if _sig["danger"] is not None:
                    _dir_word_d = "above" if _sig["direction"] == "above" else "below"
                    _dir_word_c = _dir_word_d
                    _danger_str = f"{_dir_word_d} {fmt_macro_threshold(_sig['danger'], _sig['format'])}"
                    _crisis_str = f"{_dir_word_c} {fmt_macro_threshold(_sig['crisis'], _sig['format'])}"
                else:
                    _danger_str = "Manual"
                    _crisis_str = "Manual"

                # ── Ticker badge ──────────────────────────────────────────────
                _ticker_badge = (
                    f"<span style='font-size:0.72rem;color:#888;background:#ddd;"
                    f"padding:1px 6px;border-radius:4px;margin-left:6px'>{_sig['ticker']}</span>"
                    if _sig["ticker"] else
                    "<span style='font-size:0.72rem;color:#888;background:#ddd;"
                    "padding:1px 6px;border-radius:4px;margin-left:6px'>manual</span>"
                )

                # ── Status pill colors ────────────────────────────────────────
                _sbg   = _MACRO_STATUS_BG.get(_status, "#777777")
                _sbord = _MACRO_STATUS_BORDER.get(_status, "#999999")

                # ── Extra note line ───────────────────────────────────────────
                _extra_html = (
                    f"<div style='font-size:0.75rem;color:#666;margin-top:2px'>{_extra_label}</div>"
                    if _extra_label else ""
                )

                # ── BRK.B: show note as description instead of numeric value ──
                _value_display_html = (
                    f"<div style='font-size:0.85rem;color:#444;margin:4px 0 6px 0;"
                    f"font-style:italic;line-height:1.3'>{_value_str}</div>"
                    if _sig["type"] == "manual_status"
                    else
                    f"<div style='font-size:2rem;font-weight:700;color:#1a1a1a;"
                    f"margin:2px 0;letter-spacing:-0.02em'>{_value_str}</div>"
                    f"{_extra_html}"
                )

                st.markdown(
                    f"<div style='background:#c8c9cb;border-radius:8px;padding:14px 16px;"
                    f"margin-bottom:10px;border-left:5px solid {_sbord}'>"
                    # Header row
                    f"<div style='display:flex;justify-content:space-between;align-items:flex-start'>"
                    f"  <div style='font-size:0.88rem;font-weight:700;color:#333'>"
                    f"    {_sig['name']}{_ticker_badge}"
                    f"  </div>"
                    f"  <span style='background:{_sbg};color:#fff;padding:3px 12px;"
                    f"border-radius:14px;font-size:0.82rem;font-weight:700;white-space:nowrap;"
                    f"margin-left:8px'>{_status}</span>"
                    f"</div>"
                    # Value
                    f"{_value_display_html}"
                    # Thresholds
                    f"<div style='margin:6px 0 4px 0'>"
                    f"  <span style='background:#c8a030;color:#fff;padding:2px 8px;"
                    f"border-radius:4px;font-size:0.76rem;margin-right:6px'>"
                    f"    Danger: {_danger_str}</span>"
                    f"  <span style='background:#9b3333;color:#fff;padding:2px 8px;"
                    f"border-radius:4px;font-size:0.76rem'>"
                    f"    Crisis: {_crisis_str}</span>"
                    f"</div>"
                    # Action
                    f"<div style='font-size:0.8rem;color:#333;margin-top:6px'>"
                    f"  <b>Signal:</b> {_card_action}"
                    f"</div>"
                    # Description
                    f"<div style='font-size:0.75rem;color:#666;margin-top:4px;line-height:1.35'>"
                    f"  {_sig['description']}"
                    f"</div>"
                    # Frequency
                    f"<div style='font-size:0.72rem;color:#888;margin-top:5px'>"
                    f"  Frequency: {_sig['frequency']}"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        # ── Manual signals section ────────────────────────────────────────────
        st.subheader("MANUAL SIGNALS — updated quarterly from public sources")
        grid_cols_manual = st.columns(2)
        for _idx, _sig in enumerate(_MANUAL_SIGNALS):
            _col = grid_cols_manual[_idx % 2]
            with _col:

                # ── Determine current value and status ────────────────────────
                _display_val: Optional[float] = None
                _status: str = "N/A"
                _value_str: str = "—"
                _extra_label: str = ""

                if _sig["type"] == "manual_status":
                    _status = st.session_state.macro_brk_status
                    _value_str = st.session_state.macro_brk_note
                else:
                    _static_key = {
                        "fiscal_deficit": "macro_fiscal_deficit",
                        "msft_azure":     "macro_azure_growth",
                    }.get(_sig["id"])
                    if _static_key:
                        _display_val = float(st.session_state.get(_static_key, _sig.get("default", 0.0)))
                        _status = compute_macro_status(
                            _display_val, _sig["danger"], _sig["crisis"], _sig["direction"]
                        )
                        _value_str = fmt_macro_value(_display_val, _sig["format"])

                _action_map2 = {
                    "NORMAL": _sig["action_normal"],
                    "DANGER": _sig["action_danger"],
                    "CRISIS": _sig["action_crisis"],
                    "N/A":    "—",
                }
                _card_action2 = _action_map2.get(_status, "—")

                if _sig["danger"] is not None:
                    _dw = "above" if _sig["direction"] == "above" else "below"
                    _danger_str2 = f"{_dw} {fmt_macro_threshold(_sig['danger'], _sig['format'])}"
                    _crisis_str2 = f"{_dw} {fmt_macro_threshold(_sig['crisis'], _sig['format'])}"
                else:
                    _danger_str2 = "Manual"
                    _crisis_str2 = "Manual"

                _ticker_badge2 = (
                    "<span style='font-size:0.72rem;color:#888;background:#ddd;"
                    "padding:1px 6px;border-radius:4px;margin-left:6px'>manual</span>"
                )
                _sbg2   = _MACRO_STATUS_BG.get(_status, "#777777")
                _sbord2 = _MACRO_STATUS_BORDER.get(_status, "#999999")

                _value_display_html2 = (
                    f"<div style='font-size:0.85rem;color:#444;margin:4px 0 6px 0;"
                    f"font-style:italic;line-height:1.3'>{_value_str}</div>"
                    if _sig["type"] == "manual_status"
                    else
                    f"<div style='font-size:2rem;font-weight:700;color:#1a1a1a;"
                    f"margin:2px 0;letter-spacing:-0.02em'>{_value_str}</div>"
                )

                st.markdown(
                    f"<div style='background:#c8c9cb;border-radius:8px;padding:14px 16px;"
                    f"margin-bottom:10px;border-left:5px solid {_sbord2}'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:flex-start'>"
                    f"  <div style='font-size:0.88rem;font-weight:700;color:#333'>"
                    f"    {_sig['name']}{_ticker_badge2}"
                    f"  </div>"
                    f"  <span style='background:{_sbg2};color:#fff;padding:3px 12px;"
                    f"border-radius:14px;font-size:0.82rem;font-weight:700;white-space:nowrap;"
                    f"margin-left:8px'>{_status}</span>"
                    f"</div>"
                    f"{_value_display_html2}"
                    f"<div style='margin:6px 0 4px 0'>"
                    f"  <span style='background:#c8a030;color:#fff;padding:2px 8px;"
                    f"border-radius:4px;font-size:0.76rem;margin-right:6px'>"
                    f"    Danger: {_danger_str2}</span>"
                    f"  <span style='background:#9b3333;color:#fff;padding:2px 8px;"
                    f"border-radius:4px;font-size:0.76rem'>"
                    f"    Crisis: {_crisis_str2}</span>"
                    f"</div>"
                    f"<div style='font-size:0.8rem;color:#333;margin-top:6px'>"
                    f"  <b>Signal:</b> {_card_action2}"
                    f"</div>"
                    f"<div style='font-size:0.75rem;color:#666;margin-top:4px;line-height:1.35'>"
                    f"  {_sig['description']}"
                    f"</div>"
                    f"<div style='font-size:0.72rem;color:#888;margin-top:5px'>"
                    f"  Frequency: {_sig['frequency']}"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.caption(
            "Live data: Yahoo Finance via yfinance.  "
            "Static data: update quarterly from CBO/OMB, MSFT earnings, Berkshire 13-F.  "
            "Not financial advice."
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
