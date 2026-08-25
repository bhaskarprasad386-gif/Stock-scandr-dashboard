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
# AUTO REFRESH
# ============================================================

with st.sidebar:

    st.header("⚙️ Settings")

    auto_refresh = st.checkbox(
        "🔄 Auto Refresh",
        value=False
    )

    refresh_seconds = st.number_input(
        "Refresh Seconds",
        min_value=10,
        max_value=300,
        value=30,
        step=5
    )

    parity_threshold = st.number_input(
        "Parity Alert Threshold",
        min_value=0.0,
        value=5.0,
        step=0.5
    )

    parity_strikes = st.number_input(
        "Strikes Around Future",
        min_value=3,
        max_value=20,
        value=10,
        step=1
    )


# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get(
    "ANGEL_API_KEY",
    ""
)

CLIENT_ID = st.secrets.get(
    "ANGEL_CLIENT_CODE",
    ""
)

PASSWORD = st.secrets.get(
    "ANGEL_PASSWORD",
    ""
)

TOTP_SECRET = st.secrets.get(
    "ANGEL_TOTP_SECRET",
    ""
)


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
# HEADERS
# ============================================================

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

    h["Authorization"] = (
        "Bearer " + jwt
    )

    return h


# ============================================================
# LOGIN
# ============================================================

@st.cache_resource(
    ttl=120
)
def login():

    totp = pyotp.TOTP(
        TOTP_SECRET
    ).now()

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

@st.cache_data(
    ttl=1800,
    show_spinner=False
)
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
        raise Exception(
            "Angel master खाली मिला"
        )

    return pd.DataFrame(data)


@st.cache_data(
    ttl=1800,
    show_spinner=False
)
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
#
# इसमें LTP + BID + ASK मिलेगा
# ============================================================

def batch_full_quote(
    jwt,
    exchange,
    tokens
):

    tokens = list(
        dict.fromkeys(
            str(x)
            for x in tokens
            if str(x)
        )
    )

    if not tokens:
        return {}

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "market/v1/quote/"
    )

    headers = auth_headers(jwt)

    result = {}

    for i in range(
        0,
        len(tokens),
        50
    ):

        batch = tokens[
            i:i + 50
        ]

        payload = {
            "mode": "FULL",
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
                    item.get(
                        "symbolToken",
                        ""
                    )
                )

                if not token:
                    continue

                ltp = item.get(
                    "ltp"
                )

                bid = None
                ask = None

                # Angel FULL quote depth
                depth = item.get(
                    "depth",
                    {}
                )

                buys = depth.get(
                    "buy",
                    []
                )

                sells = depth.get(
                    "sell",
                    []
                )

                if buys:

                    bid = buys[0].get(
                        "price"
                    )

                if sells:

                    ask = sells[0].get(
                        "price"
                    )

                # fallback
                if bid is None:

                    bid = item.get(
                        "bestBid"
                    )

                if ask is None:

                    ask = item.get(
                        "bestAsk"
                    )

                result[token] = {
                    "ltp":
                        float(ltp)
                        if ltp is not None
                        else None,

                    "bid":
                        float(bid)
                        if bid is not None
                        else None,

                    "ask":
                        float(ask)
                        if ask is not None
                        else None
                }

        except Exception:
            continue

    return result


# ============================================================
# LTP COMPATIBILITY
# ============================================================

def batch_ltp(
    jwt,
    exchange,
    tokens
):

    data = batch_full_quote(
        jwt,
        exchange,
        tokens
    )

    return {
        token: x["ltp"]
        for token, x in data.items()
        if x.get("ltp") is not None
    }


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
        pd.Timedelta(
            days=days
        )
    )

    payload = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": interval,
        "fromdate":
            start.strftime(
                "%Y-%m-%d %H:%M"
            ),
        "todate":
            end.strftime(
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

        candles = (
            data.get("data")
            or []
        )

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

        return (
            df.sort_values(
                "datetime"
            )
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
        avg_gain /
        avg_loss.replace(
            0,
            np.nan
        )
    )

    return (
        100 -
        (
            100 /
            (1 + rs)
        )
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
            "symbol":
                row["symbol"],

            "token":
                str(row["token"])
        }

    return result


# ============================================================
# RSI SCAN
# ============================================================

def scan_rsi(
    jwt,
    master
):

    tokens = cash_token_map(
        master
    )

    stocks = [
        s for s in NIFTY_50
        if s in tokens
    ]

    rows = []

    def worker(stock):

        df = historical(
            jwt,
            tokens[stock]["token"],
            "ONE_DAY",
            180
        )

        if df.empty:
            return None

        if len(df) < 30:
            return None

        if not price_fall_sideways(df):
            return None

        df["RSI"] = rsi(
            df["close"]
        )

        df["OBV"] = obv(df)

        rsi_yes = rising(
            df["RSI"],
            6
        )

        if not rsi_yes:
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

            "20 SMA":
                round(sma, 2)
                if sma is not None
                else None,

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
        }

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                worker,
                stock
            )
            for stock in stocks
        ]

        for f in as_completed(
            futures
        ):

            try:

                result = f.result()

                if result:
                    rows.append(result)

            except Exception:
                pass

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            [
                "RSI",
                "OBV Rising"
            ],
            ascending=[
                False,
                False
            ]
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
# CURRENT EXPIRY
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
# ALL F&O STOCKS
# ============================================================

