import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Fast F&O Parity Scanner",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Fast F&O Put-Call Parity Scanner")

IST = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://apiconnect.angelone.in"

QUOTE_URL = (
    BASE_URL
    + "/rest/secure/angelbroking/market/v1/quote/"
)

MARGIN_URL = (
    BASE_URL
    + "/rest/secure/angelbroking/margin/v1/batch"
)

# ============================================================
# USER SETTINGS
# ============================================================

STRIKES_EACH_SIDE = 12

MIN_EDGE = 1.0

HIGH_EDGE_LOT = 5000.0

HIGH_ROM = 1.0

QUOTE_BATCH_SIZE = 50

QUOTE_SLEEP = 1.05

BACKGROUND_SECONDS = 20

# ============================================================
# WHATSAPP
# ============================================================
#
# अभी number नहीं दिया गया है इसलिए OFF है।
#
# बाद में अपना WhatsApp API/Webhook लगाने पर
# सिर्फ यही section बदलना होगा.
#
# ============================================================

WHATSAPP_ENABLED = False
WHATSAPP_NUMBER = ""

# ============================================================
# GLOBAL BACKGROUND STORAGE
# ============================================================

if "bg_results" not in st.session_state:
    st.session_state["bg_results"] = pd.DataFrame()

if "bg_last_scan" not in st.session_state:
    st.session_state["bg_last_scan"] = ""

if "bg_status" not in st.session_state:
    st.session_state["bg_status"] = "Stopped"

if "alert_history" not in st.session_state:
    st.session_state["alert_history"] = []

# Process-level shared cache
if "parity_global_store" not in st.session_state:
    st.session_state["parity_global_store"] = {}

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
        raise Exception(
            "Angel master खाली मिला"
        )

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
# FULL QUOTE
# ============================================================

def full_quote_batch(
    jwt,
    exchange_tokens
):

    result = {}

    for exchange, tokens in exchange_tokens.items():

        tokens = [
            str(x)
            for x in tokens
            if str(x)
        ]

        tokens = list(
            dict.fromkeys(tokens)
        )

        for i in range(
            0,
            len(tokens),
            QUOTE_BATCH_SIZE
        ):

            batch = tokens[
                i:i + QUOTE_BATCH_SIZE
            ]

            payload = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: batch
                }
            }

            try:

                r = requests.post(
                    QUOTE_URL,
                    json=payload,
                    headers=auth_headers(jwt),
                    timeout=20
                )

                data = r.json()

                if data.get("status") is not True:
                    continue

                fetched = (
                    data.get(
                        "data",
                        {}
                    ).get(
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

                    depth = item.get(
                        "depth",
                        {}
                    )

                    buy = (
                        depth.get(
                            "buy",
                            []
                        )
                        if isinstance(
                            depth,
                            dict
                        )
                        else []
                    )

                    sell = (
                        depth.get(
                            "sell",
                            []
                        )
                        if isinstance(
                            depth,
                            dict
                        )
                        else []
                    )

                    bid = None
                    ask = None

                    if buy:
                        try:
                            bid = float(
                                buy[0].get(
                                    "price"
                                )
                            )
                        except Exception:
                            pass

                    if sell:
                        try:
                            ask = float(
                                sell[0].get(
                                    "price"
                                )
                            )
                        except Exception:
                            pass

                    try:
                        ltp = float(
                            item.get("ltp")
                        )
                    except Exception:
                        ltp = None

                    result[token] = {
                        "ltp": ltp,
                        "bid": bid,
                        "ask": ask,
                        "symbol": item.get(
                            "tradingSymbol",
                            ""
                        )
                    }

            except Exception:
                continue

            if (
                i + QUOTE_BATCH_SIZE
                < len(tokens)
            ):
                time.sleep(
                    QUOTE_SLEEP
                )

    return result


# ============================================================
# EXPIRY
# ============================================================

def nearest_expiry_for_instrument(
    master,
    instrument,
    name
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == instrument)
        &
        (master["name"] == name)
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] >= today
        )
    ]

    if x.empty:
        return None

    return x[
        "expiry_date"
    ].min()


# ============================================================
# STOCK EXPIRY
# ============================================================

def stock_expiry(
    master
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (
            master["instrument"] == "FUTSTK"
        )
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] >= today
        )
    ]

    if x.empty:
        return None

    # nearest common stock expiry
    return x[
        "expiry_date"
    ].min()


