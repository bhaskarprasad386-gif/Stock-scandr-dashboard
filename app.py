import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Fast Market Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Fast & Furious Market Scanner")

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelone.in"

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
# NIFTY 50
# ============================================================

NIFTY_50 = [
    "ADANIENT",
    "ADANIPORTS",
    "APOLLOHOSP",
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJ-AUTO",
    "BAJFINANCE",
    "BAJAJFINSV",
    "BEL",
    "BHARTIARTL",
    "CIPLA",
    "COALINDIA",
    "DRREDDY",
    "EICHERMOT",
    "ETERNAL",
    "GRASIM",
    "HCLTECH",
    "HDFCBANK",
    "HDFCLIFE",
    "HEROMOTOCO",
    "HINDALCO",
    "HINDUNILVR",
    "ICICIBANK",
    "INDUSINDBK",
    "INFY",
    "ITC",
    "JIOFIN",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "MAXHEALTH",
    "NESTLEIND",
    "NTPC",
    "ONGC",
    "POWERGRID",
    "RELIANCE",
    "SBILIFE",
    "SHRIRAMFIN",
    "SBIN",
    "SUNPHARMA",
    "TATACONSUM",
    "TATASTEEL",
    "TCS",
    "TECHM",
    "TITAN",
    "TRENT",
    "ULTRACEMCO",
    "WIPRO"
]

# ============================================================
# HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def auth_headers(jwt):
    h = BASE_HEADERS.copy()
    h["Authorization"] = "Bearer " + jwt
    return h


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

    r = requests.post(
        url,
        json=payload,
        headers=BASE_HEADERS,
        timeout=20
    )

    data = r.json()

    if data.get("status") is not True:
        raise Exception(
            "Angel Login Failed: "
            + str(data.get("message", "Unknown error"))
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER
# ============================================================

@st.cache_data(ttl=1800)
def download_master():

    url = (
        "https://margincalculator.angelbroking.com/"
        "OpenAPI_File/files/OpenAPIScripMaster.json"
    )

    r = requests.get(
        url,
        timeout=60
    )

    r.raise_for_status()

    data = r.json()

    if not data:
        raise Exception("Angel master खाली मिला")

    return pd.DataFrame(data)


@st.cache_data(ttl=1800)
def prepare_master(master):

    df = master.copy()

    df["token"] = (
        df["token"]
        .astype(str)
        .str.strip()
    )

    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .str.upper()
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

    df["expiry_date"] = pd.to_datetime(
        df["expiry"],
        errors="coerce",
        dayfirst=True
    )

    df["strike_num"] = (
        pd.to_numeric(
            df["strike"],
            errors="coerce"
        ) / 100
    )

    df["lot_size"] = pd.to_numeric(
        df["lotsize"],
        errors="coerce"
    )

    return df


# ============================================================
# LTP
# ============================================================

def batch_ltp(jwt, exchange, tokens):

    tokens = [
        str(x)
        for x in tokens
        if str(x)
    ]

    if not tokens:
        return {}

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "market/v1/quote/"
    )

    headers = auth_headers(jwt)

    prices = {}

    for i in range(0, len(tokens), 50):

        batch = tokens[i:i + 50]

        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: batch
            }
        }

        try:

            r = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=15
            )

            data = r.json()

            if data.get("status") is not True:
                continue

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
# HISTORICAL
# ============================================================

