import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

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
# SETTINGS
# ============================================================

MIN_EDGE = 0.50

# ATM +/- 10 = maximum 21 strikes
STRIKES_EACH_SIDE = 10

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
# Used only by RSI + Future/Spot scanners
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
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = "Bearer " + jwt
    return headers


# ============================================================
# LOGIN
# ============================================================

@st.cache_data(ttl=1500, show_spinner=False)
def login():

    totp = pyotp.TOTP(TOTP_SECRET).now()

    url = (
        BASE_URL
        + "/rest/auth/angelbroking/"
        + "user/v1/loginByPassword"
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
        timeout=20
    )

    data = response.json()

    if data.get("status") is not True:
        raise Exception(
            "Angel Login Failed: "
            + str(
                data.get(
                    "message",
                    "Unknown error"
                )
            )
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
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
            "Angel master खाली मिला"
        )

    return pd.DataFrame(data)


@st.cache_data(ttl=1800, show_spinner=False)
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
# FULL QUOTE
# ============================================================

def extract_bid_ask(item):

    bid = None
    ask = None

    # --------------------------------------------------------
    # Direct fields
    # --------------------------------------------------------

    for key in [
        "bid",
        "bidPrice",
        "bestBid",
        "buyPrice"
    ]:

        value = item.get(key)

        if value is not None:

            try:
                bid = float(value)
                break
            except Exception:
                pass

    for key in [
        "ask",
        "askPrice",
        "bestAsk",
        "sellPrice"
    ]:

        value = item.get(key)

        if value is not None:

            try:
                ask = float(value)
                break
            except Exception:
                pass

    # --------------------------------------------------------
    # Angel FULL quote depth
    # --------------------------------------------------------

    depth = item.get("depth") or {}

    buy_depth = depth.get("buy") or []
    sell_depth = depth.get("sell") or []

    if bid is None and buy_depth:

        bid_prices = []

        for level in buy_depth:

            if not isinstance(level, dict):
                continue

            value = level.get("price")

            try:

                if value is not None:
                    bid_prices.append(
                        float(value)
                    )

            except Exception:
                pass

        if bid_prices:
            bid = max(bid_prices)

    if ask is None and sell_depth:

        ask_prices = []

        for level in sell_depth:

            if not isinstance(level, dict):
                continue

            value = level.get("price")

            try:

                if value is not None:
                    ask_prices.append(
                        float(value)
                    )

            except Exception:
                pass

        if ask_prices:
            ask = min(ask_prices)

    return bid, ask


# ============================================================
# FAST BATCH FULL QUOTE
# ============================================================

def batch_full_quotes(
    jwt,
    exchange,
    tokens
):

    tokens = list(
        dict.fromkeys(
            str(token)
            for token in tokens
            if str(token)
        )
    )

    if not tokens:
        return {}

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
        + "market/v1/quote/"
    )

    headers = auth_headers(jwt)

    result = {}

    # Angel API batch
    for start in range(
        0,
        len(tokens),
        50
    ):

        batch = tokens[
            start:start + 50
        ]

        payload = {
            "mode": "FULL",
            "exchangeTokens": {
                exchange: batch
            }
        }

        try:

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=15
            )

            data = response.json()

            if data.get("status") is not True:
                continue

            fetched = (
                data.get("data", {})
                .get("fetched", [])
            )

            for item in fetched:

                token = str(
                    item.get(
                        "symbolToken",
                        ""
                    )
                )

                if not token:
                    continue

                ltp = item.get("ltp")

                try:

                    ltp = (
                        float(ltp)
                        if ltp is not None
                        else None
                    )

                except Exception:

                    ltp = None

                bid, ask = extract_bid_ask(
                    item
                )

                result[token] = {
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask
                }

        except Exception:
            continue

    return result


# ============================================================
# HISTORICAL
# ============================================================

