from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import numpy as np
import requests
import pandas as pd
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="F&O Future Spot Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 NSE F&O Future − Spot Scanner")

st.caption(
    "Only Current Month Future > Spot stocks are shown"
)

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

# ============================================================
# ANGEL ONE
# ============================================================

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

# ============================================================
# LOGIN
# ============================================================

def login():

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

    response = requests.post(
        url,
        json=payload,
        headers=BASE_HEADERS,
        timeout=30
    )

    data = response.json()

    if data.get("status") is not True:
        message = data.get(
            "message",
            "Login failed"
        )
        raise Exception(
            "Angel One Login Failed: "
            + str(message)
        )

    return data["data"]["jwtToken"]


# ============================================================
# MASTER DOWNLOAD
# ============================================================

@st.cache_data(ttl=1800)
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
            "Angel One master खाली मिला"
        )

    return pd.DataFrame(data)


# ============================================================
# EXPIRY PARSER
# ============================================================

def parse_expiry(value):

    if pd.isna(value):
        return pd.NaT

    text = str(value).strip()

    formats = [
        "%d%b%Y",
        "%d-%b-%Y",
        "%d/%b/%Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S"
    ]

    for fmt in formats:
        try:
            return pd.to_datetime(
                text,
                format=fmt
            )
        except Exception:
            continue

    return pd.to_datetime(
        text,
        errors="coerce",
        dayfirst=True
    )


# ============================================================
# BUILD STOCK LIST
# ============================================================

