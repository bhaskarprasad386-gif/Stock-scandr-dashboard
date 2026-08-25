import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
import io
import time
from datetime import datetime
from zoneinfo import ZoneInfo


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Market Scanner PRO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

IST = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://apiconnect.angelone.in"

st.title("📊 Market Scanner PRO")
st.caption(
    "Future > Spot + Liquid Put-Call Parity | Current & Next Month"
)


# ============================================================
# SESSION STATE
# ============================================================

DEFAULT_KEYS = [
    "jwt",
    "future_result",
    "stock_part_1",
    "stock_part_2",
    "stock_part_3",
    "stock_part_4",
    "stock_part_5",
    "nifty_result",
    "banknifty_result",
    "master"
]

for key in DEFAULT_KEYS:
    if key not in st.session_state:
        st.session_state[key] = None


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("⚙️ Scanner Settings")

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

    st.subheader("💧 Liquidity")

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
        max_value=30.0,
        value=3.0,
        step=0.5
    )

    st.subheader("💰 Margin")

    margin_percent = st.number_input(
        "Estimated Future Margin %",
        min_value=1.0,
        max_value=100.0,
        value=15.0,
        step=1.0
    )

    st.subheader("📊 Display")

    max_results = st.number_input(
        "Maximum Results",
        min_value=10,
        max_value=500,
        value=100,
        step=10
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
        "Bearer " + str(jwt)
    )

    return h


# ============================================================
# UTILITY
# ============================================================

def safe_float(value):

    try:

        if value is None:
            return None

        value = float(value)

        if np.isnan(value):
            return None

        return value

    except Exception:

        return None


def now_ist():

    return datetime.now(IST)


# ============================================================
# LOGIN
# ============================================================

def angel_login():

    if not API_KEY:
        raise Exception(
            "ANGEL_API_KEY Streamlit Secrets me nahi mila."
        )

    if not CLIENT_ID:
        raise Exception(
            "ANGEL_CLIENT_CODE Streamlit Secrets me nahi mila."
        )

    if not PASSWORD:
        raise Exception(
            "ANGEL_PASSWORD Streamlit Secrets me nahi mila."
        )

    if not TOTP_SECRET:
        raise Exception(
            "ANGEL_TOTP_SECRET Streamlit Secrets me nahi mila."
        )

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
            "JWT Token nahi mila."
        )

    return token


# ============================================================
# MASTER DOWNLOAD
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
            "Angel master empty hai."
        )

    return pd.DataFrame(data)


# ============================================================
# PREPARE MASTER
# ============================================================

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

    for col in required:

        if col not in df.columns:

            df[col] = ""

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
        )
        / 100
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

    tokens = [
        str(x)
        for x in tokens
        if str(x).strip()
    ]

    tokens = list(
        dict.fromkeys(tokens)
    )

    if not tokens:
        return {}

    url = (
        BASE_URL
        + "/rest/secure/angelbroking/"
          "market/v1/quote/"
    )

    result = {}

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

                bid = None
                ask = None

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
                        safe_float(
                            item.get("ltp")
                        ),

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


# ============================================================
# EXPIRIES
# ============================================================

def get_future_expiries(
    master,
    name
):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == name)
        &
        (
            master["instrument"]
            .isin(
                [
                    "FUTSTK",
                    "FUTIDX"
                ]
            )
        )
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"]
            >= today
        )
    ]

    if x.empty:

        return []

    return sorted(
        x["expiry_date"]
        .dropna()
        .unique()
    )


def get_stock_names(master):

    today = pd.Timestamp(
        now_ist().date()
    )

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"]
            >= today
        )
    ]

    return sorted(
        x["name"]
        .dropna()
        .unique()
    )


# ============================================================
# FUTURE MAP
# ============================================================

def get_future_contract(
    master,
    stock,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == stock)
        &
        (master["instrument"] == "FUTSTK")
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
# CASH TOKEN MAP
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
            row["symbol"]
            .replace("-EQ", "")
            .strip()
        )

        result[stock] = {
            "token":
                str(row["token"]),

            "symbol":
                row["symbol"]
        }

    return result