def historical(
    jwt,
    token,
    interval="ONE_DAY",
    days=180
):

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "historical/v1/getCandleData"
    )

    end = now_ist()

    start = (
        end -
        pd.Timedelta(days=days)
    )

    payload = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": interval,
        "fromdate": start.strftime(
            "%Y-%m-%d %H:%M"
        ),
        "todate": end.strftime(
            "%Y-%m-%d %H:%M"
        )
    }

    try:

        r = requests.post(
            url,
            json=payload,
            headers=auth_headers(jwt),
            timeout=20
        )

        data = r.json()

        if data.get("status") is not True:
            return pd.DataFrame()

        candles = data.get("data") or []

        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            candles,
            columns=[
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df = df.dropna(
            subset=[
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        return df.sort_values(
            "datetime"
        ).reset_index(drop=True)

    except Exception:
        return pd.DataFrame()


# ============================================================
# RSI
# ============================================================

def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# OBV
# ============================================================

def obv(df):

    direction = np.sign(
        df["close"].diff()
    ).fillna(0)

    return (
        direction *
        df["volume"]
    ).cumsum()


# ============================================================
# RISING
# ============================================================

def rising(series, lookback=6):

    s = series.dropna()

    if len(s) < lookback:
        return False

    x = s.iloc[-lookback:]

    overall = (
        x.iloc[-1] >
        x.iloc[0]
    )

    rising_count = (
        x.diff()
        .dropna()
        .gt(0)
        .sum()
    )

    return (
        overall
        and
        rising_count >= 3
    )


# ============================================================
# PRICE FALL -> SIDEWAYS
#
# कोई 4% fall limit नहीं
# कोई 8% sideways limit नहीं
# ============================================================

def price_fall_sideways(df):

    if len(df) < 30:
        return False

    close = df["close"]

    previous_high = (
        close.iloc[:-8].max()
    )

    recent_low = (
        close.iloc[-8:].min()
    )

    if previous_high <= 0:
        return False

    # पहले के मुकाबले नीचे आया हो
    fall_exists = (
        recent_low < previous_high
    )

    if not fall_exists:
        return False

    # अंतिम 8 candles में directionless/consolidating
    recent = close.iloc[-8:]

    if len(recent) < 8:
        return False

    up_moves = (
        recent.diff() > 0
    ).sum()

    down_moves = (
        recent.diff() < 0
    ).sum()

    # दोनों तरफ movement होना चाहिए
    return (
        up_moves >= 2
        and
        down_moves >= 2
    )


# ============================================================
# 20 SMA
# ============================================================

def sma20(df):

    if len(df) < 20:
        return None

    return float(
        df["close"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )


def sma20_within_1_percent(
    price,
    sma
):

    if sma is None or sma <= 0:
        return "NO"

    distance = (
        abs(price - sma)
        / sma
    ) * 100

    return (
        "YES"
        if distance <= 1
        else "NO"
    )


# ============================================================
# RSI BEFORE SIDEWAYS
# ============================================================

def rsi_before_sideways(df):

    if len(df) < 30:
        return "Not Enough Data"

    x = df.copy()

    x["RSI"] = rsi(
        x["close"]
    )

    sideways_start = len(x) - 8

    before = x["RSI"].iloc[
        max(
            0,
            sideways_start - 6
        ):
        sideways_start
    ]

    after = x["RSI"].iloc[
        sideways_start:
    ]

    before_yes = (
        len(before) >= 4
        and
        rising(
            before,
            min(5, len(before))
        )
    )

    after_yes = (
        len(after) >= 4
        and
        rising(
            after,
            min(6, len(after))
        )
    )

    if before_yes and after_yes:
        return "⭐ RSI Rising Before Sideways"

    if before_yes:
        return "⭐ RSI Rising Before Sideways"

    if after_yes:
        return "⚡ RSI Rising During Sideways"

    return "NO"


# ============================================================
# NSE CASH TOKEN MAP
# ============================================================

def cash_token_map(master):

    cash = master[
        (master["exchange"] == "NSE")
        &
        master["symbol"].str.endswith("-EQ")
    ]

    result = {}

    for _, row in cash.iterrows():

        stock = (
            row["symbol"]
            .replace("-EQ", "")
            .strip()
        )

        result[stock] = {
            "symbol": row["symbol"],
            "token": str(row["token"])
        }

    return result


# ============================================================
# RSI SCANNER
# ============================================================

def scan_rsi(jwt, master):

    tokens = cash_token_map(
        master
    )

    rows = []

    for stock in NIFTY_50:

        if stock not in tokens:
            continue

        df = historical(
            jwt,
            tokens[stock]["token"],
            "ONE_DAY",
            180
        )

        if df.empty or len(df) < 30:
            continue

        if not price_fall_sideways(df):
            continue

        df["RSI"] = rsi(
            df["close"]
        )

        df["OBV"] = obv(df)

        rsi_yes = rising(
            df["RSI"],
            6
        )

        if not rsi_yes:
            continue

        obv_yes = rising(
            df["OBV"],
            6
        )

        price = float(
            df["close"].iloc[-1]
        )

        sma = sma20(df)

        rows.append({

            "Stock": stock,

            "Price": round(
                price,
                2
            ),

            "20 SMA": (
                round(sma, 2)
                if sma is not None
                else None
            ),

            "20 SMA Within 1%":
                sma20_within_1_percent(
                    price,
                    sma
                ),

            "RSI": round(
                float(
                    df["RSI"].iloc[-1]
                ),
                2
            ),

            "RSI Rising":
                "YES",

            "OBV Rising":
                "YES"
                if obv_yes
                else "NO",

            "RSI Before Sideways":
                rsi_before_sideways(
                    df
                ),

            "Price Phase":
                "Fall → Sideways"
        })

    result = pd.DataFrame(rows)

    if not result.empty:

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
# CURRENT MONTH EXPIRY
# ============================================================

def current_month_expiry(
    master,
    exchange="NFO"
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == exchange)
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] >= today
        )
    ].copy()

    if x.empty:
        return None

    same_month = x[
        (x["expiry_date"].dt.month == today.month)
        &
        (x["expiry_date"].dt.year == today.year)
    ]

    if not same_month.empty:

        return same_month[
            "expiry_date"
        ].min()

    return x[
        "expiry_date"
    ].min()


# ============================================================
# FUTURE MAP
# ============================================================

def stock_future_map(
    master,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (
            master["expiry_date"] == expiry
        )
    ]

    result = {}

    for stock in NIFTY_50:

        a = x[
            (x["name"] == stock)
            |
            (
                x["symbol"].str.startswith(
                    stock + "FUT"
                )
            )
        ]

        if a.empty:
            continue

        row = a.iloc[0]

        result[stock] = row

    return result


# ============================================================
# FUTURE > SPOT SCANNER
# ============================================================

def scan_future_spot(
    jwt,
    master
):

    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    spot_map = cash_token_map(
        master
    )

    fmap = stock_future_map(
        master,
        expiry
    )

    stocks = [
        s for s in NIFTY_50
        if s in spot_map and s in fmap
    ]

    spot_tokens = [
        spot_map[s]["token"]
        for s in stocks
    ]

    future_tokens = [
        str(fmap[s]["token"])
        for s in stocks
    ]

    spot_prices = batch_ltp(
        jwt,
        "NSE",
        spot_tokens
    )

    future_prices = batch_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        spot = spot_prices.get(
            spot_map[stock]["token"]
        )

        future = future_prices.get(
            str(fmap[stock]["token"])
        )

        if spot is None or future is None:
            continue

        difference = (
            future - spot
        )

        if difference <= 0:
            continue

        lot = int(
            fmap[stock]["lot_size"]
        )

        profit = (
            difference * lot
        )

        rows.append({

            "Stock": stock,

            "Spot": round(
                spot,
                2
            ),

            "Future": round(
                future,
                2
            ),

            "Future > Spot":
                "YES",

            "Difference": round(
                difference,
                2
            ),

            "Lot Size": lot,

            "Difference × Lot":
                round(
                    profit,
                    2
                ),

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                )
        })

    result = pd.DataFrame(rows)

    if not result.empty:

        result = result.sort_values(
            "Difference × Lot",
            ascending=False
        ).reset_index(drop=True)

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
# OPTION MAP
# ============================================================

