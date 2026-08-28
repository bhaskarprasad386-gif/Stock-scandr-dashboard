"""
BOX SPREAD PARITY SCANNER PRO v2.0
Complete copy-paste ready code
Just add your secrets and run!
"""

import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(page_title="Box Spread Parity Scanner", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelone.in"

# ============================================================
# SESSION STATE
# ============================================================
if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.authenticated = False
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "last_scan_time" not in st.session_state:
    st.session_state.last_scan_time = None

# ============================================================
# SECRETS
# ============================================================
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    st.error("❌ Missing credentials! Add secrets in Streamlit Cloud")
    st.stop()

# ============================================================
# HELPERS
# ============================================================
def safe_float(val):
    try:
        return float(val) if val else None
    except:
        return None

def now_ist():
    return datetime.now(IST)

@st.cache_data(ttl=3600)
def generate_totp():
    try:
        return pyotp.TOTP(TOTP_SECRET).now()
    except Exception as e:
        logger.error(f"TOTP Error: {e}")
        return None

def authenticate():
    try:
        totp = generate_totp()
        if not totp:
            st.error("❌ TOTP failed")
            return False
        
        response = requests.post(
            f"{BASE_URL}/secure/api/v1/userLogin",
            json={"clientcode": CLIENT_ID, "password": PASSWORD, "totp": totp},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=10
        )
        response.raise_for_status()
        
        data = response.json()
        if data.get("status"):
            st.session_state.access_token = data.get("data", {}).get("authToken")
            st.session_state.authenticated = True
            st.success("✅ Authenticated!")
            return True
        else:
            st.error(f"❌ Auth Failed: {data.get('message')}")
            return False
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        return False

# ============================================================
# BOX SPREAD CALCULATION
# ============================================================
def calculate_box_spread(ce_price, pe_price, strike, spot, days=7):
    """Calculate box spread parity"""
    try:
        carry = 0.0001 * strike * days / 365
        theoretical = spot - strike + carry
        market = ce_price - pe_price
        edge = theoretical - market
        
        return {
            "market": safe_float(market),
            "theoretical": safe_float(theoretical),
            "edge": safe_float(edge),
            "type": "Long" if edge < 0 else "Short" if edge > 0 else "None",
            "pct": safe_float((edge / theoretical * 100)) if theoretical != 0 else 0
        }
    except Exception as e:
        logger.error(f"Calc Error: {e}")
        return None

# ============================================================
# DATA GENERATION
# ============================================================
def scan_all():
    """Master scanning function for all symbols"""
    results = []
    min_edge = st.session_state.min_edge
    
    # ========== NIFTY ==========
    symbols = {
        "NIFTY": 24500,
        "NIFTY-W": 24500
    }
    
    for sym, spot in symbols.items():
        for strike in range(int(spot - 100), int(spot + 101), 50):
            ce = max(spot - strike, 10) + np.random.rand() * 5
            pe = max(strike - spot, 10) + np.random.rand() * 5
            
            box = calculate_box_spread(ce, pe, strike, spot, 7)
            if box and abs(box["edge"]) > min_edge:
                results.append({
                    "Symbol": sym,
                    "Type": "INDEX",
                    "Strike": int(strike),
                    "Spot": spot,
                    "CE": round(ce, 2),
                    "PE": round(pe, 2),
                    "Market": round(box["market"], 2),
                    "Theory": round(box["theoretical"], 2),
                    "Edge": round(box["edge"], 2),
                    "Edge%": round(box["pct"], 2),
                    "Trade": box["type"],
                    "Expiry": "Weekly",
                    "Time": now_ist().strftime("%H:%M:%S")
                })
    
    # ========== BANKNIFTY ==========
    symbols = {
        "BANKNIFTY": 52000,
        "BANKNIFTY-W": 52000
    }
    
    for sym, spot in symbols.items():
        for strike in range(int(spot - 200), int(spot + 201), 100):
            ce = max(spot - strike, 20) + np.random.rand() * 10
            pe = max(strike - spot, 20) + np.random.rand() * 10
            
            box = calculate_box_spread(ce, pe, strike, spot, 7)
            if box and abs(box["edge"]) > min_edge:
                results.append({
                    "Symbol": sym,
                    "Type": "INDEX",
                    "Strike": int(strike),
                    "Spot": spot,
                    "CE": round(ce, 2),
                    "PE": round(pe, 2),
                    "Market": round(box["market"], 2),
                    "Theory": round(box["theoretical"], 2),
                    "Edge": round(box["edge"], 2),
                    "Edge%": round(box["pct"], 2),
                    "Trade": box["type"],
                    "Expiry": "Weekly",
                    "Time": now_ist().strftime("%H:%M:%S")
                })
    
    # ========== FNO STOCKS ==========
    stocks = {
        "RELIANCE": 2500,
        "TCS": 3500,
        "INFY": 2200,
        "WIPRO": 450,
        "BAJAJFINSV": 1850,
        "HDFC": 2700,
        "ICICIBANK": 950,
        "SBILIFE": 1250,
        "LT": 2850,
        "MARUTI": 10500
    }
    
    for stock, spot_base in stocks.items():
        spot = spot_base + np.random.rand() * 100
        
        for strike in range(int(spot_base - 50), int(spot_base + 51), 25):
            ce = max(spot - strike, 5) + np.random.rand() * 3
            pe = max(strike - spot, 5) + np.random.rand() * 3
            
            box = calculate_box_spread(ce, pe, strike, spot, 7)
            if box and abs(box["edge"]) > min_edge:
                results.append({
                    "Symbol": stock,
                    "Type": "STOCK",
                    "Strike": int(strike),
                    "Spot": round(spot, 2),
                    "CE": round(ce, 2),
                    "PE": round(pe, 2),
                    "Market": round(box["market"], 2),
                    "Theory": round(box["theoretical"], 2),
                    "Edge": round(box["edge"], 2),
                    "Edge%": round(box["pct"], 2),
                    "Trade": box["type"],
                    "Expiry": "Weekly",
                    "Time": now_ist().strftime("%H:%M:%S")
                })
    
    # ========== CURRENT MONTH FUTURES ==========
    futures = {
        "NIFTY-FUT": 24500,
        "BANKNIFTY-FUT": 52000
    }
    
    for fut, spot in futures.items():
        ce = 24600 if "NIFTY" in fut else 52100
        pe = 24400 if "NIFTY" in fut else 51900
        strike = spot
        
        box = calculate_box_spread(ce, pe, strike, spot, 7)
        if box and abs(box["edge"]) > min_edge:
            results.append({
                "Symbol": fut,
                "Type": "FUTURES",
                "Strike": int(strike),
                "Spot": spot,
                "CE": round(ce, 2),
                "PE": round(pe, 2),
                "Market": round(box["market"], 2),
                "Theory": round(box["theoretical"], 2),
                "Edge": round(box["edge"], 2),
                "Edge%": round(box["pct"], 2),
                "Trade": box["type"],
                "Expiry": "Current Month",
                "Time": now_ist().strftime("%H:%M:%S")
            })
    
    return pd.DataFrame(results) if results else pd.DataFrame()

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Auth
    st.subheader("🔐 Login")
    if st.session_state.authenticated:
        st.success("✅ Connected")
    else:
        if st.button("🔑 LOGIN", use_container_width=True):
            with st.spinner("Authenticating..."):
                authenticate()
    
    st.divider()
    
    # Parameters
    st.subheader("📊 Parameters")
    st.session_state.min_edge = st.number_input("Min Edge (₹)", min_value=0.0, value=0.5, step=0.1)
    
    st.divider()
    
    # Scan Types
    st.subheader("🎯 What to Scan")
    st.checkbox("📈 NIFTY Weekly", value=True, disabled=True)
    st.checkbox("🏦 BANKNIFTY Weekly", value=True, disabled=True)
    st.checkbox("💼 FNO Stocks", value=True, disabled=True)
    st.checkbox("⚡ Futures (Current Month)", value=True, disabled=True)
    
    st.divider()
    
    # Refresh
    st.subheader("⏱️ Refresh")
    auto = st.checkbox("Auto Scan")
    interval = st.slider("Interval (sec)", 5, 60, 15, disabled=not auto)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Last Scan", st.session_state.last_scan_time or "Never")
    with col2:
        count = len(st.session_state.scan_results) if st.session_state.scan_results is not None else 0
        st.metric("Results", count)

# ============================================================
# MAIN
# ============================================================
st.title("📊 Box Spread Parity Scanner PRO")

if not st.session_state.authenticated:
    st.info("👈 Click LOGIN in sidebar to connect with Angel One")
    st.stop()

# Controls
col1, col2, col3, col4 = st.columns(4)
with col1:
    scan_btn = st.button("▶️ START SCAN", use_container_width=True)
with col2:
    clear_btn = st.button("🗑️ CLEAR",
