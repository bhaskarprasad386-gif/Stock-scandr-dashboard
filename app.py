import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
import io
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Fast Market Scanner PRO",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Fast & Furious Market Scanner PRO")

IST = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://apiconnect.angelone.in"

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/"
}


# ============================================================
# SIDEBAR
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

    st.subheader("Liquidity")

    min_option_volume = st.number_input(
        "Minimum Option Volume",
        min_value=0,
        value=1000,
        step=100
    )

    min_option_oi = st.number_input(
        "Minimum Option OI",
        min_value=0,
        value=10000,
        step=1000
    )

    max_spread_percent = st.number_input(
        "Maximum Bid/Ask Spread %",
        min_value=0.1,
        max_value=20.0,
        value=3.0,
        step=0.5
    )

    st.subheader("MTF")

    mtf_funding_percent = st.number_input(
        "Broker Funding %",
        min_value=1.0,
        max_value=90.0,
        value=75.0,
        step=1.0
    )

    mtf_interest_daily = st.number_input(
        "MTF Interest % / Day",
        min_value=0.0,
        max_value=1.0,
        value=0.041,
        step=0.001,
        format="%.3f"
    )

    st.subheader("Rollover")

    rollover_min_oi = st.number_input(
        "Minimum Rollover OI",
        min_value=0,
        value=10000,
        step=1000
    )

    rollover_min_volume = st.number_input(
        "Minimum Rollover Volume",
        min_value=0,
        value=1000,
        step=100
    )

    backtest_days = st.number_input(
        "Backtest Days",
        min_value=30,
        max_value=365,
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


def auth_headers(jwt):

    h = BASE_HEADERS.copy()

    h["Authorization"] = (
        "Bearer " + jwt
    )

    return h


def now_ist():

    return datetime.now(IST)


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
# LOGIN
# ============================================================

@st.cache_resource(ttl=120)
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

                volume = item.get(
                    "tradeVolume"
                )

                if volume is None:
                    volume = item.get(
                        "volume"
                    )

                oi = item.get(
                    "opnInterest"
                )

                if oi is None:
                    oi = item.get(
                        "openInterest"
                    )

                result[token] = {

                    "ltp":
                        safe_float(ltp),

                    "bid":
                        safe_float(bid),

                    "ask":
                        safe_float(ask),

                    "volume":
                        safe_float(volume),

                    "oi":
                        safe_float(oi)
                }

        except Exception:
            continue

    return result


def safe_float(x):

    try:

        if x is None:
            return None

        return float(x)

    except Exception:

        return None


# ============================================================
# HISTORICAL ANGEL
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

        return (
            df.dropna()
            .sort_values("datetime")
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

    return (
        x.iloc[-1] >
        x.iloc[0]
        and
        (
            x.diff()
            .dropna()
            .gt(0)
            .sum()
            >= 3
        )
    )


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
            .replace("-EQ", "")
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
    ]

    if x.empty:
        return None

    same = x[
        (x["expiry_date"].dt.month == today.month)
        &
        (x["expiry_date"].dt.year == today.year)
    ]

    if not same.empty:

        return same[
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
        (master["expiry_date"] == expiry)
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
# LIQUIDITY
# ============================================================

def quote_is_liquid(
    q,
    min_volume,
    min_oi,
    max_spread
):

    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")
    volume = q.get("volume")
    oi = q.get("oi")

    if (
        bid is None
        or ask is None
        or ltp is None
    ):
        return False

    if bid <= 0 or ask <= 0:
        return False

    if ask < bid:
        return False

    if ltp <= 0:
        return False

    if (
        volume is not None
        and volume < min_volume
    ):
        return False

    if (
        oi is not None
        and oi < min_oi
    ):
        return False

    spread_pct = (
        (ask - bid)
        / ltp
    ) * 100

    if spread_pct > max_spread:
        return False

    return True


def spread_percent(q):

    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")

    if not bid or not ask or not ltp:
        return None

    return (
        (ask - bid)
        / ltp
    ) * 100


# ============================================================
# MTF + CHARGES
# ============================================================

def equity_delivery_brokerage(turnover):

    return max(
        5,
        min(
            20,
            turnover * 0.001
        )
    )


def future_brokerage():

    return 20.0


def calculate_equity_charges(
    buy_value,
    sell_value
):

    turnover = (
        buy_value +
        sell_value
    )

    brokerage = (
        equity_delivery_brokerage(
            buy_value
        )
        +
        equity_delivery_brokerage(
            sell_value
        )
    )

    stt = (
        turnover *
        0.001
    )

    exchange = (
        turnover *
        0.0000307
    )

    sebi = (
        turnover *
        0.000001
    )

    stamp = (
        buy_value *
        0.00015
    )

    gst = (
        brokerage +
        exchange +
        sebi
    ) * 0.18

    total = (
        brokerage +
        stt +
        exchange +
        sebi +
        stamp +
        gst
    )

    return {
        "brokerage": brokerage,
        "STT": stt,
        "Exchange": exchange,
        "SEBI": sebi,
        "Stamp": stamp,
        "GST": gst,
        "Total": total
    }


def calculate_future_charges(
    buy_value,
    sell_value
):

    turnover = (
        buy_value +
        sell_value
    )

    brokerage = (
        future_brokerage() * 2
    )

    stt = (
        sell_value *
        0.0002
    )

    exchange = (
        turnover *
        0.0000183
    )

    sebi = (
        turnover *
        0.000001
    )

    stamp = (
        buy_value *
        0.00002
    )

    gst = (
        brokerage +
        exchange +
        sebi
    ) * 0.18

    total = (
        brokerage +
        stt +
        exchange +
        sebi +
        stamp +
        gst
    )

    return {
        "brokerage": brokerage,
        "STT": stt,
        "Exchange": exchange,
        "SEBI": sebi,
        "Stamp": stamp,
        "GST": gst,
        "Total": total
    }


def mtf_trade_calculation(
    spot,
    future,
    lot,
    expiry
):

    stock_value = (
        spot * lot
    )

    broker_funding = (
        stock_value *
        mtf_funding_percent /
        100
    )

    own_money = (
        stock_value -
        broker_funding
    )

    today = now_ist().date()

    expiry_date = expiry.date()

    days = max(
        1,
        (
            expiry_date -
            today
        ).days
    )

    interest = (
        broker_funding
        *
        mtf_interest_daily
        / 100
        *
        days
    )

    future_value = (
        future * lot
    )

    gross = (
        future_value -
        stock_value
    )

    eq_charges = calculate_equity_charges(
        stock_value,
        stock_value
    )

    f_charges = calculate_future_charges(
        future_value,
        future_value
    )

    total_charges = (
        eq_charges["Total"]
        +
        f_charges["Total"]
        +
        interest
    )

    net = (
        gross -
        total_charges
    )

    roi = (
        net /
        own_money *
        100
        if own_money > 0
        else 0
    )

    return {

        "Spot Value":
            stock_value,

        "Broker Funding":
            broker_funding,

        "Your Capital":
            own_money,

        "MTF Days":
            days,

        "MTF Interest":
            interest,

        "Future Value":
            future_value,

        "Gross Spread Profit":
            gross,

        "Equity Charges":
            eq_charges["Total"],

        "Future Charges":
            f_charges["Total"],

        "Total Charges + Interest":
            total_charges,

        "NET PROFIT":
            net,

        "ROI %":
            roi
    }


# ============================================================
# ANGEL MARGIN CALCULATOR
# ============================================================

def angel_margin(
    jwt,
    positions
):

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "margin/v1/batch"
    )

    payload = {
        "positions": positions
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
            return None

        return data.get(
            "data"
        )

    except Exception:

        return None


# ============================================================
# FUTURE > SPOT
# ============================================================

def scan_future_spot(
    jwt,
    master
):

    expiry = current_month_expiry(
        master
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

    for stock in stocks:

        sq = spot_data.get(
            spot_map[stock]["token"],
            {}
        )

        fq = future_data.get(
            str(fmap[stock]["token"]),
            {}
        )

        spot = sq.get("ltp")
        future = fq.get("ltp")

        if spot is None or future is None:
            continue

        if future <= spot:
            continue

        lot = int(
            fmap[stock]["lot_size"]
        )

        calc = mtf_trade_calculation(
            spot,
            future,
            lot,
            expiry
        )

        rows.append({

            "Stock":
                stock,

            "Spot":
                round(spot, 2),

            "Future":
                round(future, 2),

            "Future - Spot":
                round(
                    future - spot,
                    2
                ),

            "Lot Size":
                lot,

            "Spot Purchase Value":
                round(
                    calc["Spot Value"],
                    2
                ),

            "Broker Funds 75%":
                round(
                    calc["Broker Funding"],
                    2
                ),

            "Your 25% Capital":
                round(
                    calc["Your Capital"],
                    2
                ),

            "MTF Days":
                calc["MTF Days"],

            "MTF Interest":
                round(
                    calc["MTF Interest"],
                    2
                ),

            "Gross Profit":
                round(
                    calc["Gross Spread Profit"],
                    2
                ),

            "Equity Charges":
                round(
                    calc["Equity Charges"],
                    2
                ),

            "Future Charges":
                round(
                    calc["Future Charges"],
                    2
                ),

            "Total Cost":
                round(
                    calc["Total Charges + Interest"],
                    2
                ),

            "NET PROFIT":
                round(
                    calc["NET PROFIT"],
                    2
                ),

            "ROI %":
                round(
                    calc["ROI %"],
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
            "NET PROFIT",
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
            "token":
                str(row["token"]),

            "symbol":
                symbol,

            "lot":
                int(row["lot_size"])
        }

    return result


# ============================================================
# STOCK PARITY
# ============================================================

def scan_stock_parity_part(
    jwt,
    master,
    stocks,
    strike_count,
    threshold
):

    expiry = current_month_expiry(
        master
    )

    if expiry is None:
        return pd.DataFrame()

    fmap = stock_future_map(
        master,
        expiry
    )

    stocks = [
        s
        for s in stocks
        if s in fmap
    ]

    future_tokens = [
        str(fmap[s]["token"])
        for s in stocks
    ]

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        future_row = fmap[stock]

        future_token = str(
            future_row["token"]
        )

        fq = future_quotes.get(
            future_token,
            {}
        )

        future = fq.get(
            "ltp"
        )

        future_bid = fq.get(
            "bid"
        )

        future_ask = fq.get(
            "ask"
        )

        if (
            future is None
            or
            future_bid is None
            or
            future_ask is None
        ):
            continue

        if (
            future_ask <=
            future_bid
        ):
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
                k[0]
                for k in contracts
            ),
            key=lambda x:
                abs(
                    x - future
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

        for strike in strikes:

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

            if not ce or not pe:
                continue

            ceq = quotes.get(
                ce["token"],
                {}
            )

            peq = quotes.get(
                pe["token"],
                {}
            )

            # IMPORTANT:
            # BOTH CE AND PE MUST BE LIQUID
            if not quote_is_liquid(
                ceq,
                min_option_volume,
                min_option_oi,
                max_spread_percent
            ):
                continue

            if not quote_is_liquid(
                peq,
                min_option_volume,
                min_option_oi,
                max_spread_percent
            ):
                continue

            # FUTURE MUST ALSO HAVE TWO SIDES
            if (
                future_bid <= 0
                or future_ask <= 0
            ):
                continue

            ce_bid = ceq["bid"]
            ce_ask = ceq["ask"]

            pe_bid = peq["bid"]
            pe_ask = peq["ask"]

            # ------------------------------------------------
            # POSITIVE EXECUTABLE EDGE
            #
            # SELL CE
            # BUY PE
            # BUY FUTURE
            # ------------------------------------------------

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

            # ------------------------------------------------
            # NEGATIVE EXECUTABLE EDGE
            #
            # BUY CE
            # SELL PE
            # SELL FUTURE
            # ------------------------------------------------

            negative = (
                ce_ask
                -
                pe_bid
                -
                (
                    future_bid -
                    strike
                )
            )

            candidates = [
                (
                    positive,
                    "CE SELL / PE BUY / FUTURE BUY"
                ),
                (
                    negative,
                    "CE BUY / PE SELL / FUTURE SELL"
                )
            ]

            best_value, side = max(
                candidates,
                key=lambda x:
                    abs(x[0])
            )

            if abs(
                best_value
            ) <= threshold:
                continue

            lot = int(
                future_row["lot_size"]
            )

            gross_profit = (
                abs(best_value)
                * lot
            )

            # conservative estimated capital
            future_margin_est = (
                future
                * lot
                * 0.15
            )

            option_premium = (
                pe_ask * lot
                +
                ce_ask * lot
            )

            estimated_capital = (
                future_margin_est
                +
                option_premium
            )

            # rough F&O round-trip charges
            fno_charges = (
                calculate_future_charges(
                    future * lot,
                    future * lot
                )["Total"]
                +
                40
            )

            net_profit = (
                gross_profit -
                fno_charges
            )

            rows.append({

                "Stock":
                    stock,

                "Direction":
                    (
                        "CE−PE Rich"
                        if best_value > 0
                        else
                        "CE−PE Cheap"
                    ),

                "Trade":
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
                    round(
                        future_bid,
                        2
                    ),

                "Future Ask":
                    round(
                        future_ask,
                        2
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

                "CE Spread %":
                    round(
                        spread_percent(ceq),
                        2
                    ),

                "PE Spread %":
                    round(
                        spread_percent(peq),
                        2
                    ),

                "CE Volume":
                    ceq.get("volume"),

                "PE Volume":
                    peq.get("volume"),

                "CE OI":
                    ceq.get("oi"),

                "PE OI":
                    peq.get("oi"),

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
                    lot,

                "Gross Profit/Lot":
                    round(
                        gross_profit,
                        2
                    ),

                "Est. Future Margin":
                    round(
                        future_margin_est,
                        2
                    ),

                "Est. Option Capital":
                    round(
                        option_premium,
                        2
                    ),

                "Est. Total Capital":
                    round(
                        estimated_capital,
                        2
                    ),

                "Est. Charges":
                    round(
                        fno_charges,
                        2
                    ),

                "Est. NET PROFIT":
                    round(
                        net_profit,
                        2
                    )
            })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            [
                "Absolute Edge",
                "CE Volume",
                "PE Volume"
            ],
            ascending=[
                False,
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
# INDEX PARITY
# ============================================================

def scan_index_parity(
    jwt,
    master,
    index_name,
    strike_count,
    threshold
):

    expiry = current_month_expiry(
        master
    )

    if expiry is None:
        return pd.DataFrame()

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == index_name)
        &
        (master["expiry_date"] == expiry)
    ]

    futures = x[
        x["instrument"] == "FUTIDX"
    ]

    options = x[
        x["instrument"] == "OPTIDX"
    ]

    if futures.empty or options.empty:
        return pd.DataFrame()

    fr = futures.iloc[0]

    ft = str(
        fr["token"]
    )

    fq = batch_full_quote(
        jwt,
        "NFO",
        [ft]
    ).get(
        ft,
        {}
    )

    future = fq.get("ltp")
    fb = fq.get("bid")
    fa = fq.get("ask")

    if (
        future is None
        or fb is None
        or fa is None
    ):
        return pd.DataFrame()

    strikes = sorted(
        options["strike_num"]
        .dropna()
        .astype(float)
        .unique(),
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

        ceq = quotes.get(
            ce_token,
            {}
        )

        peq = quotes.get(
            pe_token,
            {}
        )

        if not quote_is_liquid(
            ceq,
            min_option_volume,
            min_option_oi,
            max_spread_percent
        ):
            continue

        if not quote_is_liquid(
            peq,
            min_option_volume,
            min_option_oi,
            max_spread_percent
        ):
            continue

        positive = (
            ceq["bid"]
            -
            peq["ask"]
            -
            (
                fa -
                strike
            )
        )

        negative = (
            ceq["ask"]
            -
            peq["bid"]
            -
            (
                fb -
                strike
            )
        )

        best = max(
            [
                positive,
                negative
            ],
            key=abs
        )

        if abs(best) <= threshold:
            continue

        rows.append({

            "Index":
                index_name,

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Future":
                round(
                    future,
                    2
                ),

            "Strike":
                round(
                    strike,
                    2
                ),

            "CE Bid":
                ceq["bid"],

            "CE Ask":
                ceq["ask"],

            "PE Bid":
                peq["bid"],

            "PE Ask":
                peq["ask"],

            "CE Volume":
                ceq.get("volume"),

            "PE Volume":
                peq.get("volume"),

            "CE OI":
                ceq.get("oi"),

            "PE OI":
                peq.get("oi"),

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
# NSE BHAVCOPY
# ============================================================

@st.cache_data(
    ttl=86400,
    show_spinner=False
)
def download_nse_fo_bhavcopy(
    date_obj
):

    d = pd.Timestamp(
        date_obj
    )

    yyyymmdd = d.strftime(
        "%Y%m%d"
    )

    ddmmyyyy = d.strftime(
        "%d%m%Y"
    )

    urls = [

        # New UDiFF style
        (
            "https://nsearchives.nseindia.com/"
            "content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_"
            f"{yyyymmdd}_F_0000.csv.zip"
        ),

        # Alternate archive path
        (
            "https://nsearchives.nseindia.com/"
            "content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_"
            f"{yyyymmdd}_F_0000.csv.zip"
        )
    ]

    session = requests.Session()

    session.headers.update(
        NSE_HEADERS
    )

    for url in urls:

        try:

            r = session.get(
                url,
                timeout=30
            )

            if (
                r.status_code != 200
                or
                len(r.content) < 500
            ):
                continue

            z = zipfile.ZipFile(
                io.BytesIO(
                    r.content
                )
            )

            names = z.namelist()

            csv_name = next(
                (
                    n for n in names
                    if n.lower().endswith(
                        ".csv"
                    )
                ),
                None
            )

            if csv_name is None:
                continue

            with z.open(
                csv_name
            ) as f:

                df = pd.read_csv(
                    f
                )

            if not df.empty:
                return df

        except Exception:
            continue

    return pd.DataFrame()


# ============================================================
# NORMALIZE NSE BHAVCOPY
# ============================================================

def normalize_fo_bhavcopy(
    df,
    date_obj
):

    if df.empty:
        return df

    x = df.copy()

    x.columns = [
        str(c)
        .strip()
        .upper()
        .replace(" ", "_")
        for c in x.columns
    ]

    # Common UDiFF names
    rename_map = {

        "TCKR_SYMB":
            "SYMBOL",

        "FIN_INSTRM_ID":
            "TOKEN",

        "XPRY_DT":
            "EXPIRY",

        "STRIKE_PRC":
            "STRIKE",

        "OPTN_TYP":
            "OPTION_TYPE",

        "FIN_INSTRM_TP":
            "INSTRUMENT",

        "CLSE_PRC":
            "CLOSE",

        "TTLE_TRADG_QTY":
            "VOLUME",

        "OPN_INTRST":
            "OI",

        "UNDRLYNG":
            "UNDERLYING",

        "UNDRLYNG_ASSET":
            "UNDERLYING"
    }

    for old, new in rename_map.items():

        if old in x.columns:
            x.rename(
                columns={
                    old: new
                },
                inplace=True
            )

    # Older NSE names
    legacy = {

        "SYMBOL":
            "SYMBOL",

        "EXPIRY_DT":
            "EXPIRY",

        "STRIKE_PR":
            "STRIKE",

        "OPTION_TYP":
            "OPTION_TYPE",

        "INSTRUMENT":
            "INSTRUMENT",

        "CLOSE":
            "CLOSE",

        "CONTRACTS":
            "VOLUME",

        "OPEN_INT":
            "OI"
    }

    for old, new in legacy.items():

        if (
            old in x.columns
            and new not in x.columns
        ):
            x.rename(
                columns={
                    old: new
                },
                inplace=True
            )

    x["DATE"] = pd.Timestamp(
        date_obj
    )

    if "EXPIRY" in x.columns:

        x["EXPIRY"] = pd.to_datetime(
            x["EXPIRY"],
            errors="coerce"
        )

    for col in [
        "STRIKE",
        "CLOSE",
        "VOLUME",
        "OI"
    ]:

        if col in x.columns:

            x[col] = pd.to_numeric(
                x[col],
                errors="coerce"
            )

    return x


# ============================================================
# DOWNLOAD 1 YEAR NSE DATA
# ============================================================

@st.cache_data(
    ttl=86400,
    show_spinner=False
)
def load_nse_year(
    days=365
):

    end = now_ist().date()

    start = (
        pd.Timestamp(end)
        -
        pd.Timedelta(
            days=days
        )
    ).date()

    # weekdays only
    dates = pd.date_range(
        start,
        end,
        freq="B"
    )

    all_data = []

    progress = st.progress(
        0
    )

    total = len(dates)

    for i, d in enumerate(
        dates
    ):

        df = download_nse_fo_bhavcopy(
            d
        )

        if not df.empty:

            df = normalize_fo_bhavcopy(
                df,
                d
            )

            all_data.append(
                df
            )

        progress.progress(
            int(
                (i + 1)
                / total
                * 100
            )
        )

    progress.empty()

    if not all_data:
        return pd.DataFrame()

    return pd.concat(
        all_data,
        ignore_index=True
    )


# ============================================================
# ROLLOVER DATA PREPARATION
# ============================================================

def find_col(
    df,
    names
):

    for name in names:

        if name in df.columns:
            return name

    return None


def prepare_rollover_data(
    df
):

    if df.empty:
        return pd.DataFrame()

    symbol_col = find_col(
        df,
        [
            "SYMBOL",
            "TCKR_SYMB"
        ]
    )

    expiry_col = find_col(
        df,
        [
            "EXPIRY",
            "XPRY_DT"
        ]
    )

    close_col = find_col(
        df,
        [
            "CLOSE",
            "CLSE_PRC"
        ]
    )

    volume_col = find_col(
        df,
        [
            "VOLUME",
            "TTLE_TRADG_QTY",
            "CONTRACTS"
        ]
    )

    oi_col = find_col(
        df,
        [
            "OI",
            "OPEN_INT",
            "OPN_INTRST"
        ]
    )

    instrument_col = find_col(
        df,
        [
            "INSTRUMENT",
            "FIN_INSTRM_TP"
        ]
    )

    if not symbol_col:
        return pd.DataFrame()

    if not expiry_col:
        return pd.DataFrame()

    if not close_col:
        return pd.DataFrame()

    if not oi_col:
        return pd.DataFrame()

    x = df.copy()

    x["SYMBOL_X"] = (
        x[symbol_col]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    x["EXPIRY_X"] = pd.to_datetime(
        x[expiry_col],
        errors="coerce"
    )

    x["CLOSE_X"] = pd.to_numeric(
        x[close_col],
        errors="coerce"
    )

    x["OI_X"] = pd.to_numeric(
        x[oi_col],
        errors="coerce"
    )

    if volume_col:

        x["VOLUME_X"] = pd.to_numeric(
            x[volume_col],
            errors="coerce"
        )

    else:

        x["VOLUME_X"] = 0

    if instrument_col:

        x["INSTRUMENT_X"] = (
            x[instrument_col]
            .astype(str)
            .str.upper()
        )

    else:

        x["INSTRUMENT_X"] = ""

    # Futures only
    x = x[
        x["INSTRUMENT_X"].str.contains(
            "FUT",
            na=False
        )
    ]

    x = x[
        x["EXPIRY_X"].notna()
        &
        x["CLOSE_X"].notna()
        &
        x["OI_X"].notna()
    ]

    return x


# ============================================================
# ROLLOVER CALCULATION
# ============================================================

def calculate_rollover_signals(
    df
):

    x = prepare_rollover_data(
        df
    )

    if x.empty:
        return pd.DataFrame()

    rows = []

    for date, day in x.groupby(
        "DATE"
    ):

        date = pd.Timestamp(
            date
        )

        day = day.copy()

        expiries = sorted(
            day["EXPIRY_X"]
            .dropna()
            .unique()
        )

        if len(expiries) < 2:
            continue

        current_expiry = expiries[0]
        next_expiry = expiries[1]

        cur = day[
            day["EXPIRY_X"]
            == current_expiry
        ]

        nxt = day[
            day["EXPIRY_X"]
            == next_expiry
        ]

        if cur.empty or nxt.empty:
            continue

        cur = (
            cur.groupby(
                "SYMBOL_X"
            )
            .agg(
                Current_Close=(
                    "CLOSE_X",
                    "last"
                ),
                Current_OI=(
                    "OI_X",
                    "sum"
                ),
                Current_Volume=(
                    "VOLUME_X",
                    "sum"
                )
            )
            .reset_index()
        )

        nxt = (
            nxt.groupby(
                "SYMBOL_X"
            )
            .agg(
                Next_Close=(
                    "CLOSE_X",
                    "last"
                ),
                Next_OI=(
                    "OI_X",
                    "sum"
                ),
                Next_Volume=(
                    "VOLUME_X",
                    "sum"
                )
            )
            .reset_index()
        )

        merged = cur.merge(
            nxt,
            on="SYMBOL_X",
            how="inner"
        )

        for _, r in merged.iterrows():

            if (
                r["Current_OI"]
                <
                rollover_min_oi
            ):
                continue

            if (
                r["Current_Volume"]
                <
                rollover_min_volume
            ):
                continue

            current_price = r[
                "Current_Close"
            ]

            next_price = r[
                "Next_Close"
            ]

            if current_price <= 0:
                continue

            rollover_cost = (
                (
                    next_price -
                    current_price
                )
                /
                current_price
                *
                100
            )

            total_oi = (
                r["Current_OI"]
                +
                r["Next_OI"]
            )

            rollover_pct = (
                r["Next_OI"]
                /
                total_oi
                *
                100
                if total_oi > 0
                else 0
            )

            rows.append({

                "Date":
                    date.date(),

                "Stock":
                    r["SYMBOL_X"],

                "Current Expiry":
                    current_expiry.date(),

                "Next Expiry":
                    next_expiry.date(),

                "Current Future":
                    current_price,

                "Next Future":
                    next_price,

                "Rollover Cost %":
                    rollover_cost,

                "Current OI":
                    r["Current_OI"],

                "Next OI":
                    r["Next_OI"],

                "Rollover OI %":
                    rollover_pct,

                "Volume":
                    r["Current_Volume"]
            })

    return pd.DataFrame(
        rows
    )


# ============================================================
# BULLISH LAST-WEEK FILTER
# ============================================================

def add_bullish_score(
    rollover
):

    if rollover.empty:
        return rollover

    x = rollover.copy()

    x["Date"] = pd.to_datetime(
        x["Date"]
    )

    x = x.sort_values(
        [
            "Stock",
            "Date"
        ]
    )

    rows = []

    for stock, g in x.groupby(
        "Stock"
    ):

        g = g.copy()

        g["Price_5D"] = (
            g["Current Future"]
            .shift(5)
        )

        g["Price_Change_5D"] = (
            (
                g["Current Future"]
                /
                g["Price_5D"]
                - 1
            )
            * 100
        )

        g["Bullish"] = (
            g["Price_Change_5D"]
            > 0
        )

        rows.append(g)

    return pd.concat(
        rows,
        ignore_index=True
    )


# ============================================================
# ROLLOVER SCANNER
# ============================================================

def rollover_scanner(
    df
):

    x = calculate_rollover_signals(
        df
    )

    if x.empty:
        return pd.DataFrame()

    x = add_bullish_score(
        x
    )

    latest_date = x[
        "Date"
    ].max()

    latest = x[
        x["Date"]
        == latest_date
    ].copy()

    latest = latest[
        latest["Bullish"] == True
    ]

    # high rollover + positive price
    latest["Score"] = (
        latest["Rollover OI %"]
        +
        latest["Price_Change_5D"].clip(
            lower=0
        )
        +
        latest["Rollover Cost %"].clip(
            lower=0
        )
    )

    latest = latest.sort_values(
        "Score",
        ascending=False
    ).reset_index(
        drop=True
    )

    latest.insert(
        0,
        "Rank",
        range(
            1,
            len(latest) + 1
        )
    )

    return latest


# ============================================================
# 1 YEAR ROLLOVER BACKTEST
# ============================================================

def rollover_backtest(
    df
):

    x = calculate_rollover_signals(
        df
    )

    if x.empty:
        return pd.DataFrame()

    x = add_bullish_score(
        x
    )

    x = x.sort_values(
        [
            "Stock",
            "Date"
        ]
    )

    results = []

    for stock, g in x.groupby(
        "Stock"
    ):

        g = g.copy()

        # signal:
        # bullish 5D
        # high rollover
        # positive rollover cost

        signal = (
            (g["Bullish"] == True)
            &
            (
                g["Rollover OI %"]
                >= 50
            )
            &
            (
                g["Rollover Cost %"]
                > 0
            )
        )

        signal_dates = g[
            signal
        ]

        for _, row in signal_dates.iterrows():

            entry_date = pd.Timestamp(
                row["Date"]
            )

            future = g[
                g["Date"]
                >
                entry_date
            ].head(5)

            if future.empty:
                continue

            exit_row = future.iloc[-1]

            entry_price = float(
                row["Current Future"]
            )

            exit_price = float(
                exit_row["Current Future"]
            )

            if entry_price <= 0:
                continue

            return_pct = (
                (
                    exit_price -
                    entry_price
                )
                /
                entry_price
                *
                100
            )

            results.append({

                "Stock":
                    stock,

                "Entry Date":
                    entry_date.date(),

                "Exit Date":
                    pd.Timestamp(
                        exit_row["Date"]
                    ).date(),

                "Entry Future":
                    entry_price,

                "Exit Future":
                    exit_price,

                "Rollover %":
                    row["Rollover OI %"],

                "Rollover Cost %":
                    row["Rollover Cost %"],

                "5D Price Change %":
                    row["Price_Change_5D"],

                "Return %":
                    return_pct,

                "Win":
                    "YES"
                    if return_pct > 0
                    else "NO"
            })

    result = pd.DataFrame(
        results
    )

    if result.empty:
        return result

    result = result.sort_values(
        "Entry Date"
    ).reset_index(
        drop=True
    )

    result.insert(
        0,
        "Trade #",
        range(
            1,
            len(result) + 1
        )
    )

    return result


# ============================================================
# BACKTEST SUMMARY
# ============================================================

def backtest_summary(
    result
):

    if result.empty:
        return {}

    returns = result[
        "Return %"
    ].astype(float)

    wins = (
        returns > 0
    ).sum()

    losses = (
        returns <= 0
    ).sum()

    win_rate = (
        wins /
        len(returns)
        *
        100
    )

    avg_return = (
        returns.mean()
    )

    total_return = (
        returns.sum()
    )

    equity = (
        1 +
        returns / 100
    ).cumprod()

    peak = (
        equity.cummax()
    )

    drawdown = (
        equity /
        peak -
        1
    ) * 100

    max_dd = (
        drawdown.min()
    )

    return {

        "Total Trades":
            len(result),

        "Winning Trades":
            wins,

        "Losing Trades":
            losses,

        "Win Rate %":
            win_rate,

        "Average Return %":
            avg_return,

        "Total Trade Return %":
            total_return,

        "Compounded Return %":
            (
                equity.iloc[-1]
                - 1
            ) * 100,

        "Max Drawdown %":
            max_dd
    }


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
            "कोई qualifying result नहीं मिला।"
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
# LOGIN
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
# FUTURE SPOT
# ============================================================

st.divider()

st.header(
    "1️⃣ ⚡ Future > Spot + MTF"
)

st.caption(
    "Spot खरीदना + 75% MTF funding + "
    "expiry तक interest + charges + NET profit"
)

if st.button(
    "🔄 Scan Future > Spot",
    key="future_button",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Future > Spot calculation..."
    ):

        result = scan_future_spot(
            jwt,
            master
        )

    st.session_state[
        "future_result"
    ] = result


show_result(
    st.session_state.get(
        "future_result",
        pd.DataFrame()
    ),
    "future_spot_mtf.csv"
)


# ============================================================
# STOCK PARITY SPLIT
# ============================================================

fno_expiry = current_month_expiry(
    master
)

fmap_all = stock_future_map(
    master,
    fno_expiry
) if fno_expiry is not None else {}

all_stocks = sorted(
    fmap_all.keys()
)

parts = np.array_split(
    all_stocks,
    3
)


# ============================================================
# PART 1
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚖️ Stock Parity — Part 1"
)

st.caption(
    "केवल liquid CE + PE + Future contracts"
)

if st.button(
    "🚀 Run Stock Parity Part 1",
    key="stock_part_1",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Part 1 liquid parity scan..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            list(parts[0]),
            parity_strikes,
            parity_threshold
        )

    st.session_state[
        "stock_parity_1"
    ] = result


show_result(
    st.session_state.get(
        "stock_parity_1",
        pd.DataFrame()
    ),
    "stock_parity_part_1.csv"
)


# ============================================================
# PART 2
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ Stock Parity — Part 2"
)

if st.button(
    "🚀 Run Stock Parity Part 2",
    key="stock_part_2",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Part 2 liquid parity scan..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            list(parts[1]),
            parity_strikes,
            parity_threshold
        )

    st.session_state[
        "stock_parity_2"
    ] = result


show_result(
    st.session_state.get(
        "stock_parity_2",
        pd.DataFrame()
    ),
    "stock_parity_part_2.csv"
)


# ============================================================
# PART 3
# ============================================================

st.divider()

st.header(
    "4️⃣ ⚖️ Stock Parity — Part 3"
)

if st.button(
    "🚀 Run Stock Parity Part 3",
    key="stock_part_3",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Part 3 liquid parity scan..."
    ):

        result = scan_stock_parity_part(
            jwt,
            master,
            list(parts[2]),
            parity_strikes,
            parity_threshold
        )

    st.session_state[
        "stock_parity_3"
    ] = result


show_result(
    st.session_state.get(
        "stock_parity_3",
        pd.DataFrame()
    ),
    "stock_parity_part_3.csv"
)


# ============================================================
# NIFTY
# ============================================================

st.divider()

st.header(
    "5️⃣ 📊 Nifty 50 Liquid Put-Call Parity"
)

if st.button(
    "🔄 Scan Nifty 50",
    key="nifty",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Nifty parity..."
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
    "nifty_liquid_parity.csv"
)


# ============================================================
# BANKNIFTY
# ============================================================

st.divider()

st.header(
    "6️⃣ 🏦 BankNifty Liquid Put-Call Parity"
)

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty",
    type="primary",
    use_container_width=True
):

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


show_result(
    st.session_state.get(
        "banknifty_result",
        pd.DataFrame()
    ),
    "banknifty_liquid_parity.csv"
)


# ============================================================
# ROLLOVER LIVE
# ============================================================

st.divider()

st.header(
    "7️⃣ 🔥 High Rollover + Bullish Scanner"
)

st.caption(
    "NSE F&O Bhavcopy | High rollover OI + "
    "positive 5-day future trend + rollover cost"
)

if st.button(
    "🚀 Scan Rollover",
    key="rollover",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NSE rollover data download/calculation..."
    ):

        nse_data = load_nse_year(
            30
        )

        result = rollover_scanner(
            nse_data
        )

    st.session_state[
        "rollover_result"
    ] = result


show_result(
    st.session_state.get(
        "rollover_result",
        pd.DataFrame()
    ),
    "rollover_scanner.csv"
)


# ============================================================
# 1 YEAR BACKTEST
# ============================================================

st.divider()

st.header(
    "8️⃣ 📚 NSE Bhavcopy — 1 Year Rollover Backtest"
)

st.caption(
    "Historical NSE F&O Bhavcopy/UDiFF data से "
    "signal → अगले 5 trading observations का result"
)

if st.button(
    "🧪 Run 1-Year Rollover Backtest",
    key="backtest",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "लगभग 1 साल की NSE F&O bhavcopy "
        "download और backtest हो रही है..."
    ):

        nse_data = load_nse_year(
            int(backtest_days)
        )

        bt = rollover_backtest(
            nse_data
        )

    st.session_state[
        "backtest_result"
    ] = bt

    st.session_state[
        "backtest_summary"
    ] = backtest_summary(
        bt
    )


summary = st.session_state.get(
    "backtest_summary",
    {}
)

if summary:

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Total Trades",
        summary["Total Trades"]
    )

    c2.metric(
        "Win Rate",
        f'{summary["Win Rate %"]:.2f}%'
    )

    c3.metric(
        "Avg Return",
        f'{summary["Average Return %"]:.2f}%'
    )

    c4.metric(
        "Max Drawdown",
        f'{summary["Max Drawdown %"]:.2f}%'
    )

    st.write(
        "Compounded Return:",
        f'{summary["Compounded Return %"]:.2f}%'
    )


show_result(
    st.session_state.get(
        "backtest_result",
        pd.DataFrame()
    ),
    "nse_rollover_1year_backtest.csv"
)


# ============================================================
# NOTES
# ============================================================

st.divider()

st.subheader(
    "ℹ️ Scanner Rules"
)

st.markdown(
    """
### Stock Parity

**Result में केवल liquid contract आएगा:**

- CE में Bid + Ask जरूरी
- PE में Bid + Ask जरूरी
- Future में Bid + Ask जरूरी
- CE volume minimum filter
- PE volume minimum filter
- CE OI minimum filter
- PE OI minimum filter
- Bid/Ask spread maximum filter
- Zero/stale quote reject
- CE और PE दोनों liquid होना जरूरी
- सिर्फ theoretical LTP parity नहीं
- **Executable Bid/Ask parity** से ranking

### Future > Spot

- Stock Spot खरीदा
- MTF funding default 75%
- आपकी capital default 25%
- 0.041% daily MTF interest
- Current expiry तक days
- Equity charges
- Future charges
- Gross spread
- Interest
- **NET PROFIT**
- ROI on own capital

### Rollover

NSE F&O historical bhavcopy से:

- Current expiry
- Next expiry
- Current Future price
- Next Future price
- Rollover OI %
- Rollover cost %
- Volume
- 5-day bullish trend

निकाला जाता है।

### Backtest

Signal:

**Bullish 5D + Rollover OI ≥ 50% + Positive Rollover Cost**

के बाद अगले 5 available trading observations का future return calculate किया जाता है।
"""
)


st.caption(
    "📡 Live market data: Angel One SmartAPI"
)

st.caption(
    "📚 Historical derivatives data: NSE F&O Bhavcopy / UDiFF"
)

st.caption(
    "⚠️ Margin और charges estimates हैं; actual RMS/contract "
    "charges broker/exchange settlement के अनुसार अलग हो सकते हैं।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st.info(
        f"🔄 Auto Refresh ON — "
        f"{refresh_seconds} seconds"
    )

    time.sleep(
        refresh_seconds
    )

    st.rerun()