def stock_option_map(
    master,
    stock,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "OPTSTK")
        &
        (master["name"] == stock)
        &
        (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():

        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        symbol = str(
            row["symbol"]
        )

        if symbol.endswith("CE"):
            typ = "CE"
        elif symbol.endswith("PE"):
            typ = "PE"
        else:
            continue

        result[
            (
                round(
                    float(strike),
                    2
                ),
                typ
            )
        ] = {
            "token": str(row["token"]),
            "symbol": symbol
        }

    return result


# ============================================================
# STOCK PUT-CALL PARITY
# ============================================================

def scan_stock_parity(
    jwt,
    master
):

    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    fmap = stock_future_map(
        master,
        expiry
    )

    rows = []

    for stock in NIFTY_50:

        if stock not in fmap:
            continue

        future_token = str(
            fmap[stock]["token"]
        )

        future_data = batch_ltp(
            jwt,
            "NFO",
            [future_token]
        )

        future = future_data.get(
            future_token
        )

        if future is None:
            continue

        contracts = stock_option_map(
            master,
            stock,
            expiry
        )

        if not contracts:
            continue

        strikes = sorted(
            set(
                strike
                for strike, typ
                in contracts.keys()
            )
        )

        strikes = sorted(
            strikes,
            key=lambda x:
                abs(x - future)
        )[:10]

        tokens = []

        for strike in strikes:

            for typ in ["CE", "PE"]:

                item = contracts.get(
                    (strike, typ)
                )

                if item:
                    tokens.append(
                        item["token"]
                    )

        prices = batch_ltp(
            jwt,
            "NFO",
            tokens
        )

        for strike in strikes:

            ce_item = contracts.get(
                (strike, "CE")
            )

            pe_item = contracts.get(
                (strike, "PE")
            )

            if not ce_item or not pe_item:
                continue

            ce = prices.get(
                ce_item["token"]
            )

            pe = prices.get(
                pe_item["token"]
            )

            if ce is None or pe is None:
                continue

            # सही parity residual
            parity = (
                ce
                - pe
                - (
                    future
                    - strike
                )
            )

            if abs(parity) <= 5:
                continue

            rows.append({

                "Stock": stock,

                "Expiry":
                    expiry.strftime(
                        "%d-%b-%Y"
                    ),

                "Future": round(
                    future,
                    2
                ),

                "Strike": round(
                    strike,
                    2
                ),

                "CE": round(
                    ce,
                    2
                ),

                "PE": round(
                    pe,
                    2
                ),

                "CE − PE": round(
                    ce - pe,
                    2
                ),

                "Future − Strike":
                    round(
                        future - strike,
                        2
                    ),

                "Parity Difference":
                    round(
                        parity,
                        2
                    ),

                "Absolute Difference":
                    round(
                        abs(parity),
                        2
                    )
            })

    result = pd.DataFrame(rows)

    if not result.empty:

        result = result.sort_values(
            "Absolute Difference",
            ascending=False
        ).reset_index(drop=True)

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
# INDEX OPTION HELPERS
# ============================================================

def index_contracts(
    master,
    name,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["expiry_date"] == expiry)
        &
        (
            master["name"] == name
        )
    ].copy()

    return x


