import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
import io
import zipfile
import re

from datetime import datetime, timedelta
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

ANGEL_BASE = "https://apiconnect.angelone.in"

NSE_BASE = "https://www.nseindia.com"


# ============================================================
# SIDEBAR SETTINGS
# ============================================================

with st.sidebar:

    st.header("⚙️ Scanner Settings")

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

    st.subheader("Parity")

    parity_threshold = st.number_input(
        "Minimum Executable Edge ₹",
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

    st.subheader("MTF")

    mtf_own_percent = st.number_input(
        "Your Own Money %",
        min_value=1.0,
        max_value=100.0,
        value=25.0,
        step=1.0
    )

    mtf_broker_percent = (
        100.0 -
        mtf_own_percent
    )

    mtf_interest_daily = st.number_input(
        "MTF Interest % / Day",
        min_value=0.0,
        max_value=1.0,
        value=0.049,
        step=0.001,
        format="%.3f"
    )

    st.caption(
        f"Broker funded = {mtf_broker_percent:.1f}%"
    )

    st.subheader("Rollover")

    rollover_high_percent = st.number_input(
        "High Rollover %",
        min_value=50.0,
        max_value=100.0,
        value=80.0,
        step=1.0
    )

    rollover_cost_high_percent = st.number_input(
        "High Rollover Cost %",
        min_value=0.0,
        max_value=20.0,
        value=0.50,
        step=0.05
    )

    backtest_days = st.number_input(
        "Backtest Days",
        min_value=90,
        max_value=400,
        value=365,
        step=30
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
# ANGEL HEADERS
# ============================================================

ANGEL_HEADERS = {
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
# TIME
# ============================================================

def now_ist():

    return datetime.now(IST)


# ============================================================
# ANGEL AUTH
# ============================================================

def auth_headers(jwt):

    h = ANGEL_HEADERS.copy()

    h["Authorization"] = (
        "Bearer " + jwt
    )

    return h


# ============================================================
# LOGIN
# ============================================================

@st.cache_resource(ttl=120)
def login():

    totp = pyotp.TOTP(
        TOTP_SECRET
    ).now()

    url = ANGEL_BASE + (
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
        headers=ANGEL_HEADERS,
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

    url = ANGEL_BASE + (
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
                data.get(
                    "data",
                    {}
                )
                .get(
                    "fetched",
                    []
                )
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

                bid = None
                ask = None

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
# HISTORICAL
# ============================================================

def historical(
    jwt,
    token,
    interval="ONE_DAY",
    days=365
):

    url = ANGEL_BASE + (
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

        "symboltoken":
            str(token),

        "interval":
            interval,

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
            timeout=25
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

        return (
            df.dropna()
            .sort_values(
                "datetime"
            )
            .reset_index(
                drop=True
            )
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
        100 /
        (1 + rs)
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
# FALL SIDEWAYS
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
        return "⭐ RSI Rising Before Sideways"

    if after_yes:
        return "⚡ RSI Rising During Sideways"

    return "NO"


# ============================================================
# CASH MAP
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
# RSI SCANNER
# ============================================================

def scan_rsi(
    jwt,
    master
):

    tokens = cash_token_map(
        master
    )

    stocks = [
        s
        for s in NIFTY_50
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

            "Stock":
                stock,

            "Price":
                round(
                    price,
                    2
                ),

            "20 SMA":
                round(
                    sma,
                    2
                )
                if sma is not None
                else None,

            "20 SMA Within 1%":
                sma20_within_1_percent(
                    price,
                    sma
                ),

            "RSI":
                round(
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
                    rows.append(
                        result
                    )

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
    ]

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
# ALL FNO STOCKS
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
        (
            master["expiry_date"]
            == expiry
        )
    ]

    return sorted(
        x["name"]
        .dropna()
        .unique()
        .tolist()
    )


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
# CHARGE ENGINE
# ============================================================

GST = 0.18

ANGEL_EQUITY_BROKERAGE_CAP = 20.0
ANGEL_EQUITY_BROKERAGE_RATE = 0.001
ANGEL_EQUITY_MIN_BROKERAGE = 5.0

FNO_BROKERAGE_PER_ORDER = 20.0

NSE_EQUITY_TXN = 0.0000325
NSE_FUTURE_TXN = 0.0000173

SEBI_PER_CRORE = 10.0

EQUITY_DELIVERY_STT = 0.001
FUTURE_SELL_STT = 0.0005

STAMP_EQUITY_BUY = 0.00015
STAMP_FUTURE_BUY = 0.00002


def equity_delivery_brokerage(
    turnover
):

    if turnover <= 0:
        return 0.0

    value = min(
        ANGEL_EQUITY_BROKERAGE_CAP,
        turnover *
        ANGEL_EQUITY_BROKERAGE_RATE
    )

    return max(
        ANGEL_EQUITY_MIN_BROKERAGE,
        value
    )


def fno_brokerage():

    return FNO_BROKERAGE_PER_ORDER


def sebi_charge(
    turnover
):

    return (
        turnover /
        10_000_000
    ) * SEBI_PER_CRORE


def gst_on(
    brokerage,
    transaction,
    sebi,
    other=0
):

    return (
        brokerage
        +
        transaction
        +
        sebi
        +
        other
    ) * GST


# ============================================================
# MTF COST
# ============================================================

def calculate_mtf_cost(
    buy_value,
    sell_value,
    days,
    own_percent,
    daily_interest
):

    own_money = (
        buy_value *
        own_percent /
        100
    )

    funded = max(
        0,
        buy_value -
        own_money
    )

    interest = (
        funded *
        daily_interest /
        100 *
        max(
            0,
            days
        )
    )

    buy_brokerage = equity_delivery_brokerage(
        buy_value
    )

    sell_brokerage = equity_delivery_brokerage(
        sell_value
    )

    buy_txn = (
        buy_value *
        NSE_EQUITY_TXN
    )

    sell_txn = (
        sell_value *
        NSE_EQUITY_TXN
    )

    buy_stt = (
        buy_value *
        EQUITY_DELIVERY_STT
    )

    sell_stt = (
        sell_value *
        EQUITY_DELIVERY_STT
    )

    stamp = (
        buy_value *
        STAMP_EQUITY_BUY
    )

    buy_sebi = sebi_charge(
        buy_value
    )

    sell_sebi = sebi_charge(
        sell_value
    )

    gst = gst_on(
        buy_brokerage +
        sell_brokerage,
        buy_txn +
        sell_txn,
        buy_sebi +
        sell_sebi
    )

    total_charges = (
        interest
        +
        buy_brokerage
        +
        sell_brokerage
        +
        buy_txn
        +
        sell_txn
        +
        buy_stt
        +
        sell_stt
        +
        stamp
        +
        buy_sebi
        +
        sell_sebi
        +
        gst
    )

    return {

        "Own Capital":
            own_money,

        "Broker Funded":
            funded,

        "MTF Interest":
            interest,

        "Equity Brokerage":
            buy_brokerage +
            sell_brokerage,

        "Equity STT":
            buy_stt +
            sell_stt,

        "Transaction Charges":
            buy_txn +
            sell_txn,

        "Stamp Duty":
            stamp,

        "SEBI Charges":
            buy_sebi +
            sell_sebi,

        "GST":
            gst,

        "Total MTF + Charges":
            total_charges
    }


# ============================================================
# FUTURE MARGIN ESTIMATE
# ============================================================

def estimated_future_margin(
    future_price,
    lot_size
):

    if future_price is None:
        return None

    if lot_size is None:
        return None

    contract_value = (
        float(future_price)
        *
        int(lot_size)
    )

    # Conservative estimate.
    # Actual SPAN + exposure can differ.

    margin = (
        contract_value *
        0.15
    )

    return round(
        margin,
        2
    )


# ============================================================
# FUTURE SELL COST
# ============================================================

def calculate_future_sell_cost(
    future_sell_price,
    lot_size
):

    turnover = (
        future_sell_price *
        lot_size
    )

    brokerage = fno_brokerage()

    transaction = (
        turnover *
        NSE_FUTURE_TXN
    )

    stt = (
        turnover *
        FUTURE_SELL_STT
    )

    sebi = sebi_charge(
        turnover
    )

    gst = gst_on(
        brokerage,
        transaction,
        sebi
    )

    stamp = (
        turnover *
        STAMP_FUTURE_BUY
    )

    total = (
        brokerage
        +
        transaction
        +
        stt
        +
        sebi
        +
        gst
        +
        stamp
    )

    return {

        "Future Margin":
            estimated_future_margin(
                future_sell_price,
                lot_size
            ),

        "Future Brokerage":
            brokerage,

        "Future STT":
            stt,

        "Future Transaction":
            transaction,

        "Future SEBI":
            sebi,

        "Future Stamp":
            stamp,

        "Future GST":
            gst,

        "Future Total Charges":
            total
    }


# ============================================================
# FUTURE > SPOT WITH COMPLETE COST
# ============================================================

def scan_future_spot(
    jwt,
    master,
    own_percent,
    daily_interest
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
        s
        for s in fmap
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

    today = pd.Timestamp(
        now_ist().date()
    )

    days_to_expiry = max(
        1,
        (
            expiry -
            today
        ).days
    )

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

        spot = spot_q.get("ltp")
        future = future_q.get("ltp")

        if (
            spot is None
            or
            future is None
        ):
            continue

        difference = (
            future -
            spot
        )

        if difference <= 0:
            continue

        lot = int(
            fmap[stock]["lot_size"]
        )

        spot_buy_value = (
            spot *
            lot
        )

        future_sell_value = (
            future *
            lot
        )

        gross_profit = (
            difference *
            lot
        )

        mtf = calculate_mtf_cost(
            spot_buy_value,
            spot_buy_value,
            days_to_expiry,
            own_percent,
            daily_interest
        )

        future_cost = calculate_future_sell_cost(
            future,
            lot
        )

        total_cost = (
            mtf["Total MTF + Charges"]
            +
            future_cost[
                "Future Total Charges"
            ]
        )

        net_profit = (
            gross_profit -
            total_cost
        )

        own_capital = (
            mtf["Own Capital"]
            +
            future_cost[
                "Future Margin"
            ]
        )

        roi = (
            net_profit /
            own_capital *
            100
        ) if own_capital > 0 else 0

        rows.append({

            "Stock":
                stock,

            "Spot":
                round(
                    spot,
                    2
                ),

            "Future":
                round(
                    future,
                    2
                ),

            "Spread":
                round(
                    difference,
                    2
                ),

            "Lot Size":
                lot,

            "Spot Buy Value":
                round(
                    spot_buy_value,
                    2
                ),

            "MTF Own Money":
                round(
                    mtf["Own Capital"],
                    2
                ),

            "Broker Funding":
                round(
                    mtf["Broker Funded"],
                    2
                ),

            "Days To Expiry":
                days_to_expiry,

            "MTF Interest":
                round(
                    mtf["MTF Interest"],
                    2
                ),

            "Future Margin":
                round(
                    future_cost[
                        "Future Margin"
                    ],
                    2
                ),

            "Gross Profit":
                round(
                    gross_profit,
                    2
                ),

            "Total Charges":
                round(
                    total_cost,
                    2
                ),

            "Net Profit":
                round(
                    net_profit,
                    2
                ),

            "Own Capital Required":
                round(
                    own_capital,
                    2
                ),

            "ROI on Own Capital %":
                round(
                    roi,
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
            "Net Profit",
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
# PARITY COST
# ============================================================

def calculate_parity_cost(
    future_price,
    strike,
    ce_price,
    pe_price,
    lot_size,
    side,
    days_to_expiry
):

    # --------------------------------------------------------
    # Four legs:
    #
    # Positive:
    # Sell CE
    # Buy PE
    # Buy Future
    #
    # Negative:
    # Buy CE
    # Sell PE
    # Sell Future
    #
    # This is an ESTIMATE.
    # Exact exchange/broker charges depend on execution.
    # --------------------------------------------------------

    if side == "POSITIVE":

        ce_sell = ce_price
        pe_buy = pe_price
        future_buy = future_price

        gross = (
            ce_sell
            -
            pe_buy
            -
            (
                future_buy -
                strike
            )
        ) * lot_size

        ce_turnover = (
            ce_sell *
            lot_size
        )

        pe_turnover = (
            pe_buy *
            lot_size
        )

        future_turnover = (
            future_buy *
            lot_size
        )

    else:

        ce_buy = ce_price
        pe_sell = pe_price
        future_sell = future_price

        gross = (
            (
                future_sell -
                strike
            )
            -
            (
                ce_buy -
                pe_sell
            )
        ) * lot_size

        ce_turnover = (
            ce_buy *
            lot_size
        )

        pe_turnover = (
            pe_sell *
            lot_size
        )

        future_turnover = (
            future_sell *
            lot_size
        )

    # --------------------------------------------------------
    # F&O BROKERAGE
    # --------------------------------------------------------

    brokerage = (
        FNO_BROKERAGE_PER_ORDER
        *
        3
    )

    # --------------------------------------------------------
    # TRANSACTION CHARGES
    # --------------------------------------------------------

    txn = (
        ce_turnover
        +
        pe_turnover
        +
        future_turnover
    ) * NSE_FUTURE_TXN

    # --------------------------------------------------------
    # STT
    #
    # Option sale only
    # Future sale only
    # --------------------------------------------------------

    if side == "POSITIVE":

        option_stt = (
            ce_turnover *
            0.0015
        )

        future_stt = 0

    else:

        option_stt = (
            pe_turnover *
            0.0015
        )

        future_stt = (
            future_turnover *
            FUTURE_SELL_STT
        )

    sebi = sebi_charge(
        ce_turnover
        +
        pe_turnover
        +
        future_turnover
    )

    stamp = (
        (
            ce_turnover
            +
            pe_turnover
            +
            future_turnover
        )
        *
        0.00002
    )

    gst = gst_on(
        brokerage,
        txn,
        sebi
    )

    total_charges = (
        brokerage
        +
        txn
        +
        option_stt
        +
        future_stt
        +
        sebi
        +
        stamp
        +
        gst
    )

    future_margin = estimated_future_margin(
        future_price,
        lot_size
    )

    # Option margin approximation.
    # Since parity consists of option + future legs,
    # actual SPAN may offset significantly.
    option_margin_estimate = (
        (
            ce_price +
            pe_price
        )
        *
        lot_size
    )

    estimated_total_margin = (
        future_margin
        +
        option_margin_estimate
    )

    net = (
        gross -
        total_charges
    )

    return {

        "Gross Profit":
            gross,

        "Total Charges":
            total_charges,

        "Net Profit":
            net,

        "Future Margin":
            future_margin,

        "Option Premium Value":
            option_margin_estimate,

        "Estimated Total Margin":
            estimated_total_margin,

        "Brokerage":
            brokerage,

        "STT":
            option_stt +
            future_stt,

        "Transaction Charges":
            txn,

        "SEBI":
            sebi,

        "Stamp":
            stamp,

        "GST":
            gst
    }


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
# STOCK PARITY MASTER SCANNER
# ============================================================

def scan_stock_parity_part(
    jwt,
    master,
    strike_count,
    threshold,
    part
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

    stocks = [
        s
        for s in stocks
        if s in fmap
    ]

    # --------------------------------------------------------
    # SPLIT INTO 3 INDEPENDENT PARTS
    # --------------------------------------------------------

    chunks = np.array_split(
        stocks,
        3
    )

    stocks = list(
        chunks[
            part - 1
        ]
    )

    if not stocks:
        return pd.DataFrame()

    future_tokens = [
        str(
            fmap[s]["token"]
        )
        for s in stocks
    ]

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    today = pd.Timestamp(
        now_ist().date()
    )

    days_to_expiry = max(
        1,
        (
            expiry -
            today
        ).days
    )

    for stock in stocks:

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

        quotes = batch_full_quote(
            jwt,
            "NFO",
            tokens
        )

        lot_size = int(
            future_row[
                "lot_size"
            ]
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

            if (
                not ce_item
                or
                not pe_item
            ):
                continue

            ce_q = quotes.get(
                ce_item["token"],
                {}
            )

            pe_q = quotes.get(
                pe_item["token"],
                {}
            )

            ce_ltp = ce_q.get("ltp")
            pe_ltp = pe_q.get("ltp")

            ce_bid = ce_q.get("bid")
            ce_ask = ce_q.get("ask")

            pe_bid = pe_q.get("bid")
            pe_ask = pe_q.get("ask")

            if (
                ce_ltp is None
                or
                pe_ltp is None
            ):
                continue

            ltp_parity = (
                ce_ltp
                -
                pe_ltp
                -
                (
                    future_ltp -
                    strike
                )
            )

            positive = None
            negative = None

            # Positive:
            # Sell CE at bid
            # Buy PE at ask
            # Buy Future at ask

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
                        future_ask -
                        strike
                    )
                )

            # Negative:
            # Buy CE at ask
            # Sell PE at bid
            # Sell Future at bid

            if (
                ce_ask is not None
                and
                pe_bid is not None
                and
                future_bid is not None
            ):

                negative = (
                    (
                        future_bid -
                        strike
                    )
                    -
                    (
                        ce_ask -
                        pe_bid
                    )
                )

            candidates = []

            if positive is not None:
                candidates.append(
                    (
                        positive,
                        "POSITIVE"
                    )
                )

            if negative is not None:
                candidates.append(
                    (
                        negative,
                        "NEGATIVE"
                    )
                )

            if not candidates:
                continue

            best_value, best_side = max(
                candidates,
                key=lambda x:
                    abs(x[0])
            )

            if abs(best_value) <= threshold:
                continue

            if best_side == "POSITIVE":

                calc = calculate_parity_cost(
                    future_ask,
                    strike,
                    ce_bid,
                    pe_ask,
                    lot_size,
                    "POSITIVE",
                    days_to_expiry
                )

            else:

                calc = calculate_parity_cost(
                    future_bid,
                    strike,
                    ce_ask,
                    pe_bid,
                    lot_size,
                    "NEGATIVE",
                    days_to_expiry
                )

            rows.append({

                "Stock":
                    stock,

                "Part":
                    f"Part {part}",

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
                    strike,

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
                        ltp_parity,
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

                "Gross Profit":
                    round(
                        calc[
                            "Gross Profit"
                        ],
                        2
                    ),

                "Total Charges":
                    round(
                        calc[
                            "Total Charges"
                        ],
                        2
                    ),

                "Net Profit":
                    round(
                        calc[
                            "Net Profit"
                        ],
                        2
                    ),

                "Future Margin":
                    round(
                        calc[
                            "Future Margin"
                        ],
                        2
                    ),

                "Option Value":
                    round(
                        calc[
                            "Option Premium Value"
                        ],
                        2
                    ),

                "Estimated Margin":
                    round(
                        calc[
                            "Estimated Total Margin"
                        ],
                        2
                    ),

                "Brokerage":
                    round(
                        calc[
                            "Brokerage"
                        ],
                        2
                    ),

                "STT":
                    round(
                        calc[
                            "STT"
                        ],
                        2
                    ),

                "Transaction":
                    round(
                        calc[
                            "Transaction Charges"
                        ],
                        2
                    ),

                "GST":
                    round(
                        calc["GST"],
                        2
                    )
            })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            "Net Profit",
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
# INDEX PARITY
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


def scan_index_parity(
    jwt,
    master,
    index_label,
    strike_count,
    threshold
):

    possible_names = {

        "NIFTY":
            ["NIFTY"],

        "BANKNIFTY":
            ["BANKNIFTY"],

        "SENSEX":
            ["SENSEX"]
    }

    name = find_index_name(
        master,
        possible_names.get(
            index_label,
            []
        )
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
    ]

    futures = x[
        x["instrument"]
        == "FUTIDX"
    ]

    options = x[
        x["instrument"]
        == "OPTIDX"
    ]

    if futures.empty or options.empty:
        return pd.DataFrame()

    future_row = futures.iloc[0]

    future_token = str(
        future_row["token"]
    )

    fq = batch_full_quote(
        jwt,
        "NFO",
        [future_token]
    ).get(
        future_token,
        {}
    )

    future = fq.get("ltp")
    future_bid = fq.get("bid")
    future_ask = fq.get("ask")

    if future is None:
        return pd.DataFrame()

    strikes = sorted(
        set(
            options["strike_num"]
            .dropna()
            .astype(float)
        )
    )

    strikes = sorted(
        strikes,
        key=lambda x:
            abs(
                x -
                future
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

    lot_size = int(
        future_row["lot_size"]
    )

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

        ce = ce_q.get("ltp")
        pe = pe_q.get("ltp")

        ce_bid = ce_q.get("bid")
        ce_ask = ce_q.get("ask")

        pe_bid = pe_q.get("bid")
        pe_ask = pe_q.get("ask")

        if ce is None or pe is None:
            continue

        ltp_parity = (
            ce -
            pe -
            (
                future -
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
                    future_ask -
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
                (
                    future_bid -
                    strike
                )
                -
                (
                    ce_ask -
                    pe_bid
                )
            )

        candidates = []

        if positive is not None:
            candidates.append(
                (
                    positive,
                    "POSITIVE"
                )
            )

        if negative is not None:
            candidates.append(
                (
                    negative,
                    "NEGATIVE"
                )
            )

        if not candidates:
            continue

        best, side = max(
            candidates,
            key=lambda x:
                abs(x[0])
        )

        if abs(best) <= threshold:
            continue

        if side == "POSITIVE":

            calc = calculate_parity_cost(
                future_ask,
                strike,
                ce_bid,
                pe_ask,
                lot_size,
                "POSITIVE",
                1
            )

        else:

            calc = calculate_parity_cost(
                future_bid,
                strike,
                ce_ask,
                pe_bid,
                lot_size,
                "NEGATIVE",
                1
            )

        rows.append({

            "Index":
                index_label,

            "Direction":
                parity_direction(
                    best
                ),

            "Side":
                side,

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Future":
                round(
                    future,
                    2
                ),

            "Future Bid":
                future_bid,

            "Future Ask":
                future_ask,

            "Strike":
                strike,

            "CE":
                ce,

            "CE Bid":
                ce_bid,

            "CE Ask":
                ce_ask,

            "PE":
                pe,

            "PE Bid":
                pe_bid,

            "PE Ask":
                pe_ask,

            "LTP Parity":
                round(
                    ltp_parity,
                    2
                ),

            "Executable Edge":
                round(
                    best,
                    2
                ),

            "Gross Profit":
                round(
                    calc[
                        "Gross Profit"
                    ],
                    2
                ),

            "Total Charges":
                round(
                    calc[
                        "Total Charges"
                    ],
                    2
                ),

            "Net Profit":
                round(
                    calc[
                        "Net Profit"
                    ],
                    2
                ),

            "Estimated Margin":
                round(
                    calc[
                        "Estimated Total Margin"
                    ],
                    2
                ),

            "Lot Size":
                lot_size
        })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            "Net Profit",
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
# NSE FREE SOURCE
# ============================================================

@st.cache_data(
    ttl=300,
    show_spinner=False
)
def nse_session():

    s = requests.Session()

    headers = {
        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36",

        "Accept":
            "application/json,text/plain,*/*",

        "Accept-Language":
            "en-US,en;q=0.9",

        "Referer":
            "https://www.nseindia.com/"
    }

    try:

        s.get(
            NSE_BASE,
            headers=headers,
            timeout=20
        )

        return s, headers

    except Exception:

        return None, headers


def nse_json(
    path,
    params=None
):

    s, headers = nse_session()

    if s is None:
        return None

    try:

        r = s.get(
            NSE_BASE + path,
            params=params,
            headers=headers,
            timeout=20
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:

        return None


# ============================================================
# NSE CURRENT DERIVATIVE DATA
# ============================================================

@st.cache_data(
    ttl=120,
    show_spinner=False
)
def nse_derivative_quote(
    symbol
):

    data = nse_json(
        "/api/quote-derivative",
        {
            "symbol": symbol
        }
    )

    if not data:
        return {}

    return data


# ============================================================
# ROLLOVER EXTRACTION
# ============================================================

def parse_rollover_from_nse(
    data,
    symbol
):

    if not data:
        return None

    rows = []

    # NSE responses can change structure.
    # Search recursively for contract records.

    def walk(obj):

        if isinstance(obj, dict):

            keys = {
                str(k).lower()
                for k in obj.keys()
            }

            if (
                "openinterest" in keys
                or
                "oi" in keys
            ):

                rows.append(obj)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    try:
        walk(data)
    except Exception:
        pass

    if not rows:
        return None

    parsed = []

    for row in rows:

        expiry = (
            row.get("expiryDate")
            or
            row.get("expiry")
            or
            row.get("expirydate")
        )

        oi = (
            row.get("openInterest")
            or
            row.get("openinterest")
            or
            row.get("oi")
        )

        ltp = (
            row.get("lastPrice")
            or
            row.get("ltp")
            or
            row.get("closePrice")
        )

        try:

            oi = float(
                str(oi)
                .replace(",", "")
            )

        except Exception:

            oi = None

        try:

            ltp = float(
                str(ltp)
                .replace(",", "")
            )

        except Exception:

            ltp = None

        if expiry:

            parsed.append({

                "Expiry":
                    str(expiry),

                "OI":
                    oi,

                "Price":
                    ltp
            })

    if not parsed:
        return None

    return pd.DataFrame(
        parsed
    )


# ============================================================
# ROLLOVER SCORE
# ============================================================

def rollover_signal(
    last_week_close,
    last_week_open,
    current_future,
    next_future,
    current_oi,
    next_oi
):

    bullish = False

    if (
        last_week_close is not None
        and
        last_week_open is not None
    ):

        bullish = (
            last_week_close >
            last_week_open
        )

    rollover = None

    if (
        current_oi
        and
        next_oi
        and
        (
            current_oi +
            next_oi
        ) > 0
    ):

        rollover = (
            next_oi /
            (
                current_oi +
                next_oi
            )
        ) * 100

    rollover_cost = None

    if (
        current_future is not None
        and
        next_future is not None
        and
        current_future > 0
    ):

        rollover_cost = (
            (
                next_future -
                current_future
            )
            /
            current_future
        ) * 100

    score = 0

    if bullish:
        score += 1

    if (
        rollover is not None
        and
        rollover >= rollover_high_percent
    ):
        score += 1

    if (
        rollover_cost is not None
        and
        rollover_cost >=
        rollover_cost_high_percent
    ):
        score += 1

    if score >= 3:
        signal = "🔥 STRONG BULLISH ROLLOVER"

    elif score == 2:
        signal = "🟢 BULLISH ROLLOVER"

    elif score == 1:
        signal = "🟡 WATCH"

    else:
        signal = "⚪ NO SIGNAL"

    return (
        bullish,
        rollover,
        rollover_cost,
        signal
    )


# ============================================================
# SIMPLE 1-YEAR BACKTEST
#
# Spot-history based:
# Bullish weekly close + breakout filter
#
# This is deliberately conservative.
# It does NOT pretend historical option bid/ask
# was available if free source doesn't provide it.
# ============================================================

def backtest_stock(
    df,
    holding_days=20
):

    if df.empty or len(df) < 100:
        return None

    x = df.copy()

    x["SMA20"] = (
        x["close"]
        .rolling(20)
        .mean()
    )

    x["SMA50"] = (
        x["close"]
        .rolling(50)
        .mean()
    )

    x["ROC20"] = (
        x["close"]
        .pct_change(20)
        *
        100
    )

    trades = []

    i = 60

    while i < len(x) - holding_days:

        price = x["close"].iloc[i]

        previous_high = (
            x["high"]
            .iloc[i-20:i]
            .max()
        )

        bullish = (
            price >
            x["SMA20"].iloc[i]
            and
            x["SMA20"].iloc[i] >
            x["SMA50"].iloc[i]
            and
            price >
            previous_high * 0.98
        )

        if not bullish:

            i += 1
            continue

        entry = price

        exit_price = (
            x["close"]
            .iloc[
                i +
                holding_days
            ]
        )

        ret = (
            (
                exit_price -
                entry
            )
            /
            entry
        ) * 100

        trades.append(ret)

        i += holding_days

    if not trades:
        return {

            "Trades":
                0,

            "Win Rate %":
                0,

            "Average Return %":
                0,

            "Total Return %":
                0,

            "Max Drawdown %":
                0
        }

    wins = [
        x for x in trades
        if x > 0
    ]

    equity = [100.0]

    for r in trades:

        equity.append(
            equity[-1] *
            (
                1 +
                r / 100
            )
        )

    eq = np.array(
        equity
    )

    peak = np.maximum.accumulate(
        eq
    )

    drawdown = (
        (
            eq -
            peak
        )
        /
        peak
    ) * 100

    return {

        "Trades":
            len(trades),

        "Win Rate %":
            round(
                len(wins) /
                len(trades) *
                100,
                2
            ),

        "Average Return %":
            round(
                np.mean(trades),
                2
            ),

        "Total Return %":
            round(
                (
                    equity[-1] /
                    equity[0] -
                    1
                )
                *
                100,
                2
            ),

        "Max Drawdown %":
            round(
                drawdown.min(),
                2
            )
    }


# ============================================================
# ROLLOVER SCANNER
# ============================================================

def scan_rollover(
    jwt,
    master,
    days=365
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

    spot_map = cash_token_map(
        master
    )

    rows = []

    stocks = sorted(
        [
            s
            for s in fmap
            if s in spot_map
        ]
    )

    def worker(stock):

        try:

            future_row = fmap[
                stock
            ]

            spot_token = (
                spot_map[stock]["token"]
            )

            df = historical(
                jwt,
                spot_token,
                "ONE_DAY",
                days
            )

            if df.empty:
                return None

            df["datetime"] = pd.to_datetime(
                df["datetime"],
                errors="coerce"
            )

            df = df.dropna(
                subset=["datetime"]
            )

            if len(df) < 100:
                return None

            last_week = df.iloc[
                -5:
            ]

            last_week_open = float(
                last_week["open"].iloc[0]
            )

            last_week_close = float(
                last_week["close"].iloc[-1]
            )

            # Current future quote
            token = str(
                future_row["token"]
            )

            fq = batch_full_quote(
                jwt,
                "NFO",
                [token]
            ).get(
                token,
                {}
            )

            current_future = fq.get(
                "ltp"
            )

            # Next expiry from master
            next_rows = master[
                (master["exchange"] == "NFO")
                &
                (master["instrument"] == "FUTSTK")
                &
                (master["name"] == stock)
                &
                (
                    master["expiry_date"]
                    > expiry
                )
            ]

            next_rows = next_rows.sort_values(
                "expiry_date"
            )

            next_future = None

            next_expiry = None

            if not next_rows.empty:

                next_row = next_rows.iloc[0]

                next_expiry = (
                    next_row[
                        "expiry_date"
                    ]
                )

                next_token = str(
                    next_row["token"]
                )

                nq = batch_full_quote(
                    jwt,
                    "NFO",
                    [next_token]
                ).get(
                    next_token,
                    {}
                )

                next_future = nq.get(
                    "ltp"
                )

            # ------------------------------------------------
            # OI from NSE where possible
            # ------------------------------------------------

            nse_data = nse_derivative_quote(
                stock
            )

            parsed = parse_rollover_from_nse(
                nse_data,
                stock
            )

            current_oi = None
            next_oi = None

            if (
                parsed is not None
                and
                not parsed.empty
            ):

                # Best effort:
                # first two contracts
                parsed = parsed.sort_values(
                    "Expiry"
                )

                if len(parsed) >= 1:
                    current_oi = parsed[
                        "OI"
                    ].iloc[0]

                if len(parsed) >= 2:
                    next_oi = parsed[
                        "OI"
                    ].iloc[1]

            (
                bullish,
                rollover,
                rollover_cost,
                signal
            ) = rollover_signal(

                last_week_close,

                last_week_open,

                current_future,

                next_future,

                current_oi,

                next_oi
            )

            bt = backtest_stock(
                df,
                20
            )

            if bt is None:
                return None

            return {

                "Stock":
                    stock,

                "Last Week Open":
                    round(
                        last_week_open,
                        2
                    ),

                "Last Week Close":
                    round(
                        last_week_close,
                        2
                    ),

                "Last Week Bullish":
                    "YES"
                    if bullish
                    else "NO",

                "Current Future":
                    current_future,

                "Next Future":
                    next_future,

                "Rollover %":
                    round(
                        rollover,
                        2
                    )
                    if rollover is not None
                    else None,

                "Rollover Cost %":
                    round(
                        rollover_cost,
                        2
                    )
                    if rollover_cost is not None
                    else None,

                "High Rollover":
                    "YES"
                    if (
                        rollover is not None
                        and
                        rollover >=
                        rollover_high_percent
                    )
                    else "NO",

                "High Rollover Cost":
                    "YES"
                    if (
                        rollover_cost is not None
                        and
                        rollover_cost >=
                        rollover_cost_high_percent
                    )
                    else "NO",

                "Backtest Trades":
                    bt["Trades"],

                "Backtest Win Rate %":
                    bt["Win Rate %"],

                "Backtest Avg Return %":
                    bt["Average Return %"],

                "Backtest Total Return %":
                    bt["Total Return %"],

                "Backtest Max DD %":
                    bt["Max Drawdown %"],

                "Signal":
                    signal
            }

        except Exception:

            return None

    with ThreadPoolExecutor(
        max_workers=5
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

                r = f.result()

                if r:
                    rows.append(r)

            except Exception:
                pass

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    signal_order = {

        "🔥 STRONG BULLISH ROLLOVER": 4,

        "🟢 BULLISH ROLLOVER": 3,

        "🟡 WATCH": 2,

        "⚪ NO SIGNAL": 1
    }

    result["_score"] = (
        result["Signal"]
        .map(
            signal_order
        )
        .fillna(0)
    )

    result = result.sort_values(
        [
            "_score",
            "Backtest Win Rate %",
            "Rollover %"
        ],
        ascending=[
            False,
            False,
            False
        ]
    ).drop(
        columns="_score"
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
# LOAD MASTER
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
# JWT
# ============================================================

if "jwt" not in st.session_state:

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
        "पहले Connect Angel One दबाएँ।"
    )

    st.stop()


# ============================================================
# 1 RSI
# ============================================================

st.divider()

st.header(
    "1️⃣ 📈 Nifty 50 RSI + OBV"
)

if st.button(
    "🔄 Scan RSI + OBV",
    key="rsi_button",
    type="primary",
    use_container_width=True
):

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

show_result(
    st.session_state.get(
        "rsi_result",
        pd.DataFrame()
    ),
    "rsi_obv_scanner.csv"
)


# ============================================================
# 2 FUTURE > SPOT
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚡ Future > Spot + MTF Cost + Net Profit"
)

st.caption(
    "Spot खरीदना + MTF funding + Future sell "
    "→ expiry तक interest + brokerage + statutory charges"
)

if st.button(
    "🚀 Scan Future > Spot + COMPLETE COST",
    key="future_button",
    type="primary",
    use_container_width=True
):

    start = time.time()

    with st.spinner(
        "Future > Spot cost calculation..."
    ):

        result = scan_future_spot(
            jwt,
            master,
            mtf_own_percent,
            mtf_interest_daily
        )

    elapsed = (
        time.time() -
        start
    )

    st.session_state[
        "future_result"
    ] = result

    st.success(
        f"Complete — "
        f"{len(result)} setups | "
        f"{elapsed:.1f} sec"
    )

show_result(
    st.session_state.get(
        "future_result",
        pd.DataFrame()
    ),
    "future_spot_complete_cost.csv"
)


# ============================================================
# 3 STOCK PARITY PART 1
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ Stock Put-Call Parity — PART 1"
)

if st.button(
    "🚀 Run Stock Parity PART 1",
    key="parity_part1",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Stock parity Part 1..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            parity_strikes,
            parity_threshold,
            1
        )

    st.session_state[
        "parity_part1_result"
    ] = result

show_result(
    st.session_state.get(
        "parity_part1_result",
        pd.DataFrame()
    ),
    "stock_parity_part1.csv"
)


# ============================================================
# 4 STOCK PARITY PART 2
# ============================================================

st.divider()

st.header(
    "4️⃣ ⚖️ Stock Put-Call Parity — PART 2"
)

if st.button(
    "🚀 Run Stock Parity PART 2",
    key="parity_part2",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Stock parity Part 2..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            parity_strikes,
            parity_threshold,
            2
        )

    st.session_state[
        "parity_part2_result"
    ] = result

show_result(
    st.session_state.get(
        "parity_part2_result",
        pd.DataFrame()
    ),
    "stock_parity_part2.csv"
)


# ============================================================
# 5 STOCK PARITY PART 3
# ============================================================

st.divider()

st.header(
    "5️⃣ ⚖️ Stock Put-Call Parity — PART 3"
)

if st.button(
    "🚀 Run Stock Parity PART 3",
    key="parity_part3",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Stock parity Part 3..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            parity_strikes,
            parity_threshold,
            3
        )

    st.session_state[
        "parity_part3_result"
    ] = result

show_result(
    st.session_state.get(
        "parity_part3_result",
        pd.DataFrame()
    ),
    "stock_parity_part3.csv"
)


# ============================================================
# 6 NIFTY
# ============================================================

st.divider()

st.header(
    "6️⃣ 📊 NIFTY Put-Call Parity"
)

if st.button(
    "🚀 Scan NIFTY",
    key="nifty_button",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NIFTY parity..."
    ):

        result = scan_index_parity(
            jwt,
            master,
            "NIFTY",
            parity_strikes,
            parity_threshold
        )

    st.session_state[
        "nifty_result"
    ] = result

show_result(
    st.session_state.get(
        "nifty_result",
        pd.DataFrame()
    ),
    "nifty_parity.csv"
)


# ============================================================
# 7 BANKNIFTY
# ============================================================

st.divider()

st.header(
    "7️⃣ 🏦 BANKNIFTY Put-Call Parity"
)

if st.button(
    "🚀 Scan BANKNIFTY",
    key="bank_button",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "BANKNIFTY parity..."
    ):

        result = scan_index_parity(
            jwt,
            master,
            "BANKNIFTY",
            parity_strikes,
            parity_threshold
        )

    st.session_state[
        "bank_result"
    ] = result

show_result(
    st.session_state.get(
        "bank_result",
        pd.DataFrame()
    ),
    "banknifty_parity.csv"
)


# ============================================================
# 8 SENSEX
# ============================================================

st.divider()

st.header(
    "8️⃣ 📊 SENSEX Put-Call Parity"
)

if st.button(
    "🚀 Scan SENSEX",
    key="sensex_button",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "SENSEX parity..."
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

show_result(
    st.session_state.get(
        "sensex_result",
        pd.DataFrame()
    ),
    "sensex_parity.csv"
)


# ============================================================
# 9 ROLLOVER
# ============================================================

st.divider()

st.header(
    "9️⃣ 🔁 Bullish + High Rollover + High Rollover Cost"
)

st.caption(
    "Free NSE data + Angel historical spot data | "
    "लगभग 1-year backtest"
)

if st.button(
    "🚀 Scan Rollover + 1Y Backtest",
    key="rollover_button",
    type="primary",
    use_container_width=True
):

    start = time.time()

    with st.spinner(
        "Rollover + backtest scan..."
    ):

        result = scan_rollover(
            jwt,
            master,
            int(backtest_days)
        )

    elapsed = (
        time.time() -
        start
    )

    st.session_state[
        "rollover_result"
    ] = result

    st.success(
        f"Rollover scan complete — "
        f"{len(result)} stocks | "
        f"{elapsed:.1f} sec"
    )

show_result(
    st.session_state.get(
        "rollover_result",
        pd.DataFrame()
    ),
    "rollover_1year_backtest.csv"
)


# ============================================================
# SUMMARY
# ============================================================

st.divider()

st.header(
    "📌 Calculation Notes"
)

st.info(
    """
    • Future > Spot में Spot stock को MTF से खरीदने की अनुमानित
      funding calculation की गई है।

    • Default MTF: 25% आपका पैसा + 75% broker funding.

    • MTF interest default 0.049%/day है; sidebar में बदल सकते हैं।

    • Interest expiry तक remaining days पर calculate किया जाता है।

    • Future sell में brokerage + STT + transaction + SEBI +
      stamp + GST estimate शामिल है।

    • Put-Call Parity में Bid/Ask executable price को LTP से
      प्राथमिकता दी गई है।

    • Stock parity को तीन independent parts में बाँटा गया है,
      इसलिए Part 1/2/3 अलग-अलग run किए जा सकते हैं।

    • NIFTY और BANKNIFTY अलग independent scanners हैं।

    • Rollover scanner के लिए NSE free/public derivative data
      जहाँ उपलब्ध है वहाँ इस्तेमाल किया जाता है।

    • 1-year backtest spot-price based confirmation है।
      Historical option bid/ask उपलब्ध न होने पर backtest को
      actual historical executable parity backtest नहीं माना जाए।

    • Future/Parity margin केवल estimated margin है।
      Actual Angel RMS/SPAN margin market conditions के अनुसार
      बदल सकता है।
    """
)

st.caption(
    "📡 Live quotes: Angel One SmartAPI | "
    "Historical/Rollover supplement: NSE public data"
)

st.caption(
    "⚠️ Final execution से पहले Angel One के actual "
    "Trades & Charges / RMS margin को verify करें।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st.info(
        f"🔄 Auto Refresh ON — "
        f"हर {refresh_seconds} सेकंड में refresh होगा।"
    )

    time.sleep(
        int(refresh_seconds)
    )

    st.rerun()