# ============================================================
# ALL FNO STOCK FUTURES
# ============================================================

def all_fno_futures(
    master,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (
            master["instrument"]
            == "FUTSTK"
        )
        &
        (
            master["expiry_date"]
            == expiry
        )
    ].copy()

    result = {}

    for _, row in x.iterrows():

        stock = str(
            row["name"]
        ).strip().upper()

        if stock:
            result[stock] = row

    return result


# ============================================================
# OPTIONS MAP
# ============================================================

def option_maps(
    master,
    expiry,
    stocks
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (
            master["instrument"]
            == "OPTSTK"
        )
        &
        (
            master["expiry_date"]
            == expiry
        )
        &
        (
            master["name"].isin(stocks)
        )
    ]

    result = {}

    for _, row in x.iterrows():

        stock = str(
            row["name"]
        ).strip().upper()

        strike = row[
            "strike_num"
        ]

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

        result.setdefault(
            stock,
            {}
        )[
            (
                round(
                    float(strike),
                    2
                ),
                typ
            )
        ] = row

    return result


# ============================================================
# SELECT NEAREST STRIKES
# ============================================================

def nearest_strikes(
    omap,
    future,
    count=12
):

    strikes = sorted(
        set(
            strike
            for strike, typ
            in omap.keys()
        )
    )

    if not strikes:
        return []

    center = min(
        range(len(strikes)),
        key=lambda i:
            abs(
                strikes[i]
                - future
            )
    )

    start = max(
        0,
        center - count
    )

    end = min(
        len(strikes),
        center + count + 1
    )

    return strikes[
        start:end
    ]


# ============================================================
# EXECUTABLE PARITY CALCULATION
# ============================================================

def calculate_two_direction(
    future_bid,
    future_ask,
    ce_bid,
    ce_ask,
    pe_bid,
    pe_ask,
    strike
):

    # Direction 1:
    #
    # BUY CE at ASK
    # SELL PE at BID
    # SELL FUTURE at BID
    #
    # Edge =
    # Future Bid - CE Ask + PE Bid - Strike

    d1 = (
        future_bid
        - ce_ask
        + pe_bid
        - strike
    )

    # Direction 2:
    #
    # SELL CE at BID
    # BUY PE at ASK
    # BUY FUTURE at ASK
    #
    # Edge =
    # CE Bid - PE Ask - Future Ask + Strike

    d2 = (
        ce_bid
        - pe_ask
        - future_ask
        + strike
    )

    return d1, d2


# ============================================================
# STOCK PARITY SCAN
# ============================================================

