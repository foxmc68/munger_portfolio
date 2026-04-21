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
import requests
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

# ── Constants ─────────────────────────────────────────────────────────────────

RED_FLAGS_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags.json")
RED_FLAGS_FILE_B  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "red_flags_b.json")
CUSTOM_TICKERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_tickers.json")
WAIT_LIST_CUSTOM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wait_list_custom.json")
MANUAL_METRICS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manual_metrics.json")
MARKET_INDICATORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_indicators.json")
FRED_API_KEY = "f3c2c99c5652b7acc8617d439d7a803e"

FLAG_NAMES = [
    "Accounting Issues",
    "Mgmt Turnover",
    "Regulatory Threat",
    "Moat Deteriorating",
]

# ── Portfolio A definition ────────────────────────────────────────────────────

PORTFOLIO: dict[str, dict] = {
    "Tier 1": {
        "tickers": ["V", "MCO", "SPGI", "MSFT", "GOOGL", "COST", "RMS.PA", "ASML", "RMBS", "WKL", "RAA.DE"],
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
        "tickers": ["JPM", "CVX", "COP", "EPD", "ASR"],
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
#   PM   16 – iQOS/IQOS-led heated tobacco transition; strong dividend coverage;
#             ex-US geographic diversification reduces US regulatory risk

PORTFOLIO_B_TICKERS: dict[str, float] = {
    "NEE":  22.0,
    "PGR":  18.0,
    "PG":   24.0,
    "KMI":  16.0,
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
    "PM":   16.0,
    "NVO":  22.0,
    "ITRK.L": 22.0,
    "BVI.PA": 20.0,
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
    {
        "ticker": "KMB",
        "from_portfolio": "B",
        "date_retired": "2026-04-08",
        "removal_reason": "Debt/equity of 4.65 far exceeds 0.5 threshold — 30 years of debt-funded buybacks and dividends. Acquired Kenvue (J&J consumer spinoff including talc liability) for $48B with borrowed money. Private label competition in diapers and paper products limiting growth. Business going nowhere.",
    },
]

ALL_TICKERS_RETIRED: list[str] = [s["ticker"] for s in RETIRED_STOCKS]

# ── Company name lookup (Ticker → "Name (Sector)") ────────────────────────────
COMPANY_NAMES: dict[str, str] = {
    # Portfolio A
    "V":      "Visa (Payment Networks)",
    "MCO":    "Moody's (Rating Agencies)",
    "SPGI":   "S&P Global (Rating Agencies)",
    "MSFT":   "Microsoft (Cloud/AI)",
    "GOOGL":  "Alphabet (Search/Cloud)",
    "COST":   "Costco (Retail)",
    "RMS.PA": "Hermès (Luxury Goods)",
    "ASML":   "ASML (Semiconductor Equipment)",
    "RMBS":   "Rambus (Semiconductor IP)",
    "ADP":    "ADP (Payroll/HR)",
    "FICO":   "Fair Isaac (Credit Scoring)",
    "AXP":    "American Express (Premium Cards)",
    "BRK-B":  "Berkshire Hathaway (Conglomerate)",
    "CME":    "CME Group (Futures Exchange)",
    "DHR":    "Danaher (Life Sciences)",
    "IDXX":   "IDEXX Labs (Veterinary Diagnostics)",
    "VRSN":   "VeriSign (Domain Registry)",
    "CNI":    "CN Rail (Canadian Railway)",
    "BAM":    "Brookfield AM (Real Assets)",
    "WM":     "Waste Management (Essential Infrastructure)",
    "AZO":    "AutoZone (Auto Parts)",
    "JPM":    "JPMorgan Chase (Global Banking)",
    "CVX":    "Chevron (Integrated Energy)",
    "COP":    "ConocoPhillips (E&P Energy)",
    "EPD":    "Enterprise Products (Midstream MLP)",
    "ASR":    "Grupo Aeroportuario (Mexican Airports)",
    "WKL":    "Wolters Kluwer (Professional Information Services)",
    "RAA.DE": "Rational AG (Commercial Kitchen Equipment)",
    # Portfolio B
    "PM":     "Philip Morris (International Tobacco)",
    "NEE":  "NextEra Energy (Renewable Utility)",
    "PGR":  "Progressive (Auto Insurance)",
    "PG":   "Procter & Gamble (Consumer Staples)",
    "KMI":  "Kinder Morgan (Gas Infrastructure)",
    "KO":   "Coca-Cola (Global Beverages)",
    "PLD":  "Prologis (Industrial REIT)",
    "TXN":  "Texas Instruments (Analog Semiconductors)",
    "XOM":  "ExxonMobil (Integrated Energy)",
    "BLK":  "BlackRock (Asset Management)",
    "BIP":  "Brookfield Infrastructure (Global Infrastructure)",
    "CHD":  "Church & Dwight (Consumer Brands)",
    "CB":   "Chubb (Global P&C Insurance)",
    "ABBV": "AbbVie (Biopharma)",
    "AVGO": "Broadcom (AI Chips/Software)",
    "CL":   "Colgate (Consumer Staples)",
    "FCX":  "Freeport-McMoRan (Copper Mining)",
    "JNJ":  "Johnson & Johnson (Healthcare)",
    "ITW":  "Illinois Tool Works (Industrial)",
    "EOG":  "EOG Resources (E&P Energy)",
    "EMR":  "Emerson Electric (Industrial Automation)",
    # Retired
    "SCHW": "Charles Schwab (Brokerage)",
    "WFC":  "Wells Fargo (US Banking)",
    "ODFL": "Old Dominion (LTL Freight)",
    "AMT":  "American Tower (Cell Tower REIT)",
    "TROW": "T. Rowe Price (Active Asset Mgmt)",
    "PAYX": "Paychex (Payroll/HR)",
    "SYY":  "Sysco (Food Distribution)",
    "HRL":  "Hormel (Packaged Foods)",
    "PSX":  "Phillips 66 (Refining)",
    "MDT":  "Medtronic (Medical Devices)",
    "KMB":  "Kimberly-Clark (Consumer Paper)",
    # Wait List / Deployment extras
    "FNV":       "Franco-Nevada (Gold Royalty Streaming)",
    "NVO":       "Novo Nordisk (GLP-1 Pharma)",
    "EQNR":      "Equinor (Norwegian Oil & Gas)",
    "CSU.TO":    "Constellation Software (Vertical Market SaaS)",
    "6861.T":    "Keyence (Japanese Sensors/Automation)",
    "KEY-6861.T":"Keyence (Japanese Sensors/Automation)",
    "WTKWY":     "Wolters Kluwer (Professional Information)",
    "CLPBY":     "Coloplast (Medical Devices/Ostomy)",
    "ITRK.L":   "Intertek (Testing & Certification)",
    "BVI.PA":   "Bureau Veritas (Testing & Certification)",
    "DPLM.L":   "Diploma PLC (UK Industrial Distribution)",
}


def _company_legend(tickers: list[str]) -> str:
    """Return a styled HTML legend: <strong>TICKER</strong> = Name · …"""
    parts = []
    for tk in tickers:
        clean = tk.lstrip("★ ").strip()
        name = COMPANY_NAMES.get(clean, "")
        if name:
            parts.append(
                f"<strong style='color:#000;font-weight:700'>{clean}</strong>"
                f"<span style='color:#444444'> = {name}</span>"
            )
    inner = " &nbsp;·&nbsp; ".join(parts)
    return (
        f'<p style="font-size:12px;color:#444444;margin:4px 0 0 0;line-height:1.6">'
        f"{inner}</p>"
    )


# ── Wait List ─────────────────────────────────────────────────────────────────
# Two sections:
#   WAIT_LIST_ADD  — existing holdings in Portfolio A or B waiting for a lower
#                    price to size up the position.
#   WAIT_LIST_NEW  — quality businesses not yet in either portfolio.
#
# entry_pe_target: the P/E (or FCF multiple for CSU.TO) at which we'd buy.
# entry_low / entry_high: the price range we're targeting.
# add_more_at: secondary add price if position opened and keeps dropping.
# currency_symbol: display prefix for prices ($ / C$ / ¥).

WAIT_LIST_ADD: list[dict] = [
    {
        "ticker": "GOOGL",
        "metric": "P/E",
        "entry_pe_target": 16,
        "entry_low": 135.0,
        "entry_high": 140.0,
        "add_more_at": 120.0,
        "currency_symbol": "$",
        "note": "Search / YouTube / Cloud at 16× trailing P/E only. Regulatory and AI disruption risk to search revenue demands valuation discipline.",
    },
    {
        "ticker": "V",
        "metric": "P/E",
        "entry_pe_target": 25,
        "entry_low": 295.0,
        "entry_high": 310.0,
        "add_more_at": 265.0,
        "currency_symbol": "$",
        "note": "Already own V in Portfolio A Tier 1 — sizing up existing position only. Need 25× trailing P/E entry; current premium too high to add.",
    },
    {
        "ticker": "ASML",
        "metric": "P/E",
        "entry_pe_target": 24,
        "entry_low": 580.0,
        "entry_high": 610.0,
        "add_more_at": 500.0,
        "currency_symbol": "$",
        "note": "Sole supplier of EUV lithography — unmatched global moat. 24× is our ceiling; chip cycle uncertainty demands patience.",
    },
    {
        "ticker": "COST",
        "metric": "P/E",
        "entry_pe_target": 43,
        "entry_low": 800.0,
        "entry_high": 830.0,
        "add_more_at": 700.0,
        "currency_symbol": "$",
        "note": "World's best retailer. Membership moat compounds indefinitely. 43× is our absolute ceiling — waiting for a recession scare to compress the multiple.",
    },
]

WAIT_LIST_NEW: list[dict] = [
    {
        "ticker": "NVO",
        "metric": "P/E",
        "entry_pe_target": 20,
        "entry_low": 52.0,
        "entry_high": 55.0,
        "add_more_at": 45.0,
        "currency_symbol": "$",
        "note": "Novo Nordisk — GLP-1 weight-loss monopoly. Ozempic/Wegovy still in early innings of global adoption. Valuation compressed from peak; waiting for further multiple reset to 20× trailing P/E.",
    },
    {
        "ticker": "EQNR",
        "metric": "P/E",
        "entry_pe_target": 8,
        "entry_low": 21.0,
        "entry_high": 22.0,
        "add_more_at": 18.0,
        "currency_symbol": "$",
        "note": "Norwegian integrated oil + offshore wind at 8×. Geopolitically safer than US majors; strong dividend shields downside in commodity cycles.",
    },
    {
        "ticker": "AXP",
        "metric": "P/E",
        "entry_pe_target": 17,
        "entry_low": 235.0,
        "entry_high": 245.0,
        "add_more_at": 210.0,
        "currency_symbol": "$",
        "note": "Premium credit card network with superior spend data moat. 17× trailing P/E is our entry ceiling; currently priced for perfection.",
    },
    {
        "ticker": "FICO",
        "metric": "P/E",
        "entry_pe_target": 42,
        "entry_low": 1400.0,
        "entry_high": 1500.0,
        "add_more_at": 1200.0,
        "currency_symbol": "$",
        "note": "Credit scoring monopoly with near-zero competitive risk. 42× still demanding even for a toll booth; waiting for a recession-lite multiple compression.",
    },
    {
        "ticker": "CSU.TO",
        "metric": "FCF",
        "entry_pe_target": 46,
        "entry_low": 4000.0,
        "entry_high": 4200.0,
        "add_more_at": 3500.0,
        "currency_symbol": "C$",
        "note": "Constellation Software — greatest serial acquirer of vertical market software. Valued on FCF multiple (46×). Management quality extraordinary; patience required.",
    },
    {
        "ticker": "6861.T",
        "display_ticker": "6861.T (Keyence)",
        "metric": "P/E",
        "entry_pe_target": 34,
        "entry_low": 52000.0,
        "entry_high": 54000.0,
        "add_more_at": 47000.0,
        "currency_symbol": "¥",
        "note": "Keyence — Japanese sensor/automation monopoly. 50%+ net margins, ~15% growth, zero debt. Wait for macro-driven Japan selloff to compress to 34×.",
    },
    {
        "ticker": "WTKWY",
        "metric": "P/E",
        "entry_pe_target": 30,
        "entry_low": 60.0,
        "entry_high": 65.0,
        "add_more_at": 55.0,
        "currency_symbol": "$",
        "note": "Professional information services monopoly — tax, legal, compliance, health. Structural analog to FICO. Subscription model with near-zero churn. US ADR available.",
    },
    {
        "ticker": "CLPBY",
        "metric": "P/E",
        "entry_pe_target": 28,
        "entry_low": 12.0,
        "entry_high": 14.0,
        "add_more_at": 10.0,
        "currency_symbol": "$",
        "note": "Danish medical device compounder. Ostomy and continence care — deeply personal, high switching cost, recurring consumable revenue. Slower compounder suited to income allocation. US ADR available.",
    },
    {
        "ticker": "DPLM.L",
        "metric": "P/E",
        "entry_pe_target": 20,
        "entry_low": 18.0,
        "entry_high": 20.0,
        "add_more_at": 15.0,
        "currency_symbol": "£",
        "note": "UK industrial distribution — emergency parts switching cost moat. ROIC borderline at 15%, watch for improvement as margins expand to 25% target. Access via Fidelity international trading.",
    },
]

# Combined list — used for fetching and ticker registration
WAIT_LIST: list[dict] = WAIT_LIST_ADD + WAIT_LIST_NEW

ALL_TICKERS_WAITLIST: list[str] = [s["ticker"] for s in WAIT_LIST]

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

STOCK_CATEGORY: dict[str, str] = {
    # Asset-Light Compounders
    "MSFT": "asset_light", "GOOGL": "asset_light", "FICO": "asset_light",
    "VRSN": "asset_light", "ADP": "asset_light", "RMBS": "asset_light",
    "WKL": "asset_light", "RAA.DE": "asset_light",
    # Toll Bridge Financials
    "MCO": "toll_financial", "CME": "toll_financial", "AXP": "toll_financial",
    "SPGI": "bank",  # IHS Markit acquisition ($44B goodwill) inflates IC → standard ROIC formula misleading
    # Banks
    "JPM": "bank", "BAM": "bank", "BLK": "bank",
    # Insurance
    "PGR": "insurance", "CB": "insurance", "BRK-B": "insurance",
    # Railroads/Infrastructure
    "CNI": "railroad", "NEE": "infrastructure", "PLD": "infrastructure", "BIP": "infrastructure",
    # Consumer Staples
    "PG": "consumer_staples", "KO": "consumer_staples", "KMB": "consumer_staples",
    "PM": "consumer_staples", "CL": "consumer_staples", "CHD": "consumer_staples",
    "COST": "consumer_staples",
    # Pharma / Biotech
    "NVO": "pharma", "ABBV": "pharma", "JNJ": "pharma",
    # Energy Majors
    "CVX": "energy", "COP": "energy", "XOM": "energy", "EOG": "energy", "EQNR": "energy",
    # MLPs
    "EPD": "mlp", "KMI": "mlp",
    # Royalties
    "FNV": "royalty",
    # Industrials/Healthcare
    "DHR": "industrial", "IDXX": "industrial", "WM": "industrial", "ASML": "industrial",
    "RMS.PA": "industrial", "ITW": "industrial", "EMR": "industrial", "TXN": "industrial",
    "AVGO": "industrial",
    # Testing, Inspection & Certification
    "ITRK.L": "tic", "BVI.PA": "tic",
    # Airport Concessions
    "ASR": "airport",
    # Special
    "AZO": "special_azo",
}

CATEGORY_THRESHOLDS: dict[str, dict] = {
    "asset_light":      {"roic": 25,   "fcf_yield": 2.0, "rev_growth": 8,  "de": 0.5},
    "toll_financial":   {"roic": 15,   "fcf_yield": 2.0, "rev_growth": 5,  "de": 2.0},
    "bank":             {"roic": None, "fcf_yield": 2.5, "rev_growth": 3,  "de": None},
    "insurance":        {"roic": None, "fcf_yield": None,"rev_growth": 5,  "de": None},
    "railroad":         {"roic": 10,   "fcf_yield": 2.5, "rev_growth": 3,  "de": 1.5},
    "infrastructure":   {"roic": 8,    "fcf_yield": 2.5, "rev_growth": 3,  "de": 2.5},
    "consumer_staples": {"roic": 12,   "fcf_yield": 3.0, "rev_growth": 2,  "de": 1.5},
    "energy":           {"roic": 10,   "fcf_yield": 4.0, "rev_growth": 0,  "de": 0.5},
    "mlp":              {"roic": None, "fcf_yield": 4.0, "rev_growth": 2,  "de": 3.5},
    "royalty":          {"roic": 8,    "fcf_yield": 3.0, "rev_growth": 5,  "de": 0.3},
    "industrial":       {"roic": 15,   "fcf_yield": 2.5, "rev_growth": 5,  "de": 1.0},
    "pharma":           {"roic": 15,   "fcf_yield": None,"rev_growth": 5,  "de": 1.0},
    "airport":          {"roic": 8,    "fcf_yield": 2.5, "rev_growth": 3,  "de": 1.5},
    "special_azo":      {"roic": 15,   "fcf_yield": 3.0, "rev_growth": 3,  "de": None},
    "tic":              {"roic": 12,   "fcf_yield": 2.5, "rev_growth": 3,  "de": 2.0},
}

# Fallback thresholds for tickers not in STOCK_CATEGORY
_DEFAULT_CATEGORY_THRESHOLDS: dict = {"roic": 15, "fcf_yield": 3.5, "rev_growth": 0, "de": 0.5}

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


def _category_thresholds(ticker: str) -> dict:
    cat = STOCK_CATEGORY.get(ticker)
    if cat:
        return CATEGORY_THRESHOLDS[cat]
    return _DEFAULT_CATEGORY_THRESHOLDS


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


# ── Manual metrics persistence ────────────────────────────────────────────────

_MANUAL_METRICS_DEFAULTS: dict[str, float] = {
    "pgr_combined_ratio":        95.0,
    "pgr_premium_growth":         0.0,
    "cb_combined_ratio":         95.0,
    "cb_premium_growth":          0.0,
    "cni_operating_ratio":       60.0,
    "jpm_roa":                    0.0,
    "jpm_efficiency_ratio":       0.0,
    "epd_dcf_coverage":           0.0,
    "epd_distribution_growth":    0.0,
    "cvx_dividend_coverage":      0.0,
    "cop_dividend_coverage":      0.0,
    "pm_dividend_coverage":       0.0,
    "pm_iqos_volume_growth":      0.0,
}


def _mm_ts_label(updated: Optional[str]) -> str:
    """Return a display string for a per-field manual-metrics timestamp."""
    if updated:
        try:
            dt = datetime.strptime(updated, "%Y-%m-%d")
            return f"Updated: {dt.strftime('%b')} {dt.day}, {dt.year}"
        except Exception:
            return f"Updated: {updated}"
    return "Never updated"


def load_manual_metrics() -> dict:
    """Return {field: {"value": float, "updated": str|None}} for all known fields."""
    defaults = {k: {"value": v, "updated": None} for k, v in _MANUAL_METRICS_DEFAULTS.items()}
    if os.path.exists(MANUAL_METRICS_FILE):
        try:
            with open(MANUAL_METRICS_FILE) as fh:
                data = json.load(fh)
            result = {}
            for k, default_val in _MANUAL_METRICS_DEFAULTS.items():
                raw = data.get(k)
                if raw is None:
                    result[k] = {"value": default_val, "updated": None}
                elif isinstance(raw, (int, float)):
                    # Old format — migrate gracefully
                    result[k] = {"value": float(raw), "updated": None}
                elif isinstance(raw, dict):
                    result[k] = {"value": float(raw.get("value", default_val)), "updated": raw.get("updated")}
                else:
                    result[k] = {"value": default_val, "updated": None}
            return result
        except Exception:
            pass
    return defaults


def save_manual_metrics(metrics: dict) -> None:
    with open(MANUAL_METRICS_FILE, "w") as fh:
        json.dump(metrics, fh, indent=2)


# ── Market Indicators persistence ─────────────────────────────────────────────

_MARKET_INDICATOR_IDS = [
    # Stage 1
    "hy_spread", "ig_spread", "yield_curve", "pct_above_200ma", "nyse_ad_line",
    "treasury_bid_cover", "indirect_bidders", "dxy", "gold_price", "ism_pmi",
    "conf_board_lei",
    # Stage 2
    "treasury_10yr", "treasury_30yr", "brent_crude",
    "hormuz_volume", "red_sea_volume", "war_risk_premium", "eps_guidance",
    "gross_margin", "cc_delinquency", "auto_delinquency", "initial_claims",
    # Stage 3
    "continuing_claims", "prof_tech_layoffs", "wage_growth",
    "retail_sales", "inventory_sales", "sp500_concentration",
    "ai_capex_ratio", "cloud_revenue_growth", "federal_deficit",
]

_MARKET_INDICATOR_DEFAULT = {"current": "", "prior": "", "signal": "N/A", "updated": None}

# Indicators auto-populated via yfinance or FRED API
_AUTO_PULL_IDS = {
    "dxy", "gold_price", "brent_crude", "treasury_10yr", "treasury_30yr",
    "hy_spread", "ig_spread", "yield_curve", "initial_claims", "continuing_claims",
    "ism_pmi", "conf_board_lei", "federal_deficit", "cc_delinquency", "auto_delinquency",
}

# Indicators that must be updated manually
_MANUAL_IDS = {
    "hormuz_volume", "red_sea_volume", "war_risk_premium", "treasury_bid_cover",
    "indirect_bidders", "nyse_ad_line", "eps_guidance", "gross_margin",
    "prof_tech_layoffs", "wage_growth",
    "pct_above_200ma", "retail_sales", "inventory_sales",
    "sp500_concentration", "ai_capex_ratio", "cloud_revenue_growth",
}


def load_market_indicators() -> dict:
    """Return {indicator_id: {current, prior, signal, updated}} for all indicators."""
    defaults = {k: dict(_MARKET_INDICATOR_DEFAULT) for k in _MARKET_INDICATOR_IDS}
    if os.path.exists(MARKET_INDICATORS_FILE):
        try:
            with open(MARKET_INDICATORS_FILE) as fh:
                data = json.load(fh)
            stored = data.get("indicators", data)
            result = {}
            for k in _MARKET_INDICATOR_IDS:
                raw = stored.get(k)
                if isinstance(raw, dict):
                    result[k] = {
                        "current": raw.get("current", ""),
                        "prior":   raw.get("prior", ""),
                        "signal":  raw.get("signal", "N/A"),
                        "updated": raw.get("updated"),
                    }
                else:
                    result[k] = dict(_MARKET_INDICATOR_DEFAULT)
            return result
        except Exception:
            pass
    return defaults


def save_market_indicators(indicators: dict) -> None:
    with open(MARKET_INDICATORS_FILE, "w") as fh:
        json.dump({"indicators": indicators}, fh, indent=2)


def _on_market_prior_change(ind_id: str) -> None:
    """on_change callback: immediately persist a Prior field edit to JSON."""
    mi = st.session_state.get("market_indicators", {})
    new_val = st.session_state.get(f"mi_pri_{ind_id}", "")
    mi.setdefault(ind_id, dict(_MARKET_INDICATOR_DEFAULT))
    mi[ind_id]["prior"] = new_val
    save_market_indicators(mi)


@st.cache_data(ttl=4 * 3600)
def _fetch_yfinance_market_data() -> dict:
    """Fetch live prices from yfinance. Returns {indicator_id: formatted_string}."""
    _tickers = {
        "dxy":           ("DX-Y.NYB", lambda p: f"{p:.2f}"),
        "gold_price":    ("GC=F",     lambda p: f"${p:,.0f}"),
        "brent_crude":   ("BZ=F",     lambda p: f"${p:.2f}"),
        "treasury_10yr": ("^TNX",     lambda p: f"{p:.2f}%"),
        "treasury_30yr": ("^TYX",     lambda p: f"{p:.2f}%"),
        "_2yr_yield":    ("^IRX",     lambda p: f"{p:.2f}%"),
    }
    result = {}
    for key, (ticker, fmt) in _tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                result[key] = fmt(float(hist["Close"].iloc[-1]))
        except Exception:
            pass
    return result


@st.cache_data(ttl=4 * 3600)
def _fetch_fred_market_data() -> dict:
    """Fetch latest observations from FRED. Returns {indicator_id: formatted_string}."""
    _base = "https://api.stlouisfed.org/fred/series/observations"

    def _get(series_id: str) -> Optional[float]:
        try:
            r = requests.get(
                _base,
                params={
                    "series_id":  series_id,
                    "api_key":    FRED_API_KEY,
                    "file_type":  "json",
                    "sort_order": "desc",
                    "limit":      10,
                },
                timeout=12,
            )
            for obs in r.json().get("observations", []):
                if obs.get("value") not in (".", ""):
                    return float(obs["value"])
        except Exception:
            pass
        return None

    result: dict = {}

    # HY spread — FRED stores in % (4.0 = 400 bps)
    v = _get("BAMLH0A0HYM2")
    if v is not None:
        result["hy_spread"] = f"{v * 100:.0f} bps"

    # IG spread
    v = _get("BAMLC0A0CM")
    if v is not None:
        result["ig_spread"] = f"{v * 100:.0f} bps"

    # 2yr/10yr yield curve (percentage points, negative = inverted)
    v = _get("T10Y2Y")
    if v is not None:
        result["yield_curve"] = f"{v:.2f}%"

    # Initial jobless claims 4-wk avg
    v = _get("IC4WSA")
    if v is not None:
        result["initial_claims"] = f"{v:,.0f}"

    # Continuing claims
    v = _get("CCSA")
    if v is not None:
        result["continuing_claims"] = f"{v:,.0f}"

    # ISM Manufacturing PMI — try MANEMP first, fallback NAPM
    v = _get("MANEMP")
    if v is None:
        v = _get("NAPM")
    if v is not None:
        result["ism_pmi"] = f"{v:.1f}"

    # Conference Board LEI (MoM)
    v = _get("USSLIND")
    if v is not None:
        result["conf_board_lei"] = f"{v:.2f}"

    # Federal deficit % of GDP (negative = deficit)
    v = _get("FYFSGDA188S")
    if v is not None:
        result["federal_deficit"] = f"{v:.1f}%"

    # Credit card delinquency rate
    v = _get("DRCCLACBS")
    if v is not None:
        result["cc_delinquency"] = f"{v:.2f}%"

    # Auto loan delinquency rate — try multiple series in order
    for _auto_series in ("DTAUTHFNM", "DRALACBS", "DRAUT", "DRAUTOACBS"):
        v = _get(_auto_series)
        if v is not None:
            result["auto_delinquency"] = f"{v:.2f}%"
            break

    return result


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


def load_wait_list_custom() -> list:
    """Load custom wait list entries from JSON."""
    if os.path.exists(WAIT_LIST_CUSTOM_FILE):
        try:
            with open(WAIT_LIST_CUSTOM_FILE) as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_wait_list_custom(entries: list) -> None:
    with open(WAIT_LIST_CUSTOM_FILE, "w") as fh:
        json.dump(entries, fh, indent=2)


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


@st.cache_data(show_spinner=False)
def fetch_financials(ticker: str) -> dict:
    """
    Fetch income statement and balance sheet fields needed for ROIC and revenue growth.
    yfinance no longer includes these in .info — they require separate calls.
    """
    result: dict = {}
    try:
        t = yf.Ticker(ticker)
        inc = t.income_stmt
        if inc is not None and not inc.empty:
            if "Operating Income" in inc.index:
                v = inc.loc["Operating Income"].iloc[0]
                if v is not None and not (isinstance(v, float) and v != v):
                    result["operatingIncome"] = float(v)
            if "Tax Rate For Calcs" in inc.index:
                v = inc.loc["Tax Rate For Calcs"].iloc[0]
                if v is not None and not (isinstance(v, float) and v != v):
                    result["taxRate"] = float(v)
            # 3-year revenue CAGR: (rev_year0 / rev_year3)^(1/3) - 1
            # Requires at least 3 annual data points; fewer than that → omit (shown as N/A).
            # Never fall back to single-year YoY which can reflect one bad quarter.
            if "Total Revenue" in inc.index:
                rev_series = inc.loc["Total Revenue"].dropna()
                rev_vals = [float(v) for v in rev_series if v is not None and not (isinstance(v, float) and v != v)]
                if len(rev_vals) >= 4:
                    # iloc[0] = most recent, iloc[3] = 3 years prior
                    r0, r3 = rev_vals[0], rev_vals[3]
                    if r3 > 0:
                        result["revenueCagr3yr"] = (r0 / r3) ** (1.0 / 3.0) - 1.0
                elif len(rev_vals) == 3:
                    r0, r2 = rev_vals[0], rev_vals[2]
                    if r2 > 0:
                        result["revenueCagr3yr"] = (r0 / r2) ** (1.0 / 2.0) - 1.0
                # 2 data points = 1-year YoY only; not set → displayed as N/A
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            if "Total Assets" in bs.index:
                v = bs.loc["Total Assets"].iloc[0]
                if v is not None and not (isinstance(v, float) and v != v):
                    result["totalAssets"] = float(v)
            if "Current Liabilities" in bs.index:
                v = bs.loc["Current Liabilities"].iloc[0]
                if v is not None and not (isinstance(v, float) and v != v):
                    result["currentLiabilities"] = float(v)
            if "Cash And Cash Equivalents" in bs.index:
                v = bs.loc["Cash And Cash Equivalents"].iloc[0]
                if v is not None and not (isinstance(v, float) and v != v):
                    result["cash"] = float(v)
    except Exception:
        pass
    return result


@st.cache_data(show_spinner=False)
def fetch_news(ticker: str) -> list[dict]:
    """
    Fetch up to 5 recent news items for a ticker.
    Handles both the current nested-content format and the legacy flat format.
    Cached indefinitely — cleared only by the Refresh button.
    """
    try:
        raw = yf.Ticker(ticker).news or []
        items: list[dict] = []
        for entry in raw[:5]:
            content = entry.get("content")
            if content and isinstance(content, dict):
                canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                items.append({
                    "title": content.get("title", ""),
                    "link": canonical.get("url", "#"),
                    "publisher": (content.get("provider") or {}).get("displayName", ""),
                    "pubDate": content.get("pubDate"),
                    "providerPublishTime": None,
                })
            else:
                items.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", "#"),
                    "publisher": entry.get("publisher", ""),
                    "pubDate": None,
                    "providerPublishTime": entry.get("providerPublishTime", 0),
                })
        return items
    except Exception:
        return []


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


