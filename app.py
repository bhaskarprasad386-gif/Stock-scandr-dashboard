import streamlit as st
import pandas as pd
import requests
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo
import time

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="F&O Spot-Future Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 F&O Spot − Current Month Future Scanner")
st.caption("Angel One | Current Month Futures | Opportunity Value Ranking")

# ============================================================
# SETTINGS / SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_CODE = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

# ============================================================
# CHECK CREDENTIALS
# ============================================================

missing = []

if not API_KEY:
    missing.append("ANGEL_API_KEY")

if not CLIENT_CODE:
    missing.append("ANGEL_CLIENT_CODE")

if not PASSWORD:
    missing.append("ANGEL_PASSWORD")

if not TOTP_SECRET:
    missing.append("ANGEL_TOTP_SECRET")

if missing:
    st.error(
        "Angel One credentials अभी Streamlit Secrets में नहीं डाली गई हैं."
    )

    st.markdown("### Required Secrets")

    for x in missing:
        st.code(x)

    st.info(
        "API key के साथ Angel One login के लिए Client Code, "
        "Password/PIN और TOTP Secret भी चाहिए."
    )

    st.stop()

# ============================================================
# ANGEL ONE HEADERS
# ============================================================

BASE_URL = "https://apiconnect.angelone.in"

HEADERS_BASE = {
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

@st.cache_resource(ttl=600)
def angel_login():

    totp = pyotp.TOTP(TOTP_SECRET).now()

    url = (
        BASE_URL
        + "/rest/auth/angelbroking/user/v1/loginByPassword"
    )

    payload = {
        "clientcode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": totp
    }

    r = requests.post(
        url,
        json=payload,
        headers=HEADERS_BASE,
        timeout=20
    )

    data = r.json()

    if not data.get("status"):
        raise Exception(
            f"Angel One Login Failed: "
            f"{data.get('message', 'Unknown error')}"
        )

    jwt = data["data"]["jwtToken"]

    return jwt


# ============================================================
# LOAD ANGEL ONE MASTER
# ============================================================

@st.cache_data(ttl=3600)
def load_master():

    url = (
        "https://margincalculator.angelone.in/"
        "OpenAPI_File/files/OpenAPIScripMaster.json"
    )

    r = requests.get(url, timeout=60)
    r.raise_for_status()

    data = r.json()

    df = pd.DataFrame(data)

    return df


# ============================================================
# GET CURRENT MONTH EXPIRY
# ============================================================

def get_current_expiry(futures):

    futures = futures.copy()

    futures["expiry_date"] = pd.to_datetime(
        futures["expiry"],
        errors="coerce",
        dayfirst=False
    )

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    future_expiries = sorted(
        futures.loc[
            futures["expiry_date"] >= today,
            "expiry_date"
        ].dropna().unique()
    )

    if not future_expiries:
        raise Exception("Current future expiry नहीं मिली.")

    return pd.Timestamp(future_expiries[0])


# ============================================================
# ANGEL QUOTE API
# ============================================================

def get_quotes(jwt, exchange, tokens):

    if not tokens:
        return {}

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
        + "market/v1/quote/"
    )

    headers = HEADERS_BASE.copy()

    headers["Authorization"] = "Bearer " + jwt

    # Angel quote API allows multiple tokens.
    # We send batches to keep scanner fast.

    result = {}

    for i in range(0, len(tokens), 450):

        batch = tokens[i:i + 450]

        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [str(x) for x in batch]
            }
        }

        try:

            r = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=20
            )

            data = r.json()

            if not data.get("status"):
                continue

            fetched = data.get("data", {}).get(
                "fetched",
                []
            )

            for item in fetched:

                token = str(
                    item.get("symbolToken", "")
                )

                ltp = item.get("ltp")

                if token and ltp is not None:

                    result[token] = float(ltp)

        except Exception:
            continue

        time.sleep(0.15)

    return result


