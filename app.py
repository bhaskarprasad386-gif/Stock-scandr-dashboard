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
    page_title="F&O Spot Future Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 F&O Spot − Current Month Future Scanner")
st.caption("Angel One Live F&O Scanner")

# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_CODE = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

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
    st.error("Angel One Secrets अधूरे हैं।")

    for item in missing:
        st.write("❌", item)

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

@st.cache_resource(ttl=600)
def angel_login():

    totp = pyotp.TOTP(TOTP_SECRET).now()

    url = (
        BASE_URL +
        "/rest/auth/angelbroking/user/v1/loginByPassword"
    )

    payload = {
        "clientcode": CLIENT_CODE,
        "password": PASSWORD,
        "totp": totp
    }

    response = requests.post(
        url,
        json=payload,
        headers=HEADERS,
        timeout=20
    )

    data = response.json()

    if not data.get("status"):
        raise Exception(
            "Angel One Login Failed: " +
            str(data.get("message", "Unknown error"))
        )

    return data["data"]["jwtToken"]


# ============================================================
# ANGEL ONE MASTER
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
        raise Exception("Angel One master data खाली है।")

    return pd.DataFrame(data)


# ============================================================
# EXPIRY CONVERTER
# ============================================================

def convert_expiry(value):

    if pd.isna(value):
        return pd.NaT

    text = str(value).strip().upper()

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
        except:
            pass

    return pd.to_datetime(
        text,
        errors="coerce",
        dayfirst=True
    )


# ============================================================
# PREPARE FUTURES
# ============================================================

