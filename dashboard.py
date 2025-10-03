import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import yfinance as yf
import matplotlib.pyplot as plt
from datetime import datetime
import pandas as pd

# Import your functions from app.py (adjust path if needed)
from app import monitor_sec_filings, get_ticker, get_stock_analysis, predict_impact, conn

# Streamlit page config
st.set_page_config(page_title="SEC Filings Monitor Dashboard", layout="wide")

st.title("📰 Real-Time SEC Filings & Stock Impact Predictor")

# Background scheduler for monitoring
if 'scheduler' not in st.session_state:
    st.session_state.scheduler = BackgroundScheduler()
    st.session_state.scheduler.add_job(monitor_sec_filings, 'interval', minutes=1)
    st.session_state.scheduler.start()
    st.session_state.last_update = datetime.now()

# Load recent filings from DB
def load_recent_filings(n=10):
    cursor = conn.execute('SELECT * FROM filings ORDER BY timestamp DESC LIMIT ?', (n,))
    filings = cursor.fetchall()
    df = pd.DataFrame(filings, columns=['id', 'timestamp', 'form_type', 'cik', 'company'])
    df['ticker'] = df['cik'].apply(get_ticker)
    df['stock_data'] = df['ticker'].apply(get_stock_analysis)
    df['impact'] = [predict_impact({'form_type': row.form_type, 'company': row.company}, row.stock_data) for _, row in df.iterrows()]
    return df

# Refresh button
if st.button("Refresh Data"):
    st.session_state.last_update = datetime.now()

st.sidebar.info(f"Last updated: {st.session_state.last_update.strftime('%Y-%m-%d %H:%M:%S')}")
st.sidebar.success("Monitoring every 1 min. Check during market hours for new filings.")

# Main dashboard
df = load_recent_filings()
if df.empty:
    st.warning("No filings in DB yet. Run the monitor (app.py) first or wait for new ones.")
else:
    # Filings table
    st.subheader("Recent Filings (Last 10)")
    display_cols = ['timestamp', 'company', 'ticker', 'form_type', 'impact']
    st.dataframe(df[display_cols].style.highlight_max(axis=0), use_container_width=True)

    # Latest filing details
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

    # High-impact alerts
    high_impact = df[df['impact'].str.contains('positive|negative', case=False)]
    if not high_impact.empty:
        st.subheader("🚨 High-Impact Alerts")
        st.dataframe(high_impact[display_cols])

# Footer
st.markdown("---")
st.caption("Built with Streamlit | Data from SEC RSS & Yahoo Finance | Predictions are estimates only—not financial advice.")