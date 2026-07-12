import os
import csv
import sys
import time
import json
import hashlib
import hmac
import base64
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "quebec_lobbyists_historical.csv")

SHARED_SECRET = "7f439088-6e80-4d97-868a-5b9c2c4614b2"
SUBSCRIPTION_KEY = "1f890884f0f44a918119d079665a5a15"
URL = "https://be-prod-api.azure-api.net/api/clq/public-api/search"

HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY,
    "Referer": "https://www.carrefourlobby.quebec/",
    "Origin": "https://www.carrefourlobby.quebec"
}

def send_email_digest(html_content, subject_text="Daily Quebec Lobbyist Registry Update"):
    """Connects to Gmail SMTP to send daily updates."""
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL")
    
    if not all([username, password, recipient]):
        print("[WARNING] Email credentials missing from environments. Skipping notification.")
        return

    smtp_server = "smtp.gmail.com"
    smtp_port = 587

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject_text
    msg["From"] = username
    msg["To"] = recipient

    msg.attach(MIMEText(html_content, "html"))

    try:
        print(f"Opening secure encrypted transport channel to {smtp_server}...")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, recipient, msg.as_string())
        print(f"Success! Daily update digest sent safely to target address: {recipient}")
    except Exception as email_fault:
        print(f"[ERROR] Mail pipeline transmission dropped: {str(email_fault)}")

def get_signature(method, path, query, body_dict):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body_dict, separators=(',', ':'), ensure_ascii=False) if body_dict is not None else ""
    body_bytes = body_str.encode('utf-8')
    sha256_hash = hashlib.sha256(body_bytes).digest()
    sha256_base64 = base64.b64encode(sha256_hash).decode('utf-8')
    message = f"{timestamp}:{method}:{path}:{query}:{sha256_base64}"
    
    secret_bytes = SHARED_SECRET.encode('utf-8')
    message_bytes = message.encode('utf-8')
    hmac_digest = hmac.new(secret_bytes, message_bytes, hashlib.sha256).digest()
    signature = base64.b64encode(hmac_digest).decode('utf-8')
    return timestamp, signature, body_str

def query_day(day_str):
    payload = {
        "searchterms": "*",
        "entrepclient": None,
        "neq": "",
        "lobbyist": None,
        "maxhits": 200,
        "institution": None,
        "activeOnly": True,
        "fromDate": day_str,
        "toDate": day_str,
        "dateType": "publication",
        "source": "new"
    }
    
    for attempt in range(3):
        try:
            timestamp, signature, body_str = get_signature("POST", "search", "", payload)
            
            headers = HEADERS_TEMPLATE.copy()
            headers["X-Public-Timestamp"] = timestamp
            headers["X-Public-Signature"] = signature
            
            res = requests.post(url=URL, data=body_str.encode('utf-8'), headers=headers, timeout=15)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 400:
                print(f"[WARNING] 400 response on day {day_str}: {res.text}")
                return None
            else:
                print(f"[WARNING] Attempt {attempt+1} failed with status {res.status_code} for day {day_str}")
        except Exception as e:
            print(f"[WARNING] Attempt {attempt+1} encountered exception: {e}")
        time.sleep(2 * (attempt + 1))
    return None

def format_date(iso_str):
    if not iso_str:
        return ""
    try:
        return iso_str.split("T")[0]
    except Exception:
        return iso_str

