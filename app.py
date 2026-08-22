
import streamlit as st
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

BASE_HEADERS = {
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

def login():

    totp = pyotp.TOTP(TOTP_SECRET).now()

    url = BASE_URL + (
        "/rest/auth/angelbroking/"
        "user/v1/loginByPassword"
    )

    payload = {
        "clientcode": CLIENT_ID,
        "password": PASSWORD,
        "totp": totp
    }

    response = requests.post(
        url,
        json=payload,
        headers=BASE_HEADERS,
        timeout=30
    )

    data = response.json()

    if data.get("status") is not True:
        message = data.get(
            "message",
            "Login failed"
        )
        raise Exception(
            "Angel One Login Failed: "
            + str(message)
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER DOWNLOAD
# ============================================================

@st.cache_data(ttl=1800)
def download_master():

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
        raise Exception(
            "Angel One master खाली मिला"
        )

    return pd.DataFrame(data)


# ============================================================
# EXPIRY PARSER
# ============================================================

def parse_expiry(value):

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
# BUILD STOCK LIST
# ============================================================

def build_stock_list(master):

    df = master.copy()

    df["expiry_date"] = df["expiry"].apply(
        parse_expiry
    )

    df["lot_size"] = pd.to_numeric(
        df["lotsize"],
        errors="coerce"
    )

    df["token"] = (
        df["token"]
        .astype(str)
        .str.strip()
    )

    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .str.strip()
    )

    df["name"] = (
        df["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

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
    # NSE STOCK FUTURES
    # --------------------------------------------------------

    futures = df[
        (df["exchange"] == "NFO")
        & (df["instrument"] == "FUTSTK")
        & (df["expiry_date"].notna())
        & (df["expiry_date"] >= today)
        & (df["lot_size"].notna())
    ].copy()

    if futures.empty:
        raise Exception(
            "NSE FUTSTK contracts नहीं मिले"
        )

    # Nearest expiry = current available contract
    expiry = futures["expiry_date"].min()

    futures = futures[
        futures["expiry_date"] == expiry
    ].copy()

    # --------------------------------------------------------
    # NSE CASH STOCKS
    # --------------------------------------------------------

    cash = df[
        (df["exchange"] == "NSE")
        & (
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

        stock = (
            str(row["symbol"])
            .upper()
            .replace("-EQ", "")
            .strip()
        )

        spot_map[stock] = {
            "symbol": str(row["symbol"]),
            "token": str(row["token"])
        }

    # --------------------------------------------------------
    # MATCH FUTURE + SPOT
    # --------------------------------------------------------

    rows = []

    for _, row in futures.iterrows():

        name = (
            str(row["name"])
            .upper()
            .strip()
        )

        future_symbol = (
            str(row["symbol"])
            .upper()
            .strip()
        )

        matched = None

        # Direct name
        if name in spot_map:
            matched = name

        # Future symbol without FUT
        if matched is None:
            if future_symbol.endswith("FUT"):

                base = (
                    future_symbol[:-3]
                    .strip()
                )

                if base in spot_map:
                    matched = base

        # Prefix matching
        if matched is None:

            for stock in spot_map:

                if (
                    future_symbol.startswith(stock)
                    and future_symbol.endswith("FUT")
                ):
                    matched = stock
                    break

        if matched is None:
            continue

        rows.append({
            "Stock": matched,
            "Spot Symbol": spot_map[matched]["symbol"],
            "Spot Token": spot_map[matched]["token"],
            "Future Symbol": str(row["symbol"]),
            "Future Token": str(row["token"]),
            "Lot Size": int(row["lot_size"]),
            "Expiry": expiry
        })

    result = pd.DataFrame(rows)

    if result.empty:
        raise Exception(
            "Future और Spot matching नहीं मिली"
        )

    result = result.drop_duplicates(
        subset=["Stock"],
        keep="first"
    )

    return result, expiry


# ============================================================
# BATCH LTP
# ============================================================

def get_batch_ltp(
    jwt,
    exchange,
    tokens
):

    if not tokens:
        return {}

    headers = BASE_HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    prices = {}

    # Angel quote API में छोटे batches
    batch_size = 50

    for start in range(
        0,
        len(tokens),
        batch_size
    ):

        batch = tokens[
            start:start + batch_size
        ]

        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [
                    str(x)
                    for x in batch
                ]
            }
        }

        url = BASE_URL + (
            "/rest/secure/angelbroking/"
            "market/v1/quote/"
        )

        try:

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            data = response.json()

            if data.get("status") is True:

                fetched = (
                    data.get("data", {})
                    .get("fetched", [])
                )

                for item in fetched:

                    token = str(
                        item.get("symbolToken", "")
                    )

                    ltp = item.get("ltp")

                    if token and ltp is not None:

                        prices[token] = float(ltp)

        except Exception:
            continue

    return prices


# ============================================================
# SCAN
# ============================================================

def scan_market():

    # Master
    master = download_master()

    # Stock contracts
    stocks, expiry = build_stock_list(
        master
    )

    # Login
    jwt = login()

    # Tokens
    spot_tokens = (
        stocks["Spot Token"]
        .astype(str)
        .tolist()
    )

    future_tokens = (
        stocks["Future Token"]
        .astype(str)
        .tolist()
    )

    # --------------------------------------------------------
    # FAST BATCH SPOT
    # --------------------------------------------------------

    spot_prices = get_batch_ltp(
        jwt,
        "NSE",
        spot_tokens
    )

    # --------------------------------------------------------
    # FAST BATCH FUTURE
    # --------------------------------------------------------

    future_prices = get_batch_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    results = []

    spot_count = 0
    future_count = 0

    # --------------------------------------------------------
    # CALCULATION
    # --------------------------------------------------------

    for _, row in stocks.iterrows():

        spot_token = str(
            row["Spot Token"]
        )

        future_token = str(
            row["Future Token"]
        )

        spot = spot_prices.get(
            spot_token
        )

        future = future_prices.get(
            future_token
        )

        if spot is not None:
            spot_count += 1

        if future is not None:
            future_count += 1

        if spot is None:
            continue

        if future is None:
            continue

        # ====================================================
        # ONLY POSITIVE FUTURE PREMIUM
        # ====================================================

        difference = future - spot

        if difference <= 0:
            continue

        lot = int(
            row["Lot Size"]
        )

        final_value = (
            difference * lot
        )

        results.append({
            "Stock": row["Stock"],
            "Spot": round(spot, 2),
            "Current Future": round(future, 2),
            "Future − Spot": round(
                difference,
                2
            ),
            "Lot Size": lot,
            "Difference × Lot": round(
                final_value,
                2
            ),
            "Expiry": row["Expiry"].strftime(
                "%d-%b-%Y"
            ),
            "Future Symbol": row["Future Symbol"]
        })

    result = pd.DataFrame(results)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    if not result.empty:

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

        result["Stock"] = result.apply(
            lambda x:
            f"{x['Stock']} ({x['Lot Size']})",
            axis=1
        )

    diagnostics = {
        "total": len(stocks),
        "spot": spot_count,
        "future": future_count,
        "positive": len(result)
    }

    return (
        result,
        diagnostics,
        expiry
    )


# ============================================================
# DASHBOARD
# ============================================================

st.subheader(
    "⚡ Current Month F&O Scanner"
)

st.markdown(
    """
**Condition:** Current Month Future > Spot

**Difference:** Future − Spot

**Ranking:** (Future − Spot) × Lot Size
"""
)

# ============================================================
# BUTTON
# ============================================================

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Angel One से live data लिया जा रहा है..."
        ):

            result, diag, expiry = (
                scan_market()
            )

        st.success(
            "✅ Scan पूरा हो गया"
        )

        # ----------------------------------------------------
        # DIAGNOSTICS
        # ----------------------------------------------------

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Total F&O",
            diag["total"]
        )

        c2.metric(
            "Spot LTP",
            diag["spot"]
        )

        c3.metric(
            "Future LTP",
            diag["future"]
        )

        c4.metric(
            "Future > Spot",
            diag["positive"]
        )

        st.write(
            "Current Expiry:",
            expiry.strftime(
                "%d-%b-%Y"
            )
        )

        st.divider()

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        if result.empty:

            st.warning(
                "Future > Spot वाला कोई stock नहीं मिला।"
            )

            st.info(
                "ऊपर Spot LTP और Future LTP counts देखें।"
            )

        else:

            st.success(
                f"🎯 {len(result)} stocks मिले"
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
                file_name="fno_future_spot.csv",
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
        "🔄 Scan Now दबाएँ।"
    )

# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Formula: (Current Month Future − Spot) × Lot Size"
)

st.caption(
    "Only positive Future − Spot stocks are displayed."
)
```
