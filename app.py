import requests
from bs4 import BeautifulSoup
import sqlite3
import datetime
import re
import time

DB_PATH = "sec_filings.db"

# --- Database setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS filings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT,
                    form_type TEXT,
                    accession_number TEXT,
                    filing_date TEXT,
                    filing_time TEXT,
                    link TEXT,
                    cik TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

# --- Scrape SEC Current Filings page ---
def scrape_sec_filings():
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    headers = {"User-Agent": "SECMonitorBot/1.0 (tushar@example.com)"}
    r = requests.get(url, headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    filings = []
    current_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        form_type = cols[0].get_text(strip=True)
        company = cols[1].get_text(strip=True)
        link_tag = cols[1].find("a", href=True)
        link = "https://www.sec.gov" + link_tag["href"] if link_tag else None
        accession_match = re.search(r"Accession Number:\s*([\d\-]+)", row.get_text())
        accession_number = accession_match.group(1) if accession_match else None

        accepted_text = cols[3].get_text(strip=True)
        if " " in accepted_text:
            filing_date, filing_time = accepted_text.split(" ", 1)
        else:
            filing_date, filing_time = current_date, accepted_text

        cik_match = re.search(r"\((\d{10})\)", company)
        cik = cik_match.group(1) if cik_match else None

        filings.append({
            "company": company,
            "form_type": form_type,
            "accession_number": accession_number,
            "filing_date": filing_date,
            "filing_time": filing_time,
            "link": link,
            "cik": cik
        })

    return filings

# --- Save to DB ---
def save_filings_to_db(filings):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    inserted_count = 0

    for f in filings:
        if not f["accession_number"]:
            continue

        c.execute("SELECT 1 FROM filings WHERE accession_number = ?", (f["accession_number"],))
        if c.fetchone():
            continue

        c.execute('''INSERT INTO filings (company, form_type, accession_number, filing_date,
                     filing_time, link, cik) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (f["company"], f["form_type"], f["accession_number"],
                   f["filing_date"], f["filing_time"], f["link"], f["cik"]))
        inserted_count += 1

    conn.commit()
    conn.close()
    return inserted_count

# --- Run Monitor ---
def monitor_sec_filings():
    print(f"Running SEC filings monitor at {datetime.datetime.utcnow()} UTC")
    filings = scrape_sec_filings()
    inserted = save_filings_to_db(filings)
    print(f"Inserted {inserted} new filings.")
    return inserted

# --- Utility functions used by dashboard.py ---
def get_recent_filings(limit=50):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT company, form_type, filing_date, filing_time, link FROM filings ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# Placeholder stubs for dashboard.py compatibility
def get_ticker(cik):
    return None

def get_stock_analysis(ticker):
    return {"summary": "No analysis available (placeholder)"}

def predict_impact(ticker, form_type):
    return "Neutral"

if __name__ == "__main__":
    init_db()
    while True:
        monitor_sec_filings()
        time.sleep(300)  # every 5 minutes
