import feedparser
import yfinance as yf
from datetime import datetime, timedelta
import sqlite3
import json
import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from apscheduler.schedulers.blocking import BlockingScheduler

nltk.download('vader_lexicon', quiet=True)

# --- Helper functions ---

def get_ticker(cik):
    try:
        with open('company_tickers.json', 'r') as f:
            data = json.load(f)
        cik_to_ticker = {}
        for entry in data.values():
            cik_key = str(entry['cik_str']).zfill(10)
            cik_to_ticker[cik_key] = entry['ticker']
        input_cik = str(cik).zfill(10)
        return cik_to_ticker.get(input_cik, 'N/A')
    except Exception as e:
        print(f"Error loading ticker map: {e}")
        return 'N/A'

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
    if 'news_headlines' in stock_data and stock_data['news_headlines']:
        news_sent = sum(sia.polarity_scores(h)['compound'] for h in stock_data['news_headlines']) / len(stock_data['news_headlines'])
    total_score = (form_score + desc_sent + rec_score + news_sent) / 4
    if total_score > 0.1:
        return 'Likely positive impact (price up ~2-5%)'
    elif total_score < -0.1:
        return 'Likely negative impact (price down ~2-5%)'
    else:
        return 'Neutral impact'

# --- Setup DB ---
DB_PATH = "sec_filings.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute('CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, timestamp DATETIME, form_type TEXT, cik TEXT, company TEXT)')

# --- Monitor function ---
def monitor_sec_filings():
    url = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&start=0&count=100&output=atom'
    feed = feedparser.parse(url)
    new_filings = []

    eastern = pytz.timezone('US/Eastern')
    cutoff = datetime.now(tz=eastern) - timedelta(minutes=60)

    for entry in feed.entries:
        try:
            timestamp_utc = datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%SZ')
            timestamp = timestamp_utc.replace(tzinfo=pytz.UTC).astimezone(eastern)

            if timestamp < cutoff:
                continue

            filing_id = entry.id.split('/')[-1]
            form_type = entry.title.split()[0]
            company = entry.author
            cik = entry.link.split('CIK=')[-1].split('&')[0].zfill(10)

            if not conn.execute('SELECT id FROM filings WHERE id=?', (filing_id,)).fetchone():
                conn.execute('INSERT INTO filings VALUES (?, ?, ?, ?, ?)', (filing_id, timestamp, form_type, cik, company))
                conn.commit()
                new_filings.append({
                    'timestamp': timestamp,
                    'form_type': form_type,
                    'company': company,
                    'cik': cik,
                    'filing_link': entry.link
                })
        except Exception as e:
            print(f"Error processing entry: {e}")
            continue

    return new_filings

# --- Scheduler ---
if __name__ == "__main__":
    import pytz
    scheduler = BlockingScheduler()
    
    def job():
        new_filings = monitor_sec_filings()
        if new_filings:
            print(f"\nFound {len(new_filings)} new filings in the last 60 minutes:")
            for filing in new_filings:
                ticker = get_ticker(filing['cik'])
                stock_data = get_stock_analysis(ticker)
                print(f"- {filing['timestamp']}: {filing['company']} ({ticker}) - {filing['form_type']}")
        else:
            print(".", end="", flush=True)

    scheduler.add_job(job, 'interval', minutes=1)
    print("Starting SEC monitor with stock analysis... Polling every minute. Press Ctrl+C to stop.")
    scheduler.start()