def all_fno_stocks(
    master,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (master["expiry_date"] == expiry)
    ].copy()

    stocks = sorted(
        x["name"]
        .dropna()
        .unique()
        .tolist()
    )

    return stocks


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
        )

        if stock not in result:
            result[stock] = row

    return result


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
        s for s in fmap
        if s in spot_map
    ]

    spot_tokens = [
        spot_map[s]["token"]
        for s in stocks
    ]

    future_tokens = [
        str(
            fmap[s]["token"]
        )
        for s in stocks
    ]

    spot_data = batch_full_quote(
        jwt,
        "NSE",
        spot_tokens
    )

    future_data = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        spot_token = (
            spot_map[stock]["token"]
        )

        future_token = str(
            fmap[stock]["token"]
        )

        spot_q = spot_data.get(
            spot_token,
            {}
        )

        future_q = future_data.get(
            future_token,
            {}
        )

        spot = spot_q.get(
            "ltp"
        )

        future = future_q.get(
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

            "Stock":
                stock,

            "Spot":
                round(spot, 2),

            "Future":
                round(future, 2),

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
    future,
    lot_size
):

    # conservative rough estimate
    # actual Angel RMS margin can differ

    if future is None:
        return None

    try:

        margin = (
            float(future)
            *
            int(lot_size)
            *
            0.15
        )

        return round(
            margin,
            2
        )

    except Exception:

        return None


# ============================================================
# PARITY DIRECTION
# ============================================================

def parity_direction(
    parity
):

    if parity > 0:
        return "CE−PE Rich"

    if parity < 0:
        return "CE−PE Cheap"

    return "Neutral"


# ============================================================
# ALL F&O STOCK PARITY
# ============================================================