def prepare_futures(master):

    df = master.copy()

    # Angel One NSE F&O segment
    futures = df[
        df["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nse_fo")
    ].copy()

    if futures.empty:

        raise Exception(
            "NSE F&O contracts नहीं मिले।"
        )

    # Stock Futures
    futures = futures[
        futures["instrumenttype"]
        .astype(str)
        .str.upper()
        .eq("FUTSTK")
    ].copy()

    if futures.empty:

        raise Exception(
            "FUTSTK contracts नहीं मिले।"
        )

    futures["expiry_date"] = (
        futures["expiry"]
        .apply(convert_expiry)
    )

    futures["lotsize_num"] = pd.to_numeric(
        futures["lotsize"],
        errors="coerce"
    )

    futures["token"] = (
        futures["token"]
        .astype(str)
    )

    futures["name_clean"] = (
        futures["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    futures = futures[
        futures["expiry_date"].notna()
    ].copy()

    futures = futures[
        futures["lotsize_num"].notna()
    ].copy()

    if futures.empty:

        raise Exception(
            "Futures मिले लेकिन expiry/lot size valid नहीं है।"
        )

    return futures


# ============================================================
# CURRENT MONTH FUTURE
# ============================================================

def get_current_month_futures(futures):

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    valid = futures[
        futures["expiry_date"] >= today
    ].copy()

    if valid.empty:

        raise Exception(
            "आज के बाद की future expiry नहीं मिली।"
        )

    # सबसे नजदीकी expiry = current active month
    current_expiry = valid[
        "expiry_date"
    ].min()

    current = valid[
        valid["expiry_date"] == current_expiry
    ].copy()

    return current, current_expiry


# ============================================================
# PREPARE SPOT
# ============================================================

def prepare_spot(master):

    spot = master[
        master["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nse_cm")
    ].copy()

    if spot.empty:

        raise Exception(
            "NSE cash market stocks नहीं मिले।"
        )

    spot["token"] = (
        spot["token"]
        .astype(str)
    )

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

    # केवल equity
    spot = spot[
        spot["symbol_clean"]
        .str.endswith("-EQ")
    ].copy()

    return spot


# ============================================================
# GET LTP
# ============================================================

def get_quotes(jwt, exchange, tokens):

    result = {}

    if not tokens:
        return result

    url = (
        BASE_URL +
        "/rest/secure/angelbroking/"
        "market/v1/quote/"
    )

    headers = HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    # Angel quote batches
    for start in range(
        0,
        len(tokens),
        450
    ):

        batch = tokens[
            start:start + 450
        ]

        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [
                    str(token)
                    for token in batch
                ]
            }
        }

        try:

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=20
            )

            data = response.json()

            if not data.get("status"):
                continue

            fetched = (
                data
                .get("data", {})
                .get("fetched", [])
            )

            for item in fetched:

                token = str(
                    item.get(
                        "symbolToken",
                        ""
                    )
                )

                ltp = item.get("ltp")

                if token and ltp is not None:

                    result[token] = float(ltp)

        except Exception:
            pass

        time.sleep(0.1)

    return result


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():

    # Master
    master = load_master()

    # Futures
    futures = prepare_futures(
        master
    )

    # Current month
    current, expiry = (
        get_current_month_futures(
            futures
        )
    )

    # Spot
    spot = prepare_spot(
        master
    )

    # --------------------------------------------------------
    # Spot lookup
    # --------------------------------------------------------

    spot_lookup = {}

    for _, row in spot.iterrows():

        name = row["name_clean"]

        if name and name != "NAN":

            spot_lookup[name] = {
                "token": str(
                    row["token"]
                ),
                "symbol": row[
                    "symbol_clean"
                ]
            }

    # --------------------------------------------------------
    # Match future with spot
    # --------------------------------------------------------

    matched = []

    for _, row in current.iterrows():

        name = row["name_clean"]

        if name not in spot_lookup:
            continue

        matched.append({

            "Stock": name,

            "Future Symbol":
                row["symbol"],

            "Future Token":
                str(row["token"]),

            "Spot Token":
                spot_lookup[name]["token"],

            "Lot Size":
                int(row["lotsize_num"])

        })

    matched = pd.DataFrame(
        matched
    )

    if matched.empty:

        raise Exception(
            "Spot और current month future में matching नहीं मिली।"
        )

    # --------------------------------------------------------
    # Login
    # --------------------------------------------------------

    jwt = angel_login()

    # --------------------------------------------------------
    # Spot LTP
    # --------------------------------------------------------

    spot_prices = get_quotes(
        jwt,
        "NSE",
        matched[
            "Spot Token"
        ].tolist()
    )

    # --------------------------------------------------------
    # Future LTP
    # --------------------------------------------------------

    future_prices = get_quotes(
        jwt,
        "NFO",
        matched[
            "Future Token"
        ].tolist()
    )

    # --------------------------------------------------------
    # CALCULATION
    # --------------------------------------------------------

    results = []

    for _, row in matched.iterrows():

        spot_price = spot_prices.get(
            str(row["Spot Token"])
        )

        future_price = future_prices.get(
            str(row["Future Token"])
        )

        if spot_price is None:
            continue

        if future_price is None:
            continue

        lot_size = int(
            row["Lot Size"]
        )

        # USER REQUEST
        difference = (
            spot_price -
            future_price
        )

        # Difference × Lot Size
        opportunity_value = (
            difference *
            lot_size
        )

        # Percentage
        if future_price != 0:

            difference_pct = (
                difference /
                future_price
            ) * 100

        else:

            difference_pct = 0

        results.append({

            "Stock":
                row["Stock"],

            "Spot":
                round(
                    spot_price,
                    2
                ),

            "Current Future":
                round(
                    future_price,
                    2
                ),

            "Difference":
                round(
                    difference,
                    2
                ),

            "Lot Size":
                lot_size,

            "Difference × Lot":
                round(
                    opportunity_value,
                    2
                ),

            "Difference %":
                round(
                    difference_pct,
                    2
                ),

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                )

        })

    result = pd.DataFrame(
        results
    )

    if result.empty:

        raise Exception(
            "Angel One से Spot/Future LTP नहीं मिला।"
        )

    # सबसे ज्यादा value ऊपर
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

    return result, expiry


# ============================================================
# DASHBOARD
# ============================================================

st.subheader(
    "⚡ Current Month F&O Scanner"
)

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Angel One से live Spot और Future data लिया जा रहा है..."
    ):

        try:

            result, expiry = (
                run_scanner()
            )

            st.session_state[
                "scanner_result"
            ] = result

            st.session_state[
                "scanner_expiry"
            ] = expiry

            st.success(
                "✅ Scan completed"
            )

        except Exception as e:

            st.error(
                "Scanner Error: " +
                str(e)
            )


# ============================================================
# RESULTS
# ============================================================

if "scanner_result" in st.session_state:

    result = st.session_state[
        "scanner_result"
    ]

    expiry = st.session_state[
        "scanner_expiry"
    ]

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Stocks",
        len(result)
    )

    col2.metric(
        "Current Expiry",
        expiry.strftime(
            "%d-%b-%Y"
        )
    )

    col3.metric(
        "Highest Value",
        f"₹{result['Difference × Lot'].iloc[0]:,.0f}"
    )

    st.divider()

    st.subheader(
        "🏆 Ranking — Difference × Lot Size"
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

else:

    st.info(
        "ऊपर 🔄 Scan Now दबाएँ।"
    )

# ============================================================
# NOTE
# ============================================================

st.caption(
    "Ranking = (Spot − Current Month Future) × Lot Size. "
    "Brokerage, taxes, slippage और funding cost शामिल नहीं हैं."
)
