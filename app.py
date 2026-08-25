code = r'''import streamlit as st
import requests
import pandas as pd
import numpy as np
import pyotp
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# FAST MARKET SCANNER PRO - FRESH SAFE VERSION
# ============================================================

st.set_page_config(
    page_title="Fast Market Scanner PRO",
    page_icon="📊",
    layout="wide",
)

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelone.in"

# ------------------------- SETTINGS -------------------------

with st.sidebar:
    st.header("⚙️ Scanner Settings")

    parity_threshold = st.number_input(
        "Minimum Executable Edge ₹",
        min_value=0.0,
        value=5.0,
        step=0.5,
    )

    strike_count = st.number_input(
        "Liquid Strikes Around Future",
        min_value=3,
        max_value=30,
        value=10,
        step=1,
    )

    min_option_volume = st.number_input(
        "Minimum Option Volume",
        min_value=0,
        value=1000,
        step=100,
    )

    min_option_oi = st.number_input(
        "Minimum Option OI",
        min_value=0,
        value=10000,
        step=1000,
    )

    max_spread_percent = st.number_input(
        "Maximum Bid/Ask Spread %",
        min_value=0.1,
        max_value=20.0,
        value=3.0,
        step=0.5,
    )

    stock_parts = st.number_input(
        "Stock Parity Parts",
        min_value=1,
        max_value=5,
        value=5,
        step=1,
    )

# ------------------------- SECRETS -------------------------

API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

# ------------------------- HEADERS -------------------------

BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-UserType": "USER",
    "X-SourceID": "WEB",
    "X-PrivateKey": API_KEY,
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP": "127.0.0.1",
    "X-MACAddress": "00:00:00:00:00:00",
}


def auth_headers(jwt):
    h = BASE_HEADERS.copy()
    h["Authorization"] = "Bearer " + jwt
    return h


def safe_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None


def now_ist():
    return datetime.now(IST)


# ============================================================
# LOGIN
# ============================================================

def login():
    if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
        raise RuntimeError(
            "Angel One Secrets missing. Required: "
            "ANGEL_API_KEY, ANGEL_CLIENT_CODE, "
            "ANGEL_PASSWORD, ANGEL_TOTP_SECRET"
        )

    url = BASE_URL + "/rest/auth/angelbroking/user/v1/loginByPassword"

    payload = {
        "clientcode": CLIENT_ID,
        "password": PASSWORD,
        "totp": pyotp.TOTP(TOTP_SECRET).now(),
    }

    r = requests.post(
        url,
        json=payload,
        headers=BASE_HEADERS,
        timeout=20,
    )
    r.raise_for_status()

    data = r.json()

    if data.get("status") is not True:
        raise RuntimeError(
            "Angel Login Failed: " +
            str(data.get("message", "Unknown error"))
        )

    token = data.get("data", {}).get("jwtToken")
    if not token:
        raise RuntimeError("JWT token नहीं मिला।")

    return token


# ============================================================
# MASTER
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def download_master():
    url = (
        "https://margincalculator.angelbroking.com/"
        "OpenAPI_File/files/OpenAPIScripMaster.json"
    )

    r = requests.get(url, timeout=60)
    r.raise_for_status()

    data = r.json()

    if not data:
        raise RuntimeError("Angel master खाली मिला।")

    return pd.DataFrame(data)


@st.cache_data(ttl=1800, show_spinner=False)
def prepare_master(master):
    df = master.copy()

    for col in ["token", "symbol", "name", "exch_seg", "instrumenttype"]:
        if col not in df.columns:
            df[col] = ""

    df["token"] = df["token"].astype(str).str.strip()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["name"] = df["name"].astype(str).str.upper().str.strip()
    df["exchange"] = df["exch_seg"].astype(str).str.upper().str.strip()
    df["instrument"] = (
        df["instrumenttype"].astype(str).str.upper().str.strip()
    )

    df["expiry_date"] = pd.to_datetime(
        df.get("expiry", ""),
        errors="coerce",
        dayfirst=True,
    )

    df["strike_num"] = (
        pd.to_numeric(df.get("strike", np.nan), errors="coerce") / 100
    )

    df["lot_size"] = pd.to_numeric(
        df.get("lotsize", np.nan),
        errors="coerce",
    )

    return df


# ============================================================
# QUOTE
# ============================================================

def batch_full_quote(jwt, exchange, tokens):
    tokens = list(
        dict.fromkeys(
            str(x) for x in tokens
            if str(x).strip()
        )
    )

    if not tokens:
        return {}

    url = BASE_URL + "/rest/secure/angelbroking/market/v1/quote/"
    result = {}

    for i in range(0, len(tokens), 50):
        batch = tokens[i:i + 50]

        payload = {
            "mode": "FULL",
            "exchangeTokens": {
                exchange: batch
            },
        }

        try:
            r = requests.post(
                url,
                json=payload,
                headers=auth_headers(jwt),
                timeout=20,
            )
            data = r.json()

            if data.get("status") is not True:
                continue

            fetched = data.get("data", {}).get("fetched", []) or []

            for item in fetched:
                token = str(item.get("symbolToken", "")).strip()
                if not token:
                    continue

                depth = item.get("depth") or {}
                buys = depth.get("buy") or []
                sells = depth.get("sell") or []

                bid = buys[0].get("price") if buys else None
                ask = sells[0].get("price") if sells else None

                if bid is None:
                    bid = item.get("bestBid")
                if ask is None:
                    ask = item.get("bestAsk")

                volume = item.get("tradeVolume")
                if volume is None:
                    volume = item.get("volume")

                oi = item.get("opnInterest")
                if oi is None:
                    oi = item.get("openInterest")

                result[token] = {
                    "ltp": safe_float(item.get("ltp")),
                    "bid": safe_float(bid),
                    "ask": safe_float(ask),
                    "volume": safe_float(volume),
                    "oi": safe_float(oi),
                }

        except Exception:
            continue

    return result


def quote_is_liquid(q):
    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")
    volume = q.get("volume")
    oi = q.get("oi")

    if bid is None or ask is None or ltp is None:
        return False

    if bid <= 0 or ask <= 0 or ltp <= 0 or ask < bid:
        return False

    if volume is None or volume < min_option_volume:
        return False

    if oi is None or oi < min_option_oi:
        return False

    spread = ((ask - bid) / ltp) * 100

    return spread <= max_spread_percent


def spread_pct(q):
    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")

    if not bid or not ask or not ltp:
        return None

    return ((ask - bid) / ltp) * 100


# ============================================================
# EXPIRIES
# ============================================================

def get_expiries(master, exchange="NFO"):
    today = pd.Timestamp(now_ist().date())

    x = master[
        (master["exchange"] == exchange)
        & master["expiry_date"].notna()
        & (master["expiry_date"] >= today)
    ].copy()

    if x.empty:
        return []

    return sorted(x["expiry_date"].drop_duplicates().tolist())


def current_next_expiry(master):
    exps = get_expiries(master, "NFO")
    if not exps:
        return None, None

    current = exps[0]
    next_expiry = exps[1] if len(exps) > 1 else None

    return current, next_expiry


# ============================================================
# FUTURE MAP
# ============================================================

def future_map(master, expiry):
    if expiry is None:
        return {}

    x = master[
        (master["exchange"] == "NFO")
        & (master["instrument"] == "FUTSTK")
        & (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():
        stock = str(row["name"]).strip()

        if not stock or stock in result:
            continue

        try:
            lot = int(row["lot_size"])
        except Exception:
            continue

        if lot <= 0:
            continue

        result[stock] = row

    return result


def index_future(master, index_name, expiry):
    x = master[
        (master["exchange"] == "NFO")
        & (master["instrument"] == "FUTIDX")
        & (master["name"] == index_name)
        & (master["expiry_date"] == expiry)
    ]

    if x.empty:
        return None

    return x.iloc[0]


# ============================================================
# FUTURE > SPOT
# ============================================================

def cash_map(master):
    x = master[
        (master["exchange"] == "NSE")
        & master["symbol"].str.endswith("-EQ")
    ]

    result = {}

    for _, row in x.iterrows():
        stock = row["symbol"].replace("-EQ", "").strip()
        result[stock] = {
            "token": str(row["token"]),
            "symbol": row["symbol"],
        }

    return result


def calculate_future_spot(master, jwt, expiry, label):
    fmap = future_map(master, expiry)
    cmap = cash_map(master)

    stocks = sorted(set(fmap) & set(cmap))

    if not stocks:
        return pd.DataFrame()

    spot_tokens = [cmap[s]["token"] for s in stocks]
    future_tokens = [str(fmap[s]["token"]) for s in stocks]

    spot_quotes = batch_full_quote(jwt, "NSE", spot_tokens)
    future_quotes = batch_full_quote(jwt, "NFO", future_tokens)

    rows = []

    for stock in stocks:
        sq = spot_quotes.get(cmap[stock]["token"], {})
        fq = future_quotes.get(str(fmap[stock]["token"]), {})

        spot = sq.get("ltp")
        future = fq.get("ltp")

        if spot is None or future is None:
            continue

        try:
            lot = int(fmap[stock]["lot_size"])
        except Exception:
            continue

        if lot <= 0:
            continue

        diff = future - spot
        gross = diff * lot

        if diff <= 0:
            continue

        rows.append({
            "Stock": stock,
            "Month": label,
            "Expiry": expiry.strftime("%d-%b-%Y"),
            "Spot": round(spot, 2),
            "Future": round(future, 2),
            "Future-Spot": round(diff, 2),
            "Lot Size": lot,
            "GROSS PROFIT / LOT": round(gross, 2),
            "Spot Value / Lot": round(spot * lot, 2),
            "Future Value / Lot": round(future * lot, 2),
            "Future Bid": fq.get("bid"),
            "Future Ask": fq.get("ask"),
        })

    return pd.DataFrame(rows)


# ============================================================
# OPTION MAP
# ============================================================

def option_map(master, underlying, expiry, index=False):
    instrument = "OPTIDX" if index else "OPTSTK"

    x = master[
        (master["exchange"] == "NFO")
        & (master["instrument"] == instrument)
        & (master["name"] == underlying)
        & (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():
        strike = row["strike_num"]
        if pd.isna(strike):
            continue

        symbol = str(row["symbol"]).upper()

        if symbol.endswith("CE"):
            typ = "CE"
        elif symbol.endswith("PE"):
            typ = "PE"
        else:
            continue

        try:
            lot = int(row["lot_size"])
        except Exception:
            continue

        if lot <= 0:
            continue

        result[(round(float(strike), 2), typ)] = {
            "token": str(row["token"]),
            "symbol": symbol,
            "lot": lot,
        }

    return result


# ============================================================
# PARITY ENGINE
# ============================================================

def scan_parity_for_underlying(
    master,
    jwt,
    underlying,
    expiry,
    month_label,
    index=False,
):
    if expiry is None:
        return pd.DataFrame()

    fr = (
        index_future(master, underlying, expiry)
        if index
        else future_map(master, expiry).get(underlying)
    )

    if fr is None:
        return pd.DataFrame()

    ft = str(fr["token"])
    fq = batch_full_quote(jwt, "NFO", [ft]).get(ft, {})

    future = fq.get("ltp")
    fb = fq.get("bid")
    fa = fq.get("ask")

    if future is None or fb is None or fa is None:
        return pd.DataFrame()

    if fb <= 0 or fa <= 0 or fa < fb:
        return pd.DataFrame()

    contracts = option_map(
        master,
        underlying,
        expiry,
        index=index,
    )

    if not contracts:
        return pd.DataFrame()

    strikes = sorted(
        {k[0] for k in contracts},
        key=lambda z: abs(z - future),
    )[:int(strike_count)]

    tokens = []

    for strike in strikes:
        for typ in ("CE", "PE"):
            item = contracts.get((strike, typ))
            if item:
                tokens.append(item["token"])

    quotes = batch_full_quote(jwt, "NFO", tokens)

    rows = []

    for strike in strikes:
        ce = contracts.get((strike, "CE"))
        pe = contracts.get((strike, "PE"))

        if not ce or not pe:
            continue

        ceq = quotes.get(ce["token"], {})
        peq = quotes.get(pe["token"], {})

        # LIQUID STRIKE CRITERIA IS KEPT
        if not quote_is_liquid(ceq):
            continue

        if not quote_is_liquid(peq):
            continue

        # FUTURE MUST HAVE TWO SIDES
        if fb <= 0 or fa <= 0:
            continue

        ce_bid = ceq["bid"]
        ce_ask = ceq["ask"]
        pe_bid = peq["bid"]
        pe_ask = peq["ask"]

        # Strategy 1:
        # SELL CE + BUY PE + BUY FUTURE
        edge_positive = ce_bid - pe_ask - (fa - strike)

        # Strategy 2:
        # BUY CE + SELL PE + SELL FUTURE
        edge_negative = ce_ask - pe_bid - (fb - strike)

        candidates = [
            (edge_positive, "CE SELL / PE BUY / FUTURE BUY"),
            (edge_negative, "CE BUY / PE SELL / FUTURE SELL"),
        ]

        edge, trade = max(candidates, key=lambda x: abs(x[0]))

        if abs(edge) <= parity_threshold:
            continue

        try:
            lot = int(fr["lot_size"])
        except Exception:
            lot = ce["lot"]

        gross = abs(edge) * lot

        # Conservative displayed margin estimate.
        # Actual RMS margin can differ.
        future_margin = future * lot * 0.15
        option_cash = (ce_ask + pe_ask) * lot
        estimated_margin = future_margin + option_cash

        rows.append({
            "Underlying": underlying,
            "Month": month_label,
            "Expiry": expiry.strftime("%d-%b-%Y"),
            "Trade": trade,
            "Future": round(future, 2),
            "Future Bid": round(fb, 2),
            "Future Ask": round(fa, 2),
            "Strike": round(strike, 2),
            "CE Bid": round(ce_bid, 2),
            "CE Ask": round(ce_ask, 2),
            "PE Bid": round(pe_bid, 2),
            "PE Ask": round(pe_ask, 2),
            "CE Spread %": round(spread_pct(ceq), 2),
            "PE Spread %": round(spread_pct(peq), 2),
            "CE Volume": ceq.get("volume"),
            "PE Volume": peq.get("volume"),
            "CE OI": ceq.get("oi"),
            "PE OI": peq.get("oi"),
            "Executable Edge": round(edge, 2),
            "Absolute Edge": round(abs(edge), 2),
            "Lot Size": lot,
            "GROSS PROFIT / TRADE": round(gross, 2),
            "Estimated Future Margin": round(future_margin, 2),
            "Estimated Option Margin": round(option_cash, 2),
            "Estimated FINAL MARGIN": round(estimated_margin, 2),
        })

    result = pd.DataFrame(rows)

    if not result.empty:
        result = result.sort_values(
            ["GROSS PROFIT / TRADE", "Absolute Edge"],
            ascending=[False, False],
        ).reset_index(drop=True)

        result.insert(0, "Rank", range(1, len(result) + 1))

    return result


# ============================================================
# 5 STOCK PARTS
# ============================================================

def stock_list(master, expiry):
    return sorted(future_map(master, expiry).keys())


def split_stocks(stocks, parts):
    if not stocks:
        return [[] for _ in range(parts)]

    arrays = np.array_split(stocks, parts)
    return [list(a) for a in arrays]


def scan_stock_part(
    master,
    jwt,
    stocks,
    current_expiry,
    next_expiry,
    part_no,
):
    all_rows = []

    for stock in stocks:
        current = scan_parity_for_underlying(
            master,
            jwt,
            stock,
            current_expiry,
            "CURRENT MONTH",
            index=False,
        )

        if not current.empty:
            all_rows.append(current)

        if next_expiry is not None:
            nxt = scan_parity_for_underlying(
                master,
                jwt,
                stock,
                next_expiry,
                "NEXT MONTH",
                index=False,
            )

            if not nxt.empty:
                all_rows.append(nxt)

    if not all_rows:
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)

    result = result.sort_values(
        "GROSS PROFIT / TRADE",
        ascending=False,
    ).reset_index(drop=True)

    result.insert(
        0,
        "Part",
        part_no,
    )

    result.insert(
        1,
        "Rank",
        range(1, len(result) + 1),
    )

    return result


# ============================================================
# INDEX SCAN
# ============================================================

def scan_index_both_months(
    master,
    jwt,
    index_name,
    current_expiry,
    next_expiry,
):
    frames = []

    cur = scan_parity_for_underlying(
        master,
        jwt,
        index_name,
        current_expiry,
        "CURRENT MONTH",
        index=True,
    )

    if not cur.empty:
        frames.append(cur)

    if next_expiry is not None:
        nxt = scan_parity_for_underlying(
            master,
            jwt,
            index_name,
            next_expiry,
            "NEXT MONTH",
            index=True,
        )

        if not nxt.empty:
            frames.append(nxt)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    result = result.sort_values(
        "GROSS PROFIT / TRADE",
        ascending=False,
    ).reset_index(drop=True)

    result.insert(0, "Rank", range(1, len(result) + 1))

    return result


# ============================================================
# DISPLAY / DOWNLOAD
# ============================================================

def show_table(df, filename):
    if df is None or df.empty:
        st.info("कोई qualifying liquid result नहीं मिला।")
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=600,
    )

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "⬇️ Download CSV / Excel में खोलें",
        data=csv,
        file_name=filename,
        mime="text/csv",
        use_container_width=True,
    )


# ============================================================
# STARTUP
# ============================================================

st.title("📊 Fast & Furious Market Scanner PRO")

st.caption(
    "Current + Next Month | Liquid Strike | "
    "Executable Bid/Ask Parity | Future > Spot"
)

if not all([API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET]):
    st.error(
        "Angel One Secrets missing. Streamlit Secrets में ये चार values रखें: "
        "ANGEL_API_KEY, ANGEL_CLIENT_CODE, "
        "ANGEL_PASSWORD, ANGEL_TOTP_SECRET"
    )
    st.stop()

try:
    master = prepare_master(download_master())
except Exception as e:
    st.error("Master load error: " + str(e))
    st.stop()

if "jwt" not in st.session_state:
    st.session_state.jwt = None

if st.button(
    "🔐 Connect Angel One",
    type="primary",
    use_container_width=True,
):
    try:
        st.session_state.jwt = login()
        st.success("Angel One Connected ✅")
    except Exception as e:
        st.error("Login Error: " + str(e))

jwt = st.session_state.jwt

if not jwt:
    st.warning("पहले Connect Angel One दबाएँ।")
    st.stop()

current_expiry, next_expiry = current_next_expiry(master)

if current_expiry is None:
    st.error("Current month expiry नहीं मिली।")
    st.stop()

st.success(
    "Current: " + current_expiry.strftime("%d-%b-%Y")
    + " | Next: "
    + (
        next_expiry.strftime("%d-%b-%Y")
        if next_expiry is not None
        else "Not Available"
    )
)

# ============================================================
# 1. FUTURE > SPOT
# ============================================================

st.divider()
st.header("1️⃣ ⚡ Future > Spot — Current + Next Month")

if st.button(
    "🚀 Scan Current + Next Month Future > Spot",
    key="future_spot",
    type="primary",
    use_container_width=True,
):
    frames = []

    with st.spinner("Current month Future > Spot..."):
        cur = calculate_future_spot(
            master,
            jwt,
            current_expiry,
            "CURRENT MONTH",
        )

    if not cur.empty:
        frames.append(cur)

    if next_expiry is not None:
        with st.spinner("Next month Future > Spot..."):
            nxt = calculate_future_spot(
                master,
                jwt,
                next_expiry,
                "NEXT MONTH",
            )

        if not nxt.empty:
            frames.append(nxt)

    if frames:
        result = pd.concat(frames, ignore_index=True)
        result = result.sort_values(
            "GROSS PROFIT / LOT",
            ascending=False,
        ).reset_index(drop=True)
        result.insert(0, "Rank", range(1, len(result) + 1))
    else:
        result = pd.DataFrame()

    st.session_state.future_result = result

show_table(
    st.session_state.get("future_result", pd.DataFrame()),
    "future_spot_current_next.csv",
)

# ============================================================
# 2-6. STOCK PARITY 5 PARTS
# ============================================================

st.divider()
st.header("2️⃣ ⚖️ Stock Put-Call Parity — 5 Independent Parts")

st.caption(
    "Liquid strike criteria ACTIVE: CE + PE volume/OI + "
    "Bid/Ask + spread + Future Bid/Ask."
)

stocks = stock_list(master, current_expiry)
parts = split_stocks(stocks, int(stock_parts))

for i in range(int(stock_parts)):
    part_no = i + 1

    st.subheader(
        f"Part {part_no} — {len(parts[i])} Stocks"
    )

    if st.button(
        f"🚀 Run Stock Parity Part {part_no}",
        key=f"stock_part_{part_no}",
        type="primary",
        use_container_width=True,
    ):
        with st.spinner(
            f"Part {part_no}: Current + Next Month liquid parity..."
        ):
            result = scan_stock_part(
                master,
                jwt,
                parts[i],
                current_expiry,
                next_expiry,
                part_no,
            )

        st.session_state[
            f"stock_result_{part_no}"
        ] = result

    show_table(
        st.session_state.get(
            f"stock_result_{part_no}",
            pd.DataFrame(),
        ),
        f"stock_parity_part_{part_no}.csv",
    )

# ============================================================
# 7. NIFTY
# ============================================================

st.divider()
st.header("7️⃣ 📊 NIFTY Liquid Put-Call Parity")

if st.button(
    "🚀 Scan NIFTY Current + Next Month",
    key="nifty_scan",
    type="primary",
    use_container_width=True,
):
    with st.spinner("NIFTY liquid parity..."):
        result = scan_index_both_months(
            master,
            jwt,
            "NIFTY",
            current_expiry,
            next_expiry,
        )

    st.session_state.nifty_result = result

show_table(
    st.session_state.get("nifty_result", pd.DataFrame()),
    "nifty_parity_current_next.csv",
)

# ============================================================
# 8. BANKNIFTY
# ============================================================

st.divider()
st.header("8️⃣ 🏦 BANKNIFTY Liquid Put-Call Parity")

if st.button(
    "🚀 Scan BANKNIFTY Current + Next Month",
    key="banknifty_scan",
    type="primary",
    use_container_width=True,
):
    with st.spinner("BANKNIFTY liquid parity..."):
        result = scan_index_both_months(
            master,
            jwt,
            "BANKNIFTY",
            current_expiry,
            next_expiry,
        )

    st.session_state.banknifty_result = result

show_table(
    st.session_state.get("banknifty_result", pd.DataFrame()),
    "banknifty_parity_current_next.csv",
)

# ============================================================
# RULES
# ============================================================

st.divider()
st.header("ℹ️ Scanner Rules")

st.markdown(
"""
### Future > Spot
- Current month और next month दोनों scan
- Spot LTP और Future LTP
- Future > Spot ही result में
- Lot size अलग-अलग expiry से
- `Future - Spot × Lot Size = GROSS PROFIT / LOT`
- Highest gross profit ऊपर

### Stock / Index Parity
- Current month + next month दोनों
- Liquid strike criteria **हटा नहीं है**
- CE Bid + Ask mandatory
- PE Bid + Ask mandatory
- Future Bid + Ask mandatory
- CE minimum Volume
- PE minimum Volume
- CE minimum OI
- PE minimum OI
- Maximum Bid/Ask spread
- Zero/stale quotes rejected
- Executable Bid/Ask edge
- Gross profit = Absolute executable edge × lot size
- Estimated final margin अलग column में

### Important
`Estimated FINAL MARGIN` conservative estimate है। Actual Angel One RMS margin market conditions, hedge benefit और exchange/broker rules के अनुसार अलग हो सकता है।
"""
)

st.caption("Live data: Angel One SmartAPI")
'''
path = "/mnt/data/app.py"
with open(path, "w", encoding="utf-8") as f:
    f.write(code)
print(path)