# ============================================================
# LIQUIDITY
# ============================================================

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


def is_liquid(
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

    sp = spread_percent(q)

    if sp is None:
        return False

    if sp > max_spread:
        return False

    return True


# ============================================================
# SIMPLE CHARGES
# ============================================================

def estimated_fno_charges(
    future_price,
    lot
):

    turnover = (
        future_price
        * lot
        * 2
    )

    brokerage = 40.0

    stt = (
        future_price
        * lot
        * 0.0002
    )

    exchange = (
        turnover
        * 0.0000183
    )

    sebi = (
        turnover
        * 0.000001
    )

    gst = (
        brokerage
        + exchange
        + sebi
    ) * 0.18

    return (
        brokerage
        + stt
        + exchange
        + sebi
        + gst
    )


# ============================================================
# FUTURE > SPOT
# ============================================================

def scan_future_spot_month(
    jwt,
    master,
    expiry,
    stocks
):

    cash_map = cash_token_map(
        master
    )

    contracts = {}

    for stock in stocks:

        if stock not in cash_map:
            continue

        contract = get_future_contract(
            master,
            stock,
            expiry
        )

        if contract is None:
            continue

        contracts[stock] = contract

    if not contracts:

        return pd.DataFrame()

    spot_tokens = [
        cash_map[s]["token"]
        for s in contracts
    ]

    future_tokens = [
        str(
            contracts[s]["token"]
        )
        for s in contracts
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

    for stock, contract in contracts.items():

        spot_token = cash_map[
            stock
        ]["token"]

        future_token = str(
            contract["token"]
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

        if (
            spot is None
            or future is None
        ):
            continue

        difference = (
            future - spot
        )

        lot = safe_float(
            contract["lot_size"]
        )

        if (
            lot is None
            or lot <= 0
        ):
            continue

        gross_profit = (
            difference
            * lot
        )

        charges = estimated_fno_charges(
            future,
            lot
        )

        net_estimate = (
            gross_profit
            - charges
        )

        margin = (
            future
            * lot
            * margin_percent
            / 100
        )

        rows.append({

            "Stock":
                stock,

            "Month":
                "Current"
                if expiry.month
                == now_ist().month
                else "Next",

            "Expiry":
                expiry.strftime(
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
                    difference,
                    2
                ),

            "Lot Size":
                int(lot),

            "Gross Profit / Lot":
                round(
                    gross_profit,
                    2
                ),

            "Estimated Charges":
                round(
                    charges,
                    2
                ),

            "Estimated Net":
                round(
                    net_estimate,
                    2
                ),

            "Estimated Margin":
                round(
                    margin,
                    2
                )
        })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

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


def scan_future_spot_both(
    jwt,
    master
):

    stocks = get_stock_names(
        master
    )

    all_rows = []

    expiry_map = {}

    for stock in stocks:

        expiries = get_future_expiries(
            master,
            stock
        )

        if len(expiries) >= 2:

            expiry_map[stock] = (
                expiries[0],
                expiries[1]
            )

    if not expiry_map:

        return pd.DataFrame()

    # Scan separately for each month
    current_expiry_stocks = []
    next_expiry_stocks = []

    current_expiries = {}

    next_expiries = {}

    for stock, pair in expiry_map.items():

        current_expiries[stock] = pair[0]
        next_expiries[stock] = pair[1]

    # Current
    grouped_current = {}

    for stock, expiry in current_expiries.items():

        grouped_current.setdefault(
            expiry,
            []
        ).append(stock)

    for expiry, names in grouped_current.items():

        result = scan_future_spot_month(
            jwt,
            master,
            expiry,
            names
        )

        if not result.empty:

            all_rows.append(
                result
            )

    # Next
    grouped_next = {}

    for stock, expiry in next_expiries.items():

        grouped_next.setdefault(
            expiry,
            []
        ).append(stock)

    for expiry, names in grouped_next.items():

        result = scan_future_spot_month(
            jwt,
            master,
            expiry,
            names
        )

        if not result.empty:

            result["Month"] = "Next"

            all_rows.append(
                result
            )

    if not all_rows:

        return pd.DataFrame()

    result = pd.concat(
        all_rows,
        ignore_index=True
    )

    result = result.sort_values(
        "Gross Profit / Lot",
        ascending=False
    ).reset_index(
        drop=True
    )

    result["Rank"] = np.arange(
        1,
        len(result) + 1
    )

    cols = [
        "Rank"
    ] + [
        c for c in result.columns
        if c != "Rank"
    ]

    return result[
        cols
    ]


# ============================================================
# OPTION MAP
# ============================================================

def option_contracts(
    master,
    name,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == name)
        &
        (master["instrument"].isin(
            [
                "OPTSTK",
                "OPTIDX"
            ]
        ))
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

            typ = "CE"

        elif symbol.endswith("PE"):

            typ = "PE"

        else:

            continue

        key = (
            round(
                float(strike),
                2
            ),
            typ
        )

        result[key] = {
            "token":
                str(row["token"]),

            "symbol":
                symbol,

            "lot":
                safe_float(
                    row["lot_size"]
                )
        }

    return result


# ============================================================
# PARITY ONE MONTH
# ============================================================

def scan_parity_month(
    jwt,
    master,
    name,
    expiry,
    strike_count,
    threshold
):

    future_instrument = (
        "FUTIDX"
        if name in [
            "NIFTY",
            "BANKNIFTY"
        ]
        else "FUTSTK"
    )

    futures = master[
        (master["exchange"] == "NFO")
        &
        (master["name"] == name)
        &
        (
            master["instrument"]
            == future_instrument
        )
        &
        (
            master["expiry_date"]
            == expiry
        )
    ]

    if futures.empty:

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

    if (
        future is None
        or future_bid is None
        or future_ask is None
    ):
        return pd.DataFrame()

    if (
        future_bid <= 0
        or future_ask <= 0
        or future_ask < future_bid
    ):
        return pd.DataFrame()

    contracts = option_contracts(
        master,
        name,
        expiry
    )

    if not contracts:

        return pd.DataFrame()

    all_strikes = sorted(
        set(
            key[0]
            for key in contracts
        ),
        key=lambda x:
            abs(
                x - future
            )
    )

    # ========================================================
    # IMPORTANT:
    # Liquid strike criteria remains active.
    # We first select strikes around future, then require
    # BOTH CE and PE to be liquid.
    # ========================================================

    strikes = all_strikes[
        :int(strike_count)
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

        # ====================================================
        # LIQUID CE + PE
        # ====================================================

        if not is_liquid(
            ceq,
            min_option_volume,
            min_option_oi,
            max_spread_percent
        ):
            continue

        if not is_liquid(
            peq,
            min_option_volume,
            min_option_oi,
            max_spread_percent
        ):
            continue

        # ====================================================
        # EXECUTABLE PARITY
        # ====================================================

        positive_edge = (
            ceq["bid"]
            - peq["ask"]
            - (
                future_ask
                - strike
            )
        )

        negative_edge = (
            ceq["ask"]
            - peq["bid"]
            - (
                future_bid
                - strike
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

        if abs(
            best_edge
        ) < threshold:

            continue

        lot = safe_float(
            future_row["lot_size"]
        )

        if (
            lot is None
            or lot <= 0
        ):
            continue

        gross_profit = (
            abs(best_edge)
            * lot
        )

        estimated_margin = (
            future
            * lot
            * margin_percent
            / 100
        )

        rows.append({

            "Name":
                name,

            "Month":
                "Current"
                if expiry
                == min(
                    get_future_expiries(
                        master,
                        name
                    )
                    or [expiry]
                )
                else "Next",

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
                strike,

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
                ceq.get("volume"),

            "PE Volume":
                peq.get("volume"),

            "CE OI":
                ceq.get("oi"),

            "PE OI":
                peq.get("oi"),

            "Trade":
                trade,

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
                int(lot),

            "Gross Profit / Trade":
                round(
                    gross_profit,
                    2
                ),

            "Estimated Final Margin":
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
            "Gross Profit / Trade",
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
# STOCK PARITY PART
# ============================================================

def scan_stock_part(
    jwt,
    master,
    stocks
):

    all_rows = []

    for stock in stocks:

        expiries = get_future_expiries(
            master,
            stock
        )

        if len(expiries) < 2:

            continue

        current_expiry = expiries[0]
        next_expiry = expiries[1]

        current_result = scan_parity_month(
            jwt,
            master,
            stock,
            current_expiry,
            parity_strikes,
            parity_threshold
        )

        if not current_result.empty:

            all_rows.append(
                current_result
            )

        next_result = scan_parity_month(
            jwt,
            master,
            stock,
            next_expiry,
            parity_strikes,
            parity_threshold
        )

        if not next_result.empty:

            all_rows.append(
                next_result
            )

    if not all_rows:

        return pd.DataFrame()

    result = pd.concat(
        all_rows,
        ignore_index=True
    )

    result = result.sort_values(
        [
            "Gross Profit / Trade",
            "Absolute Edge"
        ],
        ascending=[
            False,
            False
        ]
    ).head(
        int(max_results)
    ).reset_index(
        drop=True
    )

    result["Rank"] = np.arange(
        1,
        len(result) + 1
    )

    cols = [
        "Rank"
    ] + [
        c for c in result.columns
        if c != "Rank"
    ]

    return result[
        cols
    ]


# ============================================================
# INDEX PARITY
# ============================================================

def scan_index_both(
    jwt,
    master,
    name
):

    expiries = get_future_expiries(
        master,
        name
    )

    if len(expiries) < 2:

        return pd.DataFrame()

    all_rows = []

    for expiry in expiries[:2]:

        result = scan_parity_month(
            jwt,
            master,
            name,
            expiry,
            parity_strikes,
            parity_threshold
        )

        if not result.empty:

            all_rows.append(
                result
            )

    if not all_rows:

        return pd.DataFrame()

    result = pd.concat(
        all_rows,
        ignore_index=True
    )

    result = result.sort_values(
        [
            "Gross Profit / Trade",
            "Absolute Edge"
        ],
        ascending=[
            False,
            False
        ]
    ).reset_index(
        drop=True
    )

    result["Rank"] = np.arange(
        1,
        len(result) + 1
    )

    cols = [
        "Rank"
    ] + [
        c for c in result.columns
        if c != "Rank"
    ]

    return result[
        cols
    ]


# ============================================================
# EXCEL EXPORT
# ============================================================

def excel_bytes(
    dataframe
):

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        dataframe.to_excel(
            writer,
            index=False,
            sheet_name="Scanner_Result"
        )

    return output.getvalue()


# ============================================================
# SHOW RESULT
# ============================================================

def show_result(
    result,
    filename,
    key_prefix
):

    if (
        result is None
        or result.empty
    ):

        st.info(
            "कोई qualifying liquid result नहीं मिला।"
        )

        return

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        height=550
    )

    csv_data = result.to_csv(
        index=False
    ).encode(
        "utf-8"
    )

    st.download_button(
        "⬇️ CSV Download",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        key=key_prefix + "_csv",
        use_container_width=True
    )

    try:

        xlsx_data = excel_bytes(
            result
        )

        st.download_button(
            "⬇️ Excel Download / Editable",
            data=xlsx_data,
            file_name=filename.replace(
                ".csv",
                ".xlsx"
            ),
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            key=key_prefix + "_xlsx",
            use_container_width=True
        )

    except Exception as e:

        st.warning(
            "Excel export उपलब्ध नहीं हुआ: "
            + str(e)
        )


# ============================================================
# CONNECT ANGEL
# ============================================================

st.divider()

st.header("🔐 Angel One Connection")

if st.button(
    "🔐 Connect Angel One",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Angel One login..."
        ):

            st.session_state[
                "jwt"
            ] = angel_login()

        st.success(
            "✅ Angel One Connected"
        )

    except Exception as e:

        st.error(
            "❌ Login Error: "
            + str(e)
        )


jwt = st.session_state.get(
    "jwt"
)


# ============================================================
# MASTER LOAD ONLY AFTER LOGIN
# ============================================================

if jwt:

    if st.session_state.get(
        "master"
    ) is None:

        try:

            with st.spinner(
                "Angel master loading..."
            ):

                raw_master = download_master()

                st.session_state[
                    "master"
                ] = prepare_master(
                    raw_master
                )

            st.success(
                "✅ Master loaded"
            )

        except Exception as e:

            st.error(
                "❌ Master Error: "
                + str(e)
            )

            st.stop()

master = st.session_state.get(
    "master"
)


# ============================================================
# STOP IF NOT CONNECTED
# ============================================================

if not jwt or master is None:

    st.info(
        "ऊपर से पहले Angel One Connect करें।"
    )

    st.markdown(
        """
### इस version में startup पर API call नहीं होती

इसलिए Streamlit app पहले खुलेगा और उसके बाद ही
Angel One connection/master data load होगा।
"""
    )

    st.stop()


# ============================================================
# FUTURE > SPOT
# ============================================================

st.divider()

st.header(
    "1️⃣ ⚡ Future > Spot — Current + Next Month"
)

st.caption(
    "दोनों expiry का Spot, Future, Lot Size, "
    "Difference और Gross Profit. ज्यादा Gross Profit ऊपर."
)

if st.button(
    "🚀 Scan Current + Next Month Future > Spot",
    key="future_scan",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Current + Next Future > Spot scanning..."
        ):

            result = scan_future_spot_both(
                jwt,
                master
            )

        st.session_state[
            "future_result"
        ] = result

    except Exception as e:

        st.error(
            "Future Scanner Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "future_result"
    ),
    "future_spot_current_next.csv",
    "future"
)


# ============================================================
# STOCK PARTS
# ============================================================

stock_names = get_stock_names(
    master
)

stock_parts = np.array_split(
    stock_names,
    5
)


# ============================================================
# PART 1
# ============================================================

st.divider()

st.header(
    "2️⃣ ⚖️ Stock Parity — Part 1 / 5"
)

if st.button(
    "🚀 Run Stock Parity Part 1",
    key="part1",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Part 1 current + next month liquid parity..."
        ):

            result = scan_stock_part(
                jwt,
                master,
                list(stock_parts[0])
            )

        st.session_state[
            "stock_part_1"
        ] = result

    except Exception as e:

        st.error(
            "Part 1 Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "stock_part_1"
    ),
    "stock_parity_part_1.csv",
    "part1"
)


# ============================================================
# PART 2
# ============================================================

st.divider()

st.header(
    "3️⃣ ⚖️ Stock Parity — Part 2 / 5"
)

if st.button(
    "🚀 Run Stock Parity Part 2",
    key="part2",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Part 2 scanning..."
        ):

            result = scan_stock_part(
                jwt,
                master,
                list(stock_parts[1])
            )

        st.session_state[
            "stock_part_2"
        ] = result

    except Exception as e:

        st.error(
            "Part 2 Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "stock_part_2"
    ),
    "stock_parity_part_2.csv",
    "part2"
)


# ============================================================
# PART 3
# ============================================================

st.divider()

st.header(
    "4️⃣ ⚖️ Stock Parity — Part 3 / 5"
)

if st.button(
    "🚀 Run Stock Parity Part 3",
    key="part3",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Part 3 scanning..."
        ):

            result = scan_stock_part(
                jwt,
                master,
                list(stock_parts[2])
            )

        st.session_state[
            "stock_part_3"
        ] = result

    except Exception as e:

        st.error(
            "Part 3 Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "stock_part_3"
    ),
    "stock_parity_part_3.csv",
    "part3"
)


# ============================================================
# PART 4
# ============================================================

st.divider()

st.header(
    "5️⃣ ⚖️ Stock Parity — Part 4 / 5"
)

if st.button(
    "🚀 Run Stock Parity Part 4",
    key="part4",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Part 4 scanning..."
        ):

            result = scan_stock_part(
                jwt,
                master,
                list(stock_parts[3])
            )

        st.session_state[
            "stock_part_4"
        ] = result

    except Exception as e:

        st.error(
            "Part 4 Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "stock_part_4"
    ),
    "stock_parity_part_4.csv",
    "part4"
)


# ============================================================
# PART 5
# ============================================================

st.divider()

st.header(
    "6️⃣ ⚖️ Stock Parity — Part 5 / 5"
)

if st.button(
    "🚀 Run Stock Parity Part 5",
    key="part5",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Part 5 scanning..."
        ):

            result = scan_stock_part(
                jwt,
                master,
                list(stock_parts[4])
            )

        st.session_state[
            "stock_part_5"
        ] = result

    except Exception as e:

        st.error(
            "Part 5 Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "stock_part_5"
    ),
    "stock_parity_part_5.csv",
    "part5"
)


# ============================================================
# NIFTY
# ============================================================

st.divider()

st.header(
    "7️⃣ 📊 NIFTY — Current + Next Month Liquid Parity"
)

if st.button(
    "🚀 Scan NIFTY",
    key="nifty_scan",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "NIFTY current + next month liquid parity..."
        ):

            result = scan_index_both(
                jwt,
                master,
                "NIFTY"
            )

        st.session_state[
            "nifty_result"
        ] = result

    except Exception as e:

        st.error(
            "NIFTY Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "nifty_result"
    ),
    "nifty_current_next_parity.csv",
    "nifty"
)