def historical(
    jwt,
    token,
    interval="ONE_DAY",
    days=180
):

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
        + "historical/v1/getCandleData"
    )

    end = now_ist()

    start = (
        end
        - pd.Timedelta(days=days)
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

        response = requests.post(
            url,
            json=payload,
            headers=auth_headers(jwt),
            timeout=20
        )

        data = response.json()

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

        for column in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:

            df[column] = pd.to_numeric(
                df[column],
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

        return (
            df.sort_values("datetime")
            .reset_index(drop=True)
        )

    except Exception:

        return pd.DataFrame()


# ============================================================
# RSI
# ============================================================

def rsi(
    series,
    period=14
):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = (
        avg_gain
        /
        avg_loss.replace(
            0,
            np.nan
        )
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
        direction
        *
        df["volume"]
    ).cumsum()


# ============================================================
# RISING
# ============================================================

def rising(
    series,
    lookback=6
):

    s = series.dropna()

    if len(s) < lookback:
        return False

    x = s.iloc[
        -lookback:
    ]

    overall = (
        x.iloc[-1]
        >
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
# PRICE FALL SIDEWAYS
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

    if recent_low >= previous_high:
        return False

    recent = close.iloc[-8:]

    up_moves = (
        recent.diff() > 0
    ).sum()

    down_moves = (
        recent.diff() < 0
    ).sum()

    return (
        up_moves >= 2
        and
        down_moves >= 2
    )


# ============================================================
# SMA
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

    sideways_start = (
        len(x) - 8
    )

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
            min(
                5,
                len(before)
            )
        )
    )

    after_yes = (
        len(after) >= 4
        and
        rising(
            after,
            min(
                6,
                len(after)
            )
        )
    )

    if before_yes and after_yes:
        return (
            "⭐ RSI Rising Before Sideways"
        )

    if before_yes:
        return (
            "⭐ RSI Rising Before Sideways"
        )

    if after_yes:
        return (
            "⚡ RSI Rising During Sideways"
        )

    return "NO"


# ============================================================
# CASH TOKEN MAP
# ============================================================

def cash_token_map(master):

    cash = master[
        (master["exchange"] == "NSE")
        &
        master["symbol"].str.endswith(
            "-EQ"
        )
    ]

    result = {}

    for _, row in cash.iterrows():

        stock = (
            row["symbol"]
            .replace(
                "-EQ",
                ""
            )
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

def scan_rsi(
    jwt,
    master
):

    tokens = cash_token_map(
        master
    )

    rows = []

    def worker(stock):

        if stock not in tokens:
            return None

        df = historical(
            jwt,
            tokens[stock]["token"],
            "ONE_DAY",
            180
        )

        if df.empty or len(df) < 30:
            return None

        if not price_fall_sideways(df):
            return None

        df["RSI"] = rsi(
            df["close"]
        )

        df["OBV"] = obv(df)

        if not rising(
            df["RSI"],
            6
        ):
            return None

        obv_yes = rising(
            df["OBV"],
            6
        )

        price = float(
            df["close"].iloc[-1]
        )

        sma = sma20(df)

        return {
            "Stock": stock,
            "Price": round(
                price,
                2
            ),
            "20 SMA": (
                round(
                    sma,
                    2
                )
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
            "RSI Rising": "YES",
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
        }

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                stock
            )
            for stock in NIFTY_50
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:
                    rows.append(result)

            except Exception:
                pass

    result = pd.DataFrame(
        rows
    )

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
            master["expiry_date"]
            >= today
        )
    ].copy()

    if x.empty:
        return None

    same_month = x[
        (
            x["expiry_date"].dt.month
            ==
            today.month
        )
        &
        (
            x["expiry_date"].dt.year
            ==
            today.year
        )
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
            master["expiry_date"]
            == expiry
        )
    ]

    result = {}

    for _, row in x.iterrows():

        stock = str(
            row["name"]
        ).strip()

        if stock:
            result[stock] = row

    return result


# ============================================================
# ALL F&O STOCKS
# ============================================================

