import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
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

st.title("📊 Fast Market Scanner PRO")

IST = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://apiconnect.angelone.in"

MASTER_URL = (
    "https://margincalculator.angelbroking.com/"
    "OpenAPI_File/files/OpenAPIScripMaster.json"
)


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def now_ist():
    return datetime.now(IST)


# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("⚙️ Scanner Settings")

    st.subheader("Parity")

    parity_threshold = st.number_input(
        "Minimum Executable Edge ₹",
        min_value=0.0,
        value=5.0,
        step=0.5
    )

    strike_count = st.number_input(
        "Liquid Strikes Around Future",
        min_value=3,
        max_value=30,
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

    st.subheader("Margin")

    margin_percent = st.number_input(
        "Estimated Future Margin %",
        min_value=5.0,
        max_value=50.0,
        value=15.0,
        step=1.0
    )

    st.subheader("Refresh")

    auto_refresh = st.checkbox(
        "Auto Refresh",
        value=False
    )

    refresh_seconds = st.number_input(
        "Refresh Seconds",
        min_value=15,
        max_value=300,
        value=30,
        step=5
    )


# ============================================================
# SECRETS CHECK
# ============================================================

if not API_KEY:
    st.error("ANGEL_API_KEY नहीं मिला।")
    st.stop()

if not CLIENT_ID:
    st.error("ANGEL_CLIENT_CODE नहीं मिला।")
    st.stop()

if not PASSWORD:
    st.error("ANGEL_PASSWORD नहीं मिला।")
    st.stop()

if not TOTP_SECRET:
    st.error("ANGEL_TOTP_SECRET नहीं मिला।")
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

    headers = BASE_HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    return headers


# ============================================================
# LOGIN
# ============================================================

@st.cache_resource(ttl=120)
def angel_login():

    totp = pyotp.TOTP(
        TOTP_SECRET
    ).now()

    url = (
        BASE_URL
        + "/rest/auth/angelbroking/"
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
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if data.get("status") is not True:
        raise Exception(
            data.get(
                "message",
                "Angel One login failed"
            )
        )

    token = (
        data.get("data", {})
        .get("jwtToken")
    )

    if not token:
        raise Exception(
            "JWT token नहीं मिला।"
        )

    return token


# ============================================================
# MASTER
# ============================================================

@st.cache_data(
    ttl=1800,
    show_spinner=False
)
def download_master():

    response = requests.get(
        MASTER_URL,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if not data:
        raise Exception(
            "Angel master खाली है।"
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

    unique_tokens = []

    for token in tokens:

        token = str(token).strip()

        if token and token not in unique_tokens:
            unique_tokens.append(token)

    if not unique_tokens:
        return {}

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
          "market/v1/quote/"
    )

    result = {}

    for start in range(
        0,
        len(unique_tokens),
        50
    ):

        batch = unique_tokens[
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
                headers=auth_headers(jwt),
                timeout=20
            )

            if response.status_code != 200:
                continue

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
                    "ltp": safe_float(
                        item.get("ltp")
                    ),
                    "bid": safe_float(
                        bid
                    ),
                    "ask": safe_float(
                        ask
                    ),
                    "volume": safe_float(
                        volume
                    ),
                    "oi": safe_float(
                        oi
                    )
                }

        except Exception:
            continue

    return result


# ============================================================
# EXPIRIES
# ============================================================

def get_expiries(
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
        return []

    expiries = sorted(
        x["expiry_date"]
        .dropna()
        .unique()
    )

    return expiries


def get_current_next_expiry(
    master
):

    expiries = get_expiries(
        master,
        "NFO"
    )

    if len(expiries) < 2:
        return None, None

    return (
        pd.Timestamp(expiries[0]),
        pd.Timestamp(expiries[1])
    )


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
        (
            master["expiry_date"]
            == expiry
        )
    ]

    result = {}

    for _, row in x.iterrows():

        stock = str(
            row["name"]
        ).strip().upper()

        if stock and stock not in result:
            result[stock] = row

    return result


# ============================================================
# CASH MAP
# ============================================================

def cash_token_map(master):

    x = master[
        (master["exchange"] == "NSE")
        &
        master["symbol"].str.endswith(
            "-EQ"
        )
    ]

    result = {}

    for _, row in x.iterrows():

        stock = (
            str(row["symbol"])
            .replace("-EQ", "")
            .strip()
            .upper()
        )

        if stock:

            result[stock] = {
                "token": str(
                    row["token"]
                ),
                "symbol": str(
                    row["symbol"]
                )
            }

    return result


# ============================================================
# LIQUIDITY
# ============================================================

def quote_is_liquid(q):

    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")
    volume = q.get("volume")
    oi = q.get("oi")

    if bid is None:
        return False

    if ask is None:
        return False

    if ltp is None:
        return False

    if bid <= 0 or ask <= 0:
        return False

    if ask < bid:
        return False

    if ltp <= 0:
        return False

    if volume is None:
        return False

    if oi is None:
        return False

    if volume < min_option_volume:
        return False

    if oi < min_option_oi:
        return False

    spread = (
        (ask - bid)
        / ltp
        * 100
    )

    if spread > max_spread_percent:
        return False

    return True


def spread_percent(q):

    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")

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
        * 100
    )


# ============================================================
# STOCK OPTIONS
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
        ).upper()

        if symbol.endswith("CE"):
            option_type = "CE"

        elif symbol.endswith("PE"):
            option_type = "PE"

        else:
            continue

        key = (
            round(float(strike), 2),
            option_type
        )

        result[key] = {
            "token": str(
                row["token"]
            ),
            "symbol": symbol,
            "lot": int(
                row["lot_size"]
            )
        }

    return result


