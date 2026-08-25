import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
import io
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo


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
        "Liquid Strikes Around Future",
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

    h["Authorization"] = "Bearer " + jwt

    return h


def now_ist():

    return datetime.now(IST)


def safe_float(x):

    try:

        if x is None:
            return None

        value = float(x)

        if not np.isfinite(value):
            return None

        return value

    except Exception:

        return None


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

    r.raise_for_status()

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

    jwt = (
        data.get("data", {})
        .get("jwtToken")
    )

    if not jwt:
        raise Exception(
            "JWT token नहीं मिला"
        )

    return jwt


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
            if str(x).strip()
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

            if r.status_code != 200:
                continue

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

                ltp = safe_float(
                    item.get("ltp")
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
                    bid = safe_float(
                        buys[0].get("price")
                    )

                if sells:
                    ask = safe_float(
                        sells[0].get("price")
                    )

                if bid is None:
                    bid = safe_float(
                        item.get("bestBid")
                    )

                if ask is None:
                    ask = safe_float(
                        item.get("bestAsk")
                    )

                volume = safe_float(
                    item.get("tradeVolume")
                )

                if volume is None:
                    volume = safe_float(
                        item.get("volume")
                    )

                oi = safe_float(
                    item.get("opnInterest")
                )

                if oi is None:
                    oi = safe_float(
                        item.get("openInterest")
                    )

                result[token] = {
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "volume": volume,
                    "oi": oi
                }

        except Exception:
            continue

    return result


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
        pd.Timedelta(days=days)
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

        if r.status_code != 200:
            return pd.DataFrame()

        data = r.json()

        if data.get("status") is not True:
            return pd.DataFrame()

        candles = data.get(
            "data"
        ) or []

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
# CASH TOKEN MAP
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

    same = x[
        (x["expiry_date"].dt.month == today.month)
        &
        (
            x["expiry_date"].dt.year
            == today.year
        )
    ]

    if not same.empty:
        return same["expiry_date"].min()

    return x["expiry_date"].min()


# ============================================================
# FUTURE MAP
# ============================================================

def stock_future_map(
    master,
    expiry
):

    if expiry is None:
        return {}

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
        ).upper().strip()

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

    if not isinstance(q, dict):
        return False

    bid = safe_float(
        q.get("bid")
    )

    ask = safe_float(
        q.get("ask")
    )

    ltp = safe_float(
        q.get("ltp")
    )

    volume = safe_float(
        q.get("volume")
    )

    oi = safe_float(
        q.get("oi")
    )

    # Bid + Ask + LTP compulsory
    if (
        bid is None
        or ask is None
        or ltp is None
    ):
        return False

    if (
        bid <= 0
        or ask <= 0
        or ltp <= 0
    ):
        return False

    if ask < bid:
        return False

    # Volume compulsory when filter enabled
    if min_volume > 0:

        if volume is None:
            return False

        if volume < min_volume:
            return False

    # OI compulsory when filter enabled
    if min_oi > 0:

        if oi is None:
            return False

        if oi < min_oi:
            return False

    spread_pct = (
        (ask - bid)
        / ltp
    ) * 100

    if spread_pct > max_spread:
        return False

    return True


def spread_percent(q):

    bid = safe_float(
        q.get("bid")
    )

    ask = safe_float(
        q.get("ask")
    )

    ltp = safe_float(
        q.get("ltp")
    )

    if (
        bid is None
        or ask is None
        or ltp is None
        or ltp <= 0
    ):
        return None

    return (
        (ask - bid)
        / ltp
    ) * 100


# ============================================================
# CHARGES
# ============================================================

def equity_delivery_brokerage(
    turnover
):

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

    stt = turnover * 0.001

    exchange = (
        turnover * 0.0000307
    )

    sebi = (
        turnover * 0.000001
    )

    stamp = (
        buy_value * 0.00015
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
        sell_value * 0.0002
    )

    exchange = (
        turnover * 0.0000183
    )

    sebi = (
        turnover * 0.000001
    )

    stamp = (
        buy_value * 0.00002
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
        "Total": total
    }


# ============================================================
# MTF
# ============================================================

