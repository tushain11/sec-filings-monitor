import streamlit as st
from streamlit_autorefresh import st_autorefresh
import sqlite3
import pandas as pd
from datetime import datetime
import pytz
from app import monitor_sec_filings, get_ticker, get_stock_analysis, predict_impact

# --- Streamlit page setup ---
st.set_page_config(page_title="SEC Filings Monitor", layout="wide")
st.title("📰 Real-Time SEC Filings & Stock Impact Predictor")

# --- Auto-refresh every 60 seconds ---
st_autorefresh(interval=60 * 1000, key="refresh")

# --- Connect to DB ---
DB_PATH = "sec_filings.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

# --- Helper: Get Eastern Time formatted timestamp ---
def get_et_time():
    eastern = pytz.timezone('US/Eastern')
    return datetime.now(eastern).strftime("%Y-%m-%d %H:%M:%S ET")

# --- Header Info ---
st.caption(f"Last updated: {get_et_time()}")
st.caption("Dashboard auto-refreshes every 1 min. Click 'Run Monitor Now' for instant fetch.")

# --- Manual Monitor Trigger ---
if st.button("Run Monitor Now"):
    with st.spinner("Fetching latest filings..."):
        new_filings = monitor_sec_filings()
        st.success(f"Inserted {len(new_filings)} new filings")

# --- Display Filings Table ---
try:
    df = pd.read_sql_query("SELECT * FROM filings ORDER BY timestamp DESC LIMIT 50", conn)
    if df.empty:
        st.warning("No filings in DB yet. Run the monitor (app.py) first or click 'Run Monitor Now'.")
    else:
        st.subheader("Recent Filings")
        st.dataframe(df)

        # --- Optional: Detailed analysis for latest filing ---
        latest = df.iloc[0]
        st.divider()
        st.subheader("Latest Filing Analysis")

        ticker = get_ticker(latest["cik"])
        st.write(f"**Company:** {latest['company']}")
        st.write(f"**Form Type:** {latest['form_type']}")
        st.write(f"**Ticker:** {ticker}")

        if ticker != "N/A":
            stock_data = get_stock_analysis(ticker)
            impact = predict_impact(latest, stock_data)

            st.write(f"**Predicted Impact:** {impact}")
            st.json(stock_data)

except Exception as e:
    st.error(f"Error loading filings: {e}")

# --- Footer ---
st.divider()
st.caption("Developed for real-time SEC filings and market signal tracking.")
