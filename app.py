
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import numpy as np
import requests
import pandas as pd
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="F&O Future Spot Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 NSE F&O Future − Spot Scanner")

st.caption(
    "Only Current Month Future > Spot stocks are shown"
)

# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not API_KEY:
    st.error("ANGEL_API_KEY नहीं मिला")