def scan_stock_group(
    jwt,
    master,
    stocks
):

    expiry = stock_expiry(
        master
    )

    if expiry is None:
        return pd.DataFrame()

    futures = all_fno_futures(
        master,
        expiry
    )

    stocks = [
        s
        for s in stocks
        if s in futures
    ]

    if not stocks:
        return pd.DataFrame()

    omaps = option_maps(
        master,
        expiry,
        stocks
    )

    exchange_tokens = {
        "NFO": []
    }

    future_rows = {}

    for stock in stocks:

        fr = futures[stock]

        future_rows[
            stock
        ] = fr

        exchange_tokens[
            "NFO"
        ].append(
            str(
                fr["token"]
            )
        )

    # पहले futures quote
    future_quotes = full_quote_batch(
        jwt,
        exchange_tokens
    )

    # --------------------------------------------------------
    # अब केवल nearest strikes के option tokens
    # --------------------------------------------------------

    exchange_tokens = {
        "NFO": []
    }

    selected = {}

    for stock in stocks:

        fq = future_quotes.get(
            str(
                future_rows[stock]["token"]
            )
        )

        if not fq:
            continue

        future = fq.get(
            "ltp"
        )

        if future is None:
            continue

        omap = omaps.get(
            stock,
            {}
        )

        strikes = nearest_strikes(
            omap,
            future,
            STRIKES_EACH_SIDE
        )

        selected[
            stock
        ] = strikes

        for strike in strikes:

            for typ in [
                "CE",
                "PE"
            ]:

                row = omap.get(
                    (
                        strike,
                        typ
                    )
                )

                if row is not None:

                    exchange_tokens[
                        "NFO"
                    ].append(
                        str(
                            row["token"]
                        )
                    )

    option_quotes = full_quote_batch(
        jwt,
        exchange_tokens
    )

    rows = []

    for stock in stocks:

        fr = future_rows[
            stock
        ]

        future_token = str(
            fr["token"]
        )

        fq = future_quotes.get(
            future_token
        )

        if not fq:
            continue

        future = fq.get(
            "ltp"
        )

        future_bid = fq.get(
            "bid"
        )

        future_ask = fq.get(
            "ask"
        )

        if None in (
            future,
            future_bid,
            future_ask
        ):
            continue

        omap = omaps.get(
            stock,
            {}
        )

        lot = int(
            fr["lot_size"]
        )

        for strike in selected.get(
            stock,
            []
        ):

            ce = omap.get(
                (
                    strike,
                    "CE"
                )
            )

            pe = omap.get(
                (
                    strike,
                    "PE"
                )
            )

            if ce is None or pe is None:
                continue

            ceq = option_quotes.get(
                str(
                    ce["token"]
                )
            )

            peq = option_quotes.get(
                str(
                    pe["token"]
                )
            )

            if not ceq or not peq:
                continue

            ce_bid = ceq.get(
                "bid"
            )

            ce_ask = ceq.get(
                "ask"
            )

            pe_bid = peq.get(
                "bid"
            )

            pe_ask = peq.get(
                "ask"
            )

            if None in (
                ce_bid,
                ce_ask,
                pe_bid,
                pe_ask
            ):
                continue

            d1, d2 = calculate_two_direction(
                future_bid,
                future_ask,
                ce_bid,
                ce_ask,
                pe_bid,
                pe_ask,
                strike
            )

            # =================================================
            # DIRECTION 1
            # =================================================

            if d1 >= MIN_EDGE:

                rows.append({

                    "Stock": stock,

                    "Direction":
                        "BUY SYNTHETIC + SELL FUTURE",

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

                    "Edge/Unit":
                        round(
                            d1,
                            2
                        ),

                    "Edge × Lot":
                        round(
                            d1 * lot,
                            2
                        ),

                    "Lot Size":
                        lot,

                    "Margin":
                        None,

                    "ROM %":
                        None,

                    "CE Symbol":
                        ce["symbol"],

                    "PE Symbol":
                        pe["symbol"],

                    "Future Symbol":
                        fr["symbol"]
                })

            # =================================================
            # DIRECTION 2
            # =================================================

            if d2 >= MIN_EDGE:

                rows.append({

                    "Stock": stock,

                    "Direction":
                        "SELL SYNTHETIC + BUY FUTURE",

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

                    "Edge/Unit":
                        round(
                            d2,
                            2
                        ),

                    "Edge × Lot":
                        round(
                            d2 * lot,
                            2
                        ),

                    "Lot Size":
                        lot,

                    "Margin":
                        None,

                    "ROM %":
                        None,

                    "CE Symbol":
                        ce["symbol"],

                    "PE Symbol":
                        pe["symbol"],

                    "Future Symbol":
                        fr["symbol"]
                })

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    return result.sort_values(
        "Edge × Lot",
        ascending=False
    ).reset_index(
        drop=True
    )


# ============================================================
# INDEX SCANNER
# ============================================================

def find_index_name(
    master,
    label
):

    names = {
        "NIFTY": [
            "NIFTY"
        ],

        "BANKNIFTY": [
            "BANKNIFTY"
        ],

        "SENSEX": [
            "SENSEX"
        ]
    }

    for name in names.get(
        label,
        []
    ):

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


