import streamlit as st
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf
import sqlite3
import pytz
import time
from app import monitor_sec_filings, get_ticker, get_stock_analysis, predict_impact

# --- Setup DB ---
DB_PATH = "sec_filings.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute('CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, timestamp DATETIME, form_type TEXT, cik TEXT, company TEXT)')

# --- Streamlit page ---
st.set_page_config(page_title="SEC Filings Monitor Dashboard", layout="wide")
st.title("📰 Real-Time SEC Filings & Stock Impact Predictor")

# --- Auto-refresh using experimental_rerun ---
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 60:
    st.session_state.last_refresh = time.time()
    st.experimental_rerun()  # Refresh the app every 60 seconds

# --- Load filings ---
def load_recent_filings(n=50):
    cursor = conn.execute('SELECT * FROM filings ORDER BY timestamp DESC LIMIT ?', (n,))
    filings = cursor.fetchall()
    df = pd.DataFrame(filings, columns=['id', 'timestamp', 'form_type', 'cik', 'company'])
    if df.empty:
        return df
    df['ticker'] = df['cik'].apply(get_ticker)
    df['stock_data'] = df['ticker'].apply(get_stock_analysis)
    df['impact'] = [predict_impact({'form_type': row.form_type, 'company': row.company}, row.stock_data) for _, row in df.iterrows()]
    return df

# --- Sidebar ---
if 'last_update' not in st.session_state:
    st.session_state.last_update = datetime.now(pytz.timezone('US/Eastern'))

st.sidebar.info(f"Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S ET')}")
st.sidebar.success("Dashboard auto-refreshes every 1 min. Click 'Run Monitor Now' for instant fetch.")

# --- Manual monitor button ---
if st.button("Run Monitor Now"):
    new_filings = monitor_sec_filings()
    st.session_state.last_update = datetime.now(pytz.timezone('US/Eastern'))
    st.write(f"Inserted {len(new_filings)} filings")

# --- Main dashboard ---
df = load_recent_filings(n=50)

if df.empty:
    st.warning("No filings in DB yet. Run the monitor (app.py) first or click 'Run Monitor Now'.")
else:
    display_cols = ['timestamp', 'company', 'ticker', 'form_type', 'impact']
    st.subheader(f"Recent Filings (Last {len(df)}):")
    st.dataframe(df[display_cols].style.highlight_max(axis=0), use_container_width=True)

    latest = df.iloc[0]
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Latest Filing Details")
        st.write(f"**Company:** {latest['company']} ({latest['ticker']})")
        st.write(f"**Form:** {latest['form_type']}")
        st.write(f"**Time:** {latest['timestamp']}")
        st.write(f"**Predicted Impact:** {latest['impact']}")
    with col2:
        if latest['ticker'] != 'N/A':
            stock = yf.Ticker(latest['ticker'])
            hist = stock.history(period='5d')
            if not hist.empty:
                fig, ax = plt.subplots()
                hist['Close'].plot(ax=ax, title=f"{latest['ticker']} Price (Last 5 Days)")
                ax.set_ylabel("Price ($)")
                st.pyplot(fig)
            else:
                st.warning("No price data available.")

    high_impact = df[df['impact'].str.contains('positive|negative', case=False)]
    if not high_impact.empty:
        st.subheader("🚨 High-Impact Alerts")
        st.dataframe(high_impact[display_cols])

st.markdown("---")
st.caption("Built with Streamlit | Data from SEC RSS & Yahoo Finance | Predictions are estimates only—not financial advice.")
