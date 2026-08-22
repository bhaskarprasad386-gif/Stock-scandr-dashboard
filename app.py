import streamlit as st
import pandas as pd
import requests
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="F&O Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 F&O Spot − Current Month Future Scanner")

# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_CODE = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not all([
    API_KEY,
    CLIENT_CODE,
    PASSWORD,
    TOTP_SECRET
]):
    st.error("Angel One Secrets अधूरे हैं।")
    st.stop()

# ============================================================
# ANGEL ONE HEADERS
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

def angel_login():

    totp = pyotp.TOTP(
        TOTP_SECRET
    ).now()

    response = requests.post(
        BASE_URL +
        "/rest/auth/angelbroking/user/v1/loginByPassword",
        json={
            "clientcode": CLIENT_CODE,
            "password": PASSWORD,
            "totp": totp
        },
        headers=HEADERS,
        timeout=20
    )

    data = response.json()

    if not data.get("status"):
        raise Exception(
            "Angel One Login Failed: " +
            str(data.get("message"))
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER DATA
# ============================================================

@st.cache_data(ttl=3600)
def load_master():

    url = (
        "https://margincalculator.angelone.in/"
        "OpenAPI_File/files/OpenAPIScripMaster.json"
    )

    response = requests.get(
        url,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if not data:
        raise Exception(
            "Angel One master data खाली है।"
        )

    return pd.DataFrame(data)


# ============================================================
# EXPIRY
# ============================================================

def parse_expiry(value):

    if pd.isna(value):
        return pd.NaT

    value = str(value).strip().upper()

    for fmt in [
        "%d%b%Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d"
    ]:

        try:
            return pd.to_datetime(
                value,
                format=fmt
            )
        except:
            pass

    return pd.to_datetime(
        value,
        errors="coerce",
        dayfirst=True
    )


# ============================================================
# FIND FUTURES AUTOMATICALLY
# ============================================================

def find_futures(df):

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    # --------------------------------------------------------
    # Debug information
    # --------------------------------------------------------

    st.write("### 🔍 Angel One Master Information")

    segments = (
        df["exch_seg"]
        .astype(str)
        .str.lower()
        .value_counts()
        .head(20)
    )

    instruments = (
        df["instrumenttype"]
        .astype(str)
        .str.upper()
        .value_counts()
        .head(30)
    )

    st.write("**Exchange Segments:**")
    st.write(segments)

    st.write("**Instrument Types:**")
    st.write(instruments)

    # --------------------------------------------------------
    # Find F&O using multiple possible segment names
    # --------------------------------------------------------

    segment = (
        df["exch_seg"]
        .astype(str)
        .str.lower()
    )

    possible_segments = [
        "nse_fo",
        "nfo",
        "nsefo"
    ]

    futures = df[
        segment.isin(
            possible_segments
        )
    ].copy()

    # --------------------------------------------------------
    # If segment matching fails,
    # search using symbol/instrument information
    # --------------------------------------------------------

    if futures.empty:

        instrument = (
            df["instrumenttype"]
            .astype(str)
            .str.upper()
        )

        futures = df[
            instrument.str.contains(
                "FUT",
                na=False
            )
        ].copy()

    if futures.empty:

        raise Exception(
            "Angel One master में Future contracts नहीं मिले।"
        )

    # --------------------------------------------------------
    # Parse expiry
    # --------------------------------------------------------

    futures["expiry_date"] = (
        futures["expiry"]
        .apply(parse_expiry)
    )

    futures = futures[
        futures["expiry_date"].notna()
    ].copy()

    futures = futures[
        futures["expiry_date"] >= today
    ].copy()

    if futures.empty:

        raise Exception(
            "Future contracts मिले लेकिन valid future expiry नहीं मिली।"
        )

    # --------------------------------------------------------
    # Stock futures
    # --------------------------------------------------------

    instrument = (
        futures["instrumenttype"]
        .astype(str)
        .str.upper()
    )

    stock_futures = futures[
        instrument.str.contains(
            "FUTSTK",
            na=False
        )
    ].copy()

    # अगर FUTSTK नाम अलग है तो
    # symbol में FUT खोजें

    if stock_futures.empty:

        stock_futures = futures[
            futures["symbol"]
            .astype(str)
            .str.upper()
            .str.contains(
                "FUT",
                na=False
            )
        ].copy()

    if stock_futures.empty:

        raise Exception(
            "Stock Futures (FUTSTK) नहीं मिले।"
        )

    # --------------------------------------------------------
    # Current nearest expiry
    # --------------------------------------------------------

    current_expiry = (
        stock_futures[
            "expiry_date"
        ].min()
    )

    current = stock_futures[
        stock_futures[
            "expiry_date"
        ] == current_expiry
    ].copy()

    return current, current_expiry


# ============================================================
# SPOT STOCKS
# ============================================================

def find_spot(df):

    segment = (
        df["exch_seg"]
        .astype(str)
        .str.lower()
    )

    spot = df[
        segment.isin([
            "nse_cm",
            "nse"
        ])
    ].copy()

    if spot.empty:

        # fallback
        spot = df[
            df["symbol"]
            .astype(str)
            .str.upper()
            .str.endswith("-EQ")
        ].copy()

    spot["symbol_clean"] = (
        spot["symbol"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    spot["name_clean"] = (
        spot["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    spot["token"] = (
        spot["token"]
        .astype(str)
    )

    return spot


# ============================================================
# QUOTE
# ============================================================

def get_ltp(
    jwt,
    exchange,
    token
):

    headers = HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    response = requests.post(
        BASE_URL +
        "/rest/secure/angelbroking/"
        "market/v1/quote/",
        json={
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [
                    str(token)
                ]
            }
        },
        headers=headers,
        timeout=20
    )

    data = response.json()

    if not data.get("status"):
        return None

    fetched = (
        data
        .get("data", {})
        .get("fetched", [])
    )

    if not fetched:
        return None

    return float(
        fetched[0]["ltp"]
    )


# ============================================================
# SCANNER
# ============================================================

def scan():

    master = load_master()

    futures, expiry = find_futures(
        master
    )

    spot = find_spot(
        master
    )

    jwt = angel_login()

    # Spot lookup
    spot_lookup = {}

    for _, row in spot.iterrows():

        name = row["name_clean"]

        if name == "NAN":
            continue

        spot_lookup[name] = row

    results = []

    # --------------------------------------------------------
    # Match Future with Spot
    # --------------------------------------------------------

    for _, future in futures.iterrows():

        name = (
            str(future["name"])
            .upper()
            .strip()
        )

        if name not in spot_lookup:
            continue

        spot_row = spot_lookup[name]

        try:

            spot_ltp = get_ltp(
                jwt,
                "NSE",
                spot_row["token"]
            )

            future_ltp = get_ltp(
                jwt,
                "NFO",
                future["token"]
            )

        except:

            continue

        if spot_ltp is None:
            continue

        if future_ltp is None:
            continue

        lot_size = int(
            float(
                future["lotsize"]
            )
        )

        # ----------------------------------------------------
        # USER FORMULA
        # ----------------------------------------------------

        difference = (
            spot_ltp -
            future_ltp
        )

        value = (
            difference *
            lot_size
        )

        results.append({

            "Stock": name,

            "Spot": round(
                spot_ltp,
                2
            ),

            "Current Future": round(
                future_ltp,
                2
            ),

            "Difference": round(
                difference,
                2
            ),

            "Lot Size": lot_size,

            "Difference × Lot": round(
                value,
                2
            ),

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                )
        })

    if not results:

        raise Exception(
            "Spot और Future का live LTP नहीं मिला।"
        )

    result = pd.DataFrame(
        results
    )

    # सबसे बड़ी value ऊपर
    result = result.sort_values(
        "Difference × Lot",
        ascending=False
    ).reset_index(
        drop=True
    )

    result.insert(
        0,
        "Rank",
        range(
            1,
            len(result) + 1
        )
    )

    return result


# ============================================================
# BUTTON
# ============================================================

st.subheader(
    "⚡ Current Month F&O Scanner"
)

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Angel One data पढ़ा जा रहा है..."
        ):

            result = scan()

        st.success(
            "✅ Scanner completed"
        )

        st.subheader(
            "🏆 Highest Difference × Lot"
        )

        st.dataframe(
            result,
            use_container_width=True,
            hide_index=True,
            height=650
        )

        csv = result.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "⬇️ Download CSV",
            csv,
            "fo_scanner.csv",
            "text/csv",
            use_container_width=True
        )

    except Exception as e:

        st.error(
            "Scanner Error: " +
            str(e)
        )


st.caption(
    "Ranking = (Spot − Current Month Future) × Lot Size"
)