def scan_index(
    jwt,
    master,
    label
):

    name = find_index_name(
        master,
        label
    )

    if name is None:
        return pd.DataFrame()

    # FUTURE expiry
    expiry = nearest_expiry_for_instrument(
        master,
        "FUTIDX",
        name
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

    fr = futures.iloc[0]

    future_token = str(
        fr["token"]
    )

    fq = full_quote_batch(
        jwt,
        {
            "NFO": [
                future_token
            ]
        }
    )

    future_q = fq.get(
        future_token
    )

    if not future_q:
        return pd.DataFrame()

    future = future_q.get(
        "ltp"
    )

    future_bid = future_q.get(
        "bid"
    )

    future_ask = future_q.get(
        "ask"
    )

    if None in (
        future,
        future_bid,
        future_ask
    ):
        return pd.DataFrame()

    strikes = sorted(
        set(
            options[
                "strike_num"
            ]
            .dropna()
            .astype(float)
        )
    )

    strikes = sorted(
        strikes,
        key=lambda x:
            abs(
                x - future
            )
    )[
        :STRIKES_EACH_SIDE * 2 + 1
    ]

    selected = options[
        options[
            "strike_num"
        ].isin(strikes)
    ]

    tokens = (
        selected[
            "token"
        ]
        .astype(str)
        .tolist()
    )

    quotes = full_quote_batch(
        jwt,
        {
            "NFO": tokens
        }
    )

    rows = []

    for strike in strikes:

        ce = selected[
            (
                selected["strike_num"]
                == strike
            )
            &
            selected[
                "symbol"
            ].str.endswith("CE")
        ]

        pe = selected[
            (
                selected["strike_num"]
                == strike
            )
            &
            selected[
                "symbol"
            ].str.endswith("PE")
        ]

        if ce.empty or pe.empty:
            continue

        ce_row = ce.iloc[0]
        pe_row = pe.iloc[0]

        ce_q = quotes.get(
            str(
                ce_row["token"]
            )
        )

        pe_q = quotes.get(
            str(
                pe_row["token"]
            )
        )

        if not ce_q or not pe_q:
            continue

        ce_bid = ce_q.get("bid")
        ce_ask = ce_q.get("ask")

        pe_bid = pe_q.get("bid")
        pe_ask = pe_q.get("ask")

        if None in (
            ce_bid,
            ce_ask,
            pe_bid,
            pe_ask
        ):
            continue

        d1, d2 = calculate_two_direction(
            future_bid,
            future_ask,
            ce_bid,
            ce_ask,
            pe_bid,
            pe_ask,
            strike
        )

        for direction, edge in [
            (
                "BUY SYNTHETIC + SELL FUTURE",
                d1
            ),
            (
                "SELL SYNTHETIC + BUY FUTURE",
                d2
            )
        ]:

            if edge < MIN_EDGE:
                continue

            rows.append({

                "Index": label,

                "Direction":
                    direction,

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

                "Edge/Unit":
                    round(
                        edge,
                        2
                    ),

                "Edge × Contract":
                    round(
                        edge
                        * int(
                            fr["lot_size"]
                        ),
                        2
                    ),

                "Lot Size":
                    int(
                        fr["lot_size"]
                    ),

                "Margin":
                    None,

                "ROM %":
                    None,

                "CE Symbol":
                    ce_row["symbol"],

                "PE Symbol":
                    pe_row["symbol"],

                "Future Symbol":
                    fr["symbol"]
            })

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        return result

    return result.sort_values(
        "Edge × Contract",
        ascending=False
    ).reset_index(
        drop=True
    )


# ============================================================
# MARGIN
# ============================================================

def calculate_margin(
    jwt,
    row,
    master
):

    try:

        ce = master[
            master["symbol"]
            == row["CE Symbol"]
        ]

        pe = master[
            master["symbol"]
            == row["PE Symbol"]
        ]

        fut = master[
            master["symbol"]
            == row["Future Symbol"]
        ]

        if (
            ce.empty
            or pe.empty
            or fut.empty
        ):
            return None

        lot = int(
            row["Lot Size"]
        )

        direction = row[
            "Direction"
        ]

        if (
            direction
            == "BUY SYNTHETIC + SELL FUTURE"
        ):

            positions = [

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["CE Ask"],
                    "productType": "INTRADAY",
                    "token": str(
                        ce.iloc[0]["token"]
                    ),
                    "tradeType": "BUY",
                    "orderType": "LIMIT"
                },

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["PE Bid"],
                    "productType": "INTRADAY",
                    "token": str(
                        pe.iloc[0]["token"]
                    ),
                    "tradeType": "SELL",
                    "orderType": "LIMIT"
                },

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["Future Bid"],
                    "productType": "INTRADAY",
                    "token": str(
                        fut.iloc[0]["token"]
                    ),
                    "tradeType": "SELL",
                    "orderType": "LIMIT"
                }
            ]

        else:

            positions = [

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["CE Bid"],
                    "productType": "INTRADAY",
                    "token": str(
                        ce.iloc[0]["token"]
                    ),
                    "tradeType": "SELL",
                    "orderType": "LIMIT"
                },

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["PE Ask"],
                    "productType": "INTRADAY",
                    "token": str(
                        pe.iloc[0]["token"]
                    ),
                    "tradeType": "BUY",
                    "orderType": "LIMIT"
                },

                {
                    "exchange": "NFO",
                    "qty": lot,
                    "price": row["Future Ask"],
                    "productType": "INTRADAY",
                    "token": str(
                        fut.iloc[0]["token"]
                    ),
                    "tradeType": "BUY",
                    "orderType": "LIMIT"
                }
            ]

        r = requests.post(
            MARGIN_URL,
            json={
                "positions": positions
            },
            headers=auth_headers(jwt),
            timeout=20
        )

        data = r.json()

        if data.get("status") is not True:
            return None

        md = data.get(
            "data",
            {}
        )

        value = md.get(
            "totalMarginRequired"
        )

        if value is None:
            return None

        return float(value)

    except Exception:
        return None