def scan_all_stock_parity(
    jwt,
    master,
    strike_count=10,
    threshold=5
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

    stocks = all_fno_stocks(
        master,
        expiry
    )

    # --------------------------------------------------------
    # FUTURES QUOTE IN BATCH
    # --------------------------------------------------------

    future_tokens = [
        str(
            fmap[s]["token"]
        )
        for s in stocks
        if s in fmap
    ]

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    # --------------------------------------------------------
    # PROCESS STOCKS
    # --------------------------------------------------------

    for stock in stocks:

        if stock not in fmap:
            continue

        future_row = fmap[
            stock
        ]

        future_token = str(
            future_row["token"]
        )

        fq = future_quotes.get(
            future_token,
            {}
        )

        future_ltp = fq.get(
            "ltp"
        )

        future_bid = fq.get(
            "bid"
        )

        future_ask = fq.get(
            "ask"
        )

        if future_ltp is None:
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

        # nearest strikes to FUTURE
        strikes = sorted(
            strikes,
            key=lambda x:
                abs(
                    x -
                    future_ltp
                )
        )[
            :int(strike_count)
        ]

        tokens = []

        for strike in strikes:

            for typ in [
                "CE",
                "PE"
            ]:

                item = contracts.get(
                    (
                        strike,
                        typ
                    )
                )

                if item:
                    tokens.append(
                        item["token"]
                    )

        if not tokens:
            continue

        quotes = batch_full_quote(
            jwt,
            "NFO",
            tokens
        )

        lot_size = int(
            future_row["lot_size"]
        )

        margin = estimated_margin(
            future_ltp,
            lot_size
        )

        for strike in strikes:

            ce_item = contracts.get(
                (
                    strike,
                    "CE"
                )
            )

            pe_item = contracts.get(
                (
                    strike,
                    "PE"
                )
            )

            if not ce_item or not pe_item:
                continue

            ce_q = quotes.get(
                ce_item["token"],
                {}
            )

            pe_q = quotes.get(
                pe_item["token"],
                {}
            )

            ce_ltp = ce_q.get(
                "ltp"
            )

            pe_ltp = pe_q.get(
                "ltp"
            )

            ce_bid = ce_q.get(
                "bid"
            )

            ce_ask = ce_q.get(
                "ask"
            )

            pe_bid = pe_q.get(
                "bid"
            )

            pe_ask = pe_q.get(
                "ask"
            )

            if (
                ce_ltp is None
                or
                pe_ltp is None
            ):
                continue

            # ------------------------------------------------
            # LTP PARITY
            # ------------------------------------------------

            parity_ltp = (
                ce_ltp
                -
                pe_ltp
                -
                (
                    future_ltp
                    -
                    strike
                )
            )

            # ------------------------------------------------
            # EXECUTABLE BID/ASK PARITY
            #
            # Positive edge:
            # Sell expensive CE/Buy PE etc.
            #
            # Negative edge:
            # reverse side
            # ------------------------------------------------

            executable_positive = None
            executable_negative = None

            if (
                ce_bid is not None
                and
                pe_ask is not None
                and
                future_ask is not None
            ):

                executable_positive = (
                    ce_bid
                    -
                    pe_ask
                    -
                    (
                        future_ask
                        -
                        strike
                    )
                )

            if (
                ce_ask is not None
                and
                pe_bid is not None
                and
                future_bid is not None
            ):

                executable_negative = (
                    ce_ask
                    -
                    pe_bid
                    -
                    (
                        future_bid
                        -
                        strike
                    )
                )

            # choose strongest executable direction

            candidates = []

            if (
                executable_positive
                is not None
            ):

                candidates.append(
                    (
                        executable_positive,
                        "POSITIVE"
                    )
                )

            if (
                executable_negative
                is not None
            ):

                candidates.append(
                    (
                        executable_negative,
                        "NEGATIVE"
                    )
                )

            if candidates:

                best_value, best_side = max(
                    candidates,
                    key=lambda x:
                        abs(x[0])
                )

            else:

                best_value = parity_ltp
                best_side = (
                    "POSITIVE"
                    if parity_ltp > 0
                    else "NEGATIVE"
                )

            if abs(
                best_value
            ) <= threshold:

                continue

            rows.append({

                "Stock":
                    stock,

                "Direction":
                    parity_direction(
                        best_value
                    ),

                "Side":
                    best_side,

                "Expiry":
                    expiry.strftime(
                        "%d-%b-%Y"
                    ),

                "Future":
                    round(
                        future_ltp,
                        2
                    ),

                "Future Bid":
                    future_bid,

                "Future Ask":
                    future_ask,

                "Strike":
                    round(
                        strike,
                        2
                    ),

                "CE":
                    round(
                        ce_ltp,
                        2
                    ),

                "CE Bid":
                    ce_bid,

                "CE Ask":
                    ce_ask,

                "PE":
                    round(
                        pe_ltp,
                        2
                    ),

                "PE Bid":
                    pe_bid,

                "PE Ask":
                    pe_ask,

                "LTP Parity":
                    round(
                        parity_ltp,
                        2
                    ),

                "Executable Edge":
                    round(
                        best_value,
                        2
                    ),

                "Absolute Edge":
                    round(
                        abs(best_value),
                        2
                    ),

                "Lot Size":
                    lot_size,

                "Estimated Margin":
                    margin,

                "Potential / Lot":
                    round(
                        abs(best_value)
                        *
                        lot_size,
                        2
                    )
            })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            "Absolute Edge",
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
# INDEX HELPERS
# ============================================================

def find_index_name(
    master,
    possible_names
):

    for name in possible_names:

        if (
            (
                master["name"]
                == name
            )
            &
            (
                master["exchange"]
                == "NFO"
            )
        ).any():

            return name

    return None


# ============================================================
# INDEX PARITY
# ============================================================

def scan_index_parity(
    jwt,
    master,
    index_label,
    strike_count=10,
    threshold=5
):

    possible_names = {

        "NIFTY":
            ["NIFTY"],

        "BANKNIFTY":
            ["BANKNIFTY"],

        "SENSEX":
            ["SENSEX"]
    }

    if index_label not in possible_names:
        return pd.DataFrame()

    name = find_index_name(
        master,
        possible_names[
            index_label
        ]
    )

    if name is None:
        return pd.DataFrame()

    expiry = current_month_expiry(
        master,
        "NFO"
    )

    if expiry is None:
        return pd.DataFrame()

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == name)
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

    future_quote = batch_full_quote(
        jwt,
        "NFO",
        [future_token]
    ).get(
        future_token,
        {}
    )

    future_ltp = future_quote.get(
        "ltp"
    )

    future_bid = future_quote.get(
        "bid"
    )

    future_ask = future_quote.get(
        "ask"
    )

    if future_ltp is None:
        return pd.DataFrame()

    options = x[
        x["instrument"]
        == "OPTIDX"
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
            abs(
                s -
                future_ltp
            )
    )[
        :int(strike_count)
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

    quotes = batch_full_quote(
        jwt,
        "NFO",
        tokens
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

        ce_q = quotes.get(
            ce_token,
            {}
        )

        pe_q = quotes.get(
            pe_token,
            {}
        )

        ce_ltp = ce_q.get(
            "ltp"
        )

        pe_ltp = pe_q.get(
            "ltp"
        )

        ce_bid = ce_q.get(
            "bid"
        )

        ce_ask = ce_q.get(
            "ask"
        )

        pe_bid = pe_q.get(
            "bid"
        )

        pe_ask = pe_q.get(
            "ask"
        )

        if (
            ce_ltp is None
            or
            pe_ltp is None
        ):
            continue

        parity_ltp = (
            ce_ltp
            -
            pe_ltp
            -
            (
                future_ltp
                -
                strike
            )
        )

        positive = None
        negative = None

        if (
            ce_bid is not None
            and
            pe_ask is not None
            and
            future_ask is not None
        ):

            positive = (
                ce_bid
                -
                pe_ask
                -
                (
                    future_ask
                    -
                    strike
                )
            )

        if (
            ce_ask is not None
            and
            pe_bid is not None
            and
            future_bid is not None
        ):

            negative = (
                ce_ask
                -
                pe_bid
                -
                (
                    future_bid
                    -
                    strike
                )
            )

        candidates = []

        if positive is not None:
            candidates.append(
                positive
            )

        if negative is not None:
            candidates.append(
                negative
            )

        best = (
            max(
                candidates,
                key=abs
            )
            if candidates
            else parity_ltp
        )

        if abs(best) <= threshold:
            continue

        rows.append({

            "Index":
                index_label,

            "Direction":
                parity_direction(
                    best
                ),

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Future":
                round(
                    future_ltp,
                    2
                ),

            "Future Bid":
                future_bid,

            "Future Ask":
                future_ask,

            "Strike":
                round(
                    strike,
                    2
                ),

            "CE":
                round(
                    ce_ltp,
                    2
                ),

            "CE Bid":
                ce_bid,

            "CE Ask":
                ce_ask,

            "PE":
                round(
                    pe_ltp,
                    2
                ),

            "PE Bid":
                pe_bid,

            "PE Ask":
                pe_ask,

            "LTP Parity":
                round(
                    parity_ltp,
                    2
                ),

            "Executable Edge":
                round(
                    best,
                    2
                ),

            "Absolute Edge":
                round(
                    abs(best),
                    2
                )
        })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            "Absolute Edge",
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
# SHOW RESULT
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
# LOAD MASTER ONCE
# ============================================================

try:

    master = prepare_master(
        download_master()
    )

except Exception as e:

    st.error(
        "Master Error: "
        + str(e)
    )

    st.stop()


# ============================================================
# LOGIN BUTTON
# ============================================================

if (
    "jwt" not in st.session_state
):

    st.session_state[
        "jwt"
    ] = None


if st.button(
    "🔐 Connect Angel One",
    use_container_width=True
):

    try:

        st.session_state[
            "jwt"
        ] = login()

        st.success(
            "Angel One Connected"
        )

    except Exception as e:

        st.error(
            str(e)
        )


jwt = st.session_state.get(
    "jwt"
)


if not jwt:

    st.warning(
        "पहले ऊपर Connect Angel One दबाएँ।"
    )

    st.stop()


# ============================================================
# 1 RSI
# ============================================================

st.divider()

st.header(
    "1️⃣ 📈 Nifty 50 RSI + OBV Scanner"
)

st.caption(
    "Fall → Sideways + RSI Rising + OBV"
)

if st.button(
    "🔄 Scan RSI + OBV",
    key="rsi_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "RSI scanner..."
        ):

            result = scan_rsi(
                jwt,
                master
            )

        st.session_state[
            "rsi_result"
        ] = result

        st.success(
            f"RSI scan complete — "
            f"{len(result)} stocks"
        )

    except Exception as e:

        st.error(
            "RSI Error: "
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
# 2 FUTURE SPOT
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚡ Future > Spot Scanner"
)

if st.button(
    "🔄 Scan Future > Spot",
    key="future_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Future + Spot..."
        ):

            result = scan_future_spot(
                jwt,
                master
            )

        st.session_state[
            "future_result"
        ] = result

        st.success(
            f"Future-Spot scan complete — "
            f"{len(result)} stocks"
        )

    except Exception as e:

        st.error(
            "Future Error: "
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
# 3 ALL F&O STOCK PARITY
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ ALL F&O Stock Put-Call Parity"
)

st.caption(
    "सभी current-month F&O stocks | "
    "Bid/Ask based executable edge | दोनों direction"
)

if st.button(
    "🚀 Scan ALL F&O Stock Parity",
    key="all_stock_parity_button",
    type="primary",
    use_container_width=True
):

    try:

        start = time.time()

        with st.spinner(
            "सभी F&O stocks की parity scan हो रही है..."
        ):

            result = scan_all_stock_parity(
                jwt,
                master,
                parity_strikes,
                parity_threshold
            )

        elapsed = (
            time.time() - start
        )

        st.session_state[
            "all_stock_parity_result"
        ] = result

        st.success(
            f"F&O parity complete — "
            f"{len(result)} setups | "
            f"{elapsed:.1f} sec"
        )

    except Exception as e:

        st.error(
            "F&O Parity Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "all_stock_parity_result",
        pd.DataFrame()
    ),
    "all_fno_stock_parity.csv"
)


# ============================================================
# 4 NIFTY 50 INDEX
# ============================================================

st.divider()

st.header(
    "4️⃣ 📊 Nifty 50 Index Put-Call Parity"
)

if st.button(
    "🔄 Scan Nifty 50 Index",
    key="nifty_index_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Nifty Index parity..."
        ):

            result = scan_index_parity(
                jwt,
                master,
                "NIFTY",
                parity_strikes,
                parity_threshold
            )

        st.session_state[
            "nifty_index_result"
        ] = result

        st.success(
            f"Nifty Index scan complete — "
            f"{len(result)} setups"
        )

    except Exception as e:

        st.error(
            "Nifty Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "nifty_index_result",
        pd.DataFrame()
    ),
    "nifty_index_parity.csv"
)