# ============================================================
# INDEX OPTION MAP
# ============================================================

def index_contracts(
    master,
    index_name,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == index_name)
        &
        (
            master["expiry_date"]
            == expiry
        )
    ]

    future = x[
        x["instrument"] == "FUTIDX"
    ]

    options = x[
        x["instrument"] == "OPTIDX"
    ]

    return future, options


# ============================================================
# FUTURE > SPOT
# ============================================================

def scan_future_spot_expiry(
    jwt,
    master,
    expiry
):

    if expiry is None:
        return pd.DataFrame()

    cash_map = cash_token_map(
        master
    )

    future_map = stock_future_map(
        master,
        expiry
    )

    stocks = sorted(
        set(future_map.keys())
        &
        set(cash_map.keys())
    )

    if not stocks:
        return pd.DataFrame()

    spot_tokens = [
        cash_map[s]["token"]
        for s in stocks
    ]

    future_tokens = [
        str(future_map[s]["token"])
        for s in stocks
    ]

    spot_quotes = batch_full_quote(
        jwt,
        "NSE",
        spot_tokens
    )

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        spot_token = cash_map[
            stock
        ]["token"]

        future_token = str(
            future_map[stock]["token"]
        )

        sq = spot_quotes.get(
            spot_token,
            {}
        )

        fq = future_quotes.get(
            future_token,
            {}
        )

        spot = sq.get("ltp")
        future = fq.get("ltp")

        if spot is None or future is None:
            continue

        difference = (
            future - spot
        )

        if difference <= 0:
            continue

        lot = int(
            future_map[stock]["lot_size"]
        )

        gross_profit = (
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

            "Future - Spot": round(
                difference,
                2
            ),

            "Lot Size": lot,

            "GROSS PROFIT / LOT": round(
                gross_profit,
                2
            ),

            "Future Value / Lot": round(
                future * lot,
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

    if result.empty:
        return result

    result = result.sort_values(
        "GROSS PROFIT / LOT",
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
# STOCK PARITY
# ============================================================

def scan_stock_parity_expiry(
    jwt,
    master,
    stocks,
    expiry
):

    if expiry is None:
        return pd.DataFrame()

    future_map = stock_future_map(
        master,
        expiry
    )

    stocks = [
        s for s in stocks
        if s in future_map
    ]

    if not stocks:
        return pd.DataFrame()

    future_tokens = [
        str(future_map[s]["token"])
        for s in stocks
    ]

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in stocks:

        future_row = future_map[
            stock
        ]

        future_token = str(
            future_row["token"]
        )

        fq = future_quotes.get(
            future_token,
            {}
        )

        future = fq.get("ltp")
        future_bid = fq.get("bid")
        future_ask = fq.get("ask")

        if (
            future is None
            or future_bid is None
            or future_ask is None
        ):
            continue

        if future_bid <= 0 or future_ask <= 0:
            continue

        if future_ask < future_bid:
            continue

        contracts = stock_option_map(
            master,
            stock,
            expiry
        )

        if not contracts:
            continue

        available_strikes = sorted(
            set(
                key[0]
                for key in contracts.keys()
            ),
            key=lambda strike:
                abs(
                    strike - future
                )
        )

        # Only nearest configured strikes
        selected_strikes = (
            available_strikes[
                :int(strike_count)
            ]
        )

        option_tokens = []

        for strike in selected_strikes:

            ce = contracts.get(
                (strike, "CE")
            )

            pe = contracts.get(
                (strike, "PE")
            )

            if ce:
                option_tokens.append(
                    ce["token"]
                )

            if pe:
                option_tokens.append(
                    pe["token"]
                )

        option_quotes = batch_full_quote(
            jwt,
            "NFO",
            option_tokens
        )

        for strike in selected_strikes:

            ce = contracts.get(
                (strike, "CE")
            )

            pe = contracts.get(
                (strike, "PE")
            )

            # BOTH CONTRACTS MUST EXIST
            if not ce or not pe:
                continue

            ceq = option_quotes.get(
                ce["token"],
                {}
            )

            peq = option_quotes.get(
                pe["token"],
                {}
            )

            # =================================================
            # LIQUID STRIKE CRITERIA KEPT
            # =================================================

            if not quote_is_liquid(
                ceq
            ):
                continue

            if not quote_is_liquid(
                peq
            ):
                continue

            # =================================================
            # EXECUTABLE PARITY
            # =================================================

            # CE SELL
            # PE BUY
            # FUTURE BUY

            positive_edge = (
                ceq["bid"]
                -
                peq["ask"]
                -
                (
                    future_ask
                    -
                    strike
                )
            )

            # CE BUY
            # PE SELL
            # FUTURE SELL

            negative_edge = (
                ceq["ask"]
                -
                peq["bid"]
                -
                (
                    future_bid
                    -
                    strike
                )
            )

            candidates = [
                (
                    positive_edge,
                    "CE SELL / PE BUY / FUTURE BUY"
                ),
                (
                    negative_edge,
                    "CE BUY / PE SELL / FUTURE SELL"
                )
            ]

            best_edge, trade = max(
                candidates,
                key=lambda x:
                    abs(x[0])
            )

            if abs(best_edge) < parity_threshold:
                continue

            lot = int(
                future_row["lot_size"]
            )

            gross_profit = (
                abs(best_edge)
                * lot
            )

            # Approximate capital:
            # future margin + option premium
            future_margin = (
                future
                * lot
                * margin_percent
                / 100
            )

            option_capital = (
                ceq["ask"] * lot
                +
                peq["ask"] * lot
            )

            estimated_margin = (
                future_margin
                +
                option_capital
            )

            direction = (
                "CE-PE RICH"
                if best_edge > 0
                else
                "CE-PE CHEAP"
            )

            rows.append({

                "Stock": stock,

                "Direction":
                    direction,

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
                        ceq["bid"],
                        2
                    ),

                "CE Ask":
                    round(
                        ceq["ask"],
                        2
                    ),

                "PE Bid":
                    round(
                        peq["bid"],
                        2
                    ),

                "PE Ask":
                    round(
                        peq["ask"],
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
                    int(
                        ceq["volume"]
                    ),

                "PE Volume":
                    int(
                        peq["volume"]
                    ),

                "CE OI":
                    int(
                        ceq["oi"]
                    ),

                "PE OI":
                    int(
                        peq["oi"]
                    ),

                "Executable Edge":
                    round(
                        best_edge,
                        2
                    ),

                "Absolute Edge":
                    round(
                        abs(best_edge),
                        2
                    ),

                "Lot Size":
                    lot,

                "GROSS PROFIT / TRADE":
                    round(
                        gross_profit,
                        2
                    ),

                "Estimated Future Margin":
                    round(
                        future_margin,
                        2
                    ),

                "Estimated Option Capital":
                    round(
                        option_capital,
                        2
                    ),

                "EST. FINAL MARGIN":
                    round(
                        estimated_margin,
                        2
                    )
            })

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    result = result.sort_values(
        [
            "GROSS PROFIT / TRADE",
            "Absolute Edge"
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
# INDEX PARITY
# ============================================================

def scan_index_parity_expiry(
    jwt,
    master,
    index_name,
    expiry
):

    if expiry is None:
        return pd.DataFrame()

    futures, options = index_contracts(
        master,
        index_name,
        expiry
    )

    if futures.empty:
        return pd.DataFrame()

    if options.empty:
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

    future = future_quote.get(
        "ltp"
    )

    future_bid = future_quote.get(
        "bid"
    )

    future_ask = future_quote.get(
        "ask"
    )

    if (
        future is None
        or future_bid is None
        or future_ask is None
    ):
        return pd.DataFrame()

    if future_bid <= 0 or future_ask <= 0:
        return pd.DataFrame()

    option_rows = {}

    for _, row in options.iterrows():

        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        symbol = str(
            row["symbol"]
        ).upper()

        if symbol.endswith("CE"):
            typ = "CE"

        elif symbol.endswith("PE"):
            typ = "PE"

        else:
            continue

        option_rows[
            (
                round(
                    float(strike),
                    2
                ),
                typ
            )
        ] = row

    strikes = sorted(
        set(
            k[0]
            for k in option_rows.keys()
        ),
        key=lambda x:
            abs(
                x - future
            )
    )

    strikes = strikes[
        :int(strike_count)
    ]

    option_tokens = []

    for strike in strikes:

        ce = option_rows.get(
            (strike, "CE")
        )

        pe = option_rows.get(
            (strike, "PE")
        )

        if ce is not None:
            option_tokens.append(
                str(ce["token"])
            )

        if pe is not None:
            option_tokens.append(
                str(pe["token"])
            )

    option_quotes = batch_full_quote(
        jwt,
        "NFO",
        option_tokens
    )

    rows = []

    for strike in strikes:

        ce = option_rows.get(
            (strike, "CE")
        )

        pe = option_rows.get(
            (strike, "PE")
        )

        if ce is None or pe is None:
            continue

        ce_token = str(
            ce["token"]
        )

        pe_token = str(
            pe["token"]
        )

        ceq = option_quotes.get(
            ce_token,
            {}
        )

        peq = option_quotes.get(
            pe_token,
            {}
        )

        # LIQUIDITY FILTER
        if not quote_is_liquid(
            ceq
        ):
            continue

        if not quote_is_liquid(
            peq
        ):
            continue

        positive_edge = (
            ceq["bid"]
            -
            peq["ask"]
            -
            (
                future_ask
                -
                strike
            )
        )

        negative_edge = (
            ceq["ask"]
            -
            peq["bid"]
            -
            (
                future_bid
                -
                strike
            )
        )

        candidates = [
            (
                positive_edge,
                "CE SELL / PE BUY / FUTURE BUY"
            ),
            (
                negative_edge,
                "CE BUY / PE SELL / FUTURE SELL"
            )
        ]

        best_edge, trade = max(
            candidates,
            key=lambda x:
                abs(x[0])
        )

        if abs(best_edge) < parity_threshold:
            continue

        lot = int(
            future_row["lot_size"]
        )

        gross_profit = (
            abs(best_edge)
            * lot
        )

        future_margin = (
            future
            * lot
            * margin_percent
            / 100
        )

        option_capital = (
            ceq["ask"] * lot
            +
            peq["ask"] * lot
        )

        estimated_margin = (
            future_margin
            +
            option_capital
        )

        rows.append({

            "Index":
                index_name,

            "Direction":
                (
                    "CE-PE RICH"
                    if best_edge > 0
                    else
                    "CE-PE CHEAP"
                ),

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
                    ceq["bid"],
                    2
                ),

            "CE Ask":
                round(
                    ceq["ask"],
                    2
                ),

            "PE Bid":
                round(
                    peq["bid"],
                    2
                ),

            "PE Ask":
                round(
                    peq["ask"],
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
                int(
                    ceq["volume"]
                ),

            "PE Volume":
                int(
                    peq["volume"]
                ),

            "CE OI":
                int(
                    ceq["oi"]
                ),

            "PE OI":
                int(
                    peq["oi"]
                ),

            "Executable Edge":
                round(
                    best_edge,
                    2
                ),

            "Absolute Edge":
                round(
                    abs(best_edge),
                    2
                ),

            "Lot Size":
                lot,

            "GROSS PROFIT / TRADE":
                round(
                    gross_profit,
                    2
                ),

            "Estimated Future Margin":
                round(
                    future_margin,
                    2
                ),

            "Estimated Option Capital":
                round(
                    option_capital,
                    2
                ),

            "EST. FINAL MARGIN":
                round(
                    estimated_margin,
                    2
                )
        })

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    result = result.sort_values(
        [
            "GROSS PROFIT / TRADE",
            "Absolute Edge"
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
# DISPLAY
# ============================================================

def show_result(
    result,
    filename
):

    if (
        result is None
        or result.empty
    ):

        st.info(
            "कोई qualifying liquid contract नहीं मिला।"
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

    with st.spinner(
        "Angel One master loading..."
    ):

        master_raw = download_master()

        master = prepare_master(
            master_raw
        )

except Exception as e:

    st.error(
        "Master loading error: "
        + str(e)
    )

    st.stop()


# ============================================================
# LOGIN
# ============================================================

if "jwt" not in st.session_state:
    st.session_state["jwt"] = None


st.sidebar.divider()

if st.sidebar.button(
    "🔐 Connect Angel One",
    use_container_width=True
):

    try:

        st.session_state[
            "jwt"
        ] = angel_login()

        st.sidebar.success(
            "Angel One Connected"
        )

    except Exception as e:

        st.sidebar.error(
            "Login failed: "
            + str(e)
        )


jwt = st.session_state.get(
    "jwt"
)


if not jwt:

    st.warning(
        "पहले Sidebar में "
        "'Connect Angel One' दबाएँ।"
    )

    st.stop()


# ============================================================
# EXPIRIES
# ============================================================

current_expiry, next_expiry = (
    get_current_next_expiry(
        master
    )
)

if current_expiry is None:

    st.error(
        "Current F&O expiry नहीं मिली।"
    )

    st.stop()

if next_expiry is None:

    st.error(
        "Next F&O expiry नहीं मिली।"
    )

    st.stop()


st.success(
    "Current Month: "
    + current_expiry.strftime("%d-%b-%Y")
    + "   |   Next Month: "
    + next_expiry.strftime("%d-%b-%Y")
)


# ============================================================
# 1. FUTURE > SPOT CURRENT
# ============================================================

st.divider()

st.header(
    "1️⃣ ⚡ Future > Spot — CURRENT MONTH"
)

st.caption(
    "Current expiry का Future और Spot अलग calculate होंगे।"
)

if st.button(
    "🔄 Scan Current Month Future > Spot",
    key="future_current",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Current month Future > Spot..."
    ):

        result = scan_future_spot_expiry(
            jwt,
            master,
            current_expiry
        )

    st.session_state[
        "future_current_result"
    ] = result


show_result(
    st.session_state.get(
        "future_current_result",
        pd.DataFrame()
    ),
    "future_spot_current_month.csv"
)


# ============================================================
# 2. FUTURE > SPOT NEXT
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚡ Future > Spot — NEXT MONTH"
)

st.caption(
    "Next expiry का Future और Spot अलग calculate होंगे।"
)

if st.button(
    "🔄 Scan Next Month Future > Spot",
    key="future_next",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Next month Future > Spot..."
    ):

        result = scan_future_spot_expiry(
            jwt,
            master,
            next_expiry
        )

    st.session_state[
        "future_next_result"
    ] = result


show_result(
    st.session_state.get(
        "future_next_result",
        pd.DataFrame()
    ),
    "future_spot_next_month.csv"
)


# ============================================================
# STOCK PARTS
# ============================================================

future_current_map = stock_future_map(
    master,
    current_expiry
)

all_stocks = sorted(
    future_current_map.keys()
)

parts = np.array_split(
    all_stocks,
    5
)


# ============================================================
# CURRENT MONTH STOCK PARITY
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ STOCK PARITY — CURRENT MONTH"
)

st.caption(
    "Current Month CE + PE + Future | "
    "Liquid strike only"
)

for part_number in range(5):

    key = (
        "current_stock_part_"
        + str(part_number + 1)
    )

    result_key = (
        "current_stock_result_"
        + str(part_number + 1)
    )

    st.subheader(
        "Current Month — Part "
        + str(part_number + 1)
    )

    if st.button(
        "🚀 Run Current Month Part "
        + str(part_number + 1),
        key=key,
        type="primary",
        use_container_width=True
    ):

        with st.spinner(
            "Current Month Part "
            + str(part_number + 1)
            + " scanning..."
        ):

            result = scan_stock_parity_expiry(
                jwt,
                master,
                list(parts[part_number]),
                current_expiry
            )

        st.session_state[
            result_key
        ] = result

    show_result(
        st.session_state.get(
            result_key,
            pd.DataFrame()
        ),
        "stock_parity_current_part_"
        + str(part_number + 1)
        + ".csv"
    )


# ============================================================
# NEXT MONTH STOCK PARITY
# ============================================================

st.divider()

st.header(
    "4️⃣ ⚖️ STOCK PARITY — NEXT MONTH"
)

st.caption(
    "Next Month CE + PE + Future | "
    "Liquid strike only"
)

future_next_map = stock_future_map(
    master,
    next_expiry
)

next_stocks = sorted(
    future_next_map.keys()
)

next_parts = np.array_split(
    next_stocks,
    5
)

for part_number in range(5):

    key = (
        "next_stock_part_"
        + str(part_number + 1)
    )

    result_key = (
        "next_stock_result_"
        + str(part_number + 1)
    )

    st.subheader(
        "Next Month — Part "
        + str(part_number + 1)
    )

    if st.button(
        "🚀 Run Next Month Part "
        + str(part_number + 1),
        key=key,
        type="primary",
        use_container_width=True
    ):

        with st.spinner(
            "Next Month Part "
            + str(part_number + 1)
            + " scanning..."
        ):

            result = scan_stock_parity_expiry(
                jwt,
                master,
                list(next_parts[part_number]),
                next_expiry
            )

        st.session_state[
            result_key
        ] = result

    show_result(
        st.session_state.get(
            result_key,
            pd.DataFrame()
        ),
        "stock_parity_next_part_"
        + str(part_number + 1)
        + ".csv"
    )


# ============================================================
# NIFTY CURRENT
# ============================================================

st.divider()

st.header(
    "5️⃣ 📊 NIFTY 50 — CURRENT MONTH PARITY"
)

if st.button(
    "🔄 Scan NIFTY Current Month",
    key="nifty_current",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NIFTY current month..."
    ):

        result = scan_index_parity_expiry(
            jwt,
            master,
            "NIFTY",
            current_expiry
        )

    st.session_state[
        "nifty_current_result"
    ] = result


show_result(
    st.session_state.get(
        "nifty_current_result",
        pd.DataFrame()
    ),
    "nifty_current_month.csv"
)


# ============================================================
# NIFTY NEXT
# ============================================================

st.divider()

st.header(
    "6️⃣ 📊 NIFTY 50 — NEXT MONTH PARITY"
)

if st.button(
    "🔄 Scan NIFTY Next Month",
    key="nifty_next",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NIFTY next month..."
    ):

        result = scan_index_parity_expiry(
            jwt,
            master,
            "NIFTY",
            next_expiry
        )

    st.session_state[
        "nifty_next_result"
    ] = result


show_result(
    st.session_state.get(
        "nifty_next_result",
        pd.DataFrame()
    ),
    "nifty_next_month.csv"
)


# ============================================================
# BANKNIFTY CURRENT
# ============================================================

st.divider()

st.header(
    "7️⃣ 🏦 BANKNIFTY — CURRENT MONTH PARITY"
)

if st.button(
    "🔄 Scan BANKNIFTY Current Month",
    key="bank_current",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "BANKNIFTY current month..."
    ):

        result = scan_index_parity_expiry(
            jwt,
            master,
            "BANKNIFTY",
            current_expiry
        )

    st.session_state[
        "bank_current_result"
    ] = result


show_result(
    st.session_state.get(
        "bank_current_result",
        pd.DataFrame()
    ),
    "banknifty_current_month.csv"
)


# ============================================================
# BANKNIFTY NEXT
# ============================================================

st.divider()

st.header(
    "8️⃣ 🏦 BANKNIFTY — NEXT MONTH PARITY"
)

if st.button(
    "🔄 Scan BANKNIFTY Next Month",
    key="bank_next",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "BANKNIFTY next month..."
    ):

        result = scan_index_parity_expiry(
            jwt,
            master,
            "BANKNIFTY",
            next_expiry
        )

    st.session_state[
        "bank_next_result"
    ] = result


show_result(
    st.session_state.get(
        "bank_next_result",
        pd.DataFrame()
    ),
    "banknifty_next_month.csv"
)


# ============================================================
# RULES
# ============================================================

st.divider()

st.header(
    "ℹ️ Scanner Rules"
)

st.markdown(
    """
### ⚡ Future > Spot

Current और Next Month **पूरी तरह अलग** हैं।

- Spot LTP
- Future LTP
- Future − Spot
- Lot Size
- Gross Profit / Lot
- Future Value / Lot
- Expiry

**Highest Gross Profit ऊपर रहेगा।**

---

### ⚖️ Stock Put-Call Parity

Current और Next Month **अलग-अलग expiry contracts** हैं।

हर qualifying result में:

- CE मौजूद होना जरूरी
- PE मौजूद होना जरूरी
- Future मौजूद होना जरूरी
- CE Bid + Ask जरूरी
- PE Bid + Ask जरूरी
- Future Bid + Ask जरूरी
- CE Volume minimum
- PE Volume minimum
- CE OI minimum
- PE OI minimum
- CE spread filter
- PE spread filter
- Zero/stale quote reject
- **Liquid strike filter active है**
- Executable Bid/Ask calculation
- Gross Profit / Trade
- Estimated Future Margin
- Estimated Option Capital
- Estimated Final Margin

### 🔥 सबसे जरूरी

**Current Month CE + Current Month PE + Current Month Future**

एक साथ calculate होंगे।

और:

**Next Month CE + Next Month PE + Next Month Future**

एक साथ calculate होंगे।

दोनों को आपस में mix नहीं किया गया है।

---

### 📊 Index

NIFTY:

- Current Month
- Next Month

BANKNIFTY:

- Current Month
- Next Month

चारों अलग scanners हैं।
"""
)

st.caption(
    "📡 Live market data: Angel One SmartAPI"
)

st.caption(
    "⚠️ Estimated margin broker के actual RMS margin का replacement नहीं है।"
)


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:

    st.info(
        "🔄 Auto Refresh ON — "
        + str(refresh_seconds)
        + " seconds"
    )

    time.sleep(
        int(refresh_seconds)
    )

    st.rerun()