def find_index_name(
    master,
    possible_names
):

    for name in possible_names:

        if (
            (master["name"] == name)
            &
            (master["exchange"] == "NFO")
        ).any():

            return name

    return None


# ============================================================
# INDEX PARITY
# ============================================================

def scan_index_parity(
    jwt,
    master,
    index_label
):

    if index_label == "NIFTY":

        possible_names = [
            "NIFTY"
        ]

    elif index_label == "BANKNIFTY":

        possible_names = [
            "BANKNIFTY"
        ]

    elif index_label == "SENSEX":

        possible_names = [
            "SENSEX"
        ]

    else:

        return pd.DataFrame()

    name = find_index_name(
        master,
        possible_names
    )

    if name is None:
        return pd.DataFrame()

    # Current month expiry
    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    x = index_contracts(
        master,
        name,
        expiry
    )

    if x.empty:
        return pd.DataFrame()

    # --------------------------------------------------------
    # FUTURE
    # --------------------------------------------------------

    futures = x[
        x["instrument"] == "FUTIDX"
    ]

    if futures.empty:
        return pd.DataFrame()

    future_row = futures.iloc[0]

    future_token = str(
        future_row["token"]
    )

    future_prices = batch_ltp(
        jwt,
        "NFO",
        [future_token]
    )

    future = future_prices.get(
        future_token
    )

    if future is None:
        return pd.DataFrame()

    # --------------------------------------------------------
    # OPTIONS
    # --------------------------------------------------------

    options = x[
        x["instrument"] == "OPTIDX"
    ].copy()

    if options.empty:
        return pd.DataFrame()

    options = options[
        options["symbol"].str.endswith(
            ("CE", "PE")
        )
    ]

    strikes = sorted(
        set(
            options["strike_num"]
            .dropna()
            .astype(float)
        )
    )

    strikes = sorted(
        strikes,
        key=lambda s:
            abs(s - future)
    )[:10]

    selected = options[
        options["strike_num"].isin(
            strikes
        )
    ]

    tokens = (
        selected["token"]
        .astype(str)
        .tolist()
    )

    prices = batch_ltp(
        jwt,
        "NFO",
        tokens
    )

    rows = []

    for strike in strikes:

        ce = selected[
            (selected["strike_num"] == strike)
            &
            selected["symbol"].str.endswith("CE")
        ]

        pe = selected[
            (selected["strike_num"] == strike)
            &
            selected["symbol"].str.endswith("PE")
        ]

        if ce.empty or pe.empty:
            continue

        ce_token = str(
            ce.iloc[0]["token"]
        )

        pe_token = str(
            pe.iloc[0]["token"]
        )

        ce_price = prices.get(
            ce_token
        )

        pe_price = prices.get(
            pe_token
        )

        if ce_price is None or pe_price is None:
            continue

        parity = (
            ce_price
            - pe_price
            - (
                future
                - strike
            )
        )

        if abs(parity) <= 5:
            continue

        rows.append({

            "Index": index_label,

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Future": round(
                future,
                2
            ),

            "Strike": round(
                strike,
                2
            ),

            "CE": round(
                ce_price,
                2
            ),

            "PE": round(
                pe_price,
                2
            ),

            "CE − PE": round(
                ce_price - pe_price,
                2
            ),

            "Future − Strike":
                round(
                    future - strike,
                    2
                ),

            "Parity Difference":
                round(
                    parity,
                    2
                ),

            "Absolute Difference":
                round(
                    abs(parity),
                    2
                )
        })

    result = pd.DataFrame(rows)

    if not result.empty:

        result = result.sort_values(
            "Absolute Difference",
            ascending=False
        ).reset_index(drop=True)

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
# DOWNLOAD BUTTON
# ============================================================

