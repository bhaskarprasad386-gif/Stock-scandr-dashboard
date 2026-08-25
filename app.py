import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
from datetime import datetime
from zoneinfo import ZoneInfo


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Market Scanner PRO",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Fast Market Scanner PRO")

IST = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://apiconnect.angelone.in"

# ============================================================
# SETTINGS
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

    parity_strikes = st.number_input(
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

    st.subheader("Scanner")

    stock_parts = st.number_input(
        "Stock Scanner Parts",
        min_value=1,
        max_value=10,
        value=5,
        step=1
    )

    st.caption(
        "Liquid strike criteria हमेशा ON रहेगा."
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


# ============================================================
# VALIDATE SECRETS
# ============================================================

missing = []

if not API_KEY:
    missing.append("ANGEL_API_KEY")

if not CLIENT_ID:
    missing.append("ANGEL_CLIENT_CODE")

if not PASSWORD:
    missing.append("ANGEL_PASSWORD")

if not TOTP_SECRET:
    missing.append("ANGEL_TOTP_SECRET")


if missing:

    st.error(
        "Streamlit Secrets में ये values missing हैं: "
        + ", ".join(missing)
    )

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
# HELPERS
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


def clean_symbol(value):

    return (
        str(value)
        .upper()
        .strip()
    )


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

    response.raise_for_status()

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

    token = (
        data.get("data", {})
        .get("jwtToken")
    )

    if not token:

        raise Exception(
            "JWT token नहीं मिला."
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
            "Angel master खाली मिला."
        )

    return pd.DataFrame(data)


@st.cache_data(
    ttl=1800,
    show_spinner=False
)
def prepare_master(master):

    df = master.copy()

    required = [
        "token",
        "symbol",
        "name",
        "exch_seg",
        "instrumenttype",
        "expiry",
        "strike",
        "lotsize"
    ]

    missing = [
        x for x in required
        if x not in df.columns
    ]

    if missing:

        raise Exception(
            "Master columns missing: "
            + ", ".join(missing)
        )

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
# QUOTE
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
            if x is not None
            and str(x).strip()
        )
    )

    if not tokens:

        return {}

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
        + "market/v1/quote/"
    )

    result = {}

    # Angel supports max 50 tokens per request
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

                ltp = safe_float(
                    item.get("ltp")
                )

                depth = item.get(
                    "depth",
                    {}
                ) or {}

                buys = (
                    depth.get(
                        "buy",
                        []
                    )
                    or []
                )

                sells = (
                    depth.get(
                        "sell",
                        []
                    )
                    or []
                )

                bid = None
                ask = None

                if buys:

                    bid = safe_float(
                        buys[0].get(
                            "price"
                        )
                    )

                if sells:

                    ask = safe_float(
                        sells[0].get(
                            "price"
                        )
                    )

                # Fallback
                if bid is None:

                    bid = safe_float(
                        item.get(
                            "bestBid"
                        )
                    )

                if ask is None:

                    ask = safe_float(
                        item.get(
                            "bestAsk"
                        )
                    )

                volume = safe_float(
                    item.get(
                        "tradeVolume"
                    )
                )

                if volume is None:

                    volume = safe_float(
                        item.get(
                            "volume"
                        )
                    )

                oi = safe_float(
                    item.get(
                        "opnInterest"
                    )
                )

                if oi is None:

                    oi = safe_float(
                        item.get(
                            "openInterest"
                        )
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
# LIQUIDITY
# ============================================================

def quote_is_liquid(
    quote,
    min_volume,
    min_oi,
    max_spread
):

    if not quote:
        return False

    bid = quote.get("bid")
    ask = quote.get("ask")
    ltp = quote.get("ltp")
    volume = quote.get("volume")
    oi = quote.get("oi")

    # Bid/Ask compulsory
    if bid is None or ask is None:
        return False

    # LTP compulsory
    if ltp is None:
        return False

    if bid <= 0 or ask <= 0:
        return False

    if ask < bid:
        return False

    if ltp <= 0:
        return False

    # Volume filter
    if (
        volume is not None
        and volume < min_volume
    ):
        return False

    # OI filter
    if (
        oi is not None
        and oi < min_oi
    ):
        return False

    # Spread filter
    spread = (
        (ask - bid)
        / ltp
        * 100
    )

    if spread > max_spread:
        return False

    return True


def spread_percent(quote):

    bid = quote.get("bid")
    ask = quote.get("ask")
    ltp = quote.get("ltp")

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
# EXPIRIES
# ============================================================

def get_future_expiries(
    master,
    stock
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (master["name"] == stock)
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"]
            >= today
        )
    ]

    expiries = sorted(
        x["expiry_date"]
        .unique()
    )

    return expiries[:2]


