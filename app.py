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
    page_title="Fast F&O + RSI + Put Call Parity Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Fast & Furious Market Scanner")

# ============================================================
# SECRETS
# ============================================================

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    st.error("Angel One की सभी secrets नहीं मिलीं।")
    st.stop()

BASE_URL = "https://apiconnect.angelone.in"

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

IST = ZoneInfo("Asia/Kolkata")


# ============================================================
# LOGIN
# ============================================================

@st.cache_data(ttl=300)
def get_login_token():

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

    return pd.DataFrame(r.json())


# ============================================================
# MASTER PREPARATION
# ============================================================

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

    df["strike_num"] = pd.to_numeric(
        df["strike"],
        errors="coerce"
    ) / 100

    df["lot_size"] = pd.to_numeric(
        df["lotsize"],
        errors="coerce"
    )

    return df


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
# ANGEL HEADERS
# ============================================================

def auth_headers(jwt):

    h = BASE_HEADERS.copy()

    h["Authorization"] = (
        "Bearer " + jwt
    )

    return h


# ============================================================
# BATCH LTP
# ============================================================

def get_batch_ltp(
    jwt,
    exchange,
    tokens
):

    if not tokens:
        return {}

    prices = {}

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "market/v1/quote/"
    )

    headers = auth_headers(jwt)

    for start in range(
        0,
        len(tokens),
        50
    ):

        batch = tokens[
            start:start + 50
        ]

        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [
                    str(x)
                    for x in batch
                ]
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

            if data.get("status") is True:

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

                    ltp = item.get("ltp")

                    if token and ltp is not None:

                        prices[token] = float(
                            ltp
                        )

        except Exception:
            continue

    return prices


# ============================================================
# 20 SMA
# ============================================================

def calculate_sma20(df):

    if len(df) < 20:
        return None

    return float(
        df["close"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )


def sma20_near(price, sma20):

    if sma20 is None or sma20 <= 0:
        return "NO"

    distance = (
        abs(price - sma20)
        / sma20
    ) * 100

    return (
        "YES"
        if distance <= 1
        else "NO"
    )


# ============================================================
# HISTORICAL DATA
# ============================================================

def get_historical(
    jwt,
    token,
    interval="ONE_DAY",
    days=150
):

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "historical/v1/getCandleData"
    )

    end = datetime.now(IST)

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

        for c in [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]:

            df[c] = pd.to_numeric(
                df[c],
                errors="coerce"
            )

        df = df.dropna()

        return df.sort_values(
            "datetime"
        ).reset_index(drop=True)

    except Exception:

        return pd.DataFrame()


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
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

    return 100 - (
        100 / (1 + rs)
    )


# ============================================================
# OBV
# ============================================================

def calculate_obv(df):

    direction = np.sign(
        df["close"].diff()
    ).fillna(0)

    return (
        direction *
        df["volume"]
    ).cumsum()


def is_rising(
    series,
    lookback=6
):

    s = series.dropna()

    if len(s) < lookback:
        return False

    r = s.iloc[-lookback:]

    overall = (
        r.iloc[-1] >
        r.iloc[0]
    )

    count = (
        r.diff()
        .dropna()
        .gt(0)
        .sum()
    )

    return (
        overall
        and count >= 3
    )


# ============================================================
# PRICE STRUCTURE
# NO FIXED 4% / 8% LIMIT
# ============================================================

def price_structure(df):

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

    # केवल यह देखेंगे कि पहले high था
    # और उसके बाद price lower zone में आया
    return (
        recent_low <
        previous_high
    )


# ============================================================
# RSI SPECIAL TIMING
# ============================================================