def mtf_trade_calculation(
    spot,
    future,
    lot,
    expiry
):

    stock_value = spot * lot

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
        (expiry_date - today).days
    )

    interest = (
        broker_funding
        *
        mtf_interest_daily
        / 100
        *
        days
    )

    future_value = future * lot

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
        "Spot Value": stock_value,
        "Broker Funding": broker_funding,
        "Your Capital": own_money,
        "MTF Days": days,
        "MTF Interest": interest,
        "Future Value": future_value,
        "Gross Spread Profit": gross,
        "Equity Charges": eq_charges["Total"],
        "Future Charges": f_charges["Total"],
        "Total Charges + Interest": total_charges,
        "NET PROFIT": net,
        "ROI %": roi
    }


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
        s for s in fmap
        if s in spot_map
    ]

    if not stocks:
        return pd.DataFrame()

    spot_tokens = [
        spot_map[s]["token"]
        for s in stocks
    ]

    future_tokens = [
        str(fmap[s]["token"])
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

        spot = safe_float(
            sq.get("ltp")
        )

        future = safe_float(
            fq.get("ltp")
        )

        if (
            spot is None
            or future is None
        ):
            continue

        if future <= spot:
            continue

        lot_value = safe_float(
            fmap[stock]["lot_size"]
        )

        if lot_value is None:
            continue

        lot = int(lot_value)

        if lot <= 0:
            continue

        calc = mtf_trade_calculation(
            spot,
            future,
            lot,
            expiry
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

            "Future - Spot": round(
                future - spot,
                2
            ),

            "Lot Size": lot,

            "Spot Purchase Value": round(
                calc["Spot Value"],
                2
            ),

            "Broker Funds": round(
                calc["Broker Funding"],
                2
            ),

            "Your Capital": round(
                calc["Your Capital"],
                2
            ),

            "MTF Days":
                calc["MTF Days"],

            "MTF Interest": round(
                calc["MTF Interest"],
                2
            ),

            "Gross Profit": round(
                calc["Gross Spread Profit"],
                2
            ),

            "Equity Charges": round(
                calc["Equity Charges"],
                2
            ),

            "Future Charges": round(
                calc["Future Charges"],
                2
            ),

            "Total Cost": round(
                calc["Total Charges + Interest"],
                2
            ),

            "NET PROFIT": round(
                calc["NET PROFIT"],
                2
            ),

            "ROI %": round(
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
        (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():

        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        symbol = str(
            row["symbol"]
        ).upper().strip()

        if symbol.endswith("CE"):
            typ = "CE"

        elif symbol.endswith("PE"):
            typ = "PE"

        else:
            continue

        lot = safe_float(
            row["lot_size"]
        )

        if lot is None or lot <= 0:
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
            "symbol": symbol,
            "lot": int(lot)
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
        s for s in stocks
        if s in fmap
    ]

    if not stocks:
        return pd.DataFrame()

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

        # ====================================================
        # FUTURE MUST BE LIQUID
        # ====================================================

        if not quote_is_liquid(
            fq,
            0,
            0,
            max_spread_percent
        ):
            continue

        future = safe_float(
            fq.get("ltp")
        )

        future_bid = safe_float(
            fq.get("bid")
        )

        future_ask = safe_float(
            fq.get("ask")
        )

        if (
            future is None
            or future_bid is None
            or future_ask is None
        ):
            continue

        contracts = stock_option_map(
            master,
            stock,
            expiry
        )

        if not contracts:
            continue

        # ====================================================
        # ONLY NEAREST STRIKES AROUND FUTURE
        # THEN LIQUIDITY FILTER
        # ====================================================

        all_strikes = sorted(
            set(
                k[0]
                for k in contracts
            ),
            key=lambda x:
                abs(x - future)
        )

        strikes = all_strikes[
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

            # =================================================
            # VERY IMPORTANT
            # ONLY LIQUID CE + PE
            # =================================================

            if not quote_is_liquid(
                ceq,
                int(min_option_volume),
                int(min_option_oi),
                float(max_spread_percent)
            ):
                continue

            if not quote_is_liquid(
                peq,
                int(min_option_volume),
                int(min_option_oi),
                float(max_spread_percent)
            ):
                continue

            ce_bid = ceq["bid"]
            ce_ask = ceq["ask"]

            pe_bid = peq["bid"]
            pe_ask = peq["ask"]

            # =================================================
            # EXECUTABLE PARITY
            #
            # Positive:
            # SELL CE @ BID
            # BUY PE @ ASK
            # BUY FUTURE @ ASK
            #
            # Negative:
            # BUY CE @ ASK
            # SELL PE @ BID
            # SELL FUTURE @ BID
            # =================================================

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

            # =================================================
            # MINIMUM EXECUTABLE EDGE
            # =================================================

            if abs(best_value) <= threshold:
                continue

            lot_value = safe_float(
                future_row["lot_size"]
            )

            if lot_value is None:
                continue

            lot = int(lot_value)

            if lot <= 0:
                continue

            gross_profit = (
                abs(best_value)
                * lot
            )

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

            fno_charges = (
                calculate_future_charges(
                    future * lot,
                    future * lot
                )["Total"]
                + 40
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

                "Future Spread %":
                    round(
                        spread_percent(fq),
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

    # ========================================================
    # FUTURE LIQUID
    # ========================================================

    if not quote_is_liquid(
        fq,
        0,
        0,
        max_spread_percent
    ):
        return pd.DataFrame()

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
            abs(x - future)
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

        # ONLY LIQUID CE
        if not quote_is_liquid(
            ceq,
            int(min_option_volume),
            int(min_option_oi),
            float(max_spread_percent)
        ):
            continue

        # ONLY LIQUID PE
        if not quote_is_liquid(
            peq,
            int(min_option_volume),
            int(min_option_oi),
            float(max_spread_percent)
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

        best, trade = max(
            candidates,
            key=lambda x:
                abs(x[0])
        )

        if abs(best) <= threshold:
            continue

        rows.append({

            "Index":
                index_name,

            "Trade":
                trade,

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
                    fb,
                    2
                ),

            "Future Ask":
                round(
                    fa,
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

    urls = [

        (
            "https://nsearchives.nseindia.com/"
            "content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_"
            f"{yyyymmdd}_F_0000.csv.zip"
        ),

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

            if r.status_code != 200:
                continue

            if len(r.content) < 500:
                continue

            z = zipfile.ZipFile(
                io.BytesIO(
                    r.content
                )
            )

            csv_name = next(
                (
                    n for n in z.namelist()
                    if n.lower().endswith(".csv")
                ),
                None
            )

            if csv_name is None:
                continue

            with z.open(csv_name) as f:

                df = pd.read_csv(
                    f
                )

            if not df.empty:
                return df

        except Exception:
            continue

    return pd.DataFrame()


# ============================================================
# NORMALIZE BHAVCOPY
# ============================================================

def normalize_fo_bhavcopy(
    df,
    date_obj
):

    if df.empty:
        return pd.DataFrame()

    x = df.copy()

    x.columns = [
        str(c)
        .strip()
        .upper()
        .replace(" ", "_")
        for c in x.columns
    ]

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

    # Legacy
    if (
        "EXPIRY_DT" in x.columns
        and "EXPIRY" not in x.columns
    ):
        x.rename(
            columns={
                "EXPIRY_DT": "EXPIRY"
            },
            inplace=True
        )

    if (
        "STRIKE_PR" in x.columns
        and "STRIKE" not in x.columns
    ):
        x.rename(
            columns={
                "STRIKE_PR": "STRIKE"
            },
            inplace=True
        )

    if (
        "OPTION_TYP" in x.columns
        and "OPTION_TYPE" not in x.columns
    ):
        x.rename(
            columns={
                "OPTION_TYP":
                    "OPTION_TYPE"
            },
            inplace=True
        )

    if (
        "CONTRACTS" in x.columns
        and "VOLUME" not in x.columns
    ):
        x.rename(
            columns={
                "CONTRACTS":
                    "VOLUME"
            },
            inplace=True
        )

    if (
        "OPEN_INT" in x.columns
        and "OI" not in x.columns
    ):
        x.rename(
            columns={
                "OPEN_INT":
                    "OI"
            },
            inplace=True
        )

    if (
        "CLSE_PRC" in x.columns
        and "CLOSE" not in x.columns
    ):
        x.rename(
            columns={
                "CLSE_PRC":
                    "CLOSE"
            },
            inplace=True
        )

    x["DATE"] = pd.Timestamp(
        date_obj
    )

    if "EXPIRY" in x.columns:

        x["EXPIRY"] = pd.to_datetime(
            x["EXPIRY"],
            errors="coerce",
            dayfirst=True
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
# LOAD NSE HISTORY
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
            days=int(days)
        )
    ).date()

    dates = pd.date_range(
        start,
        end,
        freq="B"
    )

    all_data = []

    for d in dates:

        try:

            df = download_nse_fo_bhavcopy(
                d
            )

            if df.empty:
                continue

            df = normalize_fo_bhavcopy(
                df,
                d
            )

            if not df.empty:
                all_data.append(df)

        except Exception:
            continue

    if not all_data:
        return pd.DataFrame()

    return pd.concat(
        all_data,
        ignore_index=True
    )


# ============================================================
# FIND COLUMN
# ============================================================

def find_col(
    df,
    names
):

    for name in names:

        if name in df.columns:
            return name

    return None


# ============================================================
# PREPARE ROLLOVER
# ============================================================

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
        errors="coerce",
        dayfirst=True
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

            current_oi = safe_float(
                r["Current_OI"]
            )

            current_volume = safe_float(
                r["Current_Volume"]
            )

            current_price = safe_float(
                r["Current_Close"]
            )

            next_price = safe_float(
                r["Next_Close"]
            )

            next_oi = safe_float(
                r["Next_OI"]
            )

            if (
                current_oi is None
                or current_volume is None
                or current_price is None
                or next_price is None
                or next_oi is None
            ):
                continue

            if current_oi < rollover_min_oi:
                continue

            if current_volume < rollover_min_volume:
                continue

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
                current_oi +
                next_oi
            )

            rollover_pct = (
                next_oi /
                total_oi *
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
                    current_oi,

                "Next OI":
                    next_oi,

                "Rollover OI %":
                    rollover_pct,

                "Volume":
                    current_volume
            })

    return pd.DataFrame(
        rows
    )


# ============================================================
# BULLISH SCORE
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
# LIVE ROLLOVER
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

    latest_date = x["Date"].max()

    latest = x[
        x["Date"] == latest_date
    ].copy()

    latest = latest[
        latest["Bullish"] == True
    ]

    if latest.empty:
        return latest

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
# ROLLOVER BACKTEST
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

            entry_price = safe_float(
                row["Current Future"]
            )

            exit_price = safe_float(
                exit_row["Current Future"]
            )

            if (
                entry_price is None
                or exit_price is None
                or entry_price <= 0
            ):
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

    returns = pd.to_numeric(
        result["Return %"],
        errors="coerce"
    ).dropna()

    if returns.empty:
        return {}

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

    avg_return = returns.mean()

    total_return = returns.sum()

    equity = (
        1 +
        returns / 100
    ).cumprod()

    peak = equity.cummax()

    drawdown = (
        equity /
        peak -
        1
    ) * 100

    max_dd = drawdown.min()

    return {

        "Total Trades":
            len(returns),

        "Winning Trades":
            int(wins),

        "Losing Trades":
            int(losses),

        "Win Rate %":
            float(win_rate),

        "Average Return %":
            float(avg_return),

        "Total Trade Return %":
            float(total_return),

        "Compounded Return %":
            float(
                (
                    equity.iloc[-1]
                    - 1
                ) * 100
            ),

        "Max Drawdown %":
            float(max_dd)
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
        "Master Error: " + str(e)
    )

    st.stop()


# ============================================================
# SESSION STATE
# ============================================================

session_defaults = {

    "jwt": None,

    "future_result":
        pd.DataFrame(),

    "stock_parity_1":
        pd.DataFrame(),

    "stock_parity_2":
        pd.DataFrame(),

    "stock_parity_3":
        pd.DataFrame(),

    "nifty_result":
        pd.DataFrame(),

    "banknifty_result":
        pd.DataFrame(),

    "rollover_result":
        pd.DataFrame(),

    "backtest_result":
        pd.DataFrame(),

    "backtest_summary":
        {}
}

for key, value in session_defaults.items():

    if key not in st.session_state:

        st.session_state[key] = value


# ============================================================
# CONNECT
# ============================================================

st.divider()

if st.button(
    "🔐 Connect Angel One",
    use_container_width=True,
    type="primary"
):

    try:

        st.session_state["jwt"] = login()

        st.success(
            "✅ Angel One Connected"
        )

    except Exception as e:

        st.session_state["jwt"] = None

        st.error(
            "Angel Login Error: "
            + str(e)
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
# FUTURE > SPOT
# ============================================================

st.divider()

st.header(
    "1️⃣ ⚡ Future > Spot + MTF"
)

st.caption(
    "Spot खरीदना + MTF funding + expiry तक interest + charges"
)

if st.button(
    "🔄 Scan Future > Spot",
    key="future_button",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Future > Spot scanning..."
    ):

        try:

            result = scan_future_spot(
                jwt,
                master
            )

            st.session_state[
                "future_result"
            ] = result

        except Exception as e:

            st.error(
                "Future scanner error: "
                + str(e)
            )


show_result(
    st.session_state[
        "future_result"
    ],
    "future_spot_mtf.csv"
)


# ============================================================
# STOCK PARTS
# ============================================================

fno_expiry = current_month_expiry(
    master
)

fmap_all = (
    stock_future_map(
        master,
        fno_expiry
    )
    if fno_expiry is not None
    else {}
)

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

        try:

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

        except Exception as e:

            st.error(
                "Part 1 Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "stock_parity_1"
    ],
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

        try:

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

        except Exception as e:

            st.error(
                "Part 2 Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "stock_parity_2"
    ],
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

        try:

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

        except Exception as e:

            st.error(
                "Part 3 Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "stock_parity_3"
    ],
    "stock_parity_part_3.csv"
)


# ============================================================
# NIFTY
# ============================================================

st.divider()

st.header(
    "5️⃣ 📊 Nifty Liquid Put-Call Parity"
)

st.caption(
    "केवल liquid CE + PE + Future"
)

if st.button(
    "🔄 Scan Nifty 50",
    key="nifty",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Nifty liquid parity..."
    ):

        try:

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

        except Exception as e:

            st.error(
                "Nifty Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "nifty_result"
    ],
    "nifty_liquid_parity.csv"
)


# ============================================================
# BANKNIFTY
# ============================================================

st.divider()

st.header(
    "6️⃣ 🏦 BankNifty Liquid Put-Call Parity"
)

st.caption(
    "केवल liquid CE + PE + Future"
)

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "BankNifty liquid parity..."
    ):

        try:

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

        except Exception as e:

            st.error(
                "BankNifty Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "banknifty_result"
    ],
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
    "NSE F&O Bhavcopy | High rollover OI + bullish trend"
)

if st.button(
    "🚀 Scan Rollover",
    key="rollover",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NSE Bhavcopy download/calculation..."
    ):

        try:

            nse_data = load_nse_year(
                30
            )

            if nse_data.empty:

                st.warning(
                    "NSE Bhavcopy data नहीं मिली।"
                )

                result = pd.DataFrame()

            else:

                result = rollover_scanner(
                    nse_data
                )

            st.session_state[
                "rollover_result"
            ] = result

        except Exception as e:

            st.error(
                "Rollover Error: "
                + str(e)
            )


show_result(
    st.session_state[
        "rollover_result"
    ],
    "rollover_scanner.csv"
)


# ============================================================
# BACKTEST
# ============================================================

st.divider()

st.header(
    "8️⃣ 📚 NSE Bhavcopy Rollover Backtest"
)

st.caption(
    "NSE F&O Bhavcopy से historical signal और अगले 5 trading observations का return"
)

if st.button(
    "🧪 Run NSE Rollover Backtest",
    key="backtest",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NSE Bhavcopy backtest चल रहा है..."
    ):

        try:

            nse_data = load_nse_year(
                int(backtest_days)
            )

            if nse_data.empty:

                st.warning(
                    "NSE historical Bhavcopy data नहीं मिली।"
                )

                bt = pd.DataFrame()

            else:

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

        except Exception as e:

            st.error(
                "Backtest Error: "
                + str(e)
            )


summary = st.session_state[
    "backtest_summary"
]

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
    st.session_state[
        "backtest_result"
    ],
    "nse_rollover_backtest.csv"
)


# ============================================================
# RULES
# ============================================================

st.divider()

st.subheader(
    "ℹ️ Scanner Rules"
)

st.markdown(
    """
### ⚖️ Stock / Index Put-Call Parity

**Result में केवल liquid contracts आएंगे:**

- CE Bid मौजूद होना जरूरी
- CE Ask मौजूद होना जरूरी
- PE Bid मौजूद होना जरूरी
- PE Ask मौजूद होना जरूरी
- Future Bid मौजूद होना जरूरी
- Future Ask मौजूद होना जरूरी
- CE minimum volume
- PE minimum volume
- CE minimum OI
- PE minimum OI
- CE maximum spread
- PE maximum spread
- Future maximum spread
- Crossed/invalid market reject
- Zero/stale quote reject
- Illiquid strike result में नहीं आएगा
- Theoretical LTP parity नहीं
- **Executable Bid/Ask parity** ranking होगी

### ⚡ Future > Spot

- Spot खरीद
- MTF funding
- अपनी capital
- MTF interest
- Expiry तक days
- Equity charges
- Future charges
- Gross spread
- NET PROFIT
- ROI

### 🔥 Rollover

NSE F&O Bhavcopy से:

- Current expiry
- Next expiry
- Current future
- Next future
- Rollover OI %
- Rollover cost %
- Volume
- 5-day bullish trend

### 🧪 Backtest

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
    "⚠️ Margin/charges estimates हैं। Actual broker/exchange "
    "RMS और settlement charges अलग हो सकते हैं।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st.info(
        f"🔄 Auto Refresh ON — {refresh_seconds} seconds"
    )

    time.sleep(
        int(refresh_seconds)
    )

    st.rerun()