def all_fno_stocks(
    master,
    expiry
):

    futures = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (
            master["expiry_date"]
            == expiry
        )
    ]

    options = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "OPTSTK")
        &
        (
            master["expiry_date"]
            == expiry
        )
    ]

    future_names = set(
        futures["name"]
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    option_names = set(
        options["name"]
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    return sorted(
        future_names
        .intersection(
            option_names
        )
    )


# ============================================================
# FUTURE > SPOT
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
        stock
        for stock in NIFTY_50
        if (
            stock in spot_map
            and stock in fmap
        )
    ]

    spot_tokens = [
        spot_map[stock]["token"]
        for stock in stocks
    ]

    future_tokens = [
        str(
            fmap[stock]["token"]
        )
        for stock in stocks
    ]

    spot_quotes = batch_full_quotes(
        jwt,
        "NSE",
        spot_tokens
    )

    future_quotes = batch_full_quotes(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        spot_data = spot_quotes.get(
            spot_map[stock]["token"]
        )

        future_data = future_quotes.get(
            str(
                fmap[stock]["token"]
            )
        )

        if not spot_data or not future_data:
            continue

        spot = spot_data.get(
            "ltp"
        )

        future = future_data.get(
            "ltp"
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

            "Difference":
                round(
                    difference,
                    2
                ),

            "Lot Size":
                lot,

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

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = (
            result
            .sort_values(
                "Difference × Lot",
                ascending=False
            )
            .reset_index(drop=True)
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
# STOCK OPTION MAP
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
        (
            master["expiry_date"]
            == expiry
        )
    ]

    result = {}

    for _, row in x.iterrows():

        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        strike = round(
            float(strike),
            2
        )

        symbol = str(
            row["symbol"]
        )

        if symbol.endswith("CE"):
            option_type = "CE"

        elif symbol.endswith("PE"):
            option_type = "PE"

        else:
            continue

        result[
            (
                strike,
                option_type
            )
        ] = {
            "token":
                str(row["token"]),

            "symbol":
                symbol
        }

    return result


# ============================================================
# ESTIMATED MARGIN
# ============================================================

def estimated_margin(
    future_price,
    lot_size
):

    if future_price is None:
        return 0

    if lot_size <= 0:
        return 0

    contract_value = (
        future_price
        *
        lot_size
    )

    # Conservative estimate.
    # Actual SPAN + exposure margin may differ.
    return (
        contract_value
        *
        0.18
    )


# ============================================================
# PARITY CALCULATION
# ============================================================

def calculate_parity(
    stock,
    expiry,
    strike,
    ce_data,
    pe_data,
    future_data,
    lot_size
):

    ce_bid = ce_data.get(
        "bid"
    )

    ce_ask = ce_data.get(
        "ask"
    )

    pe_bid = pe_data.get(
        "bid"
    )

    pe_ask = pe_data.get(
        "ask"
    )

    future_bid = future_data.get(
        "bid"
    )

    future_ask = future_data.get(
        "ask"
    )

    values = [
        ce_bid,
        ce_ask,
        pe_bid,
        pe_ask,
        future_bid,
        future_ask
    ]

    # No executable quote
    if any(
        value is None
        or value <= 0
        for value in values
    ):
        return []

    rows = []

    # ========================================================
    # DIRECTION 1
    #
    # BUY CE @ ASK
    # SELL PE @ BID
    # SELL FUTURE @ BID
    #
    # Profit =
    # (Future Bid - Strike)
    # -
    # (CE Ask - PE Bid)
    # ========================================================

    synthetic_buy = (
        ce_ask
        -
        pe_bid
    )

    future_sell_value = (
        future_bid
        -
        strike
    )

    edge_buy = (
        future_sell_value
        -
        synthetic_buy
    )

    if edge_buy >= MIN_EDGE:

        edge_lot = (
            edge_buy
            *
            lot_size
        )

        margin = estimated_margin(
            future_bid,
            lot_size
        )

        edge_margin = (
            edge_lot
            /
            margin
            *
            100
            if margin > 0
            else 0
        )

        rows.append({

            "Stock":
                stock,

            "Direction":
                "BUY SYNTHETIC",

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Strike":
                round(
                    strike,
                    2
                ),

            "CE Bid":
                round(
                    ce_bid,
                    2
                ),

            "CE Ask":
                round(
                    ce_ask,
                    2
                ),

            "PE Bid":
                round(
                    pe_bid,
                    2
                ),

            "PE Ask":
                round(
                    pe_ask,
                    2
                ),

            "Future Bid":
                round(
                    future_bid,
                    2
                ),

            "Future Ask":
                round(
                    future_ask,
                    2
                ),

            "Synthetic":
                round(
                    synthetic_buy,
                    2
                ),

            "Future − Strike":
                round(
                    future_sell_value,
                    2
                ),

            "Edge/Unit":
                round(
                    edge_buy,
                    2
                ),

            "Lot Size":
                int(lot_size),

            "Edge × Lot":
                round(
                    edge_lot,
                    2
                ),

            "Est. Margin":
                round(
                    margin,
                    2
                ),

            "Edge/Margin %":
                round(
                    edge_margin,
                    3
                )
        })

    # ========================================================
    # DIRECTION 2
    #
    # SELL CE @ BID
    # BUY PE @ ASK
    # BUY FUTURE @ ASK
    #
    # Profit =
    # (CE Bid - PE Ask)
    # -
    # (Future Ask - Strike)
    # ========================================================

    synthetic_sell = (
        ce_bid
        -
        pe_ask
    )

    future_buy_value = (
        future_ask
        -
        strike
    )

    edge_sell = (
        synthetic_sell
        -
        future_buy_value
    )

    if edge_sell >= MIN_EDGE:

        edge_lot = (
            edge_sell
            *
            lot_size
        )

        margin = estimated_margin(
            future_ask,
            lot_size
        )

        edge_margin = (
            edge_lot
            /
            margin
            *
            100
            if margin > 0
            else 0
        )

        rows.append({

            "Stock":
                stock,

            "Direction":
                "SELL SYNTHETIC",

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Strike":
                round(
                    strike,
                    2
                ),

            "CE Bid":
                round(
                    ce_bid,
                    2
                ),

            "CE Ask":
                round(
                    ce_ask,
                    2
                ),

            "PE Bid":
                round(
                    pe_bid,
                    2
                ),

            "PE Ask":
                round(
                    pe_ask,
                    2
                ),

            "Future Bid":
                round(
                    future_bid,
                    2
                ),

            "Future Ask":
                round(
                    future_ask,
                    2
                ),

            "Synthetic":
                round(
                    synthetic_sell,
                    2
                ),

            "Future − Strike":
                round(
                    future_buy_value,
                    2
                ),

            "Edge/Unit":
                round(
                    edge_sell,
                    2
                ),

            "Lot Size":
                int(lot_size),

            "Edge × Lot":
                round(
                    edge_lot,
                    2
                ),

            "Est. Margin":
                round(
                    margin,
                    2
                ),

            "Edge/Margin %":
                round(
                    edge_margin,
                    3
                )
        })

    return rows


# ============================================================
# ALL F&O STOCK PARITY SCANNER
# ============================================================

def scan_all_fno_stock_parity(
    jwt,
    master
):

    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    # --------------------------------------------------------
    # ALL STOCK FUTURES
    # --------------------------------------------------------

    future_df = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (
            master["expiry_date"]
            == expiry
        )
    ].copy()

    # --------------------------------------------------------
    # ALL STOCK OPTIONS
    # --------------------------------------------------------

    option_df = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "OPTSTK")
        &
        (
            master["expiry_date"]
            == expiry
        )
    ].copy()

    if future_df.empty or option_df.empty:
        return pd.DataFrame()

    future_names = set(
        future_df["name"]
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    option_names = set(
        option_df["name"]
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    stocks = sorted(
        future_names
        &
        option_names
    )

    if not stocks:
        return pd.DataFrame()

    # --------------------------------------------------------
    # FUTURE MAP
    # --------------------------------------------------------

    future_map = {}

    for _, row in future_df.iterrows():

        stock = str(
            row["name"]
        ).strip()

        if not stock:
            continue

        future_map[stock] = {
            "token":
                str(row["token"]),

            "lot_size":
                int(row["lot_size"])
                if not pd.isna(
                    row["lot_size"]
                )
                else 1
        }

    # --------------------------------------------------------
    # OPTION MAP
    # --------------------------------------------------------

    option_maps = {}

    for stock in stocks:

        x = option_df[
            option_df["name"]
            == stock
        ]

        contract_map = {}

        for _, row in x.iterrows():

            strike = row["strike_num"]

            if pd.isna(strike):
                continue

            strike = round(
                float(strike),
                2
            )

            symbol = str(
                row["symbol"]
            )

            if symbol.endswith("CE"):
                option_type = "CE"

            elif symbol.endswith("PE"):
                option_type = "PE"

            else:
                continue

            contract_map[
                (
                    strike,
                    option_type
                )
            ] = {
                "token":
                    str(row["token"]),

                "symbol":
                    symbol
            }

        if contract_map:
            option_maps[stock] = (
                contract_map
            )

    # --------------------------------------------------------
    # FIRST: ALL FUTURES QUOTES
    # --------------------------------------------------------

    future_tokens = [
        future_map[stock]["token"]
        for stock in stocks
        if stock in future_map
        and stock in option_maps
    ]

    future_quotes = batch_full_quotes(
        jwt,
        "NFO",
        future_tokens
    )

    # --------------------------------------------------------
    # SELECT ATM ±10
    # --------------------------------------------------------

    selected = {}

    option_tokens = []

    for stock in stocks:

        if stock not in future_map:
            continue

        if stock not in option_maps:
            continue

        future_token = (
            future_map[stock]["token"]
        )

        future_data = future_quotes.get(
            future_token
        )

        if not future_data:
            continue

        future_ltp = future_data.get(
            "ltp"
        )

        if future_ltp is None:
            continue

        contracts = option_maps[
            stock
        ]

        strikes = sorted(
            set(
                strike
                for strike, option_type
                in contracts.keys()
            )
        )

        if not strikes:
            continue

        # Nearest ATM strike
        atm_index = min(
            range(len(strikes)),
            key=lambda i:
                abs(
                    strikes[i]
                    -
                    future_ltp
                )
        )

        start = max(
            0,
            atm_index
            -
            STRIKES_EACH_SIDE
        )

        end = min(
            len(strikes),
            atm_index
            +
            STRIKES_EACH_SIDE
            +
            1
        )

        selected_strikes = strikes[
            start:end
        ]

        selected_contracts = []

        for strike in selected_strikes:

            ce = contracts.get(
                (
                    strike,
                    "CE"
                )
            )

            pe = contracts.get(
                (
                    strike,
                    "PE"
                )
            )

            # दोनों CE + PE जरूरी
            if ce is None or pe is None:
                continue

            selected_contracts.append(
                (
                    strike,
                    ce,
                    pe
                )
            )

            option_tokens.append(
                ce["token"]
            )

            option_tokens.append(
                pe["token"]
            )

        if selected_contracts:

            selected[stock] = {
                "future":
                    future_data,

                "lot_size":
                    future_map[
                        stock
                    ]["lot_size"],

                "contracts":
                    selected_contracts
            }

    # --------------------------------------------------------
    # SECOND: ALL OPTIONS IN BATCH
    # --------------------------------------------------------

    option_quotes = batch_full_quotes(
        jwt,
        "NFO",
        option_tokens
    )

    # --------------------------------------------------------
    # CALCULATE BOTH DIRECTIONS
    # --------------------------------------------------------

    rows = []

    for stock, data in selected.items():

        future_data = data[
            "future"
        ]

        lot_size = data[
            "lot_size"
        ]

        for (
            strike,
            ce,
            pe
        ) in data["contracts"]:

            ce_data = option_quotes.get(
                ce["token"]
            )

            pe_data = option_quotes.get(
                pe["token"]
            )

            if not ce_data or not pe_data:
                continue

            result_rows = calculate_parity(
                stock,
                expiry,
                strike,
                ce_data,
                pe_data,
                future_data,
                lot_size
            )

            rows.extend(
                result_rows
            )

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    # --------------------------------------------------------
    # SORT BEST OPPORTUNITIES FIRST
    # --------------------------------------------------------

    result = (
        result
        .sort_values(
            [
                "Edge/Margin %",
                "Edge × Lot"
            ],
            ascending=False
        )
        .reset_index(
            drop=True
        )
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
# INDEX PARITY
# ============================================================

def scan_index_parity(
    jwt,
    master,
    index_name
):

    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == index_name)
        &
        (
            master["expiry_date"]
            == expiry
        )
    ].copy()

    if x.empty:
        return pd.DataFrame()

    futures = x[
        x["instrument"]
        == "FUTIDX"
    ]

    if futures.empty:
        return pd.DataFrame()

    future_row = futures.iloc[0]

    future_token = str(
        future_row["token"]
    )

    future_quotes = batch_full_quotes(
        jwt,
        "NFO",
        [future_token]
    )

    future_data = future_quotes.get(
        future_token
    )

    if not future_data:
        return pd.DataFrame()

    future_ltp = future_data.get(
        "ltp"
    )

    if future_ltp is None:
        return pd.DataFrame()

    options = x[
        x["instrument"]
        == "OPTIDX"
    ].copy()

    options = options[
        options["symbol"].str.endswith(
            (
                "CE",
                "PE"
            )
        )
    ]

    strikes = sorted(
        set(
            options["strike_num"]
            .dropna()
            .astype(float)
        )
    )

    if not strikes:
        return pd.DataFrame()

    atm_index = min(
        range(len(strikes)),
        key=lambda i:
            abs(
                strikes[i]
                -
                future_ltp
            )
    )

    start = max(
        0,
        atm_index
        -
        STRIKES_EACH_SIDE
    )

    end = min(
        len(strikes),
        atm_index
        +
        STRIKES_EACH_SIDE
        +
        1
    )

    strikes = strikes[
        start:end
    ]

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

    option_quotes = batch_full_quotes(
        jwt,
        "NFO",
        tokens
    )

    lot_size = (
        int(
            future_row["lot_size"]
        )
        if not pd.isna(
            future_row["lot_size"]
        )
        else 1
    )

    rows = []

    for strike in strikes:

        ce = selected[
            (
                selected["strike_num"]
                == strike
            )
            &
            selected["symbol"].str.endswith(
                "CE"
            )
        ]

        pe = selected[
            (
                selected["strike_num"]
                == strike
            )
            &
            selected["symbol"].str.endswith(
                "PE"
            )
        ]

        if ce.empty or pe.empty:
            continue

        ce_token = str(
            ce.iloc[0]["token"]
        )

        pe_token = str(
            pe.iloc[0]["token"]
        )

        ce_data = option_quotes.get(
            ce_token
        )

        pe_data = option_quotes.get(
            pe_token
        )

        if not ce_data or not pe_data:
            continue

        rows.extend(
            calculate_parity(
                index_name,
                expiry,
                float(strike),
                ce_data,
                pe_data,
                future_data,
                lot_size
            )
        )

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    result = (
        result
        .sort_values(
            [
                "Edge/Margin %",
                "Edge × Lot"
            ],
            ascending=False
        )
        .reset_index(
            drop=True
        )
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
# DISPLAY
# ============================================================

def show_result(
    result,
    filename
):

    if (
        result is None
        or
        result.empty
    ):

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
    ).encode(
        "utf-8"
    )

    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=filename,
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# LOAD MASTER + LOGIN
# ============================================================

try:

    master = prepare_master(
        download_master()
    )

    jwt = login()

except Exception as e:

    st.error(
        "Connection/Login Error: "
        + str(e)
    )

    st.stop()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header(
    "⚡ Scanner Settings"
)

auto_update = st.sidebar.toggle(
    "Auto Update",
    value=False
)

refresh_seconds = st.sidebar.selectbox(
    "Auto Update Interval",
    [5, 10, 15, 30, 60],
    index=1
)

st.sidebar.caption(
    "Auto Update सिर्फ Stock Parity "
    "scanner को लगातार refresh करेगा।"
)

min_edge_input = st.sidebar.number_input(
    "Minimum Edge / Unit ₹",
    min_value=0.05,
    max_value=100.0,
    value=0.50,
    step=0.05
)

# Global runtime value
MIN_EDGE = float(
    min_edge_input
)


# ============================================================
# 1. RSI SCANNER
# ============================================================

st.divider()

st.header(
    "1️⃣ 📈 Nifty 50 RSI + OBV Scanner"
)

st.caption(
    "Fall → Sideways | RSI Rising | "
    "OBV Rising | 20 SMA ±1%"
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
            f"RSI scan complete — "
            f"{len(result)} stocks"
        )

    except Exception as e:

        st.error(
            "RSI Scanner Error: "
            + str(e)
        )

show_result(
    st.session_state.get(
        "rsi_result",
        pd.DataFrame()
    ),
    "rsi_obv_scanner.csv"
)


# ============================================================
# 2. FUTURE > SPOT
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚡ Future > Spot Scanner"
)

