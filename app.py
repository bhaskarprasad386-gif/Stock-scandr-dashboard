import streamlit as st

st.set_page_config(
    page_title="Stock Scanner",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Stock Scanner Dashboard")
st.success("Dashboard successfully connected!")

st.subheader("Nifty 100 Scanner")

st.info(
    "यहाँ बाद में आपका Rollover, Rollover Cost और "
    "Backtest Result दिखाई देगा।"
)