def get_index_expiries(
    master,
    index_name
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == index_name)
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"]
            >= today
        )
    ]

    expiries = sorted(
        x["expiry_date"]
        .unique()
    )

    return expiries[:2]


# ============================================================
# STOCK FUTURES
# ============================================================

def get_stock_future(
    master,
    stock,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        (master["name"] == stock)
        &
        (
            master["expiry_date"]
            == expiry
        )
    ]

    if x.empty:
        return None

    return x.iloc[0]


# ============================================================
# CASH MAP
# ============================================================

@st.cache_data(
    ttl=1800,
    show_spinner=False
)
def create_cash_map(master):

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
            .replace(
                "-EQ",
                ""
            )
            .strip()
            .upper()
        )

        if stock:

            result[stock] = {
                "token":
                    str(row["token"]),

                "symbol":
                    str(row["symbol"])
            }

    return result


# ============================================================
# FUTURE > SPOT CALCULATION
# ============================================================

def calculate_future_spot(
    spot,
    future,
    lot
):

    spot_value = (
        spot * lot
    )

    future_value = (
        future * lot
    )

    difference = (
        future - spot
    )

    gross_profit = (
        difference * lot
    )

    estimated_margin = (
        future_value
        * margin_percent
        / 100
    )

    roi = (
        gross_profit
        / estimated_margin
        * 100
        if estimated_margin > 0
        else 0
    )

    return {

        "Difference":
            difference,

        "Gross Profit":
            gross_profit,

        "Spot Value":
            spot_value,

        "Future Value":
            future_value,

        "Estimated Margin":
            estimated_margin,

        "ROI %":
            roi
    }


# ============================================================
# FUTURE > SPOT SCANNER
# ============================================================