def rsi_special_timing(df):

    x = df.copy()

    if len(x) < 25:
        return "Not Enough Data"

    x["RSI"] = calculate_rsi(
        x["close"]
    )

    sideways_start = None

    # कोई fixed percentage range नहीं
    for window in [
        6, 7, 8, 9, 10, 12
    ]:

        if len(x) < window + 5:
            continue

        recent = x.iloc[-window:]

        # Sideways का practical structure:
        # लगातार बहुत बड़ा directional movement नहीं
        changes = (
            recent["close"]
            .pct_change()
            .abs()
        )

        if (
            changes.dropna()
            .max()
            <= 0.04
        ):

            sideways_start = (
                len(x) - window
            )

            break

    if sideways_start is None:
        return "Sideways Start Not Clear"

    before = x[
        "RSI"
    ].iloc[
        max(
            0,
            sideways_start - 6
        ):
        sideways_start
    ]

    after = x[
        "RSI"
    ].iloc[
        sideways_start:
    ]

    before_rising = (
        len(before) >= 4
        and
        is_rising(
            before,
            min(5, len(before))
        )
    )

    after_rising = (
        len(after) >= 4
        and
        is_rising(
            after,
            min(6, len(after))
        )
    )

    if (
        before_rising
        and after_rising
    ):

        return "⭐ RSI Rising Before Sideways"

    if after_rising:

        return "⚡ RSI Rising After Sideways"

    return "RSI Rising नहीं"


# ============================================================
# NIFTY 50 TOKEN MAP
# ============================================================

def nifty50_token_map(master):

    cash = master[
        (master["exchange"] == "NSE")
        &
        master["symbol"].str.endswith("-EQ")
    ].copy()

    result = {}

    for _, row in cash.iterrows():

        stock = (
            row["symbol"]
            .replace("-EQ", "")
            .strip()
        )

        if stock in NIFTY_50:

            result[stock] = {
                "symbol": row["symbol"],
                "token": row["token"]
            }

    return result


# ============================================================
# NIFTY 50 RSI SCANNER
# ============================================================

def scan_rsi_scanner(
    jwt,
    token_map
):

    rows = []

    for stock, info in token_map.items():

        df = get_historical(
            jwt,
            info["token"],
            "ONE_DAY",
            180
        )

        if df.empty or len(df) < 30:
            continue

        if not price_structure(df):
            continue

        df["RSI"] = calculate_rsi(
            df["close"]
        )

        df["OBV"] = calculate_obv(
            df
        )

        rsi_yes = is_rising(
            df["RSI"],
            6
        )

        obv_yes = is_rising(
            df["OBV"],
            6
        )

        if not rsi_yes:
            continue

        price = float(
            df["close"].iloc[-1]
        )

        sma20 = calculate_sma20(
            df
        )

        rows.append({

            "Stock": stock,

            "Price": round(
                price,
                2
            ),

            "20 SMA": (
                round(sma20, 2)
                if sma20
                else None
            ),

            "20 SMA Near 1%":
                sma20_near(
                    price,
                    sma20
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

            "RSI Special":
                rsi_special_timing(
                    df
                ),

            "Price Phase":
                "Fall → Sideways"
        })

    result = pd.DataFrame(rows)

    if not result.empty:

        result = result.reset_index(
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
# CURRENT MONTH EXPIRY
# ============================================================

def current_month_expiry(
    master
):

    today = pd.Timestamp(
        datetime.now(IST).date()
    )

    options = master[
        (master["exchange"] == "NFO")
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] >= today
        )
    ].copy()

    if options.empty:
        return None

    month = today.month
    year = today.year

    same_month = options[
        (options["expiry_date"].dt.month == month)
        &
        (options["expiry_date"].dt.year == year)
    ]

    if same_month.empty:
        return options[
            "expiry_date"
        ].min()

    return same_month[
        "expiry_date"
    ].min()


# ============================================================
# FUTURE CONTRACT MAP
# ============================================================

