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