def show_result(
    result,
    filename
):

    if result is None or result.empty:

        st.info(
            "इस scan में कोई qualifying result नहीं मिला।"
        )

        return

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        height=600
    )

    csv = result.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# 1. RSI SCANNER
# ============================================================

st.divider()

st.header(
    "1️⃣ 📈 Nifty 50 RSI + OBV Scanner"
)

st.caption(
    "Fall → Sideways | RSI Rising | OBV Rising | "
    "20 SMA ±1% | RSI Before Sideways"
)

if st.button(
    "🔄 Scan RSI + OBV",
    key="rsi_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "RSI scanner चल रहा है..."
        ):

            master = prepare_master(
                download_master()
            )

            jwt = login()

            result = scan_rsi(
                jwt,
                master
            )

        st.session_state[
            "rsi_result"
        ] = result

        st.session_state[
            "rsi_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            f"RSI scan complete — {len(result)} stocks"
        )

    except Exception as e:

        st.error(
            "RSI Scanner Error: " + str(e)
        )

rsi_result = st.session_state.get(
    "rsi_result",
    pd.DataFrame()
)

show_result(
    rsi_result,
    "rsi_obv_scanner.csv"
)


# ============================================================
# 2. FUTURE SPOT
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚡ Future > Spot Scanner"
)