def future_map(
    master,
    expiry
):

    if expiry is None:
        return {}

    f = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] == expiry
        )
    ].copy()

    result = {}

    for stock in NIFTY_50:

        x = f[
            (
                f["name"] == stock
            )
            |
            (
                f["symbol"].str.startswith(
                    stock + "FUT"
                )
            )
        ]

        if x.empty:
            continue

        row = x.iloc[0]

        result[stock] = {
            "token": str(row["token"]),
            "symbol": row["symbol"]
        }

    return result


# ============================================================
# NSE OPTION CHAIN FALLBACK
# ============================================================

@st.cache_data(ttl=30)
def nse_option_chain(symbol):

    session = requests.Session()

    headers = {
        "User-Agent":
            "Mozilla/5.0 (Linux; Android 10) "
            "AppleWebKit/537.36 "
            "Chrome/151.0 Mobile Safari/537.36",

        "Accept":
            "application/json,text/plain,*/*",

        "Referer":
            "https://www.nseindia.com/"
    }

    try:

        session.get(
            "https://www.nseindia.com/",
            headers=headers,
            timeout=10
        )

        url = (
            "https://www.nseindia.com/"
            "api/option-chain-equities"
            "?symbol="
            + symbol
        )

        r = session.get(
            url,
            headers=headers,
            timeout=15
        )

        if r.status_code != 200:
            return {}

        return r.json()

    except Exception:

        return {}


# ============================================================
# ANGEL OPTION CONTRACT MAP
# ============================================================

def angel_option_map(
    master,
    stock,
    expiry
):

    x = master[
        (master["exchange"] == "NFO")
        &
        (master["expiry_date"] == expiry)
        &
        (master["name"] == stock)
        &
        (
            master["instrument"]
            == "OPTSTK"
        )
    ].copy()

    if x.empty:
        return {}

    result = {}

    for _, row in x.iterrows():

        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        option_type = str(
            row["symbol"]
        )[-2:]

        if option_type not in [
            "CE",
            "PE"
        ]:
            continue

        key = (
            round(float(strike), 2),
            option_type
        )

        result[key] = {
            "token": str(
                row["token"]
            ),
            "symbol": row["symbol"]
        }

    return result


# ============================================================
# GET ANGEL OPTION PRICES
# ============================================================

def get_option_prices(
    jwt,
    contracts
):

    tokens = [
        x["token"]
        for x in contracts.values()
    ]

    if not tokens:
        return {}

    return get_batch_ltp(
        jwt,
        "NFO",
        tokens
    )


# ============================================================
# NSE FALLBACK PRICE
# ============================================================

def get_nse_ce_pe(
    chain,
    strike,
    expiry_date
):

    if not chain:
        return None, None

    records = (
        chain
        .get("records", {})
        .get("data", [])
    )

    target_expiry = expiry_date.strftime(
        "%d-%b-%Y"
    ).upper()

    ce = None
    pe = None

    for row in records:

        if float(
            row.get("strikePrice", -1)
        ) != float(strike):

            continue

        exp = str(
            row.get("expiryDate", "")
        ).upper()

        if exp != target_expiry:
            continue

        if "CE" in row:

            ce = row["CE"].get(
                "lastPrice"
            )

        if "PE" in row:

            pe = row["PE"].get(
                "lastPrice"
            )

        break

    return ce, pe


# ============================================================
# PUT CALL PARITY SCANNER
# ============================================================

