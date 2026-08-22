    return pd.to_datetime(
        value,
        errors="coerce",
        dayfirst=True
    )


def get_ltp(
    jwt,
    exchange,
    tokens
):

    if not tokens:
        return {}

    headers = HEADERS.copy()

    headers["Authorization"] = (
        "Bearer " + jwt
    )

    prices = {}

    for start in range(
        0,
        len(tokens),
        100
    ):

        batch = tokens[
            start:start + 100
        ]

        response = requests.post(
            BASE_URL +
            "/rest/secure/angelbroking/"
            "market/v1/quote/",
            json={
                "mode": "LTP",
                "exchangeTokens": {
                    exchange: batch
                }
            },
            headers=headers,
            timeout=30
        )

        data = response.json()

        if not data.get("status"):
            continue

        fetched = (
            data
            .get("data", {})
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

    return prices


def run_scanner():

    master = load_master()

    today = pd.Timestamp(
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).date()
    )

    # ==============================
    # NSE F&O = nfo
    # ==============================

    nfo = master[
        master["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nfo")
    ].copy()

    if nfo.empty:

        raise Exception(
            "Angel One में nfo segment नहीं मिला।"
        )

    # ==============================
    # Stock Futures
    # ==============================

    futures = nfo[
        nfo["instrumenttype"]
        .astype(str)
        .str.upper()
        .eq("FUTSTK")
    ].copy()

    if futures.empty:

        raise Exception(
            "NFO में FUTSTK contracts नहीं मिले।"
        )

    futures["expiry_date"] = (
        futures["expiry"]
        .apply(parse_expiry)
    )

    futures["lot_size"] = pd.to_numeric(
        futures["lotsize"],
        errors="coerce"
    )

    futures = futures[
        futures["expiry_date"].notna()
    ]

    futures = futures[
        futures["expiry_date"] >= today
    ]

    futures = futures[
        futures["lot_size"].notna()
    ]

    if futures.empty:

        raise Exception(
            "Valid future expiry नहीं मिली।"
        )

    # सबसे नजदीकी expiry
    current_expiry = (
        futures["expiry_date"].min()
    )

    futures = futures[
        futures["expiry_date"]
        == current_expiry
    ].copy()

    # ==============================
    # NSE Cash = nse
    # ==============================

    cash = master[
        master["exch_seg"]
        .astype(str)
        .str.lower()
        .eq("nse")
    ].copy()

    cash["base_symbol"] = (
        cash["symbol"]
        .astype(str)
        .str.upper()
        .str.replace(
            "-EQ",
            "",
            regex=False
        )
    )

    cash = cash[
        cash["symbol"]
        .astype(str)
        .str.upper()
        .str.endswith("-EQ")
    ].copy()

    cash_lookup = dict(
        zip(
            cash["base_symbol"],
            cash["token"].astype(str)
        )
    )

    # ==============================
    # Match futures with spot
    # ==============================

    contracts = []

    for _, row in futures.iterrows():

        name = (
            str(row["name"])
            .upper()
            .strip()
        )

        symbol = (
            str(row["symbol"])
            .upper()
            .strip()
        )

        underlying = name

        if underlying not in cash_lookup:

            if symbol.endswith("FUT"):

                underlying = symbol[
                    :-3
                ]

        if underlying not in cash_lookup:
            continue

        contracts.append({

            "Stock": underlying,

            "Spot Token":
                cash_lookup[underlying],

            "Future Token":
                str(row["token"]),

            "Future Symbol":
                row["symbol"],

            "Lot Size":
                int(row["lot_size"]),

            "Expiry":
                current_expiry
        })

    contracts = pd.DataFrame(
        contracts
    )

    if contracts.empty:

        raise Exception(
            "Spot और Future की matching नहीं मिली।"
        )

    # ==============================
    # Angel Login
    # ==============================

    jwt = angel_login()

    spot_tokens = (
        contracts["Spot Token"]
        .astype(str)
        .tolist()
    )

    future_tokens = (
        contracts["Future Token"]
        .astype(str)
        .tolist()
    )

    # ==============================
    # Live prices
    # ==============================

    spot_prices = get_ltp(
        jwt,
        "NSE",
        spot_tokens
    )

    future_prices = get_ltp(
        jwt,
        "NFO",
        future_tokens
    )

    results = []

    for _, row in contracts.iterrows():

        spot = spot_prices.get(
            str(row["Spot Token"])
        )

        future = future_prices.get(
            str(row["Future Token"])
        )

        if spot is None:
            continue

        if future is None:
            continue

        difference = (
            spot - future
        )

        value = (
            difference *
            row["Lot Size"]
        )

        results.append({

            "Stock":
                row["Stock"],

            "Spot":
                round(spot, 2),

            "Current Future":
                round(future, 2),

            "Difference":
                round(difference, 2),

            "Lot Size":
                row["Lot Size"],

            "Difference × Lot":
                round(value, 2),

            "Expiry":
                row["Expiry"].strftime(
                    "%d-%b-%Y"
                ),

            "Future":
                row["Future Symbol"]
        })

    if not results:

        raise Exception(
            "Angel One से Spot/Future LTP नहीं मिला।"
        )

    result = pd.DataFrame(
        results
    )

    result = result.sort_values(
        "Difference × Lot",
        ascending=False
    )

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

    return result, current_expiry


st.subheader(
    "⚡ Current Month F&O Scanner"
)

if st.button(
    "🔄 Scan Now",
    type="primary",
    use_container_width=True
):

    try:

        with st.spinner(
            "Angel One से live Spot और Future data लिया जा रहा है..."
        ):

            result, expiry = run_scanner()

        st.success(
            "✅ Scanner completed"
        )

        st.write(
            "Current Expiry:",
            expiry.strftime(
                "%d-%b-%Y"
            )
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
            "angel_one_fno_scanner.csv",
            "text/csv"
        )

    except Exception as error:

        st.error(
            "Scanner Error: " +
            str(error)
        )