def _price_from_info(info: dict) -> Optional[float]:
    """Return current price from yfinance info, converting GBp (pence) → GBP for London stocks."""
    price = _float(info, "currentPrice") or _float(info, "regularMarketPrice")
    if price is not None and info.get("currency") == "GBp":
        price = price / 100.0
    return price


def compute_row(
    ticker: str,
    fair_override: Optional[float],
    mos_pct: float,
    red_flags: dict,
    ticker_meta: dict,
    manual_metrics: Optional[dict] = None,
) -> dict:
    meta = ticker_meta[ticker]
    fair_multiple = fair_override if fair_override is not None else meta["base_fair"]
    dream_multiple = fair_multiple * (1.0 - mos_pct / 100.0)

    info = fetch_info(ticker)

    # ── Price ────────────────────────────────────────────────────────────────
    price: Optional[float] = _price_from_info(info)

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

    fins = fetch_financials(ticker)
    op_income = fins.get("operatingIncome")
    tax_rate = fins.get("taxRate")
    total_assets = fins.get("totalAssets")
    current_liabilities = fins.get("currentLiabilities")
    cash = fins.get("cash")
    if (op_income is not None and tax_rate is not None and
            total_assets is not None and current_liabilities is not None and cash is not None):
        nopat = op_income * (1.0 - tax_rate)
        invested_capital = total_assets - current_liabilities - cash
        roic: Optional[float] = (nopat / invested_capital * 100.0) if invested_capital > 0 else None
    else:
        roic = None

    fcf = _float(info, "freeCashflow")
    mktcap = _float(info, "marketCap")
    fcfy: Optional[float] = (fcf / mktcap * 100.0) if (fcf and mktcap and mktcap > 0) else None

    # Use 3-year revenue CAGR from annual financials.
    # Do NOT fall back to yfinance revenueGrowth (TTM YoY) — it reflects a single quarter
    # and can be badly misleading for ADRs or companies with inventory/seasonal corrections.
    rev_growth: Optional[float] = (
        fins["revenueCagr3yr"] * 100.0 if fins.get("revenueCagr3yr") is not None else None
    )

    de_raw = _float(info, "debtToEquity")
    de_ratio: Optional[float] = de_raw / 100.0 if de_raw is not None else None

    gm_raw = _float(info, "grossMargins")
    gm_pct: Optional[float] = gm_raw * 100.0 if gm_raw is not None else None

    insider_raw = _float(info, "heldPercentInsiders")
    insider_pct: Optional[float] = insider_raw * 100.0 if insider_raw is not None else None

    # ── Quality gate (category-specific thresholds) ───────────────────────────
    fails: list[str] = []
    thresholds = _category_thresholds(ticker)
    roic_thr = thresholds["roic"]
    fcfy_thr = thresholds["fcf_yield"]
    revgr_thr = thresholds["rev_growth"]
    de_thr = thresholds["de"]

    if roic_thr is not None:
        if roic is None:
            fails.append("ROIC N/A")
        elif roic < roic_thr:
            fails.append(f"ROIC {roic:.1f}% < {roic_thr}%")

    if fcfy_thr is not None:
        if fcfy is None:
            fails.append("FCFy N/A")
        elif fcfy < fcfy_thr:
            fails.append(f"FCFy {fcfy:.1f}% < {fcfy_thr}%")

    if revgr_thr is not None:
        if rev_growth is None:
            fails.append("RevGr N/A")
        elif rev_growth < revgr_thr:
            fails.append(f"RevGr {rev_growth:.1f}% < {revgr_thr}%")

    if de_thr is not None:
        if de_ratio is None:
            fails.append("D/E N/A")
        elif de_ratio > de_thr:
            fails.append(f"D/E {de_ratio:.2f} > {de_thr}")

    de_limit = de_thr  # preserve for display column

    # ── Manual metrics hard gates ─────────────────────────────────────────────
    if manual_metrics:
        mm = manual_metrics
        def _mmv(field):
            """Extract float value from new {value, updated} format or legacy float."""
            raw = mm.get(field, 0)
            if isinstance(raw, dict):
                return float(raw.get("value", 0))
            return float(raw) if raw else 0.0
        if ticker == "PGR":
            v = _mmv("pgr_combined_ratio")
            if v > 0 and v > 96:
                fails.append(f"Combined Ratio {v:.1f}% > 96%")
        elif ticker == "CB":
            v = _mmv("cb_combined_ratio")
            if v > 0 and v > 96:
                fails.append(f"Combined Ratio {v:.1f}% > 96%")
        elif ticker == "CNI":
            v = _mmv("cni_operating_ratio")
            if v > 0 and v > 65:
                fails.append(f"Operating Ratio {v:.1f}% > 65%")
        elif ticker == "JPM":
            roa = _mmv("jpm_roa")
            eff = _mmv("jpm_efficiency_ratio")
            if roa > 0 and roa < 1.0:
                fails.append(f"ROA {roa:.2f}% < 1.0%")
            if eff > 0 and eff > 60:
                fails.append(f"Efficiency Ratio {eff:.1f}% > 60%")
        elif ticker == "EPD":
            v = _mmv("epd_dcf_coverage")
            if v > 0 and v < 1.5:
                fails.append(f"DCF Coverage {v:.2f}x < 1.5x")
        elif ticker == "PM":
            v = _mmv("pm_dividend_coverage")
            if v > 0 and v < 1.3:
                fails.append(f"Dividend Coverage {v:.2f}x < 1.3x")
        elif ticker == "CVX":
            v = _mmv("cvx_dividend_coverage")
            if v > 0 and v < 2.0:
                fails.append(f"Div Coverage @$70 oil {v:.2f}x < 2.0x")
        elif ticker == "COP":
            v = _mmv("cop_dividend_coverage")
            if v > 0 and v < 2.0:
                fails.append(f"Div Coverage @$70 oil {v:.2f}x < 2.0x")

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
        "ROIC%": roic,
        "FCFy%": fcfy,
        "RevGr%": rev_growth,
        "GM%": gm_pct,
        "Insider%": insider_pct,
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
    price: Optional[float] = _price_from_info(info)
    pe: Optional[float] = _float(info, "trailingPE")
    return {
        "Ticker": ticker,
        "From": stock["from_portfolio"],
        "Date Retired": stock["date_retired"],
        "Price": price,
        "P/E": pe,
        "Removal Reason": stock["removal_reason"],
    }