# ============================================================
# 5 BANKNIFTY
# ============================================================

st.divider()

st.header(
    "5️⃣ 🏦 BankNifty Put-Call Parity"
)

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "BankNifty parity..."
        ):

            result = scan_index_parity(
                jwt,
                master,
                "BANKNIFTY",
                parity_strikes,
                parity_threshold
            )

        st.session_state[
            "banknifty_result"
        ] = result

        st.success(
            f"BankNifty scan complete — "
            f"{len(result)} setups"
        )

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
# 6 SENSEX
# ============================================================

st.divider()

st.header(
    "6️⃣ 📊 Sensex Put-Call Parity"
)

if st.button(
    "🔄 Scan Sensex",
    key="sensex_button",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Sensex parity..."
        ):

            result = scan_index_parity(
                jwt,
                master,
                "SENSEX",
                parity_strikes,
                parity_threshold
            )

        st.session_state[
            "sensex_result"
        ] = result

        st.success(
            f"Sensex scan complete — "
            f"{len(result)} setups"
        )

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
# LAST UPDATE
# ============================================================

st.divider()

st.caption(
    "📡 Data source: Angel One SmartAPI"
)

st.caption(
    "⚡ Parity में LTP के साथ Bid/Ask executable edge "
    "को प्राथमिकता दी गई है।"
)

st.caption(
    "⚠️ Estimated Margin केवल rough estimate है; "
    "actual Angel RMS margin अलग हो सकता है।"
)

st.caption(
    "💾 हर scanner का result अगले successful scan तक "
    "session में सुरक्षित रहता है।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st.info(
        f"🔄 Auto Refresh ON — "
        f"हर {refresh_seconds} सेकंड में page refresh होगा।"
    )

    time.sleep(
        refresh_seconds
    )

    st.rerun()