def scan_future_spot(
    jwt,
    master
):

    cash_map = create_cash_map(
        master
    )

    stocks = sorted(
        cash_map.keys()
    )

    future_rows = []

    token_map = {}

    for stock in stocks:

        expiries = get_future_expiries(
            master,
            stock
        )

        if len(expiries) < 2:
            continue

        for month_no, expiry in enumerate(
            expiries[:2],
            start=1
        ):

            row = get_stock_future(
                master,
                stock,
                expiry
            )

            if row is None:
                continue

            token_map[
                (
                    stock,
                    month_no
                )
            ] = {

                "cash_token":
                    cash_map[stock]["token"],

                "future_token":
                    str(row["token"]),

                "expiry":
                    expiry,

                "lot":
                    int(row["lot_size"])
            }

    cash_tokens = [
        x["cash_token"]
        for x in token_map.values()
    ]

    future_tokens = [
        x["future_token"]
        for x in token_map.values()
    ]

    cash_quotes = batch_full_quote(
        jwt,
        "NSE",
        cash_tokens
    )

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    for (
        stock,
        month_no
    ), info in token_map.items():

        spot_quote = cash_quotes.get(
            info["cash_token"],
            {}
        )

        future_quote = future_quotes.get(
            info["future_token"],
            {}
        )

        spot = spot_quote.get(
            "ltp"
        )

        future = future_quote.get(
            "ltp"
        )

        if spot is None or future is None:
            continue

        # User specifically wants Future > Spot
        if future <= spot:
            continue

        lot = info["lot"]

        calc = calculate_future_spot(
            spot,
            future,
            lot
        )

        future_rows.append({

            "Month":
                (
                    "Current Month"
                    if month_no == 1
                    else
                    "Next Month"
                ),

            "Stock":
                stock,

            "Expiry":
                pd.Timestamp(
                    info["expiry"]
                ).strftime(
                    "%d-%b-%Y"
                ),

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

            "Future - Spot":
                round(
                    calc["Difference"],
                    2
                ),

            "Lot Size":
                lot,

            "Gross Profit / Lot":
                round(
                    calc["Gross Profit"],
                    2
                ),

            "Future Contract Value":
                round(
                    calc["Future Value"],
                    2
                ),

            "Estimated Final Margin":
                round(
                    calc["Estimated Margin"],
                    2
                ),

            "Gross ROI %":
                round(
                    calc["ROI %"],
                    2
                )
        })

    result = pd.DataFrame(
        future_rows
    )

    if result.empty:
        return result

    # Highest gross profit first
    result = result.sort_values(
        "Gross Profit / Lot",
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
# STOCK OPTIONS MAP
# ============================================================

def get_stock_options(
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

        result[
            (
                round(
                    float(strike),
                    2
                ),
                option_type
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
# INDEX OPTIONS MAP
# ============================================================

def get_index_options(
    master,
    index_name,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "OPTIDX")
        &
        (master["name"] == index_name)
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

        result[
            (
                round(
                    float(strike),
                    2
                ),
                option_type
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
# PARITY TRADE CALCULATION
# ============================================================

def parity_calculation(
    future,
    strike,
    ce_bid,
    ce_ask,
    pe_bid,
    pe_ask,
    future_bid,
    future_ask,
    lot
):

    # --------------------------------------------------------
    # CE SELL / PE BUY / FUTURE BUY
    # --------------------------------------------------------

    positive_edge = (
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

    # --------------------------------------------------------
    # CE BUY / PE SELL / FUTURE SELL
    # --------------------------------------------------------

    negative_edge = (
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

    if abs(
        positive_edge
    ) >= abs(
        negative_edge
    ):

        edge = positive_edge

        trade = (
            "CE SELL / PE BUY / FUTURE BUY"
        )

    else:

        edge = negative_edge

        trade = (
            "CE BUY / PE SELL / FUTURE SELL"
        )

    gross_profit = (
        abs(edge)
        * lot
    )

    # Conservative estimated margin
    future_margin = (
        future
        * lot
        * margin_percent
        / 100
    )

    # Option premium exposure
    option_capital = (
        (
            ce_ask
            +
            pe_ask
        )
        * lot
    )

    estimated_margin = (
        future_margin
        +
        option_capital
    )

    roi = (
        gross_profit
        /
        estimated_margin
        *
        100
        if estimated_margin > 0
        else 0
    )

    return {

        "Edge":
            edge,

        "Trade":
            trade,

        "Gross Profit":
            gross_profit,

        "Future Margin":
            future_margin,

        "Option Capital":
            option_capital,

        "Estimated Final Margin":
            estimated_margin,

        "ROI %":
            roi
    }


# ============================================================
# STOCK PARITY ONE MONTH
# ============================================================

def scan_stock_parity_month(
    jwt,
    master,
    stocks,
    expiry,
    month_label
):

    cash_map = create_cash_map(
        master
    )

    future_info = {}

    for stock in stocks:

        if stock not in cash_map:
            continue

        row = get_stock_future(
            master,
            stock,
            expiry
        )

        if row is None:
            continue

        future_info[stock] = {

            "future_token":
                str(row["token"]),

            "cash_token":
                cash_map[stock]["token"],

            "lot":
                int(row["lot_size"])
        }

    if not future_info:
        return pd.DataFrame()

    future_tokens = [
        x["future_token"]
        for x in future_info.values()
    ]

    cash_tokens = [
        x["cash_token"]
        for x in future_info.values()
    ]

    future_quotes = batch_full_quote(
        jwt,
        "NFO",
        future_tokens
    )

    cash_quotes = batch_full_quote(
        jwt,
        "NSE",
        cash_tokens
    )

    rows = []

    for stock, info in future_info.items():

        fq = future_quotes.get(
            info["future_token"],
            {}
        )

        sq = cash_quotes.get(
            info["cash_token"],
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

        spot = sq.get(
            "ltp"
        )

        if (
            future is None
            or future_bid is None
            or future_ask is None
        ):
            continue

        if spot is None:
            continue

        if (
            future_bid <= 0
            or future_ask <= 0
        ):
            continue

        contracts = get_stock_options(
            master,
            stock,
            expiry
        )

        if not contracts:
            continue

        all_strikes = sorted(
            set(
                strike
                for (
                    strike,
                    option_type
                ) in contracts
            ),
            key=lambda strike:
                abs(
                    strike
                    -
                    future
                )
        )

        strikes = all_strikes[
            :int(parity_strikes)
        ]

        option_tokens = []

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

            # CE + PE both mandatory
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
            # LIQUID STRIKE CRITERIA
            # =================================================

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

            # Future must have both sides
            if (
                future_bid <= 0
                or future_ask <= 0
            ):
                continue

            calc = parity_calculation(
                future,
                strike,
                ceq["bid"],
                ceq["ask"],
                peq["bid"],
                peq["ask"],
                future_bid,
                future_ask,
                info["lot"]
            )

            if abs(
                calc["Edge"]
            ) < parity_threshold:
                continue

            rows.append({

                "Month":
                    month_label,

                "Stock":
                    stock,

                "Expiry":
                    pd.Timestamp(
                        expiry
                    ).strftime(
                        "%d-%b-%Y"
                    ),

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

                "Strike":
                    round(
                        strike,
                        2
                    ),

                "Trade":
                    calc["Trade"],

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
                    ceq.get(
                        "volume"
                    ),

                "PE Volume":
                    peq.get(
                        "volume"
                    ),

                "CE OI":
                    ceq.get(
                        "oi"
                    ),

                "PE OI":
                    peq.get(
                        "oi"
                    ),

                "Executable Edge":
                    round(
                        calc["Edge"],
                        2
                    ),

                "Absolute Edge":
                    round(
                        abs(calc["Edge"]),
                        2
                    ),

                "Lot Size":
                    info["lot"],

                "Gross Profit / Lot":
                    round(
                        calc["Gross Profit"],
                        2
                    ),

                "Future Margin":
                    round(
                        calc["Future Margin"],
                        2
                    ),

                "Option Capital":
                    round(
                        calc["Option Capital"],
                        2
                    ),

                "Estimated Final Margin":
                    round(
                        calc["Estimated Final Margin"],
                        2
                    ),

                "Gross ROI %":
                    round(
                        calc["ROI %"],
                        2
                    )
            })

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    # Highest gross profit first
    result = result.sort_values(
        [
            "Gross Profit / Lot",
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
# INDEX PARITY ONE MONTH
# ============================================================

def scan_index_parity_month(
    jwt,
    master,
    index_name,
    expiry,
    month_label
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

    futures = x[
        x["instrument"] == "FUTIDX"
    ]

    if futures.empty:
        return pd.DataFrame()

    future_row = futures.iloc[0]

    future_token = str(
        future_row["token"]
    )

    lot = int(
        future_row["lot_size"]
    )

    fq = batch_full_quote(
        jwt,
        "NFO",
        [future_token]
    ).get(
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
        or future_bid is None
        or future_ask is None
    ):
        return pd.DataFrame()

    if (
        future_bid <= 0
        or future_ask <= 0
    ):
        return pd.DataFrame()

    contracts = get_index_options(
        master,
        index_name,
        expiry
    )

    if not contracts:
        return pd.DataFrame()

    strikes = sorted(
        set(
            strike
            for (
                strike,
                option_type
            ) in contracts
        ),
        key=lambda strike:
            abs(
                strike
                -
                future
            )
    )[
        :int(parity_strikes)
    ]

    tokens = []

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

        if ce:
            tokens.append(
                ce["token"]
            )

        if pe:
            tokens.append(
                pe["token"]
            )

    quotes = batch_full_quote(
        jwt,
        "NFO",
        tokens
    )

    rows = []

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

        # =====================================================
        # LIQUID STRIKE
        # =====================================================

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

        calc = parity_calculation(
            future,
            strike,
            ceq["bid"],
            ceq["ask"],
            peq["bid"],
            peq["ask"],
            future_bid,
            future_ask,
            lot
        )

        if abs(
            calc["Edge"]
        ) < parity_threshold:
            continue

        rows.append({

            "Month":
                month_label,

            "Index":
                index_name,

            "Expiry":
                pd.Timestamp(
                    expiry
                ).strftime(
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

            "Trade":
                calc["Trade"],

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
                ceq.get(
                    "volume"
                ),

            "PE Volume":
                peq.get(
                    "volume"
                ),

            "CE OI":
                ceq.get(
                    "oi"
                ),

            "PE OI":
                peq.get(
                    "oi"
                ),

            "Executable Edge":
                round(
                    calc["Edge"],
                    2
                ),

            "Absolute Edge":
                round(
                    abs(calc["Edge"]),
                    2
                ),

            "Lot Size":
                lot,

            "Gross Profit / Lot":
                round(
                    calc["Gross Profit"],
                    2
                ),

            "Future Margin":
                round(
                    calc["Future Margin"],
                    2
                ),

            "Option Capital":
                round(
                    calc["Option Capital"],
                    2
                ),

            "Estimated Final Margin":
                round(
                    calc["Estimated Final Margin"],
                    2
                ),

            "Gross ROI %":
                round(
                    calc["ROI %"],
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
            "Gross Profit / Lot",
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
# SPLIT LIST
# ============================================================

def split_into_parts(
    items,
    parts
):

    items = list(items)

    if not items:
        return []

    parts = max(
        1,
        min(
            int(parts),
            len(items)
        )
    )

    arrays = np.array_split(
        np.array(items),
        parts
    )

    return [
        list(x)
        for x in arrays
        if len(x) > 0
    ]


# ============================================================
# RESULT DISPLAY
# ============================================================

def display_result(
    result,
    filename
):

    if (
        result is None
        or result.empty
    ):

        st.info(
            "कोई qualifying liquid result नहीं मिला."
        )

        return

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        height=600
    )

    csv_data = (
        result
        .to_csv(index=False)
        .encode("utf-8")
    )

    st.download_button(
        label="⬇️ Download Editable CSV / Excel में खोलें",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# LOAD MASTER
# ============================================================

with st.spinner(
    "Angel master loading..."
):

    try:

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

    st.session_state[
        "jwt"
    ] = None


st.sidebar.divider()

if st.sidebar.button(
    "🔐 Connect Angel One",
    use_container_width=True
):

    try:

        with st.spinner(
            "Angel One login..."
        ):

            st.session_state[
                "jwt"
            ] = angel_login()

        st.sidebar.success(
            "Angel One Connected ✅"
        )

    except Exception as e:

        st.sidebar.error(
            str(e)
        )


jwt = st.session_state.get(
    "jwt"
)


if not jwt:

    st.warning(
        "ऊपर Sidebar में पहले "
        "**Connect Angel One** दबाएँ."
    )

    st.stop()


# ============================================================
# 1. FUTURE > SPOT
# ============================================================

st.divider()

st.header(
    "1️⃣ ⚡ Future > Spot — Current + Next Month"
)

st.caption(
    "Current और Next month दोनों futures को Spot से compare किया जाएगा. "
    "Future > Spot होने पर lot-wise gross profit निकलेगा."
)

if st.button(
    "🚀 Scan Future > Spot",
    key="future_spot_scan",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Current + Next month Future > Spot scanning..."
    ):

        try:

            result = scan_future_spot(
                jwt,
                master
            )

            st.session_state[
                "future_spot_result"
            ] = result

        except Exception as e:

            st.error(
                "Future > Spot Error: "
                + str(e)
            )


future_result = st.session_state.get(
    "future_spot_result",
    pd.DataFrame()
)

display_result(
    future_result,
    "future_spot_current_next.csv"
)


# ============================================================
# 2. STOCK PARTS
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚖️ Stock Put-Call Parity"
)

st.caption(
    "Current + Next month parity | "
    "Liquid CE + PE + Future mandatory | "
    "5 independent parts"
)


fno_stocks = sorted(
    master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
    ]["name"]
    .dropna()
    .unique()
    .tolist()
)

stock_parts_list = split_into_parts(
    fno_stocks,
    stock_parts
)


for index, stock_list in enumerate(
    stock_parts_list,
    start=1
):

    st.subheader(
        f"Part {index} — {len(stock_list)} Stocks"
    )

    button_key = (
        "stock_parity_part_"
        + str(index)
    )

    result_key = (
        "stock_parity_result_"
        + str(index)
    )

    if st.button(
        f"🚀 Run Stock Parity Part {index}",
        key=button_key,
        type="primary",
        use_container_width=True
    ):

        with st.spinner(
            f"Part {index}: Current + Next month liquid parity..."
        ):

            all_results = []

            for stock in stock_list:

                try:

                    expiries = get_future_expiries(
                        master,
                        stock
                    )

                    if len(expiries) < 2:
                        continue

                    current_expiry = (
                        expiries[0]
                    )

                    next_expiry = (
                        expiries[1]
                    )

                    current_result = (
                        scan_stock_parity_month(
                            jwt,
                            master,
                            [stock],
                            current_expiry,
                            "Current Month"
                        )
                    )

                    next_result = (
                        scan_stock_parity_month(
                            jwt,
                            master,
                            [stock],
                            next_expiry,
                            "Next Month"
                        )
                    )

                    if (
                        current_result is not None
                        and
                        not current_result.empty
                    ):

                        all_results.append(
                            current_result
                        )

                    if (
                        next_result is not None
                        and
                        not next_result.empty
                    ):

                        all_results.append(
                            next_result
                        )

                except Exception:

                    continue

            if all_results:

                result = pd.concat(
                    all_results,
                    ignore_index=True
                )

                result = result.sort_values(
                    [
                        "Gross Profit / Lot",
                        "Absolute Edge"
                    ],
                    ascending=[
                        False,
                        False
                    ]
                ).reset_index(
                    drop=True
                )

                result["Rank"] = range(
                    1,
                    len(result) + 1
                )

                cols = [
                    "Rank"
                ] + [
                    c for c in result.columns
                    if c != "Rank"
                ]

                result = result[
                    cols
                ]

            else:

                result = pd.DataFrame()

            st.session_state[
                result_key
            ] = result

    display_result(
        st.session_state.get(
            result_key,
            pd.DataFrame()
        ),
        f"stock_parity_part_{index}.csv"
    )


# ============================================================
# 3. NIFTY
# ============================================================

st.divider()

st.header(
    "3️⃣ 📊 NIFTY Liquid Put-Call Parity"
)

st.caption(
    "Current month + Next month | Liquid strikes only"
)

if st.button(
    "🚀 Scan NIFTY Current + Next",
    key="nifty_scan",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "NIFTY current + next month parity..."
    ):

        try:

            expiries = get_index_expiries(
                master,
                "NIFTY"
            )

            results = []

            if len(expiries) >= 1:

                r1 = scan_index_parity_month(
                    jwt,
                    master,
                    "NIFTY",
                    expiries[0],
                    "Current Month"
                )

                if not r1.empty:
                    results.append(r1)

            if len(expiries) >= 2:

                r2 = scan_index_parity_month(
                    jwt,
                    master,
                    "NIFTY",
                    expiries[1],
                    "Next Month"
                )

                if not r2.empty:
                    results.append(r2)

            if results:

                result = pd.concat(
                    results,
                    ignore_index=True
                )

                result = result.sort_values(
                    "Gross Profit / Lot",
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

            else:

                result = pd.DataFrame()

            st.session_state[
                "nifty_result"
            ] = result

        except Exception as e:

            st.error(
                "NIFTY Error: "
                + str(e)
            )


display_result(
    st.session_state.get(
        "nifty_result",
        pd.DataFrame()
    ),
    "nifty_current_next_parity.csv"
)


# ============================================================
# 4. BANKNIFTY
# ============================================================

st.divider()

st.header(
    "4️⃣ 🏦 BANKNIFTY Liquid Put-Call Parity"
)

st.caption(
    "Current month + Next month | Liquid strikes only"
)

if st.button(
    "🚀 Scan BANKNIFTY Current + Next",
    key="banknifty_scan",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "BANKNIFTY current + next month parity..."
    ):

        try:

            expiries = get_index_expiries(
                master,
                "BANKNIFTY"
            )

            results = []

            if len(expiries) >= 1:

                r1 = scan_index_parity_month(
                    jwt,
                    master,
                    "BANKNIFTY",
                    expiries[0],
                    "Current Month"
                )

                if not r1.empty:
                    results.append(r1)

            if len(expiries) >= 2:

                r2 = scan_index_parity_month(
                    jwt,
                    master,
                    "BANKNIFTY",
                    expiries[1],
                    "Next Month"
                )

                if not r2.empty:
                    results.append(r2)

            if results:

                result = pd.concat(
                    results,
                    ignore_index=True
                )

                result = result.sort_values(
                    "Gross Profit / Lot",
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

            else:

                result = pd.DataFrame()

            st.session_state[
                "banknifty_result"
            ] = result

        except Exception as e:

            st.error(
                "BANKNIFTY Error: "
                + str(e)
            )


display_result(
    st.session_state.get(
        "banknifty_result",
        pd.DataFrame()
    ),
    "banknifty_current_next_parity.csv"
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

Current और Next month दोनों Future contracts check होंगे:

- Spot LTP
- Future LTP
- Future − Spot
- Lot Size
- **Gross Profit = (Future − Spot) × Lot Size**
- Estimated Final Margin
- Gross ROI %

जिस contract का **Gross Profit / Lot ज्यादा होगा, वह ऊपर आएगा।**

---

### ⚖️ Stock / Index Put-Call Parity

**Liquid strike criteria हटाया नहीं गया है।**

हर strike के लिए:

- CE Bid जरूरी
- CE Ask जरूरी
- PE Bid जरूरी
- PE Ask जरूरी
- Future Bid जरूरी
- Future Ask जरूरी
- CE minimum Volume
- PE minimum Volume
- CE minimum OI
- PE minimum OI
- CE maximum Bid/Ask spread
- PE maximum Bid/Ask spread
- Zero/stale quotes reject
- CE और PE दोनों liquid होना जरूरी

इसके बाद **Executable Bid/Ask parity** निकाली जाती है।

---

### 💰 Gross Profit

Parity में:

**Executable Edge × Lot Size = Gross Profit / Lot**

और साथ में:

- Future Margin
- Option Capital
- Estimated Final Margin
- Gross ROI %

दिखाया जाएगा।

---

### 📅 Expiry

हर stock/index के लिए:

**1. Current available expiry**

**2. Next available expiry**

दोनों अलग-अलग scan होंगे।

---

### 📊 Stock Scanner

Stock universe को **5 independent parts** में बाँटा गया है।

Part 1, Part 2, Part 3, Part 4 और Part 5 को अलग-अलग run कर सकते हैं।

इससे एक साथ पूरा heavy request भेजने के बजाय load कम रहेगा।

---

### 📥 CSV

हर result के नीचे CSV download मिलेगा।

CSV को Excel में खोलकर/edit किया जा सकता है।
"""
)

st.caption(
    "📡 Live data: Angel One SmartAPI"
)

st.caption(
    "⚠️ Estimated Final Margin केवल scanner estimate है। "
    "Actual RMS margin broker/exchange के अनुसार बदल सकता है।"
)