def compute_waitlist_row(stock: dict) -> dict:
    ticker = stock["ticker"]
    info = fetch_info(ticker)
    price: Optional[float] = _price_from_info(info)
    pe: Optional[float] = _float(info, "trailingPE")

    entry_high = stock["entry_high"]

    # % gap: (current − entry_high) / entry_high × 100
    # Negative = price already at or below entry range top (in range)
    if price is not None and entry_high > 0:
        gap_pct: Optional[float] = (price - entry_high) / entry_high * 100.0
    else:
        gap_pct = None

    if gap_pct is None:
        status = "N/A"
    elif gap_pct <= 0:
        status = "AT TARGET"
    elif gap_pct <= 15.0:
        status = "APPROACHING"
    else:
        status = "NOT YET"

    return {
        "ticker": ticker,
        "display_ticker": stock.get("display_ticker", ticker),
        "metric": stock["metric"],
        "entry_pe_target": stock["entry_pe_target"],
        "entry_low": stock["entry_low"],
        "entry_high": entry_high,
        "add_more_at": stock["add_more_at"],
        "currency_symbol": stock["currency_symbol"],
        "note": stock["note"],
        "price": price,
        "pe": pe,
        "gap_pct": gap_pct,
        "status": status,
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
            "ROIC%":        fmt_pct(r["ROIC%"]),
            "FCFy%":        fmt_pct(r["FCFy%"]),
            "RevGr%":       fmt_pct(r["RevGr%"], plus=True),
            "GM%":          fmt_pct(r["GM%"]),
            "Insider%":     fmt_pct(r["Insider%"]),
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

_SIGNAL_ROW_COLORS: dict[str, tuple[str, str]] = {
    "DREAM": ("#b7d4b0", "#1a3a1f"),
    "FAIR":  ("#f0d080", "#3d2800"),
    "WAIT":  ("#dfa898", "#3d0f00"),
    "N/A":   ("#d0d0d2", "#555555"),
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
    "Discount", "Signal", "ROIC%", "FCFy%", "RevGr%", "GM%", "Insider%", "D/E",
    "Quality", "Fail Reasons", "Red Flags", "Active Flags", "Decision",
]

# HTML row column specs: (header_label, display_df_field, flex_pct, align)
_TABLE_COLS: list[tuple[str, str, str, str]] = [
    ("Ticker",   "Ticker",        "8%",    "left"),
    ("#",        "#",             "2.5%",  "right"),
    ("Price",    "Price",         "5.5%",  "right"),
    ("Metric",   "Metric",        "3.5%",  "center"),
    ("Current",  "Current",       "4.5%",  "right"),
    ("Fair",     "Fair",          "4.5%",  "right"),
    ("Dream",    "Dream",         "4.5%",  "right"),
    ("Fair $",   "Fair Price $",  "6%",    "right"),
    ("Dream $",  "Dream Price $", "6%",    "right"),
    ("Disc%",    "Discount",      "5%",    "right"),
    ("Signal",   "Signal",        "5%",    "center"),
    ("ROIC%",    "ROIC%",         "4.5%",  "right"),
    ("FCFy%",    "FCFy%",         "4.5%",  "right"),
    ("RevGr%",   "RevGr%",        "4.5%",  "right"),
    ("GM%",      "GM%",           "4.5%",  "right"),
    ("Insider%", "Insider%",      "4.5%",  "right"),
    ("D/E",      "D/E",           "3.5%",  "right"),
    ("Quality",  "Quality",       "5%",    "center"),
    ("Fail",     "Fail Reasons",  "15%",   "left"),
    ("Flags",    "Active Flags",  "2.5%",  "right"),
    ("Decision", "Decision",      "5%",    "center"),
]

_RETIRED_TABLE_COLS: list[tuple[str, str, str, str]] = [
    ("Ticker",         "Ticker",         "8%",  "left"),
    ("From",           "From",           "5%",  "center"),
    ("Date Retired",   "Date Retired",   "10%", "center"),
    ("Price",          "Price",          "8%",  "right"),
    ("P/E",            "P/E",            "7%",  "right"),
    ("Removal Reason", "Removal Reason", "62%", "left"),
]


# ── News helpers ──────────────────────────────────────────────────────────────

_PUBLISHER_COLORS: dict[str, str] = {
    "wall street journal": "#c0392b",
    "wsj": "#c0392b",
    "barron": "#2980b9",
    "morningstar": "#e67e22",
    "reuters": "#7f8c8d",
    "bloomberg": "#2c3e50",
}
_DEFAULT_PUBLISHER_COLOR = "#6c6c9a"


def _publisher_color(publisher: str) -> str:
    p = publisher.lower()
    for key, color in _PUBLISHER_COLORS.items():
        if key in p:
            return color
    return _DEFAULT_PUBLISHER_COLOR


def _fmt_news_age(item: dict) -> str:
    """Return relative age string from a news item dict (ISO pubDate or legacy unix ts)."""
    from datetime import timezone
    pub_date = item.get("pubDate")
    if pub_date:
        try:
            dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
            diff = max(0, int(datetime.now(timezone.utc).timestamp()) - int(dt.timestamp()))
        except Exception:
            return ""
    else:
        ts = item.get("providerPublishTime") or 0
        if not ts:
            return ""
        diff = max(0, int(datetime.now().timestamp()) - ts)
    if diff < 3600:
        return f"{diff // 60}m ago"
    elif diff < 86400:
        return f"{diff // 3600}h ago"
    elif diff < 604800:
        return f"{diff // 86400}d ago"
    else:
        return f"{diff // 604800}w ago"


def _build_table_header(col_spec: list) -> str:
    cells = "".join(
        f"<div style='flex:0 0 {w};text-align:{a};padding:0 4px;"
        f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>{lbl}</div>"
        for lbl, _, w, a in col_spec
    )
    return (
        "<div style='display:flex;align-items:center;"
        "background:#555;color:#fff;"
        "font-size:0.71rem;font-weight:700;padding:3px 0;"
        "font-family:monospace;border-radius:3px 3px 0 0'>"
        + cells + "</div>"
    )


def _build_table_row(row_dict: dict, bg: str, fg: str, col_spec: list) -> str:
    cells = "".join(
        f"<div style='flex:0 0 {w};text-align:{a};padding:0 4px;"
        f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:{fg}'>"
        f"{row_dict.get(fld, '')}</div>"
        for _, fld, w, a in col_spec
    )
    return (
        f"<div style='display:flex;align-items:center;background:{bg};"
        f"font-size:0.77rem;padding:3px 0;"
        f"font-family:monospace;border-bottom:1px solid rgba(0,0,0,0.1)'>"
        + cells + "</div>"
    )


def _render_row_news(ticker: str, panel_label: str = "Recent news") -> None:
    """Render a collapsed news expander for one ticker row."""
    with st.expander(f"{ticker}  ·  {panel_label}", expanded=False):
        items = fetch_news(ticker)
        if not items:
            st.caption("No recent news found.")
            return
        for item in items:
            title = item.get("title", "")
            link = item.get("link", "#")
            publisher = item.get("publisher", "")
            age = _fmt_news_age(item)
            color = _publisher_color(publisher)
            st.markdown(
                f"<div style='margin:3px 0 5px 0;line-height:1.35'>"
                f"<span style='color:{color};font-weight:700;font-size:0.71rem'>{publisher}</span>"
                f"<span style='color:#999;font-size:0.7rem;margin-left:6px'>{age}</span><br>"
                f"<a href='{link}' target='_blank' style='color:#222;font-size:0.8rem;"
                f"text-decoration:none;line-height:1.3'>{title}</a>"
                f"</div>",
                unsafe_allow_html=True,
            )
        st.caption("If a headline raises concern, toggle a red flag in the sidebar.")


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
    signals = tier_disp["_signal"].tolist()
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

    signal_series = pd.Series(signals)
    styled = _style_df(tier_disp, signal_series)
    _table_kwargs: dict = {
        "use_container_width": True,
        "hide_index": True,
        "column_config": {"Ticker": st.column_config.TextColumn("Ticker")},
    }
    if tier_name in ("Tier 1", "Tier 2"):
        _table_kwargs["height"] = (len(tier_disp) + 1) * 35 + 10
    st.dataframe(styled, **_table_kwargs)
    st.markdown(_company_legend(tier_disp["Ticker"].tolist()), unsafe_allow_html=True)


# ── Streamlit app ─────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Munger Toll Bridge Portfolio",
        layout="wide",
        initial_sidebar_state="collapsed",
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
        ".stTabs [data-baseweb='tab']:nth-child(4){background-color:#8a9a6e !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(4):hover{background-color:#7a8a5e !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(4)[aria-selected='true']{background-color:#6a7a4e !important;color:#ffffff !important;border-bottom:3px solid #6a7a4e !important}"
        ".stTabs [data-baseweb='tab']:nth-child(5){background-color:#b88070 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(5):hover{background-color:#a87060 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(5)[aria-selected='true']{background-color:#a07060 !important;color:#ffffff !important;border-bottom:3px solid #a07060 !important}"
        ".stTabs [data-baseweb='tab']:nth-child(6){background-color:#7a7a8a !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(6):hover{background-color:#6a6a7a !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(6)[aria-selected='true']{background-color:#5a5a6a !important;color:#ffffff !important;border-bottom:3px solid #5a5a6a !important}"
        ".stTabs [data-baseweb='tab']:nth-child(7){background-color:#6e9b9b !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(7):hover{background-color:#5d8888 !important;color:#ffffff !important}"
        ".stTabs [data-baseweb='tab']:nth-child(7)[aria-selected='true']{background-color:#4d7878 !important;color:#ffffff !important;border-bottom:3px solid #4d7878 !important}"
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
        "font-size:12px;padding:3px 10px;border-radius:20px;height:auto;min-height:0;"
        "line-height:1.5;font-weight:600;background-color:#9b6e6e !important;color:#fff !important;border:none}"
        ".st-key-rf_a .stButton>button:hover{"
        "background-color:#7f5a5a !important}"
        ".st-key-rf_b .stButton>button{"
        "font-size:12px;padding:3px 10px;border-radius:20px;height:auto;min-height:0;"
        "line-height:1.5;font-weight:600;background-color:#9b6e6e !important;color:#fff !important;border:none}"
        ".st-key-rf_b .stButton>button:hover{"
        "background-color:#7f5a5a !important}"
        ".st-key-btn_b_ov .stButton>button{"
        "background-color:#6e8fa0 !important;color:#fff !important}"
        ".st-key-btn_b_ov .stButton>button:hover{"
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
        "[data-testid='element-container']:has(+[data-testid='stExpander']){"
        "margin-bottom:-10px !important}"
        ".st-key-ov_pills_a .stButton>button{"
        "font-size:12px;padding:3px 10px;border-radius:20px;height:auto;min-height:0;"
        "line-height:1.5;font-weight:600;background-color:#6e9b82;color:#fff;border:none}"
        ".st-key-ov_pills_a .stButton>button:hover{background-color:#5a8a6e}"
        ".st-key-ov_pill_b .stButton>button{"
        "font-size:12px;padding:3px 10px;border-radius:20px;height:auto;min-height:0;"
        "line-height:1.5;font-weight:600;background-color:#6e8fa0;color:#fff;border:none}"
        ".st-key-ov_pill_b .stButton>button:hover{background-color:#5a7a8c}"
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
    if "raw_rows_waitlist" not in st.session_state:
        st.session_state.raw_rows_waitlist = None
    if "last_fetched_waitlist" not in st.session_state:
        st.session_state.last_fetched_waitlist = None
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
    if "manual_metrics" not in st.session_state:
        _mm_loaded = load_manual_metrics()
        st.session_state.manual_metrics = _mm_loaded
        # Snapshot of last-saved values used to detect per-field changes on save
        st.session_state.manual_metrics_saved = {
            k: {"value": v["value"], "updated": v["updated"]} for k, v in _mm_loaded.items()
        }
    if "custom_tickers" not in st.session_state:
        st.session_state.custom_tickers = load_custom_tickers()
    if "raw_rows_custom_a" not in st.session_state:
        st.session_state.raw_rows_custom_a = None
    if "raw_rows_custom_b" not in st.session_state:
        st.session_state.raw_rows_custom_b = None
    if "add_stock_preview" not in st.session_state:
        st.session_state.add_stock_preview = None
    if "add_stock_preview_a" not in st.session_state:
        st.session_state.add_stock_preview_a = None
    if "add_stock_preview_b" not in st.session_state:
        st.session_state.add_stock_preview_b = None
    if "custom_waitlist" not in st.session_state:
        st.session_state.custom_waitlist = load_wait_list_custom()
    if "add_wl_preview" not in st.session_state:
        st.session_state.add_wl_preview = None
    if "mos_pct" not in st.session_state:
        st.session_state.mos_pct = DEFAULT_MOS_PCT
    if "mos_pct_b" not in st.session_state:
        st.session_state.mos_pct_b = DEFAULT_MOS_PCT

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

    # ── Sidebar removed — controls moved inline into each tab ─────────────────

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("Munger Toll Bridge Portfolio")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_a, tab_b, tab_r, tab_w, tab_m, tab_ms, tab_d, tab_n = st.tabs(["Portfolio A", "Portfolio B", "Retired", "Wait List", "Macro Signals", "Market Signals", "Deployment", "News"])

    # ══════════════════════════════════════════════════════════════════════════
    # PORTFOLIO A
    # ══════════════════════════════════════════════════════════════════════════
    with tab_a:
        col_refresh_a, col_ts_a = st.columns([1, 4])
        with col_refresh_a:
            if st.button("Refresh Data", key="refresh_a", type="primary", use_container_width=True):
                fetch_info.clear()
                fetch_news.clear()
                st.session_state.raw_rows = None
                st.session_state.raw_rows_custom_a = None

        # ── Dream MoS slider (inline, compact) ───────────────────────────────
        _mos_c1_a, _mos_c2_a = st.columns([2, 3])
        with _mos_c1_a:
            def _sync_mos_to_b():
                st.session_state.mos_pct_b = st.session_state.mos_pct
            st.slider(
                "Dream MoS %  ·  both portfolios",
                min_value=10, max_value=50, step=5,
                key="mos_pct",
                on_change=_sync_mos_to_b,
                help="Dream = Fair × (1 − MoS%).  Shared with Portfolio B tab.",
            )
        mos_pct = st.session_state.mos_pct

        # ── Fair Multiple Override pills (Portfolio A) ────────────────────────
        with st.container(key="ov_pills_a"):
            _pl_a, _pc1_a, _pc2_a, _pc3_a, _pad_a = st.columns([2.5, 0.9, 0.9, 0.9, 3.8])
            with _pl_a:
                st.markdown(
                    "<span style='font-size:0.82rem;font-weight:700;color:#333;"
                    "line-height:2.4'>Fair Multiple Overrides:</span>",
                    unsafe_allow_html=True,
                )
            with _pc1_a:
                if st.button("Tier 1", key="btn_a_fair_t1", use_container_width=True):
                    st.session_state.accordion_overrides_a = (
                        None if st.session_state.accordion_overrides_a == "Tier 1" else "Tier 1"
                    )
            with _pc2_a:
                if st.button("Tier 2", key="btn_a_fair_t2", use_container_width=True):
                    st.session_state.accordion_overrides_a = (
                        None if st.session_state.accordion_overrides_a == "Tier 2" else "Tier 2"
                    )
            with _pc3_a:
                if st.button("Tier 3", key="btn_a_fair_t3", use_container_width=True):
                    st.session_state.accordion_overrides_a = (
                        None if st.session_state.accordion_overrides_a == "Tier 3" else "Tier 3"
                    )

        for _tier_name in ["Tier 1", "Tier 2", "Tier 3"]:
            if st.session_state.accordion_overrides_a == _tier_name:
                _td_ov = PORTFOLIO[_tier_name]
                st.markdown(
                    f"<p style='font-size:0.8rem;font-weight:700;color:#5a7f6a;"
                    f"margin:4px 0 2px 0'>{_tier_name} — Fair Multiple Overrides</p>",
                    unsafe_allow_html=True,
                )
                _ov_tickers_a = _td_ov["tickers"]
                for _row_s in range(0, len(_ov_tickers_a), 4):
                    _row_tks = _ov_tickers_a[_row_s:_row_s + 4]
                    _ov_cols_a = st.columns(4)
                    for _ci, _tk in enumerate(_row_tks):
                        with _ov_cols_a[_ci]:
                            _dv = float(FAIR_PB.get(_tk, _td_ov["fair_pe"]))
                            st.number_input(
                                f"{_tk} ({'P/B' if _tk in USES_PB else 'P/E'})",
                                min_value=0.1, max_value=200.0,
                                value=_dv, step=0.5,
                                key=f"ov_{_tk}",
                            )

        # Compute fair_overrides from session state (persists whether panel is open)
        fair_overrides: dict[str, Optional[float]] = {}
        for _tier_name, _td in PORTFOLIO.items():
            for _tk in _td["tickers"]:
                _default_val = float(FAIR_PB.get(_tk, _td["fair_pe"]))
                _val = st.session_state.get(f"ov_{_tk}", _default_val)
                fair_overrides[_tk] = _val if _val != _default_val else None

        # ── Red Flags pills (Portfolio A) ─────────────────────────────────────
        with st.container(key="rf_a"):
            _rfl_a, _rfc1_a, _rfc2_a, _rfc3_a, _rpad_a = st.columns([2.5, 0.9, 0.9, 0.9, 3.8])
            with _rfl_a:
                st.markdown(
                    "<span style='font-size:0.82rem;font-weight:700;color:#7a4a4a;"
                    "line-height:2.4'>Red Flags:</span>",
                    unsafe_allow_html=True,
                )
            with _rfc1_a:
                if st.button("Tier 1", key="btn_a_rf_t1", use_container_width=True):
                    st.session_state.accordion_redflags_a = (
                        None if st.session_state.accordion_redflags_a == "Tier 1" else "Tier 1"
                    )
            with _rfc2_a:
                if st.button("Tier 2", key="btn_a_rf_t2", use_container_width=True):
                    st.session_state.accordion_redflags_a = (
                        None if st.session_state.accordion_redflags_a == "Tier 2" else "Tier 2"
                    )
            with _rfc3_a:
                if st.button("Tier 3", key="btn_a_rf_t3", use_container_width=True):
                    st.session_state.accordion_redflags_a = (
                        None if st.session_state.accordion_redflags_a == "Tier 3" else "Tier 3"
                    )

        _flags_a_changed = False
        for _tier_name in ["Tier 1", "Tier 2", "Tier 3"]:
            if st.session_state.accordion_redflags_a == _tier_name:
                _td_rf = PORTFOLIO[_tier_name]
                st.markdown(
                    f"<p style='font-size:0.8rem;font-weight:700;color:#9b6e6e;"
                    f"margin:4px 0 2px 0'>{_tier_name} — Red Flags</p>",
                    unsafe_allow_html=True,
                )
                for _tk in _td_rf["tickers"]:
                    st.markdown(f"**{_tk}**")
                    _rf_cols = st.columns(len(FLAG_NAMES))
                    for _fi, _fl in enumerate(FLAG_NAMES):
                        with _rf_cols[_fi]:
                            _cur = st.session_state.red_flags.get(_tk, {}).get(_fl, False)
                            _new = st.checkbox(_fl, value=_cur, key=f"rf_{_tk}_{_fl}")
                            if _new != _cur:
                                st.session_state.red_flags[_tk][_fl] = _new
                                _flags_a_changed = True

        if _flags_a_changed:
            save_red_flags(st.session_state.red_flags)
            st.session_state.raw_rows = None
            st.session_state.raw_rows_custom_a = None
            st.rerun()

        if st.session_state.raw_rows is None:
            progress = st.progress(0, text="Fetching market data…")
            raw_rows: list[dict] = []
            for i, tk in enumerate(ALL_TICKERS):
                override = fair_overrides.get(tk)
                raw_rows.append(
                    compute_row(tk, override, mos_pct, st.session_state.red_flags, _TICKER_META,
                                manual_metrics=st.session_state.manual_metrics)
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

        # ── Add a Stock to Portfolio A ────────────────────────────────────────
        st.markdown("""<style>
        .st-key-add_stock_a_wrap details summary {
            background-color: #6e9b82 !important;
            color: white !important;
            border-radius: 4px;
        }
        .st-key-add_stock_a_wrap details summary svg { fill: white !important; stroke: white !important; }
        </style>""", unsafe_allow_html=True)
        with st.container(key="add_stock_a_wrap"):
            with st.expander("+ Add a Stock to Portfolio A", expanded=False):
                _a1, _a2 = st.columns([2, 2])
                with _a1:
                    st.text_input("Ticker Symbol", key="add_a_ticker", placeholder="e.g. NVDA")
                with _a2:
                    st.number_input("Fair P/E", min_value=0.1, max_value=200.0, value=20.0, step=0.5, key="add_a_fair_pe")
                _ab1, _ab2, _ab3 = st.columns([1.5, 1.5, 5])
                with _ab1:
                    if st.button("Fetch & Preview", key="btn_a_fetch", use_container_width=True):
                        _atk = st.session_state.get("add_a_ticker", "").strip().upper()
                        if _atk:
                            _ainfo = fetch_info(_atk)
                            _afins = fetch_financials(_atk)
                            st.session_state.add_stock_preview_a = {"ticker": _atk, "info": _ainfo, "fins": _afins}
                        else:
                            st.session_state.add_stock_preview_a = None
                with _ab2:
                    if st.button("Add to Portfolio A", key="btn_a_add", use_container_width=True):
                        _atk = st.session_state.get("add_a_ticker", "").strip().upper()
                        _afpe = float(st.session_state.get("add_a_fair_pe", 20.0))
                        _all_ex = set(ALL_TICKERS) | set(ALL_TICKERS_B) | {_ct["ticker"] for _ct in st.session_state.custom_tickers}
                        if not _atk:
                            st.warning("Enter a ticker symbol.")
                        elif _atk in _all_ex:
                            st.warning(f"{_atk} already in portfolios.")
                        else:
                            _new = {"ticker": _atk, "portfolio": "A", "fair_pe": _afpe}
                            st.session_state.custom_tickers.append(_new)
                            save_custom_tickers(st.session_state.custom_tickers)
                            st.session_state.red_flags[_atk] = {f: False for f in FLAG_NAMES}
                            save_red_flags(st.session_state.red_flags)
                            st.session_state.raw_rows_custom_a = None
                            st.session_state.add_stock_preview_a = None
                            st.rerun()
                _prev_a = st.session_state.add_stock_preview_a
                if _prev_a:
                    _pai = _prev_a["info"]
                    _paf = _prev_a["fins"]
                    _pa_price = _price_from_info(_pai)
                    _pa_fcfy_raw = (_float(_pai, "freeCashflow") or 0) / (_float(_pai, "marketCap") or 1) * 100 if _float(_pai, "marketCap") else None
                    _pa_de_raw = _float(_pai, "debtToEquity")
                    _pa_de = _pa_de_raw / 100.0 if _pa_de_raw is not None else None
                    _pa_op = _paf.get("operatingIncome"); _pa_tax = _paf.get("taxRate"); _pa_ta = _paf.get("totalAssets"); _pa_cl = _paf.get("currentLiabilities"); _pa_cash = _paf.get("cash")
                    if all(x is not None for x in [_pa_op, _pa_tax, _pa_ta, _pa_cl, _pa_cash]) and (_pa_ta - _pa_cl - _pa_cash) > 0:
                        _pa_roic = _pa_op * (1 - _pa_tax) / (_pa_ta - _pa_cl - _pa_cash) * 100
                    else:
                        _pa_roic = None
                    st.markdown(
                        f"**{_prev_a['ticker']}** — "
                        f"Price: {'${:,.2f}'.format(_pa_price) if _pa_price else '—'}  ·  "
                        f"ROIC: {'{:.1f}%'.format(_pa_roic) if _pa_roic else '—'}  ·  "
                        f"FCFy: {'{:.1f}%'.format(_pa_fcfy_raw) if _pa_fcfy_raw else '—'}  ·  "
                        f"D/E: {'{:.2f}×'.format(_pa_de) if _pa_de is not None else '—'}"
                    )

        # ── Custom tickers (Portfolio A) ──────────────────────────────────────
        _custom_a = [_ct for _ct in st.session_state.custom_tickers if _ct["portfolio"] == "A"]
        if _custom_a:
            if st.session_state.raw_rows_custom_a is None:
                _custom_rows_a: list[dict] = []
                for _ci, _ct in enumerate(_custom_a, start=1):
                    _ctk = _ct["ticker"]
                    _cmeta = {_ctk: {"tier": "Custom", "rank": _ci, "base_fair": _ct["fair_pe"], "is_custom": True}}
                    _custom_rows_a.append(
                        compute_row(_ctk, None, mos_pct, st.session_state.red_flags, _cmeta,
                                    manual_metrics=st.session_state.manual_metrics)
                    )
                st.session_state.raw_rows_custom_a = _custom_rows_a
            _df_raw_ca = pd.DataFrame(st.session_state.raw_rows_custom_a)
            _df_disp_ca = build_display_df(st.session_state.raw_rows_custom_a)
            _n_buy_ca = (_df_raw_ca["Decision"] == "BUY").sum()
            st.subheader(f"Custom Watchlist  ·  BUY signals: {_n_buy_ca}")
            _ca_disp = _df_disp_ca[DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
            _ca_signals = _ca_disp["_signal"].tolist()
            _ca_disp = _ca_disp[DISPLAY_COLS].copy()
            _ca_sig_series = pd.Series(_ca_signals)
            _ca_styled = _style_df(_ca_disp, _ca_sig_series)
            st.dataframe(_ca_styled, use_container_width=True, hide_index=True)

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
Each stock is evaluated against thresholds specific to its business category.
A threshold of **—** means that check is skipped for the category.

| Category | ROIC% ≥ | FCF Yield% ≥ | Rev Growth% ≥ | D/E ≤ |
|---|---|---|---|---|
| asset_light | 25 | 2.0 | 8 | 0.5 |
| toll_financial | 15 | 2.0 | 5 | 2.0 |
| bank | — | 2.5 | 3 | — |
| insurance | — | — | 5 | — |
| railroad | 10 | 2.5 | 3 | 1.5 |
| infrastructure | 8 | 2.5 | 3 | 2.5 |
| consumer_staples | 12 | 3.0 | 2 | 1.5 |
| energy | 10 | 4.0 | 0 | 0.5 |
| mlp | — | 4.0 | 2 | 3.5 |
| royalty | 8 | 3.0 | 5 | 0.3 |
| industrial | 15 | 2.5 | 5 | 1.0 |
| pharma | 15 | — | 5 | 1.0 |
| airport | 8 | 2.5 | 3 | 1.5 |
| special_azo | 15 | 3.0 | 3 | — |
| tic | 12 | 2.5 | 3 | 2.0 |
| *(default)* | 15 | 3.5 | 0 | 0.5 |

ROIC = NOPAT / Invested Capital, where NOPAT = operatingIncome × (1 − effectiveTaxRate) and Invested Capital = totalAssets − currentLiabilities − cash.

RevGr% = 3-year revenue CAGR computed from annual Total Revenue: (revenue_year0 / revenue_year3)^(1/3) − 1. Requires at least 3 annual data points; shown as N/A otherwise. Does not fall back to TTM YoY (which can reflect a single bad quarter).

**BUY = Signal (DREAM or FAIR) AND Quality PASS AND no Red Flags active.**
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
                fetch_news.clear()
                st.session_state.raw_rows_b = None
                st.session_state.raw_rows_custom_b = None

        # ── Dream MoS slider (inline, compact) ───────────────────────────────
        _mos_c1_b, _mos_c2_b = st.columns([2, 3])
        with _mos_c1_b:
            def _sync_mos_to_a():
                st.session_state.mos_pct = st.session_state.mos_pct_b
            st.slider(
                "Dream MoS %  ·  both portfolios",
                min_value=10, max_value=50, step=5,
                key="mos_pct_b",
                on_change=_sync_mos_to_a,
                help="Dream = Fair × (1 − MoS%).  Shared with Portfolio A tab.",
            )
        mos_pct = st.session_state.mos_pct_b

        # ── Fair P/E Override pill (Portfolio B) ──────────────────────────────
        with st.container(key="ov_pill_b"):
            _pl_b, _pb_btn, _pad_b = st.columns([2.5, 1.2, 5.3])
            with _pl_b:
                st.markdown(
                    "<span style='font-size:0.82rem;font-weight:700;color:#333;"
                    "line-height:2.4'>Fair P/E Overrides:</span>",
                    unsafe_allow_html=True,
                )
            with _pb_btn:
                if st.button("Overrides", key="btn_b_ov", use_container_width=True):
                    st.session_state.pill_b_ov = not st.session_state.pill_b_ov

        if st.session_state.pill_b_ov:
            st.markdown(
                "<p style='font-size:0.8rem;font-weight:700;color:#6e8fa0;"
                "margin:4px 0 2px 0'>Portfolio B — Fair P/E Overrides</p>",
                unsafe_allow_html=True,
            )
            _b_ov_items = list(PORTFOLIO_B_TICKERS.items())
            for _row_s_b in range(0, len(_b_ov_items), 4):
                _row_b = _b_ov_items[_row_s_b:_row_s_b + 4]
                _ov_cols_b = st.columns(4)
                for _ci_b, (_tk_b, _dp_b) in enumerate(_row_b):
                    with _ov_cols_b[_ci_b]:
                        st.number_input(
                            f"{_tk_b} (P/E)",
                            min_value=0.1, max_value=200.0,
                            value=float(_dp_b), step=0.5,
                            key=f"ov_b_{_tk_b}",
                        )

        # Compute fair_overrides_b from session state (persists whether panel is open)
        fair_overrides_b: dict[str, Optional[float]] = {}
        for _tk_b, _default_pe in PORTFOLIO_B_TICKERS.items():
            _val_b = st.session_state.get(f"ov_b_{_tk_b}", float(_default_pe))
            fair_overrides_b[_tk_b] = _val_b if _val_b != _default_pe else None

        # ── Red Flags pills (Portfolio B) ─────────────────────────────────────
        _B_DEFENSIVES = ["PG", "KO", "PM", "CHD", "CL", "ABBV", "JNJ"]
        _B_GROWTH = [
            "NEE", "PGR", "PLD", "TXN", "XOM", "BLK", "BIP",
            "CB", "AVGO", "FCX", "ITW", "EOG", "EMR", "KMI",
        ]

        with st.container(key="rf_b"):
            _rfl_b, _rfc1_b, _rfc2_b, _rpad_b = st.columns([2.5, 1.2, 1.2, 4.1])
            with _rfl_b:
                st.markdown(
                    "<span style='font-size:0.82rem;font-weight:700;color:#7a4a4a;"
                    "line-height:2.4'>Red Flags:</span>",
                    unsafe_allow_html=True,
                )
            with _rfc1_b:
                if st.button("Defensives", key="btn_b_rf_def", use_container_width=True):
                    st.session_state.accordion_redflags_b = (
                        None if st.session_state.accordion_redflags_b == "Defensives" else "Defensives"
                    )
            with _rfc2_b:
                if st.button("Growth/Infra", key="btn_b_rf_growth", use_container_width=True):
                    st.session_state.accordion_redflags_b = (
                        None if st.session_state.accordion_redflags_b == "Growth/Infra" else "Growth/Infra"
                    )

        _flags_b_changed = False
        for _label_b, _tickers_b in [("Defensives", _B_DEFENSIVES), ("Growth/Infra", _B_GROWTH)]:
            if st.session_state.accordion_redflags_b == _label_b:
                st.markdown(
                    f"<p style='font-size:0.8rem;font-weight:700;color:#9b6e6e;"
                    f"margin:4px 0 2px 0'>{_label_b} — Red Flags</p>",
                    unsafe_allow_html=True,
                )
                for _tk_rf in _tickers_b:
                    st.markdown(f"**{_tk_rf}**")
                    _rf_cols_b = st.columns(len(FLAG_NAMES))
                    for _fi_b, _fl_b in enumerate(FLAG_NAMES):
                        with _rf_cols_b[_fi_b]:
                            _cur_b = st.session_state.red_flags_b.get(_tk_rf, {}).get(_fl_b, False)
                            _new_b = st.checkbox(_fl_b, value=_cur_b, key=f"rf_b_{_tk_rf}_{_fl_b}")
                            if _new_b != _cur_b:
                                st.session_state.red_flags_b[_tk_rf][_fl_b] = _new_b
                                _flags_b_changed = True

        if _flags_b_changed:
            save_red_flags_b(st.session_state.red_flags_b)
            st.session_state.raw_rows_b = None
            st.session_state.raw_rows_custom_b = None
            st.rerun()

        if st.session_state.raw_rows_b is None:
            progress_b = st.progress(0, text="Fetching market data…")
            raw_rows_b: list[dict] = []
            for i, tk in enumerate(ALL_TICKERS_B):
                override = fair_overrides_b.get(tk)
                raw_rows_b.append(
                    compute_row(tk, override, mos_pct, st.session_state.red_flags_b, _TICKER_META_B,
                                manual_metrics=st.session_state.manual_metrics)
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
        signals_b = tier_disp_b["_signal"].tolist()
        tier_disp_b = tier_disp_b[DISPLAY_COLS].copy()
        n_buy_b = (df_raw_b["Decision"] == "BUY").sum()

        st.subheader(
            f"Portfolio B  ·  Per-ticker Fair P/E  ·  "
            f"MoS {mos_pct}%  ·  BUY signals: {n_buy_b}"
        )

        _b_signal_series = pd.Series(signals_b)
        _b_styled = _style_df(tier_disp_b, _b_signal_series)
        st.dataframe(
            _b_styled,
            use_container_width=True,
            hide_index=True,
            height=(len(tier_disp_b) + 1) * 35 + 10,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker")
            },
        )
        st.markdown(_company_legend(tier_disp_b["Ticker"].tolist()), unsafe_allow_html=True)

        # ── Add a Stock to Portfolio B ────────────────────────────────────────
        st.markdown("""<style>
        .st-key-add_stock_b_wrap details summary {
            background-color: #6e8fa0 !important;
            color: white !important;
            border-radius: 4px;
        }
        .st-key-add_stock_b_wrap details summary svg { fill: white !important; stroke: white !important; }
        </style>""", unsafe_allow_html=True)
        with st.container(key="add_stock_b_wrap"):
            with st.expander("+ Add a Stock to Portfolio B", expanded=False):
                _b1, _b2 = st.columns([2, 2])
                with _b1:
                    st.text_input("Ticker Symbol", key="add_b_ticker", placeholder="e.g. NVDA")
                with _b2:
                    st.number_input("Fair P/E", min_value=0.1, max_value=200.0, value=20.0, step=0.5, key="add_b_fair_pe")
                _bb1, _bb2, _bb3 = st.columns([1.5, 1.5, 5])
                with _bb1:
                    if st.button("Fetch & Preview", key="btn_b_fetch", use_container_width=True):
                        _btk = st.session_state.get("add_b_ticker", "").strip().upper()
                        if _btk:
                            _binfo = fetch_info(_btk)
                            _bfins = fetch_financials(_btk)
                            st.session_state.add_stock_preview_b = {"ticker": _btk, "info": _binfo, "fins": _bfins}
                        else:
                            st.session_state.add_stock_preview_b = None
                with _bb2:
                    if st.button("Add to Portfolio B", key="btn_b_add", use_container_width=True):
                        _btk = st.session_state.get("add_b_ticker", "").strip().upper()
                        _bfpe = float(st.session_state.get("add_b_fair_pe", 20.0))
                        _all_ex_b = set(ALL_TICKERS) | set(ALL_TICKERS_B) | {_ct["ticker"] for _ct in st.session_state.custom_tickers}
                        if not _btk:
                            st.warning("Enter a ticker symbol.")
                        elif _btk in _all_ex_b:
                            st.warning(f"{_btk} already in portfolios.")
                        else:
                            _new_b = {"ticker": _btk, "portfolio": "B", "fair_pe": _bfpe}
                            st.session_state.custom_tickers.append(_new_b)
                            save_custom_tickers(st.session_state.custom_tickers)
                            st.session_state.red_flags_b[_btk] = {f: False for f in FLAG_NAMES}
                            save_red_flags_b(st.session_state.red_flags_b)
                            st.session_state.raw_rows_custom_b = None
                            st.session_state.add_stock_preview_b = None
                            st.rerun()
                _prev_b = st.session_state.add_stock_preview_b
                if _prev_b:
                    _pbi = _prev_b["info"]
                    _pbf = _prev_b["fins"]
                    _pb_price = _price_from_info(_pbi)
                    _pb_fcfy_raw = (_float(_pbi, "freeCashflow") or 0) / (_float(_pbi, "marketCap") or 1) * 100 if _float(_pbi, "marketCap") else None
                    _pb_de_raw = _float(_pbi, "debtToEquity")
                    _pb_de = _pb_de_raw / 100.0 if _pb_de_raw is not None else None
                    _pb_op = _pbf.get("operatingIncome"); _pb_tax = _pbf.get("taxRate"); _pb_ta = _pbf.get("totalAssets"); _pb_cl = _pbf.get("currentLiabilities"); _pb_cash = _pbf.get("cash")
                    if all(x is not None for x in [_pb_op, _pb_tax, _pb_ta, _pb_cl, _pb_cash]) and (_pb_ta - _pb_cl - _pb_cash) > 0:
                        _pb_roic = _pb_op * (1 - _pb_tax) / (_pb_ta - _pb_cl - _pb_cash) * 100
                    else:
                        _pb_roic = None
                    st.markdown(
                        f"**{_prev_b['ticker']}** — "
                        f"Price: {'${:,.2f}'.format(_pb_price) if _pb_price else '—'}  ·  "
                        f"ROIC: {'{:.1f}%'.format(_pb_roic) if _pb_roic else '—'}  ·  "
                        f"FCFy: {'{:.1f}%'.format(_pb_fcfy_raw) if _pb_fcfy_raw else '—'}  ·  "
                        f"D/E: {'{:.2f}×'.format(_pb_de) if _pb_de is not None else '—'}"
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
                        compute_row(_ctk, None, mos_pct, st.session_state.red_flags_b, _cmeta,
                                    manual_metrics=st.session_state.manual_metrics)
                    )
                st.session_state.raw_rows_custom_b = _custom_rows_b
            _df_raw_cb = pd.DataFrame(st.session_state.raw_rows_custom_b)
            _df_disp_cb = build_display_df(st.session_state.raw_rows_custom_b)
            _n_buy_cb = (_df_raw_cb["Decision"] == "BUY").sum()
            st.subheader(f"Custom Watchlist  ·  BUY signals: {_n_buy_cb}")
            _cb_disp = _df_disp_cb[DISPLAY_COLS + ["_signal"]].reset_index(drop=True)
            _cb_signals = _cb_disp["_signal"].tolist()
            _cb_disp = _cb_disp[DISPLAY_COLS].copy()
            _cb_sig_series = pd.Series(_cb_signals)
            _cb_styled = _style_df(_cb_disp, _cb_sig_series)
            st.dataframe(_cb_styled, use_container_width=True, hide_index=True)

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
| ITRK.L | 22 | Intertek — TIC leader, asset-light global testing network, pricing power |
| BVI.PA | 20 | Bureau Veritas — TIC compounder, trade/infrastructure inspection moat |

**TIC category (Testing, Inspection & Certification):** Regulated, asset-light, global trade compounders.
Thresholds: ROIC ≥ 12%, FCF Yield ≥ 2.5%, RevGr ≥ 3%, D/E < 2.0.

**BUY = Signal (DREAM or FAIR) AND Quality PASS AND no Red Flags active.**
Quality thresholds are category-specific (see Quality Gate Rules in Portfolio A for the full table).
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
                fetch_news.clear()
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
        df_retired = pd.DataFrame(retired_records)  # kept for CSV download

        st.subheader(f"Retired Positions  ·  {len(RETIRED_STOCKS)} stocks")

        def _style_retired_row(row):
            from_val = row.get("From", "")
            if from_val == "A":
                return ["background-color:#d4e6dc;color:#1a3a2a"] * len(row)
            elif from_val == "B":
                return ["background-color:#d4e0e6;color:#1a2a3a"] * len(row)
            return [""] * len(row)
        _retired_styled = df_retired.style.apply(_style_retired_row, axis=1)
        st.dataframe(
            _retired_styled,
            use_container_width=True,
            hide_index=True,
            height=(len(df_retired) + 1) * 35 + 10,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker")
            },
        )
        st.markdown(_company_legend([s["ticker"] for s in RETIRED_STOCKS]), unsafe_allow_html=True)

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
    # WAIT LIST
    # ══════════════════════════════════════════════════════════════════════════
    with tab_w:
        st.markdown(
            "<div style='background:#6a7a4e;color:#fff;padding:10px 16px;border-radius:6px;"
            "margin-bottom:12px'>"
            "<strong>Wait List</strong> — Entry price targets for both existing holdings and new positions. "
            "Status: <b>AT TARGET</b> = price within or below entry range · "
            "<b>APPROACHING</b> = within 15% above range · <b>NOT YET</b> = more than 15% above range."
            "</div>",
            unsafe_allow_html=True,
        )

        col_refresh_w, col_ts_w = st.columns([1, 4])
        with col_refresh_w:
            if st.button("Refresh Data", key="refresh_w", type="primary", use_container_width=True):
                fetch_info.clear()
                st.session_state.raw_rows_waitlist = None

        if st.session_state.raw_rows_waitlist is None:
            _all_wl_stocks = WAIT_LIST + st.session_state.custom_waitlist
            progress_w = st.progress(0, text="Fetching market data…")
            raw_rows_waitlist: list[dict] = []
            for i, stock in enumerate(_all_wl_stocks):
                raw_rows_waitlist.append(compute_waitlist_row(stock))
                progress_w.progress((i + 1) / len(_all_wl_stocks), text=f"Fetching {stock['ticker']}…")
            progress_w.empty()
            st.session_state.raw_rows_waitlist = raw_rows_waitlist
            st.session_state.last_fetched_waitlist = datetime.now()

        raw_rows_waitlist = st.session_state.raw_rows_waitlist

        fetched_str_w = (
            st.session_state.last_fetched_waitlist.strftime("%Y-%m-%d  %H:%M:%S")
            if st.session_state.last_fetched_waitlist else "—"
        )
        with col_ts_w:
            st.caption(
                f"Last fetched: **{fetched_str_w}**  ·  "
                f"Data: Yahoo Finance (yfinance)"
            )

        # ── Combined summary metrics (both sections) ──────────────────────────
        _wl_target     = sum(1 for r in raw_rows_waitlist if r["status"] == "AT TARGET")
        _wl_approach   = sum(1 for r in raw_rows_waitlist if r["status"] == "APPROACHING")
        _wl_not_yet    = sum(1 for r in raw_rows_waitlist if r["status"] == "NOT YET")
        _wmc1, _wmc2, _wmc3, _wmc4 = st.columns(4)
        _wmc1.metric("AT TARGET (in range)", _wl_target, delta_color="off")
        _wmc2.metric("APPROACHING (≤15% above)", _wl_approach, delta_color="off")
        _wmc3.metric("NOT YET (>15% above)", _wl_not_yet, delta_color="off")
        _wmc4.metric("Total Watching", len(WAIT_LIST), delta_color="off")

        st.divider()

        # ── Status color maps ─────────────────────────────────────────────────
        _WL_STATUS_BG: dict[str, str] = {
            "AT TARGET":  "#5a8a5a",   # sage green
            "APPROACHING": "#b8860b",  # amber
            "NOT YET":    "#777777",   # grey
            "N/A":        "#777777",
        }
        _WL_STATUS_FG: dict[str, str] = {
            "AT TARGET":  "#e8f4e8",
            "APPROACHING": "#fff8e0",
            "NOT YET":    "#dddddd",
            "N/A":        "#dddddd",
        }
        _WL_ROW_BG: dict[str, str] = {
            "AT TARGET":  "#c8dfc8",   # light sage green
            "APPROACHING": "#f0e0a0",  # light amber
            "NOT YET":    "#e0e0e0",   # light grey
            "N/A":        "#d8d8d8",
        }
        _WL_ROW_FG: dict[str, str] = {
            "AT TARGET":  "#1a3a1a",
            "APPROACHING": "#3d2800",
            "NOT YET":    "#444444",
            "N/A":        "#555555",
        }

        # ── Column definitions ────────────────────────────────────────────────
        _WL_COLS: list[tuple[str, str, str]] = [
            # (header, width, align)
            ("Ticker",          "11%",  "left"),
            ("Price",           "7%",   "right"),
            ("P/E",             "5%",   "right"),
            ("Entry Range",     "12%",  "center"),
            ("Entry P/E Tgt",   "8%",   "center"),
            ("Add More At",     "9%",   "right"),
            ("% Gap",           "7%",   "right"),
            ("STATUS",          "7%",   "center"),
            ("Note",            "34%",  "left"),
        ]

        _wl_header_html = (
            "<div style='display:flex;align-items:center;"
            "background:#555;color:#fff;"
            "font-size:0.71rem;font-weight:700;padding:4px 0;"
            "font-family:monospace;border-radius:3px 3px 0 0'>"
            + "".join(
                f"<div style='flex:0 0 {w};text-align:{a};padding:0 5px;"
                f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis'>{h}</div>"
                for h, w, a in _WL_COLS
            )
            + "</div>"
        )

        def _wl_rows_html(rows: list[dict]) -> str:
            """Render a list of waitlist row dicts as HTML table rows."""
            html = ""
            for r in rows:
                _status = r["status"]
                _bg = _WL_ROW_BG.get(_status, "#d8d8d8")
                _fg = _WL_ROW_FG.get(_status, "#555555")
                _sbg = _WL_STATUS_BG.get(_status, "#777777")
                _sfg = _WL_STATUS_FG.get(_status, "#dddddd")

                _sym = r["currency_symbol"]
                _metric_lbl = r["metric"]

                # Format price
                if r["price"] is not None:
                    if _sym == "¥":
                        _price_str = f"¥{r['price']:,.0f}"
                    elif _sym == "C$":
                        _price_str = f"C${r['price']:,.2f}"
                    else:
                        _price_str = f"${r['price']:,.2f}"
                else:
                    _price_str = "—"

                # Format P/E
                _pe_str = f"{r['pe']:.1f}" if r["pe"] is not None else "—"

                # Format entry range
                if _sym == "¥":
                    _range_str = f"¥{r['entry_low']:,.0f}–{r['entry_high']:,.0f}"
                elif _sym == "C$":
                    _range_str = f"C${r['entry_low']:,.0f}–{r['entry_high']:,.0f}"
                else:
                    _range_str = f"${r['entry_low']:,.0f}–{r['entry_high']:,.0f}"

                # Format entry target
                _tgt_str = f"{_metric_lbl} {r['entry_pe_target']}×"

                # Format add-more-at
                if _sym == "¥":
                    _add_str = f"¥{r['add_more_at']:,.0f}"
                elif _sym == "C$":
                    _add_str = f"C${r['add_more_at']:,.0f}"
                else:
                    _add_str = f"${r['add_more_at']:,.0f}"

                # Format gap
                if r["gap_pct"] is not None:
                    _gap_str = f"{r['gap_pct']:+.1f}%"
                else:
                    _gap_str = "—"

                # Status pill
                _status_pill = (
                    f"<span style='background:{_sbg};color:{_sfg};"
                    f"padding:2px 6px;border-radius:10px;font-size:0.72rem;"
                    f"font-weight:700;white-space:nowrap'>{_status}</span>"
                )

                _cells_data = [
                    (r["display_ticker"], "11%", "left"),
                    (_price_str,          "7%",  "right"),
                    (_pe_str,             "5%",  "right"),
                    (_range_str,          "12%", "center"),
                    (_tgt_str,            "8%",  "center"),
                    (_add_str,            "9%",  "right"),
                    (_gap_str,            "7%",  "right"),
                    (_status_pill,        "7%",  "center"),
                    (r["note"],           "34%", "left"),
                ]

                cells_html = "".join(
                    (
                        f"<div style='flex:0 0 {w};text-align:{a};padding:0 5px;"
                        f"white-space:normal;word-wrap:break-word;color:{_fg}'>"
                        if w == "34%"
                        else
                        f"<div style='flex:0 0 {w};text-align:{a};padding:0 5px;"
                        f"overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:{_fg}'>"
                    ) + f"{val}</div>"
                    for val, w, a in _cells_data
                )
                html += (
                    f"<div style='display:flex;align-items:center;background:{_bg};"
                    f"font-size:0.77rem;padding:4px 0;"
                    f"font-family:monospace;border-bottom:1px solid rgba(0,0,0,0.08)'>"
                    + cells_html + "</div>"
                )
            return html

        # ── Build per-section row sets from the combined fetched list ─────────
        _add_tickers = {s["ticker"] for s in WAIT_LIST_ADD}
        _rows_add = [r for r in raw_rows_waitlist if r["ticker"] in _add_tickers]
        _rows_new = [r for r in raw_rows_waitlist if r["ticker"] not in _add_tickers]

        # ── Section 1: Add to Position ────────────────────────────────────────
        st.markdown(
            "<div style='background:#4a6080;color:#fff;padding:8px 14px;border-radius:5px;"
            "margin-top:6px;margin-bottom:6px'>"
            "<strong>Add to Position</strong> — Stocks already held in Portfolio A or B. "
            "Waiting for a lower price to size up existing positions at better valuations."
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='overflow-x:auto;width:100%'>"
            + _wl_header_html + _wl_rows_html(_rows_add)
            + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            _company_legend(["GOOGL", "V", "ASML", "COST"]),
            unsafe_allow_html=True,
        )

        st.markdown("<div style='margin-top:18px'></div>", unsafe_allow_html=True)

        # ── Add to Wait List ─────────────────────────────────────────────────
        st.markdown("""<style>
        .st-key-add_wl_wrap details summary {
            background-color: #8a9a6e !important;
            color: white !important;
            border-radius: 4px;
        }
        .st-key-add_wl_wrap details summary svg { fill: white !important; stroke: white !important; }
        </style>""", unsafe_allow_html=True)
        with st.container(key="add_wl_wrap"):
            with st.expander("+ Add to Wait List", expanded=False):
                _wl1, _wl2 = st.columns([2, 2])
                with _wl1:
                    st.text_input("Ticker Symbol", key="add_wl_ticker", placeholder="e.g. AAPL")
                with _wl2:
                    st.number_input("Fair P/E Target", min_value=0.1, max_value=500.0, value=20.0, step=0.5, key="add_wl_fair_pe")
                _wlp1, _wlp2, _wlp3 = st.columns([2, 2, 2])
                with _wlp1:
                    st.number_input("Entry Price Low", min_value=0.01, max_value=1_000_000.0, value=100.0, step=1.0, key="add_wl_low")
                with _wlp2:
                    st.number_input("Entry Price High", min_value=0.01, max_value=1_000_000.0, value=110.0, step=1.0, key="add_wl_high")
                with _wlp3:
                    st.number_input("Add More At", min_value=0.01, max_value=1_000_000.0, value=90.0, step=1.0, key="add_wl_add_more")
                st.text_area("Note", key="add_wl_note", placeholder="Thesis / why waiting…", height=68)
                _wlb1, _wlb2 = st.columns([2, 6])
                with _wlb1:
                    if st.button("Add to Wait List", key="btn_wl_add", use_container_width=True, type="primary"):
                        _wltk = st.session_state.get("add_wl_ticker", "").strip().upper()
                        _wl_existing = {s["ticker"] for s in WAIT_LIST} | {s["ticker"] for s in st.session_state.custom_waitlist}
                        if not _wltk:
                            st.warning("Enter a ticker symbol.")
                        elif _wltk in _wl_existing:
                            st.warning(f"{_wltk} is already on the Wait List.")
                        else:
                            _wl_entry = {
                                "ticker": _wltk,
                                "metric": "P/E",
                                "entry_pe_target": float(st.session_state.get("add_wl_fair_pe", 20.0)),
                                "entry_low": float(st.session_state.get("add_wl_low", 100.0)),
                                "entry_high": float(st.session_state.get("add_wl_high", 110.0)),
                                "add_more_at": float(st.session_state.get("add_wl_add_more", 90.0)),
                                "currency_symbol": "$",
                                "note": st.session_state.get("add_wl_note", ""),
                            }
                            st.session_state.custom_waitlist.append(_wl_entry)
                            save_wait_list_custom(st.session_state.custom_waitlist)
                            st.session_state.raw_rows_waitlist = None
                            st.rerun()

        # ── Section 2: New Positions ──────────────────────────────────────────
        st.markdown(
            "<div style='background:#6a5a30;color:#fff;padding:8px 14px;border-radius:5px;"
            "margin-bottom:6px'>"
            "<strong>New Positions</strong> — Quality businesses not yet in either portfolio. "
            "Each has a Munger-style fair multiple entry target; waiting for price to come to us."
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='overflow-x:auto;width:100%'>"
            + _wl_header_html + _wl_rows_html(_rows_new)
            + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            _company_legend(["EQNR", "AXP", "FICO", "CSU.TO", "KEY-6861.T", "WTKWY", "CLPBY", "DPLM.L"]),
            unsafe_allow_html=True,
        )

        st.divider()
        st.markdown(
            "<div style='font-size:0.78rem;color:#555;margin-top:4px'>"
            "<b>% Gap</b> = (current price − top of entry range) ÷ top of entry range × 100. "
            "Negative = price already within or below entry range. "
            "<b>Add More At</b> = secondary accumulation price if position opened and weakness continues."
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Entry prices and P/E targets are pre-set conviction levels, not buy recommendations. "
            "Data: Yahoo Finance via yfinance.  Not financial advice."
        )

        # ── Add Stock to Custom Watchlist ─────────────────────────────────────
        with st.expander("Add Stock to Custom Watchlist", expanded=False):
            st.markdown(
                "<p style='font-size:0.82rem;color:#555;margin:0 0 8px 0'>"
                "Add a ticker to the Portfolio A or B custom watchlist with your own fair multiple.</p>",
                unsafe_allow_html=True,
            )
            _add_c1, _add_c2, _add_c3 = st.columns([2, 2, 2])
            with _add_c1:
                st.text_input("Ticker Symbol", key="add_ticker_input", placeholder="e.g. NVDA")
            with _add_c2:
                st.selectbox(
                    "Add to Portfolio",
                    options=["Portfolio A", "Portfolio B"],
                    key="add_portfolio_select",
                )
            with _add_c3:
                st.number_input(
                    "Fair P/E (or Fair P/B)",
                    min_value=0.1, max_value=200.0,
                    value=20.0, step=0.5,
                    key="add_fair_pe_input",
                )

            _btn_col1, _btn_col2, _btn_col3 = st.columns([1.5, 1.5, 5])
            with _btn_col1:
                with st.container(key="btn_fetch_preview"):
                    if st.button("Fetch & Preview", key="btn_fetch_preview_btn", use_container_width=True):
                        _ticker_input = st.session_state.get("add_ticker_input", "").strip().upper()
                        if _ticker_input:
                            _preview_info = fetch_info(_ticker_input)
                            _preview_fins = fetch_financials(_ticker_input)
                            st.session_state.add_stock_preview = {
                                "ticker": _ticker_input,
                                "info": _preview_info,
                                "fins": _preview_fins,
                            }
                        else:
                            st.session_state.add_stock_preview = None

            with _btn_col2:
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

            _preview = st.session_state.add_stock_preview
            if _preview:
                _pinfo = _preview["info"]
                _pticker = _preview["ticker"]
                _pprice = _price_from_info(_pinfo)
                _ppe = _float(_pinfo, "trailingPE")
                _pname = _pinfo.get("shortName", _pticker)
                st.markdown(
                    f"**{_pticker}** — {_pname}  ·  "
                    f"Price: {'${:,.2f}'.format(_pprice) if _pprice else '—'}  ·  "
                    f"Trailing P/E: {'{:.1f}'.format(_ppe) if _ppe else '—'}"
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

        # ── Manual Metrics section ────────────────────────────────────────────
        st.divider()
        st.subheader("MANUAL METRICS — company-specific quality inputs (quarterly)")

        _mm = st.session_state.manual_metrics

        # ── INSURANCE ────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:8px 0 4px 0'>INSURANCE (PGR, CB)</div>",
            unsafe_allow_html=True,
        )
        _ins1, _ins2, _ins3 = st.columns(3)
        with _ins1:
            _mm["pgr_combined_ratio"]["value"] = st.number_input(
                "PGR Combined Ratio (target < 96%)",
                min_value=50.0, max_value=150.0,
                value=_mm["pgr_combined_ratio"]["value"],
                step=0.1, format="%.1f",
                key="mm_pgr_combined_ratio",
            )
            st.caption(_mm_ts_label(_mm["pgr_combined_ratio"]["updated"]))
        with _ins2:
            _mm["pgr_premium_growth"]["value"] = st.number_input(
                "PGR Premium Growth % (target ≥ 5%)",
                min_value=-50.0, max_value=100.0,
                value=_mm["pgr_premium_growth"]["value"],
                step=0.1, format="%.1f",
                key="mm_pgr_premium_growth",
            )
            st.caption(_mm_ts_label(_mm["pgr_premium_growth"]["updated"]))
        with _ins3:
            _mm["cb_combined_ratio"]["value"] = st.number_input(
                "CB Combined Ratio (target < 96%)",
                min_value=50.0, max_value=150.0,
                value=_mm["cb_combined_ratio"]["value"],
                step=0.1, format="%.1f",
                key="mm_cb_combined_ratio",
            )
            st.caption(_mm_ts_label(_mm["cb_combined_ratio"]["updated"]))
        _ins4, _ins5, _ = st.columns(3)
        with _ins4:
            _mm["cb_premium_growth"]["value"] = st.number_input(
                "CB Premium Growth % (target ≥ 5%)",
                min_value=-50.0, max_value=100.0,
                value=_mm["cb_premium_growth"]["value"],
                step=0.1, format="%.1f",
                key="mm_cb_premium_growth",
            )
            st.caption(_mm_ts_label(_mm["cb_premium_growth"]["updated"]))

        # ── RAILROAD ─────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:12px 0 4px 0'>RAILROAD (CNI)</div>",
            unsafe_allow_html=True,
        )
        _rr1, _rr2, _rr3 = st.columns(3)
        with _rr1:
            _mm["cni_operating_ratio"]["value"] = st.number_input(
                "CNI Operating Ratio (target < 65%)",
                min_value=40.0, max_value=100.0,
                value=_mm["cni_operating_ratio"]["value"],
                step=0.1, format="%.1f",
                key="mm_cni_operating_ratio",
            )
            st.caption(_mm_ts_label(_mm["cni_operating_ratio"]["updated"]))

        # ── BANKS ────────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:12px 0 4px 0'>BANKS (JPM)</div>",
            unsafe_allow_html=True,
        )
        _bk1, _bk2, _bk3 = st.columns(3)
        with _bk1:
            _mm["jpm_roa"]["value"] = st.number_input(
                "JPM ROA % (target ≥ 1.0%)",
                min_value=0.0, max_value=10.0,
                value=_mm["jpm_roa"]["value"],
                step=0.01, format="%.2f",
                key="mm_jpm_roa",
            )
            st.caption(_mm_ts_label(_mm["jpm_roa"]["updated"]))
        with _bk2:
            _mm["jpm_efficiency_ratio"]["value"] = st.number_input(
                "JPM Efficiency Ratio % (target < 60%)",
                min_value=0.0, max_value=100.0,
                value=_mm["jpm_efficiency_ratio"]["value"],
                step=0.1, format="%.1f",
                key="mm_jpm_efficiency_ratio",
            )
            st.caption(_mm_ts_label(_mm["jpm_efficiency_ratio"]["updated"]))

        # ── MLPs ─────────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:12px 0 4px 0'>MLPs (EPD, KMI)</div>",
            unsafe_allow_html=True,
        )
        _mlp1, _mlp2, _mlp3 = st.columns(3)
        with _mlp1:
            _mm["epd_dcf_coverage"]["value"] = st.number_input(
                "EPD DCF Coverage (target ≥ 1.5x)",
                min_value=0.0, max_value=10.0,
                value=_mm["epd_dcf_coverage"]["value"],
                step=0.01, format="%.2f",
                key="mm_epd_dcf_coverage",
            )
            st.caption(_mm_ts_label(_mm["epd_dcf_coverage"]["updated"]))
        with _mlp2:
            _mm["epd_distribution_growth"]["value"] = st.number_input(
                "EPD Distribution Growth % (target ≥ 3%)",
                min_value=-20.0, max_value=50.0,
                value=_mm["epd_distribution_growth"]["value"],
                step=0.1, format="%.1f",
                key="mm_epd_distribution_growth",
            )
            st.caption(_mm_ts_label(_mm["epd_distribution_growth"]["updated"]))

        # ── ENERGY ───────────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:12px 0 4px 0'>ENERGY (CVX, COP)</div>",
            unsafe_allow_html=True,
        )
        _en1, _en2, _en3 = st.columns(3)
        with _en1:
            _mm["cvx_dividend_coverage"]["value"] = st.number_input(
                "CVX Dividend Coverage at $70 oil (target ≥ 2x)",
                min_value=0.0, max_value=20.0,
                value=_mm["cvx_dividend_coverage"]["value"],
                step=0.01, format="%.2f",
                key="mm_cvx_dividend_coverage",
            )
            st.caption(_mm_ts_label(_mm["cvx_dividend_coverage"]["updated"]))
        with _en2:
            _mm["cop_dividend_coverage"]["value"] = st.number_input(
                "COP Dividend Coverage at $70 oil (target ≥ 2x)",
                min_value=0.0, max_value=20.0,
                value=_mm["cop_dividend_coverage"]["value"],
                step=0.01, format="%.2f",
                key="mm_cop_dividend_coverage",
            )
            st.caption(_mm_ts_label(_mm["cop_dividend_coverage"]["updated"]))

        # ── PHILIP MORRIS ────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:0.8rem;font-weight:700;color:#666;letter-spacing:0.05em;"
            "margin:12px 0 4px 0'>PHILIP MORRIS (PM)</div>",
            unsafe_allow_html=True,
        )
        _pm1, _pm2, _pm3 = st.columns(3)
        with _pm1:
            _mm["pm_dividend_coverage"]["value"] = st.number_input(
                "PM Dividend Coverage Ratio (target > 1.3x)",
                min_value=0.0, max_value=10.0,
                value=_mm["pm_dividend_coverage"]["value"],
                step=0.01, format="%.2f",
                key="mm_pm_dividend_coverage",
            )
            st.caption(_mm_ts_label(_mm["pm_dividend_coverage"]["updated"]))
        with _pm2:
            _mm["pm_iqos_volume_growth"]["value"] = st.number_input(
                "PM iQOS Volume Growth % (target ≥ 10%)",
                min_value=-50.0, max_value=200.0,
                value=_mm["pm_iqos_volume_growth"]["value"],
                step=0.1, format="%.1f",
                key="mm_pm_iqos_volume_growth",
            )
            st.caption(_mm_ts_label(_mm["pm_iqos_volume_growth"]["updated"]))

        # ── Save button ───────────────────────────────────────────────────────
        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
        if st.button("Save Manual Metrics", key="save_manual_metrics", type="primary"):
            _today = datetime.now().strftime("%Y-%m-%d")
            _saved_snap = st.session_state.get("manual_metrics_saved", {})
            for _field in _MANUAL_METRICS_DEFAULTS:
                _cur_val = _mm[_field]["value"]
                _prev_val = _saved_snap.get(_field, {}).get("value") if isinstance(_saved_snap.get(_field), dict) else None
                if _prev_val is None or _cur_val != _prev_val:
                    _mm[_field]["updated"] = _today
            save_manual_metrics(_mm)
            st.session_state.manual_metrics = _mm
            st.session_state.manual_metrics_saved = {
                k: {"value": v["value"], "updated": v["updated"]} for k, v in _mm.items()
            }
            # Invalidate cached rows so compute_row() re-runs with new manual metrics
            st.session_state.raw_rows = None
            st.session_state.raw_rows_b = None
            st.session_state.raw_rows_custom_a = None
            st.session_state.raw_rows_custom_b = None
            st.success("Saved.")

        st.caption(
            "Update these quarterly after earnings releases. "
            "Sources: Morningstar, earnings transcripts, investor presentations."
        )

        st.divider()
        st.caption(
            "Live data: Yahoo Finance via yfinance.  "
            "Static data: update quarterly from CBO/OMB, MSFT earnings, Berkshire 13-F.  "
            "Not financial advice."
        )

    # ══════════════════════════════════════════════════════════════════════════
    # MARKET SIGNALS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_ms:
        # ── Signal color map ──────────────────────────────────────────────────
        _SIG_COLORS = {
            "CLEAR":   "#2e7d32",
            "WATCH":   "#f9a825",
            "CAUTION": "#e65100",
            "DANGER":  "#b71c1c",
            "N/A":     "#607d8b",
        }
        _SIG_OPTIONS = ["N/A", "CLEAR", "WATCH", "CAUTION", "DANGER"]

        # ── Indicator definitions (id, category, name, watch, danger, note) ───
        _STAGE1_INDICATORS = [
            ("hy_spread",        "Credit Markets",     "HY Spread (ICE BofA)",            "≥400 bps",                    "≥550 bps",                    "Primary risk-on/off barometer. Widens before equities crack. Widening >50 bps in 4 weeks = early alert."),
            ("ig_spread",        "Credit Markets",     "IG Spread (ICE BofA)",             "≥130 bps",                    "≥180 bps",                    "Subtler than HY but institutional money moves here first. Sustained IG widening often precedes HY blowout."),
            ("yield_curve",      "Credit Markets",     "2yr/10yr Yield Curve",             "Re-steepening after inversion","Steepening >50 bps post-inversion","Re-steepening after prolonged inversion is historically more dangerous than the inversion itself — signals recession onset, not avoidance."),
            ("pct_above_200ma",  "Equity Internals",   "% Stocks Above 200-day MA",        "<50%",                        "<35%",                        "Breadth deterioration leads index decline. Market can stay elevated while internals quietly hollow out."),
            ("nyse_ad_line",     "Equity Internals",   "NYSE Advance/Decline Line",        "Negative 4-week trend",       "Sharply diverging from index", "Divergence from S&P — index making new highs while A/D weakens — is a classic distribution signal."),
            ("treasury_bid_cover","Rates/Sovereign",   "Treasury Bid-to-Cover Ratio",      "<2.3x",                       "<2.0x",                       "Measures bond auction demand. Sustained decline = bond vigilante early warning. Watch 10yr and 30yr auctions separately."),
            ("indirect_bidders", "Rates/Sovereign",    "Indirect Bidders %",               "<60%",                        "<50%",                        "Foreign central bank proxy. Decline signals dollar reserve erosion. Critical given debasement thesis."),
            ("dxy",              "Macro/Dollar",       "DXY (Dollar Index)",               "Below 100",                   "Below 95",                    "Central to macro thesis. Dollar weakness accelerates inflation re-acceleration and commodity tailwind."),
            ("gold_price",       "Macro/Dollar",       "Gold Price (USD/oz)",              ">$2,800",                     ">$3,200",                     "Monetary stress barometer and dollar-debasement signal. FNV tracks this closely. Surge = systemic loss of confidence."),
            ("ism_pmi",          "Leading Indicators", "ISM Manufacturing PMI",            "<50 (contraction)",           "<46",                         "Best single early-cycle indicator. Below 50 = contraction. Below 46 = recession correlation high. Precedes labor data by ~3 months."),
            ("conf_board_lei",   "Leading Indicators", "Conference Board LEI (MoM)",       "Negative 3 months",           "Negative 6+ months",          "Composite of 10 leading indicators. Six consecutive monthly declines have preceded every recession since 1960."),
        ]

        _STAGE2_INDICATORS = [
            ("treasury_10yr",    "Rates/Sovereign",    "10yr Treasury Yield",              "≥4.75%",                      "≥5.50%",                      "Watch for rapid moves, not just level. A 50 bps spike in 3 weeks is more dangerous than a slow grind to same level."),
            ("treasury_30yr",    "Rates/Sovereign",    "30yr Treasury Yield",              "≥5.00%",                      "≥5.75%",                      "Mortgage and long-term capital cost benchmark. Bond vigilante pressure most visible here."),
            ("brent_crude",      "Energy/Geopolitical","Brent Crude (USD/bbl)",            ">$95",                        ">$110",                       "Supply-shock threshold. Above $95 begins meaningful consumer drag. Above $110 historically tips recessions."),
            ("hormuz_volume",    "Energy/Geopolitical","Hormuz Strait Volume (% normal)",  "<85%",                        "<70%",                        "Direct Iran scenario monitor. ~20% of global oil + LNG transits here. Disruption = immediate energy shock."),
            ("red_sea_volume",   "Energy/Geopolitical","Red Sea / Suez Volume (% normal)", "<75%",                        "<60%",                        "Shipping disruption = goods inflation re-acceleration. Houthi activity already demonstrated sensitivity."),
            ("war_risk_premium", "Energy/Geopolitical","War Risk Insurance Premium (bps)", ">50 bps above baseline",      ">150 bps above baseline",     "VLCC and tanker war risk premia are real-time geopolitical pricing. Spike precedes commodity price moves."),
            ("eps_guidance",     "Corporate Earnings", "Forward EPS Guidance Trend",       "Negative revisions >5%",      "Negative revisions >15%",     "Management guidance is mid-cycle because executives see it before analysts. Watch breadth of cuts, not just magnitude."),
            ("gross_margin",     "Corporate Earnings", "Gross Margin Trend (S&P 500)",     "Declining 100 bps YoY",       "Declining 200+ bps YoY",      "Margin compression precedes full earnings collapse. Input costs + pricing power = the battle. Labor is the lagging piece."),
            ("cc_delinquency",   "Consumer Stress",    "Credit Card Delinquency Rate",     ">3.5%",                       ">5.0%",                       "Lower-income canary. Stress here signals consumer spending slow-down before retail data shows it."),
            ("auto_delinquency", "Consumer Stress",    "Auto Loan Delinquency Rate (60d+)", ">3.0%",                      ">4.5%",                       "Middle-income stress signal. Auto delinquencies tend to peak mid-recession, not late."),
            ("initial_claims",   "Labor Market",       "Initial Jobless Claims (4-wk avg)", ">260K",                      ">320K",                       "More leading than continuing claims. Spike above 300K = labor market turning."),
        ]

        _STAGE3_INDICATORS = [
            ("continuing_claims","Labor Market",       "Continuing Jobless Claims",        ">1.9M",                       ">2.5M",                       "Confirms labor deterioration after initial claims signal. Watch for plateau pattern — people falling off UI without finding jobs."),
            ("prof_tech_layoffs","Labor Market",       "Professional/Technical Layoffs",   "Sustained monthly >30K",      "Sustained monthly >60K",      "Tech/professional layoffs signal AI capex may be overcorrecting real hiring."),
            ("wage_growth",      "Labor Market",       "Wage Growth (YoY, ECI)",           ">4.5% (re-acceleration)",     "<2.5% (collapse)",            "Double-edged late indicator. Re-acceleration = inflation problem. Sudden collapse = demand destruction. Both are danger signals."),
            ("retail_sales",     "Consumer/Retail",    "Retail Sales ex-Autos & Gas (MoM)","Negative 2 consecutive months","Negative 4+ months",         "Lags by design. By the time this turns, recession is typically already underway. Useful for magnitude, not timing."),
            ("inventory_sales",  "Corporate",          "Inventory-to-Sales Ratio",         "Rising >1.5x trend",          "Rising >1.7x trend",          "Build-up = forced production cuts ahead. Mid-2022 inventory glut is the textbook case."),
            ("sp500_concentration","Equity Internals", "S&P 500 Top-10 Concentration",     ">35% of index",               ">40% of index",               "Narrow leadership = fragile market. A correction in 5-6 mega-caps = index rout even with healthy breadth elsewhere."),
            ("ai_capex_ratio",   "AI Sector Check",   "AI CapEx vs. Revenue Growth Ratio","CapEx >2x revenue growth",    "CapEx >3x revenue growth",    "Key AI bubble monitor. $300B+ hyperscaler capex must eventually be justified by revenue. Watch MSFT, GOOG, AMZN, META quarterly."),
            ("cloud_revenue_growth","AI Sector Check", "Hyperscaler Cloud Revenue Growth", "Deceleration >5 ppts YoY",    "Deceleration >10 ppts YoY",   "The monetization side of the AI equation. Slowing cloud growth while capex surges = the blow-up scenario for tech."),
            ("federal_deficit",  "Macro/Dollar",       "Federal Deficit (% of GDP, TTM)",  ">7% GDP",                     ">9% GDP",                     "Structural fiscal excess is the backbone of the debasement thesis. A widening deficit during expansion = fiscal dominance risk."),
        ]

        # ── Load persisted indicator data ─────────────────────────────────────
        if "market_indicators" not in st.session_state:
            st.session_state.market_indicators = load_market_indicators()

        _mi = st.session_state.market_indicators

        # Pre-initialize widget session states from JSON so text_input never
        # fights with value= on rerun (Streamlit session-state-wins contract)
        for _init_id in _MARKET_INDICATOR_IDS:
            _init_data = _mi.get(_init_id, {})
            if f"mi_cur_{_init_id}" not in st.session_state:
                st.session_state[f"mi_cur_{_init_id}"] = _init_data.get("current", "")
            if f"mi_pri_{_init_id}" not in st.session_state:
                st.session_state[f"mi_pri_{_init_id}"] = _init_data.get("prior", "")

        # ── Refresh Market Data button ─────────────────────────────────────────
        _refresh_col, _refresh_status_col = st.columns([2, 5])
        with _refresh_col:
            if st.button("Refresh Market Data", type="primary", use_container_width=True):
                _fetch_yfinance_market_data.clear()
                _fetch_fred_market_data.clear()
                with st.spinner("Fetching live market data…"):
                    _yf_data  = _fetch_yfinance_market_data()
                    _fr_data  = _fetch_fred_market_data()
                _auto_fetched = {**_yf_data, **_fr_data}
                _today = datetime.now().strftime("%Y-%m-%d")
                for _aid, _aval in _auto_fetched.items():
                    if _aid.startswith("_") or _aid not in _AUTO_PULL_IDS:
                        continue
                    _mi.setdefault(_aid, dict(_MARKET_INDICATOR_DEFAULT))
                    _mi[_aid]["current"] = _aval
                    _mi[_aid]["updated"] = _today
                    st.session_state[f"mi_cur_{_aid}"] = _aval
                # Track which AUTO indicators failed to fetch (show MANUAL badge for those)
                st.session_state["_mi_failed_autos"] = {
                    _aid for _aid in _AUTO_PULL_IDS if _aid not in _auto_fetched
                }
                save_market_indicators(_mi)
                _pulled = len([k for k in _auto_fetched if not k.startswith("_") and k in _AUTO_PULL_IDS])
                with _refresh_status_col:
                    st.success(f"Updated {_pulled} indicators  ·  {_today}")
                st.rerun()
        st.markdown("<div style='margin-bottom:6px'></div>", unsafe_allow_html=True)

        # ── Header banner ─────────────────────────────────────────────────────
        st.markdown(
            "<div style='background:#4a5568;color:#fff;padding:10px 16px;border-radius:6px;"
            "margin-bottom:10px'>"
            "<div><strong>Market Signals Dashboard</strong> — 31 early-warning macro indicators across 3 stages.</div>"
            "<div style='margin-top:6px;display:flex;flex-wrap:wrap;gap:6px'>"
            "<span style='background:#2e7d32;color:#fff;padding:2px 10px;border-radius:10px;font-size:0.82rem'>&#9679; CLEAR</span>"
            "<span style='background:#f9a825;color:#fff;padding:2px 10px;border-radius:10px;font-size:0.82rem'>&#9650; WATCH</span>"
            "<span style='background:#e65100;color:#fff;padding:2px 10px;border-radius:10px;font-size:0.82rem'>&#9888; CAUTION</span>"
            "<span style='background:#b71c1c;color:#fff;padding:2px 10px;border-radius:10px;font-size:0.82rem'>&#9888; DANGER</span>"
            "<span style='background:#607d8b;color:#fff;padding:2px 10px;border-radius:10px;font-size:0.82rem'>&#8213; N/A</span>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        def _delta_str(current: str, prior: str) -> str:
            """Auto-calculate delta when both readings are numeric."""
            try:
                c = float(current.replace(",", "").replace("%", "").replace("$", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
                p = float(prior.replace(",", "").replace("%", "").replace("$", "").replace("K", "e3").replace("M", "e6").replace("B", "e9"))
                delta = c - p
                sign = "+" if delta >= 0 else ""
                if abs(delta) >= 1e9:
                    return f"{sign}{delta/1e9:.2f}B"
                elif abs(delta) >= 1e6:
                    return f"{sign}{delta/1e6:.2f}M"
                elif abs(delta) >= 1e3:
                    return f"{sign}{delta/1e3:.1f}K"
                else:
                    return f"{sign}{delta:.2f}"
            except Exception:
                return "—"

        def _render_stage(stage_label: str, header_color: str, indicators: list) -> None:
            st.markdown(
                f"<div style='background:{header_color};color:#fff;padding:8px 14px;"
                f"border-radius:5px;margin:18px 0 8px 0;font-weight:700;font-size:0.95rem'>"
                f"{stage_label}</div>",
                unsafe_allow_html=True,
            )
            # Column header row
            hc = st.columns([1.4, 1.8, 1.0, 1.0, 1.0, 1.2, 1.2, 1.0, 2.5, 1.1])
            _hdr_style = "font-size:0.75rem;font-weight:700;color:#555;margin:0"
            for _col, _lbl in zip(hc, ["Category", "Indicator", "Current", "Prior", "Delta", "Watch Level", "Danger Level", "Signal", "Notes", "Updated"]):
                _col.markdown(f"<p style='{_hdr_style}'>{_lbl}</p>", unsafe_allow_html=True)
            st.markdown("<hr style='margin:2px 0 6px 0;border-color:#ddd'/>", unsafe_allow_html=True)

            _dirty = False
            for (ind_id, category, name, watch_lvl, danger_lvl, note) in indicators:
                row_data = _mi.get(ind_id, {"current": "", "prior": "", "signal": "N/A", "updated": None})
                cols = st.columns([1.4, 1.8, 1.0, 1.0, 1.0, 1.2, 1.2, 1.0, 2.5, 1.1])
                with cols[0]:
                    st.markdown(f"<p style='font-size:0.85rem;font-weight:700;color:#444;margin:6px 0'>{category}</p>", unsafe_allow_html=True)
                with cols[1]:
                    st.markdown(f"<p style='font-size:1.0rem;font-weight:700;color:#222;margin:6px 0'>{name}</p>", unsafe_allow_html=True)
                with cols[2]:
                    new_current = st.text_input("c", key=f"mi_cur_{ind_id}", label_visibility="collapsed")
                    _failed_autos = st.session_state.get("_mi_failed_autos", set())
                    if ind_id in _AUTO_PULL_IDS and ind_id not in _failed_autos:
                        st.markdown(
                            "<span style='background:#9e9e9e;color:#fff;padding:1px 6px;"
                            "border-radius:8px;font-size:0.67rem;font-weight:600'>AUTO</span>",
                            unsafe_allow_html=True,
                        )
                    elif ind_id in _MANUAL_IDS or ind_id in _failed_autos:
                        st.markdown(
                            "<span style='background:#b85c38;color:#fff;padding:1px 6px;"
                            "border-radius:8px;font-size:0.67rem;font-weight:600'>MANUAL</span>",
                            unsafe_allow_html=True,
                        )
                with cols[3]:
                    new_prior = st.text_input("p", key=f"mi_pri_{ind_id}", label_visibility="collapsed",
                                              on_change=_on_market_prior_change, args=(ind_id,))
                with cols[4]:
                    delta_val = _delta_str(new_current, new_prior)
                    delta_color = "#2e7d32" if (delta_val.startswith("+") and delta_val != "+0.00") else ("#b71c1c" if delta_val.startswith("-") else "#555")
                    st.markdown(f"<p style='font-size:0.9rem;font-weight:600;color:{delta_color};margin:8px 0'>{delta_val}</p>", unsafe_allow_html=True)
                with cols[5]:
                    st.markdown(f"<p style='font-size:0.9rem;color:#666;margin:6px 0'>{watch_lvl}</p>", unsafe_allow_html=True)
                with cols[6]:
                    st.markdown(f"<p style='font-size:0.9rem;color:#666;margin:6px 0'>{danger_lvl}</p>", unsafe_allow_html=True)
                with cols[7]:
                    cur_sig = row_data.get("signal", "N/A")
                    new_sig = st.selectbox("s", options=_SIG_OPTIONS, index=_SIG_OPTIONS.index(cur_sig) if cur_sig in _SIG_OPTIONS else 0, key=f"mi_sig_{ind_id}", label_visibility="collapsed")
                    sig_bg = _SIG_COLORS.get(new_sig, "#607d8b")
                    # Highlight when an auto-fetched value is present but signal still N/A
                    _needs_signal = (new_sig == "N/A" and new_current.strip() and ind_id in _AUTO_PULL_IDS)
                    _sig_extra = ";outline:2px solid #f9a825;outline-offset:2px" if _needs_signal else ""
                    st.markdown(
                        f"<div style='background:{sig_bg};color:#fff;padding:1px 6px;border-radius:10px;"
                        f"font-size:0.75rem;text-align:center;margin-top:-4px{_sig_extra}'>"
                        f"{new_sig}{'  ★' if _needs_signal else ''}</div>",
                        unsafe_allow_html=True,
                    )
                with cols[8]:
                    st.markdown(f"<p style='font-size:0.72rem;color:#555;margin:6px 0;line-height:1.4'>{note}</p>", unsafe_allow_html=True)
                with cols[9]:
                    upd = row_data.get("updated")
                    upd_label = upd if upd else "—"
                    st.markdown(f"<p style='font-size:0.72rem;color:#888;margin:6px 0'>{upd_label}</p>", unsafe_allow_html=True)

                # Detect changes and update session state
                changed = (
                    new_current != row_data.get("current", "") or
                    new_prior   != row_data.get("prior", "") or
                    new_sig     != row_data.get("signal", "N/A")
                )
                if changed:
                    _mi[ind_id] = {
                        "current": new_current,
                        "prior":   new_prior,
                        "signal":  new_sig,
                        "updated": datetime.now().strftime("%Y-%m-%d"),
                    }
                    _dirty = True
            return _dirty

        _any_dirty = False
        _any_dirty |= _render_stage("STAGE 1 — EARLY INDICATORS", "#6e9b82", _STAGE1_INDICATORS)
        _any_dirty |= _render_stage("STAGE 2 — MID-CYCLE INDICATORS", "#8a9a6e", _STAGE2_INDICATORS)
        _any_dirty |= _render_stage("STAGE 3 — LATE / LAGGING INDICATORS", "#a07060", _STAGE3_INDICATORS)

        if _any_dirty:
            save_market_indicators(_mi)

        # ── Summary row ───────────────────────────────────────────────────────
        st.divider()
        _sig_counts = {"CLEAR": 0, "WATCH": 0, "CAUTION": 0, "DANGER": 0, "N/A": 0}
        for _d in _mi.values():
            _s = _d.get("signal", "N/A")
            if _s in _sig_counts:
                _sig_counts[_s] += 1
        _all_indicators = _STAGE1_INDICATORS + _STAGE2_INDICATORS + _STAGE3_INDICATORS
        _total = len(_all_indicators)
        st.markdown(
            f"<div style='background:#f5f5f5;border:1px solid #ddd;border-radius:6px;"
            f"padding:10px 16px;display:flex;gap:16px;flex-wrap:wrap;align-items:center'>"
            f"<span style='font-weight:700;color:#333;font-size:0.88rem'>Signal Summary ({_total} indicators):</span>"
            f"<span style='background:#2e7d32;color:#fff;padding:2px 12px;border-radius:10px;font-size:0.85rem'>CLEAR: {_sig_counts['CLEAR']}</span>"
            f"<span style='background:#f9a825;color:#fff;padding:2px 12px;border-radius:10px;font-size:0.85rem'>WATCH: {_sig_counts['WATCH']}</span>"
            f"<span style='background:#e65100;color:#fff;padding:2px 12px;border-radius:10px;font-size:0.85rem'>CAUTION: {_sig_counts['CAUTION']}</span>"
            f"<span style='background:#b71c1c;color:#fff;padding:2px 12px;border-radius:10px;font-size:0.85rem'>DANGER: {_sig_counts['DANGER']}</span>"
            f"<span style='background:#607d8b;color:#fff;padding:2px 12px;border-radius:10px;font-size:0.85rem'>N/A: {_sig_counts['N/A']}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(
            "Sources: FRED, ICE BofA, ISM, Conference Board, Bloomberg, EIA, Lloyd's of London | Update weekly"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # DEPLOYMENT
    # ══════════════════════════════════════════════════════════════════════════
    with tab_d:
        # ── Suggested allocation defaults (Modification 1.0) ──────────────────
        _DEPLOY_ALLOC: dict[str, tuple[int, str]] = {
            # ticker → (alloc_pct, list_label)
            # Portfolio A
            "BRK-B":  (4, "Portfolio A"),
            "MSFT":   (3, "Portfolio A"),
            "CME":    (3, "Portfolio A"),
            "CVX":    (3, "Portfolio A"),
            "COP":    (2, "Portfolio A"),
            "EPD":    (2, "Portfolio A"),
            "BAM":    (3, "Portfolio A"),
            "CNI":    (2, "Portfolio A"),
            "FNV":    (2, "Portfolio A"),
            "MCO":    (2, "Portfolio A"),
            "RMS.PA": (2, "Portfolio A"),
            "V":      (3, "Portfolio A"),
            "SPGI":   (2, "Portfolio A"),
            "DHR":    (2, "Portfolio A"),
            "IDXX":   (2, "Portfolio A"),
            "VRSN":   (2, "Portfolio A"),
            "WM":     (2, "Portfolio A"),
            "AZO":    (2, "Portfolio A"),
            "JPM":    (2, "Portfolio A"),
            "ASR":    (1, "Portfolio A"),
            "ADP":    (2, "Portfolio A"),
            "FICO":   (2, "Portfolio A"),
            "AXP":    (2, "Portfolio A"),
            "RMBS":   (1, "Portfolio A"),
            # Portfolio B
            "PGR":  (3, "Portfolio B"),
            "CB":   (3, "Portfolio B"),
            "PG":   (2, "Portfolio B"),
            "KO":   (2, "Portfolio B"),
            "TXN":  (2, "Portfolio B"),
            "XOM":  (2, "Portfolio B"),
            "BLK":  (2, "Portfolio B"),
            "BIP":  (3, "Portfolio B"),
            "CHD":  (1, "Portfolio B"),
            "ABBV": (2, "Portfolio B"),
            "AVGO": (2, "Portfolio B"),
            "CL":   (1, "Portfolio B"),
            "FCX":  (2, "Portfolio B"),
            "JNJ":  (2, "Portfolio B"),
            "ITW":  (2, "Portfolio B"),
            "EOG":  (2, "Portfolio B"),
            "EMR":    (1, "Portfolio B"),
            "PM":     (2, "Portfolio B"),
            "NEE":    (1, "Portfolio B"),
            "KMI":    (1, "Portfolio B"),
            "PLD":    (1, "Portfolio B"),
            "NVO":    (2, "Portfolio B"),
            "ITRK.L": (2, "Portfolio B"),
            "BVI.PA": (2, "Portfolio B"),
            # Wait List
            "GOOGL":   (4, "Wait List"),
            "ASML":    (3, "Wait List"),
            "COST":    (3, "Wait List"),
            "NVO":     (2, "Wait List"),
            "EQNR":    (2, "Wait List"),
            "CSU.TO":  (2, "Wait List"),
            "6861.T":  (2, "Wait List"),
            "WTKWY":   (2, "Wait List"),
            "CLPBY":   (1, "Wait List"),
            "DPLM.L":  (1, "Wait List"),
        }
        # V and AXP and FICO appear in both Portfolio A and Wait List —
        # prefer the Portfolio A entry (already set above); Wait List
        # entries for those tickers are de-duplicated via the dict.

        def _fmt_dollars(amount: float) -> str:
            return f"${amount:,.0f}"

        # ── Portfolio size input ───────────────────────────────────────────────
        if "deployment_portfolio_size" not in st.session_state:
            st.session_state["deployment_portfolio_size"] = 3_000_000

        portfolio_size = st.number_input(
            "Portfolio Size ($)",
            min_value=10_000,
            max_value=100_000_000,
            step=50_000,
            value=st.session_state["deployment_portfolio_size"],
            key="deployment_portfolio_size",
            format="%d",
        )

        # ── Gather live signals from session state ────────────────────────────
        _deploy_rows: list[dict] = []

        # Portfolio A
        _raw_a = st.session_state.get("raw_rows")
        if _raw_a:
            for _r in _raw_a:
                if _r.get("Signal") in ("FAIR", "DREAM"):
                    _tk = _r["Ticker"]
                    _alloc_pct, _list_lbl = _DEPLOY_ALLOC.get(_tk, (1, "Portfolio A"))
                    _deploy_rows.append({
                        "Ticker":       _tk,
                        "List":         "Portfolio A",
                        "Signal":       _r["Signal"],
                        "Price":        _r.get("Price"),
                        "Fair Price":   _r.get("Fair Price"),
                        "Dream Price":  _r.get("Dream Price"),
                        "Discount%":    _r.get("Discount%"),
                        "Alloc%":       _alloc_pct,
                    })

        # Portfolio B
        _raw_b = st.session_state.get("raw_rows_b")
        if _raw_b:
            for _r in _raw_b:
                if _r.get("Signal") in ("FAIR", "DREAM"):
                    _tk = _r["Ticker"]
                    _alloc_pct, _list_lbl = _DEPLOY_ALLOC.get(_tk, (1, "Portfolio B"))
                    _deploy_rows.append({
                        "Ticker":       _tk,
                        "List":         "Portfolio B",
                        "Signal":       _r["Signal"],
                        "Price":        _r.get("Price"),
                        "Fair Price":   _r.get("Fair Price"),
                        "Dream Price":  _r.get("Dream Price"),
                        "Discount%":    _r.get("Discount%"),
                        "Alloc%":       _alloc_pct,
                    })

        # Wait List — AT TARGET status surfaces in Deployment tab
        _raw_wl = st.session_state.get("raw_rows_waitlist")
        if _raw_wl:
            for _r in _raw_wl:
                if _r.get("status") == "AT TARGET":
                    _tk = _r["ticker"]
                    _alloc_pct, _ = _DEPLOY_ALLOC.get(_tk, (1, "Wait List"))
                    _price = _r.get("price")
                    _entry_high = _r.get("entry_high")
                    _entry_low  = _r.get("entry_low")
                    _gap = _r.get("gap_pct")
                    _disc = round(-_gap, 1) if _gap is not None else None
                    _deploy_rows.append({
                        "Ticker":      _r.get("display_ticker", _tk),
                        "List":        "Wait List",
                        "Signal":      "AT TARGET",
                        "Price":       _price,
                        "Fair Price":  _entry_high,
                        "Dream Price": _entry_low,
                        "Discount%":   _disc,
                        "Alloc%":      _alloc_pct,
                    })

        # ── Summary metrics ───────────────────────────────────────────────────
        _n_opps = len(_deploy_rows)
        _total_suggested = sum(
            portfolio_size * r["Alloc%"] / 100 for r in _deploy_rows
        )
        _sgov_remaining = portfolio_size - _total_suggested

        _mc1, _mc2, _mc3 = st.columns(3)
        _mc1.metric("FAIR + DREAM Opportunities", _n_opps)
        _mc2.metric(
            "Capital Suggested (if all deployed)",
            _fmt_dollars(_total_suggested),
        )
        _mc3.metric(
            "SGOV Remaining After Deployment",
            _fmt_dollars(_sgov_remaining),
        )

        st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)

        # ── Primary table ─────────────────────────────────────────────────────
        if not _deploy_rows:
            _data_loaded = bool(_raw_a or _raw_b or _raw_wl)
            if _data_loaded:
                st.info(
                    "No tickers at FAIR or DREAM signal right now. "
                    "All positions are priced above fair value — hold SGOV.",
                    icon="✅",
                )
            else:
                st.info(
                    "Load Portfolio A, Portfolio B, and/or Wait List tabs first "
                    "to populate live signals.",
                    icon="ℹ️",
                )
        else:
            # Sort: DREAM first, then FAIR/AT TARGET; within each group by Alloc% desc
            _signal_order = {"DREAM": 0, "FAIR": 1, "AT TARGET": 2}
            _deploy_rows.sort(
                key=lambda r: (_signal_order.get(r["Signal"], 9), -r["Alloc%"])
            )

            def _fmt_price(v) -> str:
                if v is None:
                    return "—"
                return f"${v:,.2f}"

            def _fmt_pct(v) -> str:
                if v is None:
                    return "—"
                return f"{v:.1f}%"

            # Build HTML table
            _hdr = (
                "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
                "<thead><tr style='background:#e8e8e8'>"
                "<th style='padding:5px 10px;text-align:left;font-weight:700;color:#444'>Ticker</th>"
                "<th style='padding:5px 10px;text-align:left;font-weight:700;color:#444'>List</th>"
                "<th style='padding:5px 10px;text-align:center;font-weight:700;color:#444'>Signal</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Current Price</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Fair Price $</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Dream Price $</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Discount %</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Suggested Alloc %</th>"
                "<th style='padding:5px 10px;text-align:right;font-weight:700;color:#444'>Suggested Amount ($)</th>"
                "</tr></thead><tbody>"
            )

            _body = ""
            for _i, _r in enumerate(_deploy_rows):
                # Row background by signal
                if _r["Signal"] == "DREAM":
                    _row_bg = "#c8e6c0"   # sage green
                    _sig_color = "#1a4a1a"
                elif _r["Signal"] == "FAIR":
                    _row_bg = "#fff0b3"   # amber
                    _sig_color = "#5a3a00"
                else:  # AT TARGET (wait list)
                    _row_bg = "#fde8b0"   # slightly warmer amber for wait list
                    _sig_color = "#5a3a00"

                _alloc_amt = portfolio_size * _r["Alloc%"] / 100
                _body += (
                    f"<tr style='background:{_row_bg}'>"
                    f"<td style='padding:5px 10px;font-weight:700;color:#1a1a1a'>{_r['Ticker']}</td>"
                    f"<td style='padding:5px 10px;color:#333'>{_r['List']}</td>"
                    f"<td style='padding:5px 10px;text-align:center'>"
                    f"<span style='background:{_sig_color};color:#fff;font-size:11px;font-weight:700;"
                    f"padding:2px 8px;border-radius:10px'>{_r['Signal']}</span></td>"
                    f"<td style='padding:5px 10px;text-align:right;font-weight:600'>{_fmt_price(_r['Price'])}</td>"
                    f"<td style='padding:5px 10px;text-align:right;color:#333'>{_fmt_price(_r['Fair Price'])}</td>"
                    f"<td style='padding:5px 10px;text-align:right;color:#555'>{_fmt_price(_r['Dream Price'])}</td>"
                    f"<td style='padding:5px 10px;text-align:right;color:#2a6a2a;font-weight:600'>{_fmt_pct(_r['Discount%'])}</td>"
                    f"<td style='padding:5px 10px;text-align:right;font-weight:700'>{_r['Alloc%']}%</td>"
                    f"<td style='padding:5px 10px;text-align:right;font-weight:700'>{_fmt_dollars(_alloc_amt)}</td>"
                    f"</tr>"
                )

            st.markdown(
                _hdr + _body + "</tbody></table>",
                unsafe_allow_html=True,
            )

        # ── Footnote ──────────────────────────────────────────────────────────
        st.markdown(
            "<div style='margin-top:12px;padding:10px 14px;background:#f7f4eb;"
            "border-left:4px solid #b8940a;border-radius:5px;"
            "color:#4a3800;font-size:0.85rem;line-height:1.6'>"
            "Allocations are defaults from Modification 1.0. Adjust sizing as circumstances warrant — "
            "Buffett deployed 40% into AXP during the salad oil scandal when conviction was highest."
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='margin-top:24px'></div>", unsafe_allow_html=True)

        # ── Tranche schedule (collapsed) ──────────────────────────────────────
        with st.expander("Market Decline Framework — Original Tranche Schedule", expanded=False):

            def _render_tranche_card(
                tranche_num: int,
                tranche_title: str,
                market_condition: str,
                sgov_remaining_pct: int,
                deploy_pct: int,
                stocks: list[tuple[str, int]],  # (ticker, alloc_pct)
                note: str,
                accent: str,
                accent_dark: str,
            ) -> None:
                deploy_amt = portfolio_size * deploy_pct / 100
                sgov_amt   = portfolio_size * sgov_remaining_pct / 100

                st.markdown(
                    f"<div style='border-left:5px solid {accent};background:#ffffff;border-radius:8px;"
                    f"padding:16px 20px 14px 18px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,0.10)'>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='display:flex;align-items:baseline;gap:14px;margin-bottom:6px'>"
                    f"<span style='font-size:1.1rem;font-weight:800;color:{accent}'>Tranche {tranche_num}</span>"
                    f"<span style='font-size:1.0rem;font-weight:700;color:#2a2a2a'>{tranche_title}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='display:inline-block;background:{accent_dark};color:#fff;"
                    f"font-size:0.78rem;font-weight:600;padding:2px 10px;border-radius:12px;margin-bottom:10px'>"
                    f"Market trigger: {market_condition}</div>",
                    unsafe_allow_html=True,
                )
                col_d, col_s = st.columns(2)
                with col_d:
                    st.markdown(
                        f"<div style='background:#f0f0f0;border-radius:6px;padding:10px 12px;text-align:center'>"
                        f"<div style='color:#555;font-size:0.75rem;font-weight:700;letter-spacing:0.05em'>DEPLOY</div>"
                        f"<div style='color:{accent};font-size:1.45rem;font-weight:800'>{deploy_pct}%</div>"
                        f"<div style='color:#333;font-size:0.92rem;font-weight:600'>{_fmt_dollars(deploy_amt)}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with col_s:
                    st.markdown(
                        f"<div style='background:#f0f0f0;border-radius:6px;padding:10px 12px;text-align:center'>"
                        f"<div style='color:#555;font-size:0.75rem;font-weight:700;letter-spacing:0.05em'>SGOV REMAINING</div>"
                        f"<div style='color:#5a8a5a;font-size:1.45rem;font-weight:800'>{sgov_remaining_pct}%</div>"
                        f"<div style='color:#333;font-size:0.92rem;font-weight:600'>{_fmt_dollars(sgov_amt)}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    "<div style='margin:14px 0 5px 0;color:#444;font-size:0.75rem;"
                    "font-weight:700;letter-spacing:0.07em'>STOCKS — PRIORITY ORDER</div>",
                    unsafe_allow_html=True,
                )
                rows_html = ""
                for i, (ticker, alloc) in enumerate(stocks):
                    bg = "#f7f7f7" if i % 2 == 0 else "#ffffff"
                    alloc_amt = portfolio_size * alloc / 100
                    rows_html += (
                        f"<tr style='background:{bg}'>"
                        f"<td style='padding:2px 8px;color:#1a1a1a;font-weight:700;font-size:12px'>{ticker}</td>"
                        f"<td style='padding:2px 8px;color:{accent};font-weight:700;font-size:12px;text-align:right'>{alloc}%</td>"
                        f"<td style='padding:2px 8px;color:#333;font-size:12px;text-align:right'>{_fmt_dollars(alloc_amt)}</td>"
                        f"</tr>"
                    )
                st.markdown(
                    f"<table style='width:100%;border-collapse:collapse;border-radius:5px;overflow:hidden;border:1px solid #e0e0e0'>"
                    f"<thead><tr style='background:#ececec'>"
                    f"<th style='padding:2px 8px;color:#555;font-size:11px;font-weight:700;text-align:left'>Ticker</th>"
                    f"<th style='padding:2px 8px;color:#555;font-size:11px;font-weight:700;text-align:right'>Alloc %</th>"
                    f"<th style='padding:2px 8px;color:#555;font-size:11px;font-weight:700;text-align:right'>Amount</th>"
                    f"</tr></thead><tbody>{rows_html}</tbody></table>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div style='margin-top:12px;background:#f8f8f8;border-left:3px solid {accent};"
                    f"border-radius:4px;padding:8px 12px;"
                    f"color:#333;font-size:0.84rem;line-height:1.55'>"
                    f"<span style='color:{accent};font-weight:700'>Note: </span>{note}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)

            _col_t0, _col_t1 = st.columns(2)
            with _col_t0:
                _render_tranche_card(
                    tranche_num=0,
                    tranche_title="Deploy Now",
                    market_condition="Current market — thesis-consistent names at fair-to-good prices",
                    sgov_remaining_pct=75,
                    deploy_pct=25,
                    stocks=[
                        ("BRK-B", 4), ("MSFT", 3), ("CME", 3), ("CVX", 3),
                        ("COP", 2), ("EPD", 2), ("BAM", 3), ("CNI", 2),
                        ("FNV", 2), ("MCO", 2), ("RMS.PA", 2),
                    ],
                    note="Deploy now into these 11 names. Retain 75% in SGOV as dry powder.",
                    accent="#7caa7c",
                    accent_dark="#4d7a4d",
                )
            with _col_t1:
                _render_tranche_card(
                    tranche_num=1,
                    tranche_title="S&P -10%",
                    market_condition="S&P 500 down 10%, VIX 25–30",
                    sgov_remaining_pct=55,
                    deploy_pct=20,
                    stocks=[
                        ("GOOGL", 2), ("ASML", 2), ("MSFT add", 2), ("SPGI add", 2),
                        ("V", 2), ("NVO add", 2), ("AXP", 2),
                    ],
                    note="Focus on wait-list names that have reached entry targets.",
                    accent="#c8a040",
                    accent_dark="#8a6a20",
                )

            _col_t2, _col_t3 = st.columns(2)
            with _col_t2:
                _render_tranche_card(
                    tranche_num=2,
                    tranche_title="S&P -20%",
                    market_condition="S&P 500 down 20%, VIX 35–40, bond market stress",
                    sgov_remaining_pct=30,
                    deploy_pct=25,
                    stocks=[
                        ("COST", 3), ("FICO", 2), ("Keyence", 3), ("V add", 2),
                        ("EQNR", 3), ("BRK-B add", 2), ("CME add", 2),
                    ],
                    note="High-quality names genuinely on sale. This is the Munger buying environment.",
                    accent="#c87858",
                    accent_dark="#8a4830",
                )
            with _col_t3:
                _render_tranche_card(
                    tranche_num=3,
                    tranche_title="S&P -35%",
                    market_condition="S&P 500 down 35%+, VIX 45+, crisis conditions",
                    sgov_remaining_pct=10,
                    deploy_pct=20,
                    stocks=[
                        ("COST full", 4), ("FICO add", 2), ("CSU.TO", 3), ("ASML add", 2),
                        ("Size up best names", 3), ("Keyence add", 2),
                    ],
                    note="Maximum deployment event. Remaining 10% SGOV is permanent reserve only.",
                    accent="#c84040",
                    accent_dark="#8a1818",
                )

            st.markdown(
                f"<div style='border-left:5px solid #c84040;background:#ffffff;border-radius:8px;"
                f"padding:14px 18px;margin-top:4px;box-shadow:0 1px 4px rgba(0,0,0,0.10)'>"
                f"<div style='color:#c84040;font-weight:800;font-size:0.95rem;margin-bottom:4px'>"
                f"PERMANENT RESERVE — {_fmt_dollars(portfolio_size * 0.10)} (10% of portfolio)</div>"
                f"<div style='color:#444;font-size:0.87rem;line-height:1.55'>"
                f"Keep minimum 10% in SGOV regardless. This is 6-month living expenses buffer plus emergency "
                f"opportunity reserve. Do NOT deploy.</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            st.markdown(
                _company_legend([
                    "BRK-B", "MSFT", "CME", "CVX", "COP", "EPD", "BAM", "CNI",
                    "FNV", "MCO", "RMS.PA", "GOOGL", "ASML", "SPGI", "V",
                    "NVO", "AXP", "COST", "FICO", "KEY-6861.T", "EQNR", "CSU.TO",
                ]),
                unsafe_allow_html=True,
            )

            st.caption("Not financial advice. Allocation percentages are guidelines, not mandates.")

    # ══════════════════════════════════════════════════════════════════════════
    # NEWS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_n:
        col_refresh_n, col_ts_n = st.columns([1, 4])
        with col_refresh_n:
            if st.button("Refresh News", key="refresh_n", type="primary", use_container_width=True):
                fetch_news.clear()
        with col_ts_n:
            st.caption(
                "5 most recent headlines per ticker  ·  "
                "Publisher color-coded  ·  Click headline to open article"
            )

        def _render_news_expander(ticker: str, label_prefix: str = "") -> None:
            header = f"{ticker}  {label_prefix}".strip() if label_prefix else ticker
            with st.expander(header, expanded=True):
                items = fetch_news(ticker)
                if label_prefix:
                    st.caption(label_prefix)
                if not items:
                    st.caption("No recent news found.")
                    return
                for item in items:
                    title = item.get("title", "")
                    link = item.get("link", "#")
                    publisher = item.get("publisher", "")
                    age = _fmt_news_age(item)
                    color = _publisher_color(publisher)
                    st.markdown(
                        f"<div style='margin:3px 0 5px 0;line-height:1.35'>"
                        f"<span style='color:{color};font-weight:700;font-size:0.71rem'>{publisher}</span>"
                        f"<span style='color:#999;font-size:0.7rem;margin-left:6px'>{age}</span><br>"
                        f"<a href='{link}' target='_blank' style='color:#222;font-size:0.8rem;"
                        f"text-decoration:none;line-height:1.3'>{title}</a>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        # ── Portfolio A ───────────────────────────────────────────────────────
        st.markdown(
            "<div style='background:#5a7f6a;color:#fff;padding:6px 14px;border-radius:5px;"
            "font-weight:700;font-size:1rem;margin:8px 0 4px 0'>Portfolio A  ·  28 tickers</div>",
            unsafe_allow_html=True,
        )
        for _tk in ALL_TICKERS:
            _render_news_expander(_tk)

        # ── Portfolio B ───────────────────────────────────────────────────────
        st.markdown(
            "<div style='background:#6e8fa0;color:#fff;padding:6px 14px;border-radius:5px;"
            "font-weight:700;font-size:1rem;margin:16px 0 4px 0'>Portfolio B  ·  21 tickers</div>",
            unsafe_allow_html=True,
        )
        for _tk in ALL_TICKERS_B:
            _render_news_expander(_tk)

        # ── Retired ───────────────────────────────────────────────────────────
        st.markdown(
            "<div style='background:#8e8eaa;color:#fff;padding:6px 14px;border-radius:5px;"
            "font-weight:700;font-size:1rem;margin:16px 0 4px 0'>Retired  ·  10 tickers</div>",
            unsafe_allow_html=True,
        )
        for _rs in RETIRED_STOCKS:
            _render_news_expander(_rs["ticker"], "Post-removal coverage")

        st.caption("Data: Yahoo Finance via yfinance.  Not financial advice.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