def map_row(item):
    lobby_type = item.get("lobbyType", "")
    normalized_type = "Consultant" if lobby_type == "LOC" else "In-House"
    
    org_name = (item.get("enterpriseName") or "").strip()
    client_name = (item.get("enterpriseName") or "").strip()
    
    designated_filer = (item.get("lobbyistName") or "").strip()
    lobbyists_str = (item.get("lobbyistName") or "").strip()
    
    subject_matter = (item.get("mandateSummary") or "").strip()
    
    filing_date = format_date(item.get("publishedDate") or item.get("lastUpdate"))
    
    status = (item.get("status") or "active").capitalize()
    
    return {
        'PROVINCE': 'QC',
        'FILING DATE': filing_date,
        'TERMINATION DATE': '-',
        'ORGANIZATION': org_name,
        'CLIENT NAME': client_name,
        'DESIGNATED FILER': designated_filer,
        'GOVERNMENT DEPARTMENT LOBBIED': '-',
        'PRESCRIBED PROVINCIAL ENTITY LOBBIED': '-',
        'SUBJECT MATTER OF LOBBYING': subject_matter,
        'REGISTRATION NUMBER': item.get("declarationNo", ""),
        'TYPE OF LOBBYIST': normalized_type,
        'LOBBYISTS': lobbyists_str,
        'TYPE OF REGISTRATION': 'Mandat',
        'REGISTRATION STATUS': status,
        'EXTRACTED_PDF_DETAILS': subject_matter
    }

def execute_daily_scrape():
    print("Initiating incremental Quebec lobbyist scraper check...")
    
    if not os.path.exists(HISTORICAL_DATA_FILE):
        print(f"[FATAL] Reference historical ledger not found: {HISTORICAL_DATA_FILE}")
        sys.exit(1)
        
    with open(HISTORICAL_DATA_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        historical_rows = list(reader)
        
    existing_versions = set((row.get("REGISTRATION NUMBER") or '').strip() for row in historical_rows)
    print(f"Loaded master archive. Found {len(existing_versions)} unique registration versions.")

    # Fetch updates from the last 2 days
    today = datetime.now()
    new_filings = []
    
    for i in range(2):
        day_str = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        print(f"Checking updates published on {day_str}...")
        
        data = query_day(day_str)
        if data:
            items = data.get("items", [])
            print(f"  Found {len(items)} items on {day_str}")
            for item in items:
                decl_no = (item.get("declarationNo") or "").strip()
                if decl_no and decl_no not in existing_versions:
                    mapped = map_row(item)
                    new_filings.append(mapped)
                    existing_versions.add(decl_no)
                    print(f"  [NEW ROW FOUND] Version: {decl_no} | Org: {mapped['ORGANIZATION']}")
        time.sleep(0.5)

    if not new_filings:
        print("No new registrations found. Quebec database is up to date.")
        return

    print(f"Syncing: Prepended {len(new_filings)} new filings to historical ledger.")
    
    # Sort new filings by filing date descending
    new_filings.sort(key=lambda x: x.get('FILING DATE', ''), reverse=True)
    
    # Combine (new filings first, then historical)
    combined_rows = new_filings + historical_rows
    
    # Write back to CSV
    with open(HISTORICAL_DATA_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined_rows)
    print("Ledger saved successfully.")

    # Email digest formatting
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .badge {{ padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }}
            .active {{ background-color: #d1e7dd; color: #0f5132; }}
            .inactive {{ background-color: #f8d7da; color: #842029; }}
        </style>
    </head>
    <body>
        <h2>Daily Quebec Lobbyist Registry Scrape Digest</h2>
        <p>Found <strong>{len(new_filings)}</strong> new filing disclosures posted in the Quebec Registry in the last 2 days.</p>
        <table>
            <thead>
                <tr>
                    <th>Filing Date</th>
                    <th>Organization / Client</th>
                    <th>Lobbyists</th>
                    <th>Subject Matter</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for row in new_filings:
        status_style = "active" if "active" in row['REGISTRATION STATUS'].lower() else "inactive"
        html_body += f"""
            <tr>
                <td>{row['FILING DATE']}</td>
                <td><strong>{row['ORGANIZATION']}</strong><br><small>Client: {row['CLIENT NAME']}</small></td>
                <td>{row['LOBBYISTS']}</td>
                <td>{row['SUBJECT MATTER OF LOBBYING']}</td>
                <td><span class="badge {status_style}">{row['REGISTRATION STATUS']}</span></td>
            </tr>
        """
        
    html_body += """
            </tbody>
        </table>
        <p>Registry Monitor automated system.</p>
    </body>
    </html>
    """
    
    send_email_digest(html_body)

if __name__ == "__main__":
    execute_daily_scrape()
