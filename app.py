code = r'''import streamlit as st
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
    page_title="Liquid Parity PRO",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Liquid Future & Put-Call Parity PRO")

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://apiconnect.angelone.in"

# ============================================================
# SETTINGS
# ============================================================
with st.sidebar:
    st.header("⚙️ Scanner Settings")

    st.subheader("Parity Liquidity")
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

    st.subheader("Future > Spot")
    future_min_edge = st.number_input(
        "Minimum Future-Spot ₹",
        min_value=0.0,
        value=0.0,
        step=0.5
    )

    st.subheader("Auto Refresh")
    auto_refresh = st.checkbox("🔄 Auto Refresh", False)
    refresh_seconds = st.number_input(
        "Refresh Seconds",
        min_value=10,
        max_value=300,
        value=30,
        step=5
    )

# ============================================================
# SECRETS
# ============================================================
API_KEY = st.secrets.get("ANGEL_API_KEY", "")
CLIENT_ID = st.secrets.get("ANGEL_CLIENT_CODE", "")
PASSWORD = st.secrets.get("ANGEL_PASSWORD", "")
TOTP_SECRET = st.secrets.get("ANGEL_TOTP_SECRET", "")

if not API_KEY:
    st.error("ANGEL_API_KEY नहीं मिला। Streamlit Secrets में डालें।")
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

def safe_float(x):
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None

def now_ist():
    return datetime.now(IST)

# ============================================================
# LOGIN
# ============================================================
@st.cache_resource(ttl=120)
def login():
    totp = pyotp.TOTP(TOTP_SECRET).now()
    url = BASE_URL + "/rest/auth/angelbroking/user/v1/loginByPassword"

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
            "Angel Login Failed: " +
            str(data.get("message", "Unknown error"))
        )

    return data["data"]["jwtToken"]

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
        raise Exception("Angel master खाली मिला।")

    return pd.DataFrame(data)

@st.cache_data(ttl=1800, show_spinner=False)
def prepare_master(master):
    df = master.copy()

    for col in ["token", "symbol", "name", "exch_seg",
                "instrumenttype", "expiry", "strike",
                "lotsize"]:
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
        df["expiry"], errors="coerce", dayfirst=True
    )

    # Angel option strike is normally stored multiplied by 100
    df["strike_num"] = (
        pd.to_numeric(df["strike"], errors="coerce") / 100.0
    )

    df["lot_size"] = pd.to_numeric(
        df["lotsize"], errors="coerce"
    )

    return df

# ============================================================
# QUOTES
# ============================================================
def batch_full_quote(jwt, exchange, tokens):
    tokens = list(dict.fromkeys(
        str(x) for x in tokens if str(x)
    ))

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
            }
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
                continue

            fetched = (
                data.get("data", {})
                .get("fetched", [])
            )

            for item in fetched:
                token = str(item.get("symbolToken", ""))
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
                    "oi": safe_float(oi)
                }

        except Exception:
            continue

    return result

# ============================================================
# EXPIRIES
# ============================================================
def get_future_expiries(master, instrument, underlying):
    today = pd.Timestamp(now_ist().date())

    x = master[
        (master["exchange"] == "NFO") &
        (master["instrument"] == instrument) &
        (master["name"] == underlying) &
        master["expiry_date"].notna() &
        (master["expiry_date"] >= today)
    ].copy()

    if x.empty:
        return []

    return sorted(x["expiry_date"].unique())

def current_next_expiry(master, instrument, underlying):
    exps = get_future_expiries(master, instrument, underlying)
    if not exps:
        return None, None
    current = exps[0]
    nxt = exps[1] if len(exps) > 1 else None
    return current, nxt

# ============================================================
# FUTURE MAP
# ============================================================
def future_row(master, underlying, expiry, index=False):
    instrument = "FUTIDX" if index else "FUTSTK"

    x = master[
        (master["exchange"] == "NFO") &
        (master["instrument"] == instrument) &
        (master["name"] == underlying) &
        (master["expiry_date"] == expiry)
    ]

    if x.empty:
        return None

    return x.iloc[0]

# ============================================================
# CASH MAP
# ============================================================
def cash_token_map(master):
    cash = master[
        (master["exchange"] == "NSE") &
        master["symbol"].str.endswith("-EQ")
    ]

    result = {}

    for _, row in cash.iterrows():
        stock = row["symbol"].replace("-EQ", "").strip()
        result[stock] = {
            "symbol": row["symbol"],
            "token": str(row["token"])
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

    if bid is None or ask is None or ltp is None:
        return False

    if bid <= 0 or ask <= 0 or ltp <= 0:
        return False

    if ask < bid:
        return False

    if volume is None or volume < min_option_volume:
        return False

    if oi is None or oi < min_option_oi:
        return False

    spread = ((ask - bid) / ltp) * 100

    if spread > max_spread_percent:
        return False

    return True

def spread_percent(q):
    bid = q.get("bid")
    ask = q.get("ask")
    ltp = q.get("ltp")

    if not bid or not ask or not ltp:
        return None

    return ((ask - bid) / ltp) * 100

# ============================================================
# STOCK OPTION MAP
# ============================================================
def stock_option_map(master, stock, expiry):
    x = master[
        (master["exchange"] == "NFO") &
        (master["instrument"] == "OPTSTK") &
        (master["name"] == stock) &
        (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():
        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        symbol = str(row["symbol"])

        if symbol.endswith("CE"):
            typ = "CE"
        elif symbol.endswith("PE"):
            typ = "PE"
        else:
            continue

        result[(round(float(strike), 2), typ)] = {
            "token": str(row["token"]),
            "symbol": symbol,
            "lot": int(row["lot_size"])
            if not pd.isna(row["lot_size"]) else 0
        }

    return result

# ============================================================
# INDEX OPTION MAP
# ============================================================
def index_option_map(master, index_name, expiry):
    x = master[
        (master["exchange"] == "NFO") &
        (master["instrument"] == "OPTIDX") &
        (master["name"] == index_name) &
        (master["expiry_date"] == expiry)
    ]

    result = {}

    for _, row in x.iterrows():
        strike = row["strike_num"]

        if pd.isna(strike):
            continue

        symbol = str(row["symbol"])

        if symbol.endswith("CE"):
            typ = "CE"
        elif symbol.endswith("PE"):
            typ = "PE"
        else:
            continue

        result[(round(float(strike), 2), typ)] = {
            "token": str(row["token"]),
            "symbol": symbol,
            "lot": int(row["lot_size"])
            if not pd.isna(row["lot_size"]) else 0
        }

    return result

# ============================================================
# PARITY CALCULATION
# ============================================================
def calculate_parity_rows(
    jwt,
    master,
    underlying,
    expiry,
    is_index=False
):
    if expiry is None:
        return pd.DataFrame()

    fr = future_row(
        master,
        underlying,
        expiry,
        index=is_index
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

    contracts = (
        index_option_map(master, underlying, expiry)
        if is_index
        else stock_option_map(master, underlying, expiry)
    )

    if not contracts:
        return pd.DataFrame()

    strikes = sorted(
        set(k[0] for k in contracts),
        key=lambda s: abs(s - future)
    )[:int(parity_strikes)]

    tokens = []

    for strike in strikes:
        for typ in ("CE", "PE"):
            item = contracts.get((strike, typ))
            if item:
                tokens.append(item["token"])

    quotes = batch_full_quote(jwt, "NFO", tokens)
    rows = []

    lot = int(fr["lot_size"]) if not pd.isna(fr["lot_size"]) else 0

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

        # Executable direction 1:
        # SELL CE / BUY PE / BUY FUTURE
        positive = (
            ceq["bid"]
            - peq["ask"]
            - (fa - strike)
        )

        # Executable direction 2:
        # BUY CE / SELL PE / SELL FUTURE
        negative = (
            ceq["ask"]
            - peq["bid"]
            - (fb - strike)
        )

        if abs(positive) >= abs(negative):
            edge = positive
            trade = "CE SELL / PE BUY / FUTURE BUY"
        else:
            edge = negative
            trade = "CE BUY / PE SELL / FUTURE SELL"

        if abs(edge) <= parity_threshold:
            continue

        gross = abs(edge) * lot

        rows.append({
            "Underlying": underlying,
            "Month": (
                "Current"
                if expiry == current_next_expiry(
                    master,
                    "FUTIDX" if is_index else "FUTSTK",
                    underlying
                )[0]
                else "Next"
            ),
            "Expiry": pd.Timestamp(expiry).strftime("%d-%b-%Y"),
            "Future": round(future, 2),
            "Future Bid": round(fb, 2),
            "Future Ask": round(fa, 2),
            "Strike": round(strike, 2),
            "CE Bid": round(ceq["bid"], 2),
            "CE Ask": round(ceq["ask"], 2),
            "PE Bid": round(peq["bid"], 2),
            "PE Ask": round(peq["ask"], 2),
            "CE Spread %": round(spread_percent(ceq), 2),
            "PE Spread %": round(spread_percent(peq), 2),
            "CE Volume": ceq.get("volume"),
            "PE Volume": peq.get("volume"),
            "CE OI": ceq.get("oi"),
            "PE OI": peq.get("oi"),
            "Trade": trade,
            "Executable Edge": round(edge, 2),
            "Absolute Edge": round(abs(edge), 2),
            "Lot Size": lot,
            "GROSS PROFIT": round(gross, 2)
        })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result.sort_values(
        ["GROSS PROFIT", "Absolute Edge"],
        ascending=[False, False]
    ).reset_index(drop=True)

# ============================================================
# STOCK PARITY CURRENT + NEXT
# ============================================================
def scan_stock_two_months(jwt, master, stock):
    current, nxt = current_next_expiry(
        master, "FUTSTK", stock
    )

    frames = []

    if current is not None:
        a = calculate_parity_rows(
            jwt, master, stock, current, False
        )
        if not a.empty:
            frames.append(a)

    if nxt is not None:
        b = calculate_parity_rows(
            jwt, master, stock, nxt, False
        )
        if not b.empty:
            frames.append(b)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    return result.sort_values(
        "GROSS PROFIT",
        ascending=False
    ).reset_index(drop=True)

# ============================================================
# INDEX PARITY CURRENT + NEXT
# ============================================================
def scan_index_two_months(jwt, master, index_name):
    current, nxt = current_next_expiry(
        master, "FUTIDX", index_name
    )

    frames = []

    if current is not None:
        a = calculate_parity_rows(
            jwt, master, index_name, current, True
        )
        if not a.empty:
            frames.append(a)

    if nxt is not None:
        b = calculate_parity_rows(
            jwt, master, index_name, nxt, True
        )
        if not b.empty:
            frames.append(b)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)

    return result.sort_values(
        "GROSS PROFIT",
        ascending=False
    ).reset_index(drop=True)

# ============================================================
# FUTURE > SPOT
# ============================================================
def scan_future_spot_two_months(jwt, master):
    spot_map = cash_token_map(master)

    rows = []

    stocks = sorted(spot_map.keys())

    # Collect current and next future rows
    future_items = []

    for stock in stocks:
        current, nxt = current_next_expiry(
            master, "FUTSTK", stock
        )

        if current is not None:
            fr = future_row(master, stock, current, False)
            if fr is not None:
                future_items.append((stock, "Current", current, fr))

        if nxt is not None:
            fr = future_row(master, stock, nxt, False)
            if fr is not None:
                future_items.append((stock, "Next", nxt, fr))

    spot_tokens = [
        spot_map[s]["token"]
        for s, _, _, _ in future_items
        if s in spot_map
    ]

    future_tokens = [
        str(fr["token"])
        for _, _, _, fr in future_items
    ]

    spot_quotes = batch_full_quote(
        jwt, "NSE", spot_tokens
    )

    future_quotes = batch_full_quote(
        jwt, "NFO", future_tokens
    )

    for stock, month, expiry, fr in future_items:
        if stock not in spot_map:
            continue

        stoken = spot_map[stock]["token"]
        ftoken = str(fr["token"])

        sq = spot_quotes.get(stoken, {})
        fq = future_quotes.get(ftoken, {})

        spot = sq.get("ltp")
        future = fq.get("ltp")

        if spot is None or future is None:
            continue

        difference = future - spot

        if difference < future_min_edge:
            continue

        lot = (
            int(fr["lot_size"])
            if not pd.isna(fr["lot_size"])
            else 0
        )

        gross = difference * lot

        rows.append({
            "Stock": stock,
            "Month": month,
            "Expiry": pd.Timestamp(expiry).strftime("%d-%b-%Y"),
            "Spot": round(spot, 2),
            "Future": round(future, 2),
            "Future - Spot": round(difference, 2),
            "Lot Size": lot,
            "GROSS PROFIT": round(gross, 2),
            "Spot Value/Lot": round(spot * lot, 2),
            "Future Value/Lot": round(future * lot, 2)
        })

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    return result.sort_values(
        "GROSS PROFIT",
        ascending=False
    ).reset_index(drop=True)

# ============================================================
# ANGEL MARGIN
# ============================================================
def angel_margin(jwt, positions):
    url = BASE_URL + "/rest/secure/angelbroking/margin/v1/batch"

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

        return data.get("data")
    except Exception:
        return None

def add_future_margin(jwt, master, result):
    if result.empty:
        return result

    x = result.copy()
    margins = []

    for _, row in x.iterrows():
        try:
            stock = row["Stock"]
            month = row["Month"]
            expiry = pd.to_datetime(
                row["Expiry"],
                format="%d-%b-%Y"
            )

            fr = future_row(
                master, stock, expiry, False
            )

            if fr is None:
                margins.append(None)
                continue

            qty = int(fr["lot_size"])

            position = [{
                "exchange": "NFO",
                "qty": qty,
                "productType": "CARRYFORWARD",
                "token": str(fr["token"]),
                "symbol": str(fr["symbol"]),
                "transactionType": "BUY"
            }]

            data = angel_margin(jwt, position)

            margin = None

            if isinstance(data, dict):
                for key in [
                    "totalMarginRequired",
                    "totalMargin",
                    "marginRequired",
                    "requiredMargin"
                ]:
                    if data.get(key) is not None:
                        margin = safe_float(data.get(key))
                        break

            elif isinstance(data, (int, float)):
                margin = float(data)

            margins.append(margin)

        except Exception:
            margins.append(None)

    x["Angel Final Margin"] = margins

    return x

# ============================================================
# DISPLAY
# ============================================================
def show_result(result, filename, excel=True):
    if result is None or result.empty:
        st.info("कोई qualifying result नहीं मिला।")
        return

    st.dataframe(
        result,
        use_container_width=True,
        hide_index=True,
        height=600
    )

    csv = result.to_csv(index=False).encode("utf-8")

    st.download_button(
        "⬇️ Download CSV",
        data=csv,
        file_name=filename.replace(".xlsx", ".csv"),
        mime="text/csv",
        use_container_width=True
    )

    if excel:
        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl"
        ) as writer:
            result.to_excel(
                writer,
                index=False,
                sheet_name="Scanner Result"
            )

        st.download_button(
            "📗 Download Editable Excel",
            data=output.getvalue(),
            file_name=filename,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            use_container_width=True
        )

# ============================================================
# LOAD MASTER
# ============================================================
try:
    master = prepare_master(download_master())
except Exception as e:
    st.error("Master Error: " + str(e))
    st.stop()

# ============================================================
# LOGIN
# ============================================================
if "jwt" not in st.session_state:
    st.session_state["jwt"] = None

if st.button(
    "🔐 Connect Angel One",
    use_container_width=True
):
    try:
        st.session_state["jwt"] = login()
        st.success("Angel One Connected")
    except Exception as e:
        st.error(str(e))

jwt = st.session_state.get("jwt")

if not jwt:
    st.warning("पहले Connect Angel One दबाएँ।")
    st.stop()

# ============================================================
# 1. FUTURE > SPOT
# ============================================================
st.divider()
st.header("1️⃣ ⚡ Future > Spot — Current Month vs Next Month")
st.caption(
    "Current और Next month दोनों future अलग-अलग calculate होंगे। "
    "जिसका gross profit ज्यादा होगा वह ऊपर रहेगा।"
)

if st.button(
    "🚀 Scan Future > Spot",
    key="future_scan",
    type="primary",
    use_container_width=True
):
    with st.spinner("Current + Next month Future > Spot scan..."):
        result = scan_future_spot_two_months(jwt, master)

    st.session_state["future_result"] = result

show_result(
    st.session_state.get("future_result", pd.DataFrame()),
    "future_spot_current_next.xlsx"
)

# ============================================================
# STOCK PARTS
# ============================================================
fno_stocks = sorted(
    set(
        master.loc[
            (master["exchange"] == "NFO") &
            (master["instrument"] == "FUTSTK"),
            "name"
        ].dropna().astype(str)
    )
)

parts = np.array_split(fno_stocks, 5)

for idx in range(5):
    part_no = idx + 1

    st.divider()
    st.header(
        f"{part_no + 1}️⃣ ⚖️ Stock Liquid Parity — Part {part_no}"
    )

    st.caption(
        "Current Month + Next Month | Liquid CE + PE + Future | "
        "Executable Bid/Ask | Gross Profit"
    )

    if st.button(
        f"🚀 Run Stock Parity Part {part_no}",
        key=f"stock_part_{part_no}",
        type="primary",
        use_container_width=True
    ):
        rows = []

        with st.spinner(
            f"Stock Parity Part {part_no} scan चल रहा है..."
        ):
            for stock in list(parts[idx]):
                try:
                    r = scan_stock_two_months(
                        jwt,
                        master,
                        stock
                    )

                    if not r.empty:
                        rows.append(r)
                except Exception:
                    continue

        if rows:
            result = pd.concat(
                rows,
                ignore_index=True
            ).sort_values(
                "GROSS PROFIT",
                ascending=False
            ).reset_index(drop=True)

            result.insert(
                0,
                "Rank",
                range(1, len(result) + 1)
            )
        else:
            result = pd.DataFrame()

        st.session_state[
            f"stock_parity_{part_no}"
        ] = result

    show_result(
        st.session_state.get(
            f"stock_parity_{part_no}",
            pd.DataFrame()
        ),
        f"stock_parity_part_{part_no}.xlsx"
    )

# ============================================================
# NIFTY
# ============================================================
st.divider()
st.header("7️⃣ 📊 Nifty 50 Liquid Parity — Current + Next")

if st.button(
    "🔄 Scan Nifty 50",
    key="nifty_scan",
    type="primary",
    use_container_width=True
):
    with st.spinner("Nifty current + next parity..."):
        result = scan_index_two_months(
            jwt,
            master,
            "NIFTY"
        )

    if not result.empty:
        result.insert(
            0,
            "Rank",
            range(1, len(result) + 1)
        )

    st.session_state["nifty_result"] = result

show_result(
    st.session_state.get(
        "nifty_result",
        pd.DataFrame()
    ),
    "nifty_current_next_parity.xlsx"
)

# ============================================================
# BANKNIFTY
# ============================================================
st.divider()
st.header("8️⃣ 🏦 BankNifty Liquid Parity — Current + Next")

if st.button(
    "🔄 Scan BankNifty",
    key="banknifty_scan",
    type="primary",
    use_container_width=True
):
    with st.spinner("BankNifty current + next parity..."):
        result = scan_index_two_months(
            jwt,
            master,
            "BANKNIFTY"
        )

    if not result.empty:
        result.insert(
            0,
            "Rank",
            range(1, len(result) + 1)
        )

    st.session_state["banknifty_result"] = result

show_result(
    st.session_state.get(
        "banknifty_result",
        pd.DataFrame()
    ),
    "banknifty_current_next_parity.xlsx"
)

# ============================================================
# RULES
# ============================================================
st.divider()
st.subheader("ℹ️ Rules")

st.markdown("""
### Future > Spot
- Current Month और Next Month दोनों scan
- Future − Spot
- Lot Size
- **GROSS PROFIT = (Future − Spot) × Lot Size**
- Gross profit के हिसाब से descending ranking

### Stock / Index Parity
- Current Month + Next Month दोनों
- केवल liquid CE + PE
- CE Bid + Ask जरूरी
- PE Bid + Ask जरूरी
- Future Bid + Ask जरूरी
- CE Volume minimum
- PE Volume minimum
- CE OI minimum
- PE OI minimum
- Maximum Bid/Ask spread
- Zero/stale quote reject
- Executable Bid/Ask parity
- **GROSS PROFIT = Absolute Executable Edge × Lot Size**
- Highest gross profit ऊपर

### Excel
हर result का editable Excel export उपलब्ध है।
""")

st.caption(
    "📡 Live market data: Angel One SmartAPI"
)

st.caption(
    "⚠️ Angel margin API उपलब्ध न होने पर margin blank रह सकता है; "
    "गलत अनुमान दिखाने के बजाय blank रखा गया है।"
)

# ============================================================
# AUTO REFRESH
# ============================================================
if auto_refresh:
    st.info(
        f"🔄 Auto Refresh ON — {refresh_seconds} seconds"
    )
    time.sleep(int(refresh_seconds))
    st.rerun()
'''
path = "/mnt/data/app.py"
with open(path, "w", encoding="utf-8") as f:
    f.write(code)
print(path)
