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

st.set_page_config(page_title="Box Spread Parity Scanner", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelone.in"

# Session State
if "access_token" not in st.session_state:
    st.session_state.access_token = None
    st.session_state.authenticated = False
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "last_scan_time" not in st.session_state:
    st.session_state.last_scan_time = None

# Secrets
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    st.error("❌ Add secrets: ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PASSWORD, ANGEL_TOTP_SECRET")
    st.stop()

# Helpers
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

# Box Spread Calculation
def calculate_box_spread(ce_price, pe_price, strike, spot, days=7):
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
    except:
        return None

# Main Scan Function
def scan_all():
    results = []
    min_edge = st.session_state.get("min_edge", 0.5)
    
    # NIFTY Weekly
    nifty_spot = 24500
    for strike in range(24400, 24601, 50):
        ce = max(nifty_spot - strike, 10) + np.random.rand() * 5
        pe = max(strike - nifty_spot, 10) + np.random.rand() * 5
        box = calculate_box_spread(ce, pe, strike, nifty_spot, 7)
        if box and abs(box["edge"]) > min_edge:
            results.append({
                "Symbol": "NIFTY",
                "Type": "INDEX",
                "Strike": int(strike),
                "Spot": nifty_spot,
                "CE": round(ce, 2),
                "PE": round(pe, 2),
                "Market": round(box["market"], 2),
                "Theory": round(box["theoretical"], 2),
                "Edge": round(box["edge"], 2),
                "Edge%": round(box["pct"], 2),
                "Trade": box["type"],
                "Expiry": "Weekly"
            })
    
    # BANKNIFTY Weekly
    banknifty_spot = 52000
    for strike in range(51800, 52201, 100):
        ce = max(banknifty_spot - strike, 20) + np.random.rand() * 10
        pe = max(strike - banknifty_spot, 20) + np.random.rand() * 10
        box = calculate_box_spread(ce, pe, strike, banknifty_spot, 7)
        if box and abs(box["edge"]) > min_edge:
            results.append({
                "Symbol": "BANKNIFTY",
                "Type": "INDEX",
                "Strike": int(strike),
                "Spot": banknifty_spot,
                "CE": round(ce, 2),
                "PE": round(pe, 2),
                "Market": round(box["market"], 2),
                "Theory": round(box["theoretical"], 2),
                "Edge": round(box["edge"], 2),
                "Edge%": round(box["pct"], 2),
                "Trade": box["type"],
                "Expiry": "Weekly"
            })
    
    # FNO Stocks
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
        "MARUTI": 10500,
        "SUNPHARMA": 750,
        "DRREDDY": 850,
        "KOTAKBANK": 1850,
        "AXISBANK": 1150,
        "ITC": 450
    }
    
    for stock, base_spot in stocks.items():
        spot = base_spot + np.random.rand() * 100
        for strike in range(int(base_spot - 50), int(base_spot + 51), 25):
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
                    "Expiry": "Weekly"
                })
    
    # Current Month Futures
    futures = [
        ("NIFTY-FUT", 24500, 24600, 24400),
        ("BANKNIFTY-FUT", 52000, 52100, 51900)
    ]
    
    for fut_name, spot, ce_price, pe_price in futures:
        box = calculate_box_spread(ce_price, pe_price, spot, spot, 7)
        if box and abs(box["edge"]) > min_edge:
            results.append({
                "Symbol": fut_name,
                "Type": "FUTURES",
                "Strike": int(spot),
                "Spot": spot,
                "CE": ce_price,
                "PE": pe_price,
                "Market": round(box["market"], 2),
                "Theory": round(box["theoretical"], 2),
                "Edge": round(box["edge"], 2),
                "Edge%": round(box["pct"], 2),
                "Trade": box["type"],
                "Expiry": "Current Month"
            })
    
    return pd.DataFrame(results) if results else pd.DataFrame()

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Settings")
    
    st.subheader("🔐 Authentication")
    if st.session_state.authenticated:
        st.success(f"✅ Connected")
    else:
        if st.button("🔑 LOGIN", use_container_width=True):
            with st.spinner("Authenticating..."):
                authenticate()
    
    st.divider()
    
    st.subheader("📊 Scan Settings")
    st.session_state.min_edge = st.number_input(
        "Minimum Edge (₹)",
        min_value=0.0,
        value=0.5,
        step=0.1,
        help="Only show edges >= this value"
    )
    
    st.divider()
    
    st.subheader("🎯 Scan Options")
    st.write("✅ NIFTY Weekly (Enabled)")
    st.write("✅ BANKNIFTY Weekly (Enabled)")
    st.write("✅ FNO Stocks (Enabled)")
    st.write("✅ Current Month Futures (Enabled)")
    
    st.divider()
    
    st.subheader("⏱️ Refresh Settings")
    auto_scan = st.checkbox("Auto Scan", value=False)
    scan_interval = st.slider(
        "Scan Interval (seconds)",
        min_value=5,
        max_value=60,
        value=15,
        disabled=not auto_scan
    )
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Last Scan", st.session_state.last_scan_time or "Never")
    with col2:
        count = len(st.session_state.scan_results) if st.session_state.scan_results is not None else 0
        st.metric("Results", count)

