import os
import csv
import json
import time
import hashlib
import hmac
import base64
from datetime import datetime, timedelta
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
    
    # Retry logic up to 3 times
    for attempt in range(3):
        try:
            timestamp, signature, body_str = get_signature("POST", "search", "", payload)
            
            headers = HEADERS_TEMPLATE.copy()
            headers["X-Public-Timestamp"] = timestamp;
            headers["X-Public-Signature"] = signature;
            
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
        # e.g., "2026-07-02T21:03:50.041Z" -> "2026-07-02"
        return iso_str.split("T")[0]
    except Exception:
        return iso_str

def map_row(item):
    # Mapping to unified schema
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

def run_backfill():
    print("=========================================")
    print("STARTING QUEBEC HISTORICAL BACKFILL (90 DAYS)")
    print("=========================================\n")
    
    # We will fetch data day by day for the last 90 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    all_mapped_rows = []
    seen_ids = set()
    
    current_date = end_date
    days_fetched = 0
    
    while current_date >= start_date:
        day_str = current_date.strftime("%Y-%m-%d")
        print(f"Fetching day {day_str} ({days_fetched+1}/91)...")
        
        data = query_day(day_str)
        if data:
            items = data.get("items", [])
            total = data.get("total", 0)
            print(f"  Found {len(items)} items (total available: {total})")
            
            day_mapped = 0
            for item in items:
                # Deduplicate based on base declaration initialization or full declarationNo
                decl_no = item.get("declarationNo")
                if decl_no and decl_no not in seen_ids:
                    seen_ids.add(decl_no)
                    mapped = map_row(item)
                    all_mapped_rows.append(mapped)
                    day_mapped += 1
            print(f"  Added {day_mapped} new unique items.")
        else:
            print("  Failed or empty response for this day.")
            
        current_date -= timedelta(days=1)
        days_fetched += 1
        time.sleep(0.5) # rate limit delay
        
    print(f"\nBackfill fetch complete. Mapped {len(all_mapped_rows)} unique rows total.")
    
    # Sort descending by FILING DATE
    all_mapped_rows.sort(key=lambda x: x.get('FILING DATE', ''), reverse=True)
    
    # Headers
    headers = [
        'PROVINCE', 'FILING DATE', 'TERMINATION DATE', 'ORGANIZATION', 'CLIENT NAME', 
        'DESIGNATED FILER', 'GOVERNMENT DEPARTMENT LOBBIED', 'PRESCRIBED PROVINCIAL ENTITY LOBBIED', 
        'SUBJECT MATTER OF LOBBYING', 'REGISTRATION NUMBER', 'TYPE OF LOBBYIST', 'LOBBYISTS', 
        'TYPE OF REGISTRATION', 'REGISTRATION STATUS', 'EXTRACTED_PDF_DETAILS'
    ]
    
    os.makedirs(CURRENT_DIR, exist_ok=True)
    with open(HISTORICAL_DATA_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(all_mapped_rows)
        
    print(f"Saved {len(all_mapped_rows)} rows to {HISTORICAL_DATA_FILE}")

if __name__ == "__main__":
    run_backfill()