st.caption(
    "Current-month Future > Spot | "
    "Difference × Lot"
)

if st.button(
    "🔄 Scan Future > Spot",
    key="future_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Future + Spot data..."
        ):

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
            "Future Scanner Error: "
            + str(e)
        )

show_result(
    st.session_state.get(
        "future_result",
        pd.DataFrame()
    ),
    "future_spot_scanner.csv"
)


# ============================================================
# 3. ALL F&O STOCK PARITY
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ ALL F&O Stock Put-Call Parity"
)

st.caption(
    "All F&O Stocks | Current Month | "
    "ATM ±10 = 21 Strikes | Both Directions | "
    "Bid/Ask Executable Prices"
)

scan_button = st.button(
    "🚀 Scan ALL F&O Stock Parity",
    key="all_fno_parity_button",
    type="primary",
    use_container_width=True
)

# Auto update trigger
if auto_update:
    scan_button = True


if scan_button:

    start_time = time.time()

    try:

        with st.spinner(
            "⚡ सभी F&O stocks का fast Bid/Ask scan..."
        ):

            result = scan_all_fno_stock_parity(
                jwt,
                master
            )

        # ----------------------------------------------------
        # IMPORTANT:
        # Replace old result ONLY after successful scan
        # ----------------------------------------------------

        st.session_state[
            "stock_parity_result"
        ] = result

        st.session_state[
            "stock_parity_time"
        ] = now_ist().strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        elapsed = (
            time.time()
            - start_time
        )

        st.success(
            f"Scan complete — "
            f"{len(result)} opportunities | "
            f"{elapsed:.1f} sec"
        )

    except Exception as e:

        st.error(
            "Stock Parity Error: "
            + str(e)
        )


