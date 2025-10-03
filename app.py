import feedparser
import yfinance as yf
import requests
from datetime import datetime, timedelta
import sqlite3  # For tracking seen filings
import json
# Warning suppression (no urllib3 import needed)
import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
nltk.download('vader_lexicon', quiet=True)  # Runs once
def get_ticker(cik):
    try:
        with open('company_tickers.json', 'r') as f:
            data = json.load(f)
        cik_to_ticker = {}
        for entry in data.values():
            cik_raw = entry['cik_str']  # Number like 320193 or str
            cik_key = str(cik_raw).zfill(10)  # Pad to '0000320193'
            if cik_key not in cik_to_ticker:
                cik_to_ticker[cik_key] = entry['ticker']
        input_cik = str(cik).zfill(10)  # Pad input too
        return cik_to_ticker.get(input_cik, 'N/A')
    except Exception as e:
        print(f"Error loading ticker map: {e}")
        return 'N/A'
# Setup DB
conn = sqlite3.connect('sec_filings.db')
conn.execute('CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, timestamp DATETIME, form_type TEXT, cik TEXT, company TEXT)')

def get_stock_analysis(ticker):
    if ticker == 'N/A':
        return {'error': 'No ticker available'}
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            'current_price': info.get('currentPrice', 'N/A'),
            'recommendation': info.get('recommendationKey', 'N/A'),  # e.g., 'buy', 'hold'
            'target_price': info.get('targetMeanPrice', 'N/A'),
            'news_headlines': [n['title'] for n in stock.news[:3]]  # Top 3 recent news
        }
    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {e}")
        return {'error': 'Fetch failed'}

def predict_impact(filing, stock_data):
    sia = SentimentIntensityAnalyzer()
    form_impact = {
        '8-K': 0.2,  # Material events: often positive
        '10-Q': 0.1,  # Earnings: variable
        '10-K': 0.1,
        '4': -0.3,  # Insider sells often negative
        'SC 13D': 0.4,  # Activist ownership: bullish
        # Add more as needed
    }
    form_score = form_impact.get(filing['form_type'], 0)
    
    # Content sentiment from company/form (proxy; expand to full text later)
    desc_sent = sia.polarity_scores(filing['company'] + ' ' + filing['form_type'])['compound']
    
    # Stock sentiment (recommendation: buy=positive)
    rec_score = 0.3 if stock_data.get('recommendation') in ['buy', 'strong_buy'] else -0.2 if stock_data.get('recommendation') in ['sell', 'strong_sell'] else 0
    
    # News sentiment
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

def monitor_sec_filings():
    url = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&start=0&count=100&output=atom'
    feed = feedparser.parse(url)
    new_filings = []
    cutoff = datetime.now() - timedelta(minutes=60)
    
    for entry in feed.entries:
        try:
            timestamp = datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%SZ')  # Parse UTC timestamp
            if timestamp < cutoff:
                continue  # Skip older than 60 min (inside loop)
            filing_id = entry.id.split('/')[-1]  # Extract unique ID
            form_type = entry.title.split()[0]  # e.g., '8-K'
            company = entry.author  # Company name
            cik = entry.link.split('CIK=')[-1].split('&')[0]  # Extract CIK
            cik = str(cik).zfill(10)  # Pad to 10 digits (e.g., '0000320193')
            
            # Check if new
            if not conn.execute('SELECT id FROM filings WHERE id=?', (filing_id,)).fetchone():
                conn.execute('INSERT INTO filings VALUES (?, ?, ?, ?, ?)', (filing_id, timestamp, form_type, cik, company))
                conn.commit()
                new_filings.append({
                    'timestamp': timestamp,
                    'form_type': form_type,
                    'company': company,
                    'cik': cik,
                    'filing_link': entry.link,  # Link to filing page
                    'content_link': next((link['href'] for link in entry.links if 'txt' in link['href'] or 'xml' in link['href']), None)  # Better content link
                })
        except Exception as e:
            print(f"Error processing entry: {e}")
            continue  # Skip to next entry (inside loop)
    
    return new_filings

from apscheduler.schedulers.blocking import BlockingScheduler

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    def job():
        new_filings = monitor_sec_filings()
        if new_filings:
            print(f"\nFound {len(new_filings)} new filings in the last 60 minutes:")
            for filing in new_filings:
                ticker = get_ticker(filing['cik'])
                stock_data = get_stock_analysis(ticker)
                print(f"- {filing['timestamp']}: {filing['company']} ({ticker}) - {filing['form_type']}")
                print(f"  Stock: Price=${stock_data.get('current_price', 'N/A')}, Recommendation={stock_data.get('recommendation', 'N/A')}, Target=${stock_data.get('target_price', 'N/A')}")
                if 'news_headlines' in stock_data:
                    print(f"  Recent News: {', '.join(stock_data['news_headlines'][:2])}")  # First 2 headlines
                print(f"  Link: {filing['filing_link']}\n")
        else:
            print(".", end="", flush=True)  # Quiet dot every poll
    
    scheduler.add_job(job, 'interval', minutes=1)
    print("Starting SEC monitor with stock analysis... Polling every minute. Press Ctrl+C to stop.")
    scheduler.start()