def scan_put_call_parity(
    jwt,
    master
):

    expiry = current_month_expiry(
        master
    )

    if expiry is None:

        return pd.DataFrame()

    fmap = future_map(
        master,
        expiry
    )

    if not fmap:
        return pd.DataFrame()

    future_tokens = [
        x["token"]
        for x in fmap.values()
    ]

    future_prices = get_batch_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    rows = []

    for stock in NIFTY_50:

        if stock not in fmap:
            continue

        ftoken = fmap[stock]["token"]

        future = future_prices.get(
            ftoken
        )

        if future is None:
            continue

        # ----------------------------------------------------
        # ANGEL CONTRACTS
        # ----------------------------------------------------

        contracts = angel_option_map(
            master,
            stock,
            expiry
        )

        if not contracts:
            continue

        available_strikes = sorted(
            set(
                strike
                for strike, typ
                in contracts.keys()
            )
        )

        if not available_strikes:
            continue

        # 10 nearest strikes
        nearest = sorted(
            available_strikes,
            key=lambda x:
                abs(x - future)
        )[:10]

        # ----------------------------------------------------
        # ANGEL CE/PE LTP
        # ----------------------------------------------------

        prices = get_option_prices(
            jwt,
            {
                k: contracts[k]
                for k in contracts
                if k[0] in nearest
            }
        )

        # ----------------------------------------------------
        # NSE FALLBACK
        # ----------------------------------------------------

        chain = None

        for strike in nearest:

            ce_contract = contracts.get(
                (strike, "CE")
            )

            pe_contract = contracts.get(
                (strike, "PE")
            )

            ce = None
            pe = None
            source = "Angel"

            if ce_contract:

                ce = prices.get(
                    ce_contract["token"]
                )

            if pe_contract:

                pe = prices.get(
                    pe_contract["token"]
                )

            # अगर Angel से कोई एक/both missing
            if ce is None or pe is None:

                if chain is None:

                    chain = nse_option_chain(
                        stock
                    )

                nce, npe = get_nse_ce_pe(
                    chain,
                    strike,
                    expiry
                )

                if ce is None:
                    ce = (
                        float(nce)
                        if nce is not None
                        else None
                    )

                if pe is None:
                    pe = (
                        float(npe)
                        if npe is not None
                        else None
                    )

                if ce is not None and pe is not None:
                    source = "Angel + NSE"
                else:
                    source = "Unavailable"

            if ce is None or pe is None:
                continue

            # ------------------------------------------------
            # PUT-CALL PARITY
            #
            # C - P = F - K
            #
            # Residual:
            # C - P - (F - K)
            # ------------------------------------------------

            parity = (
                ce
                - pe
                - (
                    future
                    - strike
                )
            )

            abs_difference = abs(
                parity
            )

            # केवल > 5
            if abs_difference <= 5:
                continue

            rows.append({

                "Stock": stock,

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

                "CE":
                    round(
                        ce,
                        2
                    ),

                "PE":
                    round(
                        pe,
                        2
                    ),

                "CE − PE":
                    round(
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
                        abs_difference,
                        2
                    ),

                "Data Source":
                    source
            })

    result = pd.DataFrame(
        rows
    )

    if not result.empty:

        result = result.sort_values(
            "Absolute Difference",
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
# F&O FUTURE > SPOT
# ============================================================

def scan_future_spot(
    jwt,
    master
):

    today = pd.Timestamp(
        datetime.now(IST).date()
    )

    futures = master[
        (master["exchange"] == "NFO")
        &
        (master["instrument"] == "FUTSTK")
        &
        master["expiry_date"].notna()
        &
        (
            master["expiry_date"] >= today
        )
    ].copy()

    if futures.empty:
        return pd.DataFrame()

    expiry = futures[
        "expiry_date"
    ].min()

    futures = futures[
        futures["expiry_date"] == expiry
    ]

    spot_map = nifty50_token_map(
        master
    )

    rows = []

    future_tokens = []

    temp = {}

    for stock in NIFTY_50:

        if stock not in spot_map:
            continue

        x = futures[
            (
                futures["name"] == stock
            )
            |
            (
                futures["symbol"].str.startswith(
                    stock + "FUT"
                )
            )
        ]

        if x.empty:
            continue

        row = x.iloc[0]

        temp[stock] = row

        future_tokens.append(
            str(row["token"])
        )

    spot_tokens = [
        spot_map[x]["token"]
        for x in temp
        if x in spot_map
    ]

    spot_prices = get_batch_ltp(
        jwt,
        "NSE",
        spot_tokens
    )

    future_prices = get_batch_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    for stock, row in temp.items():

        spot = spot_prices.get(
            spot_map[stock]["token"]
        )

        future = future_prices.get(
            str(row["token"])
        )

        if spot is None or future is None:
            continue

        difference = (
            future - spot
        )

        if difference <= 0:
            continue

        lot = int(
            row["lot_size"]
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
# MAIN SCAN
# ============================================================

def run_all_scanners():

    master_raw = download_master()

    master = prepare_master(
        master_raw
    )

    jwt = get_login_token()

    token_map = nifty50_token_map(
        master
    )

    rsi_result = scan_rsi_scanner(
        jwt,
        token_map
    )

    future_result = scan_future_spot(
        jwt,
        master
    )

    parity_result = scan_put_call_parity(
        jwt,
        master
    )

    return (
        rsi_result,
        future_result,
        parity_result
    )


# ============================================================
# DASHBOARD
# ============================================================

if st.button(
    "🚀 SCAN ALL",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Fast scanner चल रहा है..."
        ):

            (
                rsi_result,
                future_result,
                parity_result
            ) = run_all_scanners()

        # अगले scan तक SAVE
        st.session_state[
            "rsi_result"
        ] = rsi_result

        st.session_state[
            "future_result"
        ] = future_result

        st.session_state[
            "parity_result"
        ] = parity_result

        st.session_state[
            "last_scan"
        ] = datetime.now(
            IST
        ).strftime(
            "%d-%m-%Y %H:%M:%S"
        )

        st.success(
            "✅ Scan complete"
        )

    except Exception as e:

        st.error(
            "Scanner Error: " + str(e)
        )


# ============================================================
# SAVED RESULTS
# ============================================================

last_scan = st.session_state.get(
    "last_scan"
)

if last_scan:

    st.caption(
        "Last successful scan: "
        + last_scan
    )


# ============================================================
# RSI
# ============================================================

st.divider()

st.subheader(
    "📈 Nifty 50 RSI + OBV Scanner"
)

rsi_result = st.session_state.get(
    "rsi_result",
    pd.DataFrame()
)

if not rsi_result.empty:

    st.dataframe(
        rsi_result,
        use_container_width=True,
        hide_index=True,
        height=600
    )

else:

    st.info(
        "पहले SCAN ALL दबाएँ।"
    )


# ============================================================
# FUTURE SPOT
# ============================================================

st.divider()

st.subheader(
    "⚡ Future > Spot Scanner"
)

future_result = st.session_state.get(
    "future_result",
    pd.DataFrame()
)

if not future_result.empty:

    st.dataframe(
        future_result,
        use_container_width=True,
        hide_index=True,
        height=600
    )

else:

    st.info(
        "Future > Spot का result यहाँ आएगा।"
    )


# ============================================================
# PUT CALL PARITY
# ============================================================

st.divider()

st.subheader(
    "⚖️ Nifty 50 Put-Call Parity Arbitrage"
)

st.caption(
    "Current-month expiry | 10 nearest strikes | "
    "|CE − PE − (Future − Strike)| > 5"
)

parity_result = st.session_state.get(
    "parity_result",
    pd.DataFrame()
)

if not parity_result.empty:

    st.dataframe(
        parity_result,
        use_container_width=True,
        hide_index=True,
        height=700
    )

    csv = parity_result.to_csv(
        index=False
    ).encode(
        "utf-8"
    )

    st.download_button(
        "⬇️ Download Parity CSV",
        data=csv,
        file_name="put_call_parity.csv",
        mime="text/csv",
        use_container_width=True
    )

else:

    st.info(
        "5 से ज्यादा parity difference वाला "
        "कोई setup नहीं मिला।"
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "20 SMA: Angel One | "
    "Options: Angel One → NSE fallback | "
    "Results remain saved until next successful scan."
)
