
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
    )

    response = requests.get(
        url,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if not data:
        raise Exception("Angel One master खाली है")

    return pd.DataFrame(data)


# ============================================================
# EXPIRY
# ============================================================

def expiry_date(value):

    if pd.isna(value):
        return pd.NaT

    text = str(value).strip()

    formats = [
        "%d%b%Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S"
    ]

    for fmt in formats:
        try:
            return pd.to_datetime(
                text,
                format=fmt
            )
        except Exception:
            continue

    return pd.to_datetime(
        text,
        errors="coerce",
        dayfirst=True
    )


# ============================================================
# PREPARE STOCKS
# ============================================================

def prepare_stocks(df):

    df = df.copy()

    df["expiry_date"] = df["expiry"].apply(
        expiry_date
    )

    df["lot_size"] = pd.to_numeric(
        df["lotsize"],
        errors="coerce"
    )

    df["token"] = df["token"].astype(str)
    df["symbol"] = df["symbol"].astype(str)
    df["name"] = df["name"].astype(str).str.upper()

    df["exchange"] = (
        df["exch_seg"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    df["instrument"] = (
        df["instrumenttype"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    # --------------------------------------------------------
    # ALL NSE STOCK FUTURES
    # --------------------------------------------------------

    futures = df[
        (df["exchange"] == "NFO")
        &
        (df["instrument"] == "FUTSTK")
        &
        (df["expiry_date"].notna())
        &
        (df["expiry_date"] >= today)
        &
        (df["lot_size"].notna())
    ].copy()

    if futures.empty:
        raise Exception(
            "NFO FUTSTK stock futures नहीं मिले"
        )

    # सबसे नजदीकी expiry
    nearest = futures["expiry_date"].min()

    futures = futures[
        futures["expiry_date"] == nearest
    ].copy()

    # --------------------------------------------------------
    # NSE CASH
    # --------------------------------------------------------

    cash = df[
        (df["exchange"] == "NSE")
        &
        (
            df["symbol"]
            .str.upper()
            .str.endswith("-EQ")
        )
    ].copy()

    if cash.empty:
        raise Exception(
            "NSE cash stocks नहीं मिले"
        )

    # --------------------------------------------------------
    # SPOT MAP
    # --------------------------------------------------------

    spot_map = {}

    for _, row in cash.iterrows():

        name = (
            str(row["symbol"])
            .upper()
            .replace("-EQ", "")
            .strip()
        )

        spot_map[name] = {
            "symbol": str(row["symbol"]),
            "token": str(row["token"])
        }

    # --------------------------------------------------------
    # MATCH FUTURES WITH SPOT
    # --------------------------------------------------------

    stocks = []

    for _, row in futures.iterrows():

        future_name = (
            str(row["name"])
            .upper()
            .strip()
        )

        future_symbol = (
            str(row["symbol"])
            .upper()
            .strip()
        )

        match = None

        # 1. Master name match
        if future_name in spot_map:
            match = future_name

        # 2. FUT symbol match
        if match is None and future_symbol.endswith("FUT"):

            base = future_symbol[:-3].strip()

            if base in spot_map:
                match = base

        if match is None:
            continue

        spot = spot_map[match]

        stocks.append({
            "Stock": match,
            "Spot Symbol": spot["symbol"],
            "Spot Token": spot["token"],
            "Future Symbol": str(row["symbol"]),
            "Future Token": str(row["token"]),
            "Lot Size": int(row["lot_size"]),
            "Expiry": nearest
        })

    result = pd.DataFrame(stocks)

    if result.empty:
        raise Exception(
            "F&O और Spot matching नहीं मिली"
        )

    result = result.drop_duplicates(
        subset=["Stock"]
    )

    return result, nearest


# ============================================================
# LTP
# ============================================================

def get_ltp(
    jwt,
    exchange,
    symbol,
    token
):

    headers = HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    try:

        response = requests.post(
            BASE_URL +
            "/rest/secure/angelbroking/order/v1/getLtpData",

            json={
                "exchange": exchange,
                "tradingsymbol": symbol,
                "symboltoken": str(token)
            },

            headers=headers,
            timeout=20
        )

        data = response.json()

        if data.get("status") is True:

            if data.get("data"):

                ltp = data["data"].get("ltp")

                if ltp is not None:
                    return float(ltp)

    except Exception:
        return None

    return None


# ============================================================
# SCANNER
# ============================================================

def scan():

    master = get_master()

    stocks, expiry = prepare_stocks(
        master
    )

    jwt = login_angel()

    results = []

    progress = st.progress(0)

    total = len(stocks)

    for number, (_, row) in enumerate(
        stocks.iterrows(),
        start=1
    ):

        spot = get_ltp(
            jwt,
            "NSE",
            row["Spot Symbol"],
            row["Spot Token"]
        )

        future = get_ltp(
            jwt,
            "NFO",
            row["Future Symbol"],
            row["Future Token"]
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # ONLY FUTURE > SPOT
        # ----------------------------------------------------

        if spot is not None and future is not None:

            difference = future - spot

            if difference > 0:

                lot = int(
                    row["Lot Size"]
                )

                final_value = (
                    difference * lot
                )

                results.append({

                    "Stock":
                        row["Stock"],

                    "Spot":
                        round(spot, 2),

                    "Current Future":
                        round(future, 2),

                    "Future − Spot":
                        round(difference, 2),

                    "Lot Size":
                        lot,

                    "Difference × Lot":
                        round(final_value, 2),

                    "Expiry":
                        row["Expiry"].strftime(
                            "%d-%b-%Y"
                        ),

                    "Future Symbol":
                        row["Future Symbol"]
                })

        progress.progress(
            number / total
        )

        time.sleep(0.06)

    progress.empty()

    result = pd.DataFrame(results)

    if result.empty:
        return result, stocks, expiry

    # --------------------------------------------------------
    # HIGHEST FINAL VALUE FIRST
    # --------------------------------------------------------

    result = result.sort_values(
        "Difference × Lot",
        ascending=False
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # RANK
    # --------------------------------------------------------

    result.insert(
        0,
        "Rank",
        range(
            1,
            len(result) + 1
        )
    )

    # Stock + Lot
    result["Stock"] = result.apply(
        lambda x:
        f"{x['Stock']} ({x['Lot Size']})",
        axis=1
    )

    return result, stocks, expiry


# ============================================================
# DASHBOARD
# ============================================================

st.subheader(
    "⚡ Current Month F&O Scanner"
)

st.markdown(
    """
**Filter:** Future > Spot

**Difference:** Future − Spot

**Ranking:** Difference × Lot Size
"""
)

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "सभी NSE F&O stocks scan हो रहे हैं..."
        ):

            result, all_stocks, expiry = scan()

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Total F&O Stocks",
            len(all_stocks)
        )

        c2.metric(
            "Future > Spot",
            len(result)
        )

        c3.metric(
            "Expiry",
            expiry.strftime("%d-%b-%Y")
        )

        st.divider()

        if result.empty:

            st.warning(
                "अभी किसी stock का Future > Spot नहीं है।"
            )

        else:

            st.success(
                f"✅ {len(result)} stocks मिले"
            )

            st.dataframe(
                result,
                use_container_width=True,
                hide_index=True,
                height=700
            )

            csv = result.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "⬇️ Download CSV",
                data=csv,
                file_name="fno_future_premium.csv",
                mime="text/csv",
                use_container_width=True
            )

    except Exception as e:

        st.error(
            "Scanner Error: " + str(e)
        )

        st.exception(e)

else:

    st.write(
        "🔄 Scan Now दबाकर scanner चलाएँ।"
    )

st.divider()

st.caption(
    "Final Formula: (Current Month Future − Spot) × Lot Size"
)