def add_margins(
    jwt,
    result,
    master,
    max_rows=20
):

    if (
        result is None
        or result.empty
    ):
        return result

    result = result.copy()

    # केवल top opportunities पर margin
    limit = min(
        len(result),
        max_rows
    )

    margins = [
        None
        for _ in range(
            len(result)
        )
    ]

    for i in range(limit):

        margin = calculate_margin(
            jwt,
            result.iloc[i],
            master
        )

        margins[i] = margin

        time.sleep(
            0.12
        )

    result[
        "Margin"
    ] = margins

    result[
        "ROM %"
    ] = np.where(
        result["Margin"].notna()
        &
        (
            result["Margin"]
            > 0
        ),

        (
            result["Edge × Lot"]
            /
            result["Margin"]
        )
        * 100,

        np.nan
    )

    result[
        "ROM %"
    ] = result[
        "ROM %"
    ].round(2)

    return result


# ============================================================
# HIGH EDGE ALERT
# ============================================================

def generate_alerts(
    result
):

    if (
        result is None
        or result.empty
    ):
        return []

    alerts = []

    for _, row in result.iterrows():

        edge_lot = float(
            row.get(
                "Edge × Lot",
                0
            )
        )

        rom = row.get(
            "ROM %",
            np.nan
        )

        high = (
            edge_lot
            >= HIGH_EDGE_LOT
        )

        if not pd.isna(rom):
            high = (
                high
                or
                float(rom)
                >= HIGH_ROM
            )

        if not high:
            continue

        key = (
            str(
                row.get(
                    "Stock",
                    row.get(
                        "Index",
                        ""
                    )
                )
            )
            + "|"
            + str(
                row["Direction"]
            )
            + "|"
            + str(
                row["Strike"]
            )
            + "|"
            + str(
                row["Expiry"]
            )
        )

        alerts.append(
            (
                key,
                row.to_dict()
            )
        )

    return alerts


# ============================================================
# BACKGROUND SCAN WORKER
# ============================================================

background_lock = threading.Lock()

background_running = False