st.caption(
    "Current-month Future > Spot | "
    "Difference × Lot Size"
)

if st.button(
    "🔄 Scan Future > Spot",
    key="future_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Future + Spot data लिया जा रहा है..."
        ):

            master = prepare_master(
                download_master()
            )

            jwt = login()

            result = scan_future_spot(
                jwt,
                master
            )

        st.session_state[
            "future_result"
        ] = result

        st.session_state[
            "future_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            f"Future-Spot scan complete — "
            f"{len(result)} stocks"
        )

    except Exception as e:

        st.error(
            "Future Scanner Error: " + str(e)
        )

future_result = st.session_state.get(
    "future_result",
    pd.DataFrame()
)

show_result(
    future_result,
    "future_spot_scanner.csv"
)


# ============================================================
# 3. NIFTY 50 STOCK PARITY
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ Nifty 50 Stock Put-Call Parity"
)

st.caption(
    "Current-month expiry | 10 nearest strikes | "
    "|CE − PE − (Future − Strike)| > 5"
)

if st.button(
    "🔄 Scan Nifty 50 Stock Parity",
    key="stock_parity_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Nifty 50 stock option chain scan..."
        ):

            master = prepare_master(
                download_master()
            )

            jwt = login()

            result = scan_stock_parity(
                jwt,
                master
            )

        st.session_state[
            "stock_parity_result"
        ] = result

        st.session_state[
            "stock_parity_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            f"Nifty 50 parity scan complete — "
            f"{len(result)} setups"
        )

    except Exception as e:

        st.error(
            "Nifty 50 Parity Error: " + str(e)
        )

stock_parity_result = st.session_state.get(
    "stock_parity_result",
    pd.DataFrame()
)

show_result(
    stock_parity_result,
    "nifty50_stock_parity.csv"
)


# ============================================================
# 4. BANKNIFTY
# ============================================================

st.divider()

st.header(
    "4️⃣ 🏦 BankNifty Put-Call Parity"
)

st.caption(
    "Current-month expiry | 10 nearest strikes | "
    "|CE − PE − (Future − Strike)| > 5"
)

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "BankNifty option chain scan..."
        ):

            master = prepare_master(
                download_master()
            )

            jwt = login()

            result = scan_index_parity(
                jwt,
                master,
                "BANKNIFTY"
            )

        st.session_state[
            "banknifty_result"
        ] = result

        st.session_state[
            "banknifty_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            f"BankNifty scan complete — "
            f"{len(result)} setups"
        )

    except Exception as e:

        st.error(
            "BankNifty Error: " + str(e)
        )

banknifty_result = st.session_state.get(
    "banknifty_result",
    pd.DataFrame()
)

show_result(
    banknifty_result,
    "banknifty_parity.csv"
)


# ============================================================
# 5. SENSEX
# ============================================================

st.divider()

st.header(
    "5️⃣ 📊 Sensex Put-Call Parity"
)

st.caption(
    "Current-month expiry | 10 nearest strikes | "
    "|CE − PE − (Future − Strike)| > 5"
)

if st.button(
    "🔄 Scan Sensex",
    key="sensex_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Sensex option chain scan..."
        ):

            master = prepare_master(
                download_master()
            )

            jwt = login()

            result = scan_index_parity(
                jwt,
                master,
                "SENSEX"
            )

        st.session_state[
            "sensex_result"
        ] = result

        st.session_state[
            "sensex_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            f"Sensex scan complete — "
            f"{len(result)} setups"
        )

    except Exception as e:

        st.error(
            "Sensex Error: " + str(e)
        )

sensex_result = st.session_state.get(
    "sensex_result",
    pd.DataFrame()
)

show_result(
    sensex_result,
    "sensex_parity.csv"
)


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "हर scanner अलग है। एक scanner चलाने पर "
    "बाकी scanners का market data fetch नहीं होता।"
)

st.caption(
    "Result अगले successful scan तक session में saved रहता है।"
)
