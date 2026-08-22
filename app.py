
import streamlit as st
import pandas as pd
import requests
import pyotp
import time
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="F&O Future Premium Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 NSE F&O Future − Spot Scanner")

st.info(
    "सिर्फ वही stock दिखेगा जिसका Current Month Future > Spot है"
)

# ============================================================
# ANGEL ONE SECRETS
# ===========================================
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not API_KEY:
    st.error("ANGEL_API_KEY नहीं मिला")
    st.stop()

if not CLIENT_ID:
    st.error("ANGEL_CLIENT_CODE नहीं मिला")
    st.stop()

if not PASSWORD:
    st.error("ANGEL_PASSWORD नहीं मिला")
    st.stop()

if not TOTP_SECRET:
    st.error("ANGEL_TOTP_SECRET नहीं मिला")
    st.stop()
# ============================================================
# ANGEL ONE
# ============================================================

BASE_URL = "https://apiconnect.angelone.in"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-UserType": "USER",
    "X-SourceID": "WEB",
    "X-PrivateKey": API_KEY,
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP": "127.0.0.1",
    "X-MACAddress": "00:00:00:00:00:00"
}

# ============================================================
# LOGIN
# ============================================================

def login_angel():

    totp = pyotp.TOTP(TOTP_SECRET).now()

    response = requests.post(
        BASE_URL + "/rest/auth/angelbroking/user/v1/loginByPassword",
        json={
            "clientcode": CLIENT_ID,
            "password": PASSWORD,
            "totp": totp
        },
        headers=HEADERS,
        timeout=30
    )

    data = response.json()

    if data.get("status") is not True:
        raise Exception(
            "Angel One Login Failed: "
            + str(data.get("message", "Unknown error"))
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER DOWNLOAD
# ============================================================

@st.cache_data(ttl=1800)
def get_master():

    url = (
        "https://margincalculator.angelbroking.com/"
        "OpenAPI_File/files/OpenAPIScripMaster.json"
