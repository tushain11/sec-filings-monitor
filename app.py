import feedparser
import yfinance as yf
import requests
from datetime import datetime, timedelta
import sqlite3
import json
import warnings
import pytz
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from apscheduler.schedulers.background import BackgroundScheduler

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
nltk.download('vader_lexicon', quiet=True)

# --- SQLite setup (thread-safe for scheduler) ---
DB_PATH = "sec_filings.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute('CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, timestamp DATETIME, form_type TEXT, cik TEXT, company TEXT)')

# --- Load ticker mapping ---
def get_ticker(cik):
    try:
        with open('company_tickers.json', 'r') as f:
            data = json.load(f)
        cik_to_ticker = {}
        for entry in data.values():
            cik_key = str(entry['cik_str']).zfill(10)
            cik_to_ticker[cik_key] = entry['ticker']
        return cik_to_ticker.get(str(cik).zfill(10), 'N/A')
    except Exception as e:
        print(f"Error loading ticker map: {e}")
        return 'N/A'

# --- Stock analysis ---
def get_stock_analysis(ticker):
    if ticker == 'N/A':
        return {'error': 'No ticker available'}
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            'current_price': info.get('currentPrice', 'N/A'),
            'recommendation': info.get('recommendationKey', 'N/A'),
            'target_price': info.get('targetMeanPrice', 'N/A'),
            'news_headlines': [n['title'] for n in stock.news[:3]]
        }
    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {e}")
        return {'error': 'Fetch failed'}

# --- Predict filing impact ---
def predict_impact(filing, stock_data):
    sia = SentimentIntensityAnalyzer()
    form_impact = {
        '8-K': 0.2,
        '10-Q': 0.1,
        '10-K': 0.1,
        '4': -0.3,
        'SC 13D': 0.4,
    }
    form_score = form_impact.get(filing['form_type'], 0)
    desc_sent = sia.polarity_scores(filing['company'] + ' ' + filing['form_type'])['compound']
    rec_score = 0.3 if stock_data.get('recommendation') in ['buy', 'strong_buy'] else -0.2 if stock_data.get('recommendation') in ['sell', 'strong_sell'] else 0
    news_sent = 0
    if 'news_headlines' in stock_data:
        news_sent = sum(sia.polarity_scores(headline)['compound'] for headline in stock_data['news_headlines']) / len(stock_data['news_headlines'])
    total_score = (form_score + desc_sent + rec_score + news_sent) / 4
    if total_score > 0.1:
        return 'Likely positive impact (price up ~2-5%)'
    elif total_score < -0.1:
        return 'Likely negative impact (price down ~2-5%)'
    else:
        return 'Neutral impact'

# --- Monitor SEC filings ---
def monitor_sec_filings():
    import pytz
    import feedparser
    from datetime import datetime, timedelta

    eastern = pytz.timezone('US/Eastern')
    url = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&start=0&count=100&output=atom'
    feed = feedparser.parse(url)
    new_filings = []

    cutoff = datetime.now(eastern) - timedelta(minutes=120)  # last 2 hours

    print(f"Fetched {len(feed.entries)} entries from SEC feed")

    for entry in feed.entries:
        try:
            print("---- ENTRY ----")
            print("Title:", entry.title)
            print("Author:", getattr(entry, 'author', 'N/A'))
            print("Link:", entry.link)
            print("Updated:", getattr(entry, 'updated', 'N/A'))

            timestamp = datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%SZ')  # Parse UTC timestamp
            timestamp = timestamp.astimezone(eastern)

            if timestamp < cutoff:
                print("Skipping: older than cutoff")
                continue

            filing_id = entry.id.split('/')[-1]  # Unique ID
            form_type = entry.title.split()[0]  # e.g., '8-K'
            company = getattr(entry, 'author', 'N/A')
            cik = entry.link.split('CIK=')[-1].split('&')[0]
            cik = str(cik).zfill(10)

            # Check if already in DB
            if not conn.execute('SELECT id FROM filings WHERE id=?', (filing_id,)).fetchone():
                conn.execute('INSERT INTO filings VALUES (?, ?, ?, ?, ?)',
                             (filing_id, timestamp, form_type, cik, company))
                conn.commit()
                new_filings.append({
                    'timestamp': timestamp,
                    'form_type': form_type,
                    'company': company,
                    'cik': cik,
                    'filing_link': entry.link
                })
                print(f"Inserted: {form_type} - {company} ({cik})")
            else:
                print("Already in DB:", filing_id)

        except Exception as e:
            print(f"Error processing entry: {e}")
            continue

    print(f"Total new filings inserted: {len(new_filings)}")
    return new_filings

# --- Start background scheduler ---
scheduler = BackgroundScheduler()
scheduler.add_job(monitor_sec_filings, 'interval', minutes=1)
scheduler.start()
print("SEC monitor running every 1 min. Press Ctrl+C to stop.")

# --- Optional: run once immediately ---
if __name__ == "__main__":
    new = monitor_sec_filings()
    if new:
        print(f"Inserted {len(new)} filings")