def background_worker():

    global background_running

    if background_running:
        return

    background_running = True

    try:

        while True:

            try:

                master = prepare_master(
                    download_master()
                )

                jwt = login()

                # --------------------------------------------
                # ALL FNO STOCKS
                # --------------------------------------------

                expiry = stock_expiry(
                    master
                )

                if expiry is not None:

                    futures = all_fno_futures(
                        master,
                        expiry
                    )

                    all_stocks = sorted(
                        futures.keys()
                    )

                    # Two groups
                    group_a = [
                        s
                        for s in all_stocks
                        if s[0] <= "M"
                    ]

                    group_b = [
                        s
                        for s in all_stocks
                        if s[0] > "M"
                    ]

                    results = []

                    if group_a:

                        a = scan_stock_group(
                            jwt,
                            master,
                            group_a
                        )

                        if not a.empty:
                            results.append(a)

                    if group_b:

                        b = scan_stock_group(
                            jwt,
                            master,
                            group_b
                        )

                        if not b.empty:
                            results.append(b)

                    # ----------------------------------------
                    # INDEXES
                    # ----------------------------------------

                    for index_name in [
                        "NIFTY",
                        "BANKNIFTY",
                        "SENSEX"
                    ]:

                        try:

                            idx = scan_index(
                                jwt,
                                master,
                                index_name
                            )

                            if not idx.empty:

                                results.append(
                                    idx
                                )

                        except Exception:
                            continue

                    if results:

                        combined = pd.concat(
                            results,
                            ignore_index=True
                        )

                        combined = combined.sort_values(
                            "Edge × Lot"
                            if
                            "Edge × Lot"
                            in combined.columns
                            else "Edge × Contract",
                            ascending=False
                        ).reset_index(
                            drop=True
                        )

                        # Margin only top opportunities
                        combined = add_margins(
                            jwt,
                            combined,
                            master,
                            20
                        )

                    else:

                        combined = pd.DataFrame()

                    # ----------------------------------------
                    # ALERTS
                    # ----------------------------------------

                    alerts = generate_alerts(
                        combined
                    )

                    for key, data in alerts:

                        # process-level alert memory
                        if key not in ALERT_KEYS:

                            ALERT_KEYS.add(
                                key
                            )

                            ALERT_QUEUE.append(
                                {
                                    "time":
                                        now_ist().strftime(
                                            "%H:%M:%S"
                                        ),
                                    "data":
                                        data
                                }
                            )

                            # WhatsApp disabled until
                            # credentials are supplied.
                            if WHATSAPP_ENABLED:
                                send_whatsapp_alert(
                                    data
                                )

                    # ----------------------------------------
                    # STORE
                    # ----------------------------------------

                    GLOBAL_RESULTS[
                        "result"
                    ] = combined

                    GLOBAL_RESULTS[
                        "last_scan"
                    ] = now_ist().strftime(
                        "%d-%m-%Y %H:%M:%S"
                    )

                    GLOBAL_RESULTS[
                        "status"
                    ] = "Running"

                else:

                    GLOBAL_RESULTS[
                        "status"
                    ] = "No F&O expiry found"

            except Exception as e:

                GLOBAL_RESULTS[
                    "status"
                ] = (
                    "Error: "
                    + str(e)
                )

            time.sleep(
                BACKGROUND_SECONDS
            )

    finally:

        background_running = False


# ============================================================
# PROCESS LEVEL STORAGE
# ============================================================

if "global_initialized" not in st.session_state:

    GLOBAL_RESULTS = {
        "result": pd.DataFrame(),
        "last_scan": "",
        "status": "Stopped"
    }

    ALERT_QUEUE = []

    ALERT_KEYS = set()

    st.session_state[
        "global_initialized"
    ] = True

else:

    if "GLOBAL_RESULTS" not in globals():

        GLOBAL_RESULTS = {
            "result": pd.DataFrame(),
            "last_scan": "",
            "status": "Stopped"
        }

    if "ALERT_QUEUE" not in globals():
        ALERT_QUEUE = []

    if "ALERT_KEYS" not in globals():
        ALERT_KEYS = set()


# ============================================================
# WHATSAPP FUNCTION
# ============================================================

def send_whatsapp_alert(
    data
):

    # --------------------------------------------------------
    # अभी intentionally disabled
    # --------------------------------------------------------
    #
    # Number/API credentials मिलने के बाद यहां
    # WhatsApp provider API लगाई जाएगी.
    #
    return False


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header(
    "⚙️ Scanner Settings"
)

MIN_EDGE = st.sidebar.number_input(
    "Minimum Edge / Unit",
    min_value=0.0,
    value=1.0,
    step=0.5
)

HIGH_EDGE_LOT = st.sidebar.number_input(
    "High Edge × Lot Alert",
    min_value=0.0,
    value=5000.0,
    step=1000.0
)

HIGH_ROM = st.sidebar.number_input(
    "High ROM % Alert",
    min_value=0.0,
    value=1.0,
    step=0.25
)

BACKGROUND_SECONDS = st.sidebar.number_input(
    "Background Scan Seconds",
    min_value=10,
    max_value=300,
    value=20,
    step=5
)

st.sidebar.divider()

st.sidebar.write(
    "📱 WhatsApp"
)

st.sidebar.info(
    "WhatsApp number अभी नहीं दिया गया है। "
    "इसलिए WhatsApp sending OFF है।"
)

# ============================================================
# BACKGROUND CONTROL
# ============================================================

st.divider()

st.header(
    "🔄 Background Parity Scanner"
)

c1, c2, c3 = st.columns(3)

with c1:

    if st.button(
        "▶️ START BACKGROUND",
        type="primary",
        use_container_width=True
    ):

        if not background_running:

            t = threading.Thread(
                target=background_worker,
                daemon=True
            )

            t.start()

            st.success(
                "Background parity scanner START हो गया।"
            )

        else:

            st.info(
                "Background scanner पहले से चल रहा है।"
            )