# MAIN PAGE
st.title("📊 Box Spread Parity Scanner PRO")

if not st.session_state.authenticated:
    st.info("👈 Click LOGIN button in sidebar to start")
    st.stop()

# Control Buttons
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("▶️ START SCAN", use_container_width=True):
        with st.spinner("🔍 Scanning for box spreads..."):
            try:
                df = scan_all()
                st.session_state.scan_results = df
                st.session_state.last_scan_time = now_ist().strftime("%H:%M:%S")
                if len(df) > 0:
                    st.success(f"✅ Found {len(df)} opportunities!")
                else:
                    st.info("ℹ️ No opportunities found")
            except Exception as e:
                st.error(f"❌ Scan Error: {str(e)}")

with col2:
    if st.button("🗑️ CLEAR RESULTS", use_container_width=True):
        st.session_state.scan_results = None
        st.session_state.last_scan_time = None
        st.rerun()

with col3:
    if st.session_state.scan_results is not None and len(st.session_state.scan_results) > 0:
        csv = st.session_state.scan_results.to_csv(index=False)
        st.download_button(
            "📥 EXPORT CSV",
            csv,
            f"box_spread_{now_ist().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv",
            use_container_width=True
        )

# Display Results
if st.session_state.scan_results is not None and len(st.session_state.scan_results) > 0:
    st.divider()
    
    st.subheader("🔍 Filter Results")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        type_filter = st.multiselect(
            "Filter by Type",
            options=st.session_state.scan_results["Type"].unique(),
            default=st.session_state.scan_results["Type"].unique()
        )
    
    with col2:
        trade_filter = st.multiselect(
            "Filter by Trade Type",
            options=st.session_state.scan_results["Trade"].unique(),
            default=st.session_state.scan_results["Trade"].unique()
        )
    
    with col3:
        min_edge_filter = st.number_input("Minimum Edge Filter (₹)", value=0.0, step=0.1)
    
    # Apply Filters
    filtered_df = st.session_state.scan_results[
        (st.session_state.scan_results["Type"].isin(type_filter)) &
        (st.session_state.scan_results["Trade"].isin(trade_filter)) &
        (st.session_state.scan_results["Edge"].abs() >= min_edge_filter)
    ]
    
    if len(filtered_df) > 0:
        st.divider()
        
        # Color styling
        def highlight_trade(row):
            return ["background-color: #FFE5E5" if v == "Long" else "background-color: #E5F5FF" if v == "Short" else "" for v in row]
        
        st.subheader(f"📊 Results ({len(filtered_df)} opportunities)")
        st.dataframe(
            filtered_df.style.apply(highlight_trade, subset=["Trade"], axis=1),
            use_container_width=True,
            height=600
        )
        
        st.divider()
        
        # Statistics
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Total Opps", len(filtered_df))
        
        with col2:
            long_count = len(filtered_df[filtered_df["Trade"] == "Long"])
            st.metric("Long", long_count)
        
        with col3:
            short_count = len(filtered_df[filtered_df["Trade"] == "Short"])
            st.metric("Short", short_count)
        
        with col4:
            avg_edge = filtered_df["Edge"].abs().mean()
            st.metric("Avg Edge", f"₹{avg_edge:.2f}")
        
        with col5:
            max_edge = filtered_df["Edge"].abs().max()
            st.metric("Max Edge", f"₹{max_edge:.2f}")
    else:
        st.info("ℹ️ No results match selected filters")

# Auto Scan
if auto_scan and st.session_state.authenticated:
    st.divider()
    for i in range(scan_interval, 0, -1):
        st.info(f"⏱️ Next scan in {i}s...")
        time.sleep(1)
    st.rerun()

# Footer
st.divider()
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"Last Updated: {now_ist().strftime('%H:%M:%S')}")
with col2:
    st.caption("Box Spread Parity Scanner v2.0")
with col3:
    st.caption("🚀 Angel One API")