# ============================================================
# BANKNIFTY
# ============================================================

st.divider()

st.header(
    "8️⃣ 🏦 BANKNIFTY — Current + Next Month Liquid Parity"
)

if st.button(
    "🚀 Scan BANKNIFTY",
    key="bank_scan",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "BANKNIFTY current + next month liquid parity..."
        ):

            result = scan_index_both(
                jwt,
                master,
                "BANKNIFTY"
            )

        st.session_state[
            "banknifty_result"
        ] = result

    except Exception as e:

        st.error(
            "BANKNIFTY Error: "
            + str(e)
        )


show_result(
    st.session_state.get(
        "banknifty_result"
    ),
    "banknifty_current_next_parity.csv",
    "banknifty"
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

- Current month Future
- Next month Future
- Spot price
- Future price
- Future − Spot
- Lot size
- **Gross Profit / Lot**
- Estimated charges
- Estimated net
- Estimated margin
- Highest gross-profit opportunity ऊपर

### ⚖️ Stock / Index Put-Call Parity

**Liquid-strike criteria हटाया नहीं गया है।**

किसी strike को result में आने के लिए:

- CE Bid मौजूद
- CE Ask मौजूद
- PE Bid मौजूद
- PE Ask मौजूद
- CE minimum volume
- PE minimum volume
- CE minimum OI
- PE minimum OI
- CE maximum spread
- PE maximum spread
- Future Bid मौजूद
- Future Ask मौजूद
- Invalid / zero quote reject

जरूरी है।

इसके बाद **executable Bid/Ask prices** से edge निकाला जाता है।

### 📅 दो expiry

हर stock/index में:

- Current Month
- Next Month

दोनों अलग-अलग scan होंगे।

### 💰 Gross Profit

`Executable Edge × Lot Size`

से gross profit/trade निकलेगा।

### 🏦 Estimated Margin

Future price × lot size × configured margin %

से estimated final margin दिखाया जाएगा।

### 📥 Excel

हर result को Excel में export किया जा सकता है।
Excel file में result editable रहेगा।

### ❌ Removed

इस version में:

- NSE rollover scanner नहीं
- NSE rollover backtest नहीं
- NSE Bhavcopy download नहीं
- पुराने rollover calculations नहीं
"""
)

st.caption(
    "📡 Live data: Angel One SmartAPI"
)

st.caption(
    "⚠️ Margin/charges estimates हैं। Actual broker RMS "
    "margin और final charges अलग हो सकते हैं।"
)