with c2:

    if st.button(
        "🔄 REFRESH RESULT",
        use_container_width=True
    ):

        st.rerun()

with c3:

    if st.button(
        "🧹 CLEAR ALERTS",
        use_container_width=True
    ):

        ALERT_QUEUE.clear()
        ALERT_KEYS.clear()

        st.success(
            "Alert history clear हो गई।"
        )


# ============================================================
# STATUS
# ============================================================

status = GLOBAL_RESULTS.get(
    "status",
    "Stopped"
)

last_scan = GLOBAL_RESULTS.get(
    "last_scan",
    ""
)

st.metric(
    "Background Status",
    status
)

if last_scan:

    st.caption(
        "Last background scan: "
        + last_scan
    )


# ============================================================
# BACKGROUND RESULT
# ============================================================

bg_result = GLOBAL_RESULTS.get(
    "result",
    pd.DataFrame()
)

st.header(
    "🚨 Live Parity Opportunities"
)

if (
    bg_result is None
    or bg_result.empty
):

    st.info(
        "अभी कोई qualifying parity opportunity नहीं मिली। "
        "Background scanner चलने दें।"
    )

else:

    st.success(
        f"{len(bg_result)} live opportunities मिलीं।"
    )

    st.dataframe(
        bg_result,
        use_container_width=True,
        hide_index=True,
        height=650
    )

    csv = bg_result.to_csv(
        index=False
    ).encode(
        "utf-8"
    )

    st.download_button(
        "⬇️ Download Live Parity CSV",
        data=csv,
        file_name="live_fno_parity.csv",
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# ALERT QUEUE
# ============================================================

st.divider()

st.header(
    "🚨 High Edge Alerts"
)

if not ALERT_QUEUE:

    st.info(
        "अभी कोई high-edge alert नहीं।"
    )

else:

    alert_rows = []

    for item in reversed(
        ALERT_QUEUE[-100:]
    ):

        d = item["data"]

        alert_rows.append({

            "Time":
                item["time"],

            "Stock / Index":
                d.get(
                    "Stock",
                    d.get(
                        "Index",
                        ""
                    )
                ),

            "Direction":
                d.get(
                    "Direction",
                    ""
                ),

            "Strike":
                d.get(
                    "Strike",
                    ""
                ),

            "Edge/Unit":
                d.get(
                    "Edge/Unit",
                    ""
                ),

            "Edge × Lot":
                d.get(
                    "Edge × Lot",
                    d.get(
                        "Edge × Contract",
                        ""
                    )
                ),

            "Margin":
                d.get(
                    "Margin",
                    ""
                ),

            "ROM %":
                d.get(
                    "ROM %",
                    ""
                )
        })

    st.dataframe(
        pd.DataFrame(
            alert_rows
        ),
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# MANUAL GROUP SCANNERS
# ============================================================

st.divider()

st.header(
    "⚡ Manual F&O Stock Scanners"
)

st.caption(
    "Background scanner के अलावा A–M और N–Z को "
    "अलग-अलग manually भी scan कर सकते हैं।"
)

master_manual = None

# ============================================================
# A-M
# ============================================================

col1, col2 = st.columns(2)

with col1:

    st.subheader(
        "🅰️ F&O Stocks A–M"
    )

    if st.button(
        "Scan A–M",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "A–M F&O stocks scan हो रहे हैं..."
            ):

                master_manual = prepare_master(
                    download_master()
                )

                jwt = login()

                expiry = stock_expiry(
                    master_manual
                )

                futures = all_fno_futures(
                    master_manual,
                    expiry
                )

                stocks = sorted([
                    s
                    for s in futures
                    if s[0] <= "M"
                ])

                result_am = scan_stock_group(
                    jwt,
                    master_manual,
                    stocks
                )

                result_am = add_margins(
                    jwt,
                    result_am,
                    master_manual,
                    20
                )

            st.session_state[
                "manual_am"
            ] = result_am

        except Exception as e:

            st.error(
                "A–M Error: "
                + str(e)
            )

with col2:

    st.subheader(
        "🅽 F&O Stocks N–Z"
    )

    if st.button(
        "Scan N–Z",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "N–Z F&O stocks scan हो रहे हैं..."
            ):

                master_manual = prepare_master(
                    download_master()
                )

                jwt = login()

                expiry = stock_expiry(
                    master_manual
                )

                futures = all_fno_futures(
                    master_manual,
                    expiry
                )

                stocks = sorted([
                    s
                    for s in futures
                    if s[0] > "M"
                ])

                result_nz = scan_stock_group(
                    jwt,
                    master_manual,
                    stocks
                )

                result_nz = add_margins(
                    jwt,
                    result_nz,
                    master_manual,
                    20
                )

            st.session_state[
                "manual_nz"
            ] = result_nz

        except Exception as e:

            st.error(
                "N–Z Error: "
                + str(e)
            )


if (
    "manual_am"
    in st.session_state
):

    st.subheader(
        "A–M Results"
    )

    st.dataframe(
        st.session_state[
            "manual_am"
        ],
        use_container_width=True,
        hide_index=True,
        height=500
    )


if (
    "manual_nz"
    in st.session_state
):

    st.subheader(
        "N–Z Results"
    )

    st.dataframe(
        st.session_state[
            "manual_nz"
        ],
        use_container_width=True,
        hide_index=True,
        height=500
    )


# ============================================================
# INDEX SCANNERS
# ============================================================

st.divider()

st.header(
    "📊 Index Put-Call Parity"
)

n1, n2, n3 = st.columns(3)

# ============================================================
# NIFTY
# ============================================================

with n1:

    st.subheader(
        "📈 NIFTY 50"
    )

    if st.button(
        "Scan NIFTY 50",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "NIFTY 50 parity..."
            ):

                m = prepare_master(
                    download_master()
                )

                j = login()

                r = scan_index(
                    j,
                    m,
                    "NIFTY"
                )

                r = add_margins(
                    j,
                    r,
                    m,
                    20
                )

            st.session_state[
                "nifty_index_result"
            ] = r

        except Exception as e:

            st.error(
                "NIFTY Error: "
                + str(e)
            )

# ============================================================
# BANKNIFTY
# ============================================================

with n2:

    st.subheader(
        "🏦 BANKNIFTY"
    )

    if st.button(
        "Scan BANKNIFTY",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "BANKNIFTY parity..."
            ):

                m = prepare_master(
                    download_master()
                )

                j = login()

                r = scan_index(
                    j,
                    m,
                    "BANKNIFTY"
                )

                r = add_margins(
                    j,
                    r,
                    m,
                    20
                )

            st.session_state[
                "bank_index_result"
            ] = r

        except Exception as e:

            st.error(
                "BANKNIFTY Error: "
                + str(e)
            )

# ============================================================
# SENSEX
# ============================================================

with n3:

    st.subheader(
        "📊 SENSEX"
    )

    if st.button(
        "Scan SENSEX",
        use_container_width=True
    ):

        try:

            with st.spinner(
                "SENSEX parity..."
            ):

                m = prepare_master(
                    download_master()
                )

                j = login()

                r = scan_index(
                    j,
                    m,
                    "SENSEX"
                )

                r = add_margins(
                    j,
                    r,
                    m,
                    20
                )

            st.session_state[
                "sensex_index_result"
            ] = r

        except Exception as e:

            st.error(
                "SENSEX Error: "
                + str(e)
            )


# ============================================================
# DISPLAY INDEX RESULTS
# ============================================================

if (
    "nifty_index_result"
    in st.session_state
):

    st.subheader(
        "NIFTY 50 Results"
    )

    st.dataframe(
        st.session_state[
            "nifty_index_result"
        ],
        use_container_width=True,
        hide_index=True
    )


if (
    "bank_index_result"
    in st.session_state
):

    st.subheader(
        "BANKNIFTY Results"
    )

    st.dataframe(
        st.session_state[
            "bank_index_result"
        ],
        use_container_width=True,
        hide_index=True
    )


if (
    "sensex_index_result"
    in st.session_state
):

    st.subheader(
        "SENSEX Results"
    )

    st.dataframe(
        st.session_state[
            "sensex_index_result"
        ],
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# AUTO REFRESH UI
# ============================================================

st.divider()

st.caption(
    "⚡ Background scanner अलग thread में चलता है। "
    "Page को बार-बार scan button दबाने की जरूरत नहीं।"
)

st.caption(
    "📌 Bid/Ask आधारित executable parity इस्तेमाल हो रही है।"
)

st.caption(
    "📌 High-edge opportunity पहले alert queue में आएगी; "
    "WhatsApp अभी credentials न होने के कारण OFF है।"
)