def build_stock_list(master):

    df = master.copy()

    df["expiry_date"] = df["expiry"].apply(
        parse_expiry
    )

    df["lot_size"] = pd.to_numeric(
        df["lotsize"],
        errors="coerce"
    )

    df["token"] = (
        df["token"]
        .astype(str)
        .str.strip()
    )

    df["symbol"] = (
        df["symbol"]
        .astype(str)
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

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    # --------------------------------------------------------
    # NSE STOCK FUTURES
    # --------------------------------------------------------

    futures = df[
        (df["exchange"] == "NFO")
        & (df["instrument"] == "FUTSTK")
        & (df["expiry_date"].notna())
        & (df["expiry_date"] >= today)
        & (df["lot_size"].notna())
    ].copy()

    if futures.empty:
        raise Exception(
            "NSE FUTSTK contracts नहीं मिले"
        )

    # Nearest expiry = current available contract
    expiry = futures["expiry_date"].min()

    futures = futures[
        futures["expiry_date"] == expiry
    ].copy()

    # --------------------------------------------------------
    # NSE CASH STOCKS
    # --------------------------------------------------------

    cash = df[
        (df["exchange"] == "NSE")
        & (
            df["symbol"]
            .str.upper()
            .str.endswith("-EQ")
        )
    ].copy()

    if cash.empty:
        raise Exception(
            "NSE cash stocks नहीं मिले"
        )

    # --------------------------------------------------------
    # SPOT MAP
    # --------------------------------------------------------

    spot_map = {}

    for _, row in cash.iterrows():

        stock = (
            str(row["symbol"])
            .upper()
            .replace("-EQ", "")
            .strip()
        )

        spot_map[stock] = {
            "symbol": str(row["symbol"]),
            "token": str(row["token"])
        }

    # --------------------------------------------------------
    # MATCH FUTURE + SPOT
    # --------------------------------------------------------

    rows = []

    for _, row in futures.iterrows():

        name = (
            str(row["name"])
            .upper()
            .strip()
        )

        future_symbol = (
            str(row["symbol"])
            .upper()
            .strip()
        )

        matched = None

        # Direct name
        if name in spot_map:
            matched = name

        # Future symbol without FUT
        if matched is None:
            if future_symbol.endswith("FUT"):

                base = (
                    future_symbol[:-3]
                    .strip()
                )

                if base in spot_map:
                    matched = base

        # Prefix matching
        if matched is None:

            for stock in spot_map:

                if (
                    future_symbol.startswith(stock)
                    and future_symbol.endswith("FUT")
                ):
                    matched = stock
                    break

        if matched is None:
            continue

        rows.append({
            "Stock": matched,
            "Spot Symbol": spot_map[matched]["symbol"],
            "Spot Token": spot_map[matched]["token"],
            "Future Symbol": str(row["symbol"]),
            "Future Token": str(row["token"]),
            "Lot Size": int(row["lot_size"]),
            "Expiry": expiry
        })

    result = pd.DataFrame(rows)

    if result.empty:
        raise Exception(
            "Future और Spot matching नहीं मिली"
        )

    result = result.drop_duplicates(
        subset=["Stock"],
        keep="first"
    )

    return result, expiry


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

    headers = BASE_HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    prices = {}

    # Angel quote API में छोटे batches
    batch_size = 50

    for start in range(
        0,
        len(tokens),
        batch_size
    ):

        batch = tokens[
            start:start + batch_size
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

        url = BASE_URL + (
            "/rest/secure/angelbroking/"
            "market/v1/quote/"
        )

        try:

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            data = response.json()

            if data.get("status") is True:

                fetched = (
                    data.get("data", {})
                    .get("fetched", [])
                )

                for item in fetched:

                    token = str(
                        item.get("symbolToken", "")
                    )

                    ltp = item.get("ltp")

                    if token and ltp is not None:

                        prices[token] = float(ltp)

        except Exception:
            continue

    return prices


# ============================================================
# SCAN
# ============================================================

def scan_market():

    # Master
    master = download_master()

    # Stock contracts
    stocks, expiry = build_stock_list(
        master
    )

    # Login
    jwt = login()

    # Tokens
    spot_tokens = (
        stocks["Spot Token"]
        .astype(str)
        .tolist()
    )

    future_tokens = (
        stocks["Future Token"]
        .astype(str)
        .tolist()
    )

    # --------------------------------------------------------
    # FAST BATCH SPOT
    # --------------------------------------------------------

    spot_prices = get_batch_ltp(
        jwt,
        "NSE",
        spot_tokens
    )

    # --------------------------------------------------------
    # FAST BATCH FUTURE
    # --------------------------------------------------------

    future_prices = get_batch_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    results = []

    spot_count = 0
    future_count = 0

    # --------------------------------------------------------
    # CALCULATION
    # --------------------------------------------------------

    for _, row in stocks.iterrows():

        spot_token = str(
            row["Spot Token"]
        )

        future_token = str(
            row["Future Token"]
        )

        spot = spot_prices.get(
            spot_token
        )

        future = future_prices.get(
            future_token
        )

        if spot is not None:
            spot_count += 1

        if future is not None:
            future_count += 1

        if spot is None:
            continue

        if future is None:
            continue

        # ====================================================
        # ONLY POSITIVE FUTURE PREMIUM
        # ====================================================

        difference = future - spot

        if difference <= 0:
            continue

        lot = int(
            row["Lot Size"]
        )

        final_value = (
            difference * lot
        )

        results.append({
            "Stock": row["Stock"],
            "Spot": round(spot, 2),
            "Current Future": round(future, 2),
            "Future − Spot": round(
                difference,
                2
            ),
            "Lot Size": lot,
            "Difference × Lot": round(
                final_value,
                2
            ),
            "Expiry": row["Expiry"].strftime(
                "%d-%b-%Y"
            ),
            "Future Symbol": row["Future Symbol"]
        })

    result = pd.DataFrame(results)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

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

        result["Stock"] = result.apply(
            lambda x:
            f"{x['Stock']} ({x['Lot Size']})",
            axis=1
        )

    diagnostics = {
        "total": len(stocks),
        "spot": spot_count,
        "future": future_count,
        "positive": len(result)
    }

    return (
        result,
        diagnostics,
        expiry
    )

# ============================================================
# FAST NIFTY 100 FALL → SIDEWAYS SCANNER
# ============================================================

from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# RSI
# ============================================================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
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


# ============================================================
# RISING CHECK
# ============================================================

def is_rising(series, lookback=6):

    s = series.dropna()

    if len(s) < lookback:
        return False

    recent = s.iloc[-lookback:]

    overall_rise = (
        recent.iloc[-1]
        > recent.iloc[0]
    )

    rising_count = (
        recent.diff()
        .dropna()
        > 0
    ).sum()

    return (
        overall_rise
        and
        rising_count >= 3
    )


# ============================================================
# PRICE FALL + SIDEWAYS
# ============================================================

def check_price_structure(df):

    if df is None or len(df) < 30:
        return False, False, 0

    close = df["close"]

    previous_high = close.iloc[:-8].max()

    recent_low = close.iloc[-8:].min()

    if previous_high <= 0:
        return False, False, 0

    fall_percent = (
        (previous_high - recent_low)
        / previous_high
    ) * 100

    # कम से कम 4% fall
    fall_ok = fall_percent >= 4

    # --------------------------------------------------------
    # SIDEWAYS RANGE
    # --------------------------------------------------------

    recent = df.iloc[-8:]

    high = recent["high"].max()
    low = recent["low"].min()

    if low <= 0:
        return fall_ok, False, fall_percent

    sideways_range = (
        (high - low) / low
    ) * 100

    # 8% तक sideways
    sideways_ok = sideways_range <= 8

    # एक candle में बहुत बड़ा move नहीं
    daily_move = (
        recent["close"]
        .pct_change()
        .abs()
        * 100
    )

    if (
        not daily_move.dropna().empty
        and
        daily_move.dropna().max() > 4
    ):
        sideways_ok = False

    return (
        fall_ok,
        sideways_ok,
        fall_percent
    )


# ============================================================
# NIFTY 100 LIST
# ============================================================

NIFTY_100 = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "BHARTIARTL",
    "TCS", "SBIN", "INFY", "BAJFINANCE", "HINDUNILVR",
    "LT", "ITC", "KOTAKBANK", "AXISBANK", "MARUTI",
    "M&M", "SUNPHARMA", "TITAN", "ULTRACEMCO",
    "NTPC", "ONGC", "POWERGRID", "ADANIENT",
    "ADANIPORTS", "JSWSTEEL", "TATASTEEL",
    "HCLTECH", "WIPRO", "TECHM", "NESTLEIND",
    "ASIANPAINT", "HINDALCO", "COALINDIA", "GRASIM",
    "DRREDDY", "CIPLA", "DIVISLAB", "EICHERMOT",
    "HEROMOTOCO", "BAJAJFINSV", "BAJAJ-AUTO",
    "APOLLOHOSP", "BRITANNIA", "TATACONSUM",
    "INDUSINDBK", "SBILIFE", "HDFCLIFE",
    "SHRIRAMFIN", "BEL", "HAL", "TRENT",
    "JIOFIN", "INDIGO", "ADANIGREEN", "ADANIPOWER",
    "DMART", "VEDL", "IOC", "BPCL", "GAIL",
    "HINDPETRO", "RECLTD", "PFC", "PIDILITIND",
    "AMBUJACEM", "ACC", "SIEMENS", "ABB",
    "DLF", "LODHA", "GODREJCP", "GODREJPROP",
    "ICICIPRULI", "ICICIGI", "HAVELLS", "DABUR",
    "MARICO", "COLPAL", "BERGEPAINT", "TORNTPHARM",
    "MANKIND", "ZYDUSLIFE", "LUPIN", "AUROPHARMA",
    "BIOCON", "MOTHERSON", "TVSMOTOR", "BOSCHLTD",
    "ASHOKLEY", "CANBK", "BANKBARODA", "PNB",
    "UNIONBANK", "INDIANB", "BANKINDIA", "LICI",
    "IRFC", "JINDALSTEL", "SAIL", "NHPC",
    "IRCTC"
]


# ============================================================
# TOKEN MAP
# ============================================================

def get_nifty100_token_map(master):

    df = master.copy()

    df["exchange"] = (
        df["exch_seg"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    df["token"] = (
        df["token"]
        .astype(str)
        .str.strip()
    )

    cash = df[
        (df["exchange"] == "NSE")
        &
        (df["symbol"].str.endswith("-EQ"))
    ].copy()

    token_map = {}

    for _, row in cash.iterrows():

        stock = (
            row["symbol"]
            .replace("-EQ", "")
            .strip()
        )

        if stock in NIFTY_100:

            token_map[stock] = {
                "symbol": row["symbol"],
                "token": row["token"]
            }

    return token_map


# ============================================================
# HISTORICAL DATA
# ============================================================

def get_historical_candles_fast(
    jwt,
    token,
    days=180
):

    headers = BASE_HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    url = BASE_URL + (
        "/rest/secure/angelbroking/"
        "historical/v1/getCandleData"
    )

    end_date = datetime.now(
        ZoneInfo("Asia/Kolkata")
    )

    start_date = (
        end_date
        - pd.Timedelta(days=days)
    )

    payload = {
        "exchange": "NSE",
        "symboltoken": str(token),
        "interval": "ONE_DAY",
        "fromdate": start_date.strftime(
            "%Y-%m-%d %H:%M"
        ),
        "todate": end_date.strftime(
            "%Y-%m-%d %H:%M"
        )
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
            return pd.DataFrame()

        candles = data.get(
            "data",
            []
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

        return df.sort_values(
            "datetime"
        ).reset_index(
            drop=True
        )

    except Exception:

        return pd.DataFrame()


# ============================================================
# WEEKLY CONVERSION
# ============================================================

def convert_to_weekly(df):

    x = df.copy()

    x["datetime"] = pd.to_datetime(
        x["datetime"]
    )

    x = x.set_index(
        "datetime"
    )

    weekly = x.resample(
        "W-FRI"
    ).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    })

    return weekly.dropna().reset_index()


# ============================================================
# ANALYZE ONE STOCK
# ============================================================

def analyze_stock(
    stock,
    info,
    jwt,
    timeframe
):

    df = get_historical_candles_fast(
        jwt,
        info["token"],
        180
    )

    if df.empty:
        return None

    if timeframe == "Weekly":

        df = convert_to_weekly(df)

    if len(df) < 30:
        return None

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    fall_ok, sideways_ok, fall_percent = (
        check_price_structure(df)
    )

    if not fall_ok or not sideways_ok:
        return None

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    df["RSI"] = calculate_rsi(
        df["close"]
    )

    # --------------------------------------------------------
    # OBV
    # --------------------------------------------------------

    df["OBV"] = calculate_obv(
        df
    )

    rsi_rising = is_rising(
        df["RSI"],
        6
    )

    obv_rising = is_rising(
        df["OBV"],
        6
    )

    # RSI जरूरी
    if not rsi_rising:
        return None

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    if rsi_rising and obv_rising:

        signal = "🟢"

        strength = (
            "RSI + OBV Rising"
        )

        signal_rank = 1

    else:

        signal = "🟡"

        strength = (
            "RSI Rising"
        )

        signal_rank = 2

    # --------------------------------------------------------
    # CURRENT
    # --------------------------------------------------------

    price = float(
        df["close"].iloc[-1]
    )

    rsi = float(
        df["RSI"].iloc[-1]
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    return {
        "Signal": signal,
        "Signal Strength": strength,
        "Stock": stock,
        "Price": round(price, 2),
        "RSI": round(rsi, 2),
        "RSI Rising": "YES",
        "OBV Rising":
            "YES"
            if obv_rising
            else "NO",
        "Price Fall %": round(
            fall_percent,
            2
        ),
        "Price Phase":
            "Fall → Sideways",
        "Timeframe": timeframe,
        "Signal Rank": signal_rank
    }


# ============================================================
# FAST SCAN
# ============================================================

def fast_nifty100_scan(
    jwt,
    token_map,
    timeframe
):

    results = []

    # 12 workers = fast but controlled
    max_workers = min(
        12,
        max(1, len(token_map))
    )

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {
            executor.submit(
                analyze_stock,
                stock,
                info,
                jwt,
                timeframe
            ): stock
            for stock, info
            in token_map.items()
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception:
                continue

    result = pd.DataFrame(
        results
    )

    if result.empty:
        return result

    result = result.sort_values(
        [
            "Signal Rank",
            "RSI"
        ],
        ascending=[
            True,
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

    result = result.drop(
        columns=[
            "Signal Rank"
        ]
    )

    return result


# ============================================================
# RUN ONE TIMEFRAME
# ============================================================

def run_fast_nifty100(
    timeframe
):

    master = download_master()

    token_map = get_nifty100_token_map(
        master
    )

    if not token_map:
        raise Exception(
            "Nifty 100 tokens नहीं मिले"
        )

    jwt = login()

    return fast_nifty100_scan(
        jwt,
        token_map,
        timeframe
    )


# ============================================================
# NIFTY 100 DASHBOARD
# ============================================================

st.divider()

st.subheader(
    "📈 Nifty 100 Fall → Sideways Scanner"
)

st.caption(
    "Price Fall ≥ 4% → Sideways ≤ 8% → RSI Rising"
)

# ============================================================
# TIMEFRAME SELECTOR
# ============================================================

timeframe = st.radio(
    "⏱️ Time Frame",
    [
        "Daily",
        "Weekly"
    ],
    horizontal=True,
    key="nifty100_timeframe"
)

# ============================================================
# SCAN BUTTON
# ============================================================

if st.button(
    f"🔄 Scan Nifty 100 {timeframe}",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            f"⚡ Nifty 100 {timeframe} fast scan चल रहा है..."
        ):

            new_result = run_fast_nifty100(
                timeframe
            )

        # ----------------------------------------------------
        # SAVE RESULT
        # ----------------------------------------------------

        st.session_state[
            f"nifty100_{timeframe.lower()}"
        ] = new_result

        st.session_state[
            f"nifty100_{timeframe.lower()}_time"
        ] = datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).strftime(
            "%d-%b-%Y %H:%M:%S"
        )

        st.success(
            f"✅ {timeframe} scan complete — "
            f"{len(new_result)} stocks मिले"
        )

    except Exception as e:

        st.error(
            "Nifty 100 Scanner Error: "
            + str(e)
        )


# ============================================================
# SHOW SAVED RESULT
# ============================================================

saved_result = st.session_state.get(
    f"nifty100_{timeframe.lower()}",
    pd.DataFrame()
)

saved_time = st.session_state.get(
    f"nifty100_{timeframe.lower()}_time",
    ""
)

if saved_time:

    st.caption(
        f"💾 Last saved {timeframe} result: "
        f"{saved_time}"
    )


if not saved_result.empty:

    st.success(
        f"🎯 {len(saved_result)} stocks मिले"
    )

    st.dataframe(
        saved_result,
        use_container_width=True,
        hide_index=True,
        height=650
    )

    csv = saved_result.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=(
            f"nifty100_{timeframe.lower()}.csv"
        ),
        mime="text/csv",
        use_container_width=True
    )

else:

    st.info(
        f"🔄 अभी {timeframe} का result नहीं है। "
        f"ऊपर Scan button दबाएँ।"
    )