stock_parity_result = st.session_state.get(
    "stock_parity_result",
    pd.DataFrame()
)

show_result(
    stock_parity_result,
    "all_fno_stock_parity.csv"
)

if (
    "stock_parity_time"
    in st.session_state
):

    st.caption(
        "Last successful update: "
        +
        st.session_state[
            "stock_parity_time"
        ]
    )


# ============================================================
# 4. BANKNIFTY
# ============================================================

st.divider()

st.header(
    "4️⃣ 🏦 BankNifty Put-Call Parity"
)

st.caption(
    "Bid/Ask | Both Directions | ATM ±10"
)

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "BankNifty parity scan..."
        ):

            result = scan_index_parity(
                jwt,
                master,
                "BANKNIFTY"
            )

        st.session_state[
            "banknifty_result"
        ] = result

    except Exception as e:

        st.error(
            "BankNifty Error: "
            + str(e)
        )

show_result(
    st.session_state.get(
        "banknifty_result",
        pd.DataFrame()
    ),
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
    "Bid/Ask | Both Directions | ATM ±10"
)

if st.button(
    "🔄 Scan Sensex",
    key="sensex_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Sensex parity scan..."
        ):

            result = scan_index_parity(
                jwt,
                master,
                "SENSEX"
            )

        st.session_state[
            "sensex_result"
        ] = result

    except Exception as e:

        st.error(
            "Sensex Error: "
            + str(e)
        )

show_result(
    st.session_state.get(
        "sensex_result",
        pd.DataFrame()
    ),
    "sensex_parity.csv"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_update:

    st.caption(
        f"🔄 Auto Update ON — "
        f"हर {refresh_seconds} सेकंड में नया scan"
    )

    time.sleep(
        refresh_seconds
    )

    st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "⚡ Stock Parity: सभी उपलब्ध F&O stocks"
)

st.caption(
    "BUY हमेशा Ask और SELL हमेशा Bid "
    "पर calculate किया जाता है।"
)

st.caption(
    "दोनों directions independently scan होती हैं।"
)

st.caption(
    "ATM से ±10 strikes यानी maximum 21 strikes "
    "per stock scan होते हैं।"
)

st.caption(
    "Estimated Margin केवल अनुमान है; "
    "actual SPAN + Exposure margin broker के "
    "actual requirement से अलग हो सकता है।"
)

st.caption(
    "पुराना result अगले successful scan तक "
    "session में saved रहता है।"
)
