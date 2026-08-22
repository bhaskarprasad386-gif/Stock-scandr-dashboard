# =========================================================
# EXPIRY PARSER
# =========================================================

def parse_expiry(x):

    if pd.isna(x):
        return pd.NaT

    x = str(x).strip().upper()

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
                x,
                format=fmt
            )
        except:
            pass

    return pd.to_datetime(
        x,
        errors="coerce",
        dayfirst=True
    )


# =========================================================
# FIND CURRENT MONTH FUTURES
# =========================================================

def get_current_month_futures(master):

    df = master.copy()

    # IMPORTANT:
    # Angel One master में NSE F&O = nfo
    futures = df[
        df["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nfo")
    ].copy()

    if futures.empty:
        raise Exception(
            "NFO segment नहीं मिला।"
        )

    # Stock Futures only
    instrument = (
        futures["instrumenttype"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    futures = futures[
        instrument.eq("FUTSTK")
    ].copy()

    if futures.empty:
        raise Exception(
            "NFO में FUTSTK contracts नहीं मिले।"
        )

    # Expiry
    futures["expiry_date"] = (
        futures["expiry"]
        .apply(parse_expiry)
    )

    futures = futures[
        futures["expiry_date"].notna()
    ].copy()

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    futures = futures[
        futures["expiry_date"] >= today
    ].copy()

    if futures.empty:
        raise Exception(
            "Current date के बाद कोई FUTSTK expiry नहीं मिली।"
        )

    # Nearest expiry = current active month
    current_expiry = (
        futures["expiry_date"].min()
    )

    current = futures[
        futures["expiry_date"]
        == current_expiry
    ].copy()

    current["token"] = (
        current["token"]
        .astype(str)
    )

    current["name_clean"] = (
        current["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    current["lotsize_num"] = pd.to_numeric(
        current["lotsize"],
        errors="coerce"
    )

    current = current[
        current["lotsize_num"].notna()
    ].copy()

    return current, current_expiry


# =========================================================
# FIND NSE SPOT
# =========================================================

def get_spot(master):

    df = master.copy()

    spot = df[
        df["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nse")
    ].copy()

    # Only equity
    spot["symbol_clean"] = (
        spot["symbol"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    spot = spot[
        spot["symbol_clean"]
        .str.endswith("-EQ")
    ].copy()

    spot["name_clean"] = (
        spot["name"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    spot["token"] = (
        spot["token"]
        .astype(str)
    )

    return spot


# =========================================================
# GET LTP
# =========================================================

def get_ltp(
    jwt,
    exchange,
    token
):

    headers = HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    response = requests.post(
        BASE_URL +
        "/rest/secure/angelbroking/"
        "market/v1/quote/",
        json={
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [
                    str(token)
                ]
            }
        },
        headers=headers,
        timeout=20
    )

    data = response.json()

    if not data.get("status"):
        return None

    fetched = (
        data
        .get("data", {})
        .get("fetched", [])
    )

    if not fetched:
        return None

    return float(
        fetched[0]["ltp"]
    )


# =========================================================
# SCANNER
# =========================================================

def run_scanner():

    master = load_master()

    # -----------------------------
    # Current month futures
    # -----------------------------

    futures, expiry = (
        get_current_month_futures(
            master
        )
    )

    # -----------------------------
    # NSE spot
    # -----------------------------

    spot = get_spot(
        master
    )

    # Spot lookup
    spot_lookup = {}

    for _, row in spot.iterrows():

        name = row["name_clean"]

        if name and name != "NAN":

            spot_lookup[name] = {
                "token": row["token"],
                "symbol": row["symbol_clean"]
            }

    # -----------------------------
    # Login
    # -----------------------------

    jwt = angel_login()

    results = []

    # -----------------------------
    # Process futures
    # -----------------------------

    for _, future in futures.iterrows():

        stock_name = (
            str(future["name"])
            .upper()
            .strip()
        )

        if stock_name not in spot_lookup:
            continue

        spot_token = spot_lookup[
            stock_name
        ]["token"]

        future_token = str(
            future["token"]
        )

        try:

            spot_ltp = get_ltp(
                jwt,
                "NSE",
                spot_token
            )

            future_ltp = get_ltp(
                jwt,
                "NFO",
                future_token
            )

        except Exception:

            continue

        if spot_ltp is None:
            continue

        if future_ltp is None:
            continue

        lot_size = int(
            float(
                future["lotsize_num"]
            )
        )

        # ---------------------------------
        # Spot minus Future
        # ---------------------------------

        difference = (
            spot_ltp -
            future_ltp
        )

        # ---------------------------------
        # Difference × Lot Size
        # ---------------------------------

        value = (
            difference *
            lot_size
        )

        difference_pct = (
            difference /
            future_ltp *
            100
            if future_ltp != 0
            else 0
        )

        results.append({

            "Stock":
                stock_name,

            "Spot":
                round(
                    spot_ltp,
                    2
                ),

            "Current Future":
                round(
                    future_ltp,
                    2
                ),

            "Difference":
                round(
                    difference,
                    2
                ),

            "Lot Size":
                lot_size,

            "Difference × Lot":
                round(
                    value,
                    2
                ),

            "Difference %":
                round(
                    difference_pct,
                    2
                ),

            "Expiry":
                expiry.strftime(
                    "%d-%b-%Y"
                ),

            "Future Symbol":
                future["symbol"]
        })

    if not results:

        raise Exception(
            "Spot और Current Month Future का live data नहीं मिला।"
        )

    result = pd.DataFrame(
        results
    )

    # ---------------------------------
    # Highest value first
    # ---------------------------------

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

    return result, expiry


# =========================================================
# DASHBOARD
# =========================================================

st.subheader(
    "⚡ Current Month F&O Scanner"
)

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    with st.spinner(
        "Angel One से live Spot और Future data लिया जा रहा है..."
    ):

        try:

            result, expiry = (
                run_scanner()
            )

            st.success(
                "✅ Scanner completed"
            )

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Stocks",
                len(result)
            )

            col2.metric(
                "Current Expiry",
                expiry.strftime(
                    "%d-%b-%Y"
                )
            )

            col3.metric(
                "Highest Value",
                f"₹{result['Difference × Lot'].iloc[0]:,.0f}"
            )

            st.subheader(
                "🏆 Ranking — Difference × Lot Size"
            )

            st.dataframe(
                result,
                use_container_width=True,
                hide_index=True,
                height=650
            )

            csv = result.to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "⬇️ Download CSV",
                csv,
                "fo_scanner.csv",
                "text/csv",
                use_container_width=True
            )

        except Exception as e:

            st.error(
                "Scanner Error: " +
                str(e)
            )

else:

    st.in