# ============================================================
# BUILD F&O UNIVERSE
# ============================================================

def prepare_futures(master):

    df = master.copy()

    # Stock futures
    futures = df[
        (df["exch_seg"].astype(str).str.lower() == "nse_fo")
        &
        (df["instrumenttype"].astype(str).str.upper() == "FUTSTK")
    ].copy()

    futures["expiry_date"] = pd.to_datetime(
        futures["expiry"],
        errors="coerce"
    )

    futures["lotsize_num"] = pd.to_numeric(
        futures["lotsize"],
        errors="coerce"
    )

    futures["token"] = futures["token"].astype(str)

    futures["name_clean"] = (
        futures["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    futures["symbol_clean"] = (
        futures["symbol"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    futures = futures.dropna(
        subset=["expiry_date", "lotsize_num"]
    )

    return futures


# ============================================================
# GET SPOT TOKENS
# ============================================================

def prepare_spot(master):

    spot = master[
        (master["exch_seg"].astype(str).str.lower() == "nse_cm")
    ].copy()

    spot["token"] = spot["token"].astype(str)

    spot["name_clean"] = (
        spot["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    spot["symbol_clean"] = (
        spot["symbol"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    # Equity symbols only
    spot = spot[
        spot["symbol_clean"].str.endswith("-EQ")
    ].copy()

    return spot


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():

    master = load_master()

    futures = prepare_futures(master)
    spot = prepare_spot(master)

    current_expiry = get_current_expiry(futures)

    current = futures[
        futures["expiry_date"] == current_expiry
    ].copy()

    # Remove duplicate contracts
    current = current.drop_duplicates(
        subset=["name_clean"],
        keep="first"
    )

    # --------------------------------------------------------
    # Match spot stock with future
    # --------------------------------------------------------

    spot_lookup = {}

    for _, row in spot.iterrows():

        name = row["name_clean"]

        if name and name != "NAN":

            spot_lookup[name] = {
                "token": str(row["token"]),
                "symbol": row["symbol_clean"]
            }

    matched = []

    for _, row in current.iterrows():

        name = row["name_clean"]

        if name not in spot_lookup:
            continue

        matched.append({
            "Name": name,
            "Future Symbol": row["symbol"],
            "Future Token": str(row["token"]),
            "Spot Token": spot_lookup[name]["token"],
            "Spot Symbol": spot_lookup[name]["symbol"],
            "Lot Size": int(row["lotsize_num"])
        })

    matched_df = pd.DataFrame(matched)

    if matched_df.empty:
        raise Exception(
            "Current month F&O stocks और NSE spot में match नहीं मिला."
        )

    jwt = angel_login()

    # --------------------------------------------------------
    # Spot quotes
    # --------------------------------------------------------

    spot_tokens = matched_df[
        "Spot Token"
    ].tolist()

    spot_prices = get_quotes(
        jwt,
        "NSE",
        spot_tokens
    )

    # --------------------------------------------------------
    # Future quotes
    # --------------------------------------------------------

    future_tokens = matched_df[
        "Future Token"
    ].tolist()

    future_prices = get_quotes(
        jwt,
        "NFO",
        future_tokens
    )

    # --------------------------------------------------------
    # CALCULATION
    # --------------------------------------------------------

    results = []

    for _, row in matched_df.iterrows():

        spot_token = str(row["Spot Token"])
        future_token = str(row["Future Token"])

        spot_price = spot_prices.get(
            spot_token
        )

        future_price = future_prices.get(
            future_token
        )

        if spot_price is None:
            continue

        if future_price is None:
            continue

        lot_size = int(row["Lot Size"])

        # USER REQUESTED FORMULA
        difference = spot_price - future_price

        # IMPORTANT:
        # Ranking is based on difference × lot size
        opportunity_value = difference * lot_size

        # Percentage difference
        if future_price != 0:

            difference_pct = (
                difference / future_price
            ) * 100

        else:

            difference_pct = 0

        results.append({

            "Stock": row["Name"],

            "Spot": round(
                spot_price, 2
            ),

            "Current Future": round(
                future_price, 2
            ),

            "Difference": round(
                difference, 2
            ),

            "Lot Size": lot_size,

            "Opportunity Value": round(
                opportunity_value, 2
            ),

            "Difference %": round(
                difference_pct, 2
            ),

            "Expiry": current_expiry.strftime(
                "%d-%b-%Y"
            ),

            "Future Symbol": row[
                "Future Symbol"
            ]

        })

    result = pd.DataFrame(results)

    if result.empty:
        raise Exception(
            "Angel One से Spot/Future LTP नहीं मिला."
        )

    # --------------------------------------------------------
    # HIGHEST VALUE FIRST
    # --------------------------------------------------------

    result = result.sort_values(
        "Opportunity Value",
        ascending=False
    ).reset_index(drop=True)

    result.insert(
        0,
        "Rank",
        range(1, len(result) + 1)
    )

    return result, current_expiry


# ============================================================
# DASHBOARD
# ============================================================

st.subheader("⚡ Current Month F&O Scanner")

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Angel One से Spot और Current Month Futures data लिया जा रहा है..."
    ):

        try:

            result, expiry = run_scanner()

            st.session_state["scanner_result"] = result
            st.session_state["expiry"] = expiry

            st.success(
                f"Scan completed | Expiry: "
                f"{expiry.strftime('%d-%b-%Y')}"
            )

        except Exception as e:

            st.error(
                f"Scanner Error: {e}"
            )


# ============================================================
# SHOW RESULT
# ============================================================

if "scanner_result" in st.session_state:

    result = st.session_state[
        "scanner_result"
    ]

    expiry = st.session_state[
        "expiry"
    ]

    # --------------------------------------------------------
    # TOP METRICS
    # --------------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Stocks Scanned",
        len(result)
    )

    c2.metric(
        "Expiry",
        expiry.strftime("%d-%b-%Y")
    )

    c3.metric(
        "Highest Opportunity",
        f"₹{result['Opportunity Value'].iloc[0]:,.0f}"
    )

    positive_count = (
        result["Opportunity Value"] > 0
    ).sum()

    c4.metric(
        "Positive Difference",
        positive_count
    )

    st.divider()

    # --------------------------------------------------------
    # TABLE
    # --------------------------------------------------------

    st.subheader(
        "🏆 Highest Spot − Future Value First"
    )

    display = result.copy()

    # Indian-style display formatting
    display["Spot"] = display["Spot"].map(
        lambda x: f"₹{x:,.2f}"
    )

    display["Current Future"] = display[
        "Current Future"
    ].map(
        lambda x: f"₹{x:,.2f}"
    )

    display["Difference"] = display[
        "Difference"
    ].map(
        lambda x: f"₹{x:,.2f}"
    )

    display["Opportunity Value"] = display[
        "Opportunity Value"
    ].map(
        lambda x: f"₹{x:,.0f}"
    )

    display["Difference %"] = display[
        "Difference %"
    ].map(
        lambda x: f"{x:.2f}%"
    )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=650
    )

    # --------------------------------------------------------
    # DOWNLOAD
    # --------------------------------------------------------

    csv = result.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        "⬇️ Download CSV",
        csv,
        "fo_spot_future_scanner.csv",
        "text/csv",
        use_container_width=True
    )

else:

    st.info(
        "ऊपर 🔄 Scan Now दबाएँ। "
        "Angel One से current month F&O data लेकर ranking बनेगी."
    )

# ============================================================
# DISCLAIMER
# ============================================================

st.caption(
    "This scanner is for analysis only. "
    "Opportunity Value is a mathematical Spot-Future difference "
    "multiplied by lot size and does not include brokerage, taxes, "
    "slippage, margin or financing costs."
)
