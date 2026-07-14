import os
import re
import csv
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings()

# Configuration
SEARCH_URL = "https://www.pxw1.snb.ca/snb9000/product.aspx?productid=A001PLOBBYSearch&l=e"
DETAILS_BASE_URL = "https://www.pxw1.snb.ca/snb9000/product.aspx?ProductID=A001PLOBBYDetailsA&ReturnID="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(CURRENT_DIR, "new_brunswick_lobbyists_historical.csv")

def format_date(date_str):
    if not date_str or date_str == '-':
        return '-'
    return date_str.split(' ')[0]

def parse_activities_subpage(html):
    soup = BeautifulSoup(html, 'html.parser')
    
    # Checked IDs
    checked_ids = []
    scripts = soup.find_all('script')
    for scr in scripts:
        match = re.search(r"var activities\s*=\s*'([^']*)'", scr.text)
        if match:
            checked_ids = [x.strip() for x in match.group(1).split(',') if x.strip()]
            break
            
    # Labels mapping
    cb_labels = {}
    for cb in soup.find_all('input', type='checkbox'):
        cb_id = cb.get('id')
        if cb_id and cb.next_sibling:
            cb_labels[cb_id] = cb.next_sibling.strip()
            
    subjects = []
    targets = []
    
    for cb in soup.find_all('input', type='checkbox'):
        cb_id = cb.get('id')
        cb_name = cb.get('name')
        if cb_id in checked_ids:
            label = cb_labels.get(cb_id, cb_id)
            if cb_name == 'Activity':
                subjects.append(label)
            elif cb_name == 'Target':
                targets.append(label)
                
    # Custom text fields
    target1 = soup.find('input', {'name': 'Target1'})
    if target1 and target1.get('value'):
        custom_tgt = target1.get('value').strip()
        if custom_tgt:
            targets.append(custom_tgt)
            
    activity1 = soup.find('input', {'name': 'Activity1'})
    if activity1 and activity1.get('value'):
        custom_act = activity1.get('value').strip()
        if custom_act:
            subjects.append(custom_act)
            
    # Focus description
    focus_text = ""
    question = "Which Members of the Legislative Assembly or senior public officials (name or title) do you intend to lobby and what is the focus of your lobbying activity?"
    for td in soup.find_all('td'):
        txt = td.text.strip().replace('\xa0', ' ')
        txt = " ".join(txt.split())
        if question in txt:
            after = txt.split(question)[-1].strip()
            suffix = "Don't use the following characters"
            if suffix in after:
                after = after.split(suffix)[0].strip()
            focus_text = after
            break
            
    return subjects, targets, focus_text

def fetch_lobbyist_details(session, return_id):
    url = f"{DETAILS_BASE_URL}{return_id}"
    r_detail = session.get(url, headers=HEADERS, verify=False, timeout=15)
    soup_detail = BeautifulSoup(r_detail.text, 'html.parser')
    
    inputs = soup_detail.find_all('input')
    post_payload = {}
    for inp in inputs:
        name = inp.get('name')
        val = inp.get('value', '')
        if name:
            post_payload[name] = val
            
    post_payload["__VIEWSTATE"] = soup_detail.find(id="__VIEWSTATE")['value'] if soup_detail.find(id="__VIEWSTATE") else ""
    post_payload["__VIEWSTATEGENERATOR"] = soup_detail.find(id="__VIEWSTATEGENERATOR")['value'] if soup_detail.find(id="__VIEWSTATEGENERATOR") else ""
    post_payload["__EVENTVALIDATION"] = soup_detail.find(id="__EVENTVALIDATION")['value'] if soup_detail.find(id="__EVENTVALIDATION") else ""
    post_payload["__EVENTTARGET"] = ""
    post_payload["__EVENTARGUMENT"] = ""
    post_payload["_ctl4:btnActivity"] = "View More"
    
    for k in list(post_payload.keys()):
        if k.startswith("_ctl4:btn") and k != "_ctl4:btnActivity":
            post_payload.pop(k)
            
    time.sleep(0.3)
    r_act = session.post(url, headers=HEADERS, data=post_payload, verify=False, timeout=15)
    
    subjects, targets, focus_text = parse_activities_subpage(r_act.text)
    
    lobbyist_first = post_payload.get('First_Name', '')
    lobbyist_last = post_payload.get('Last_Name', '')
    lobbyist_name = f"{lobbyist_first} {lobbyist_last}".strip()
    
    org_name = post_payload.get('Business_Name', '')
    client_name = post_payload.get('Client_Name', '')
    lobbyist_type = post_payload.get('ReturnType', '')
    filing_date = format_date(post_payload.get('ReturnDate', ''))
    status = post_payload.get('ReturnStatus', 'Active')
    reg_type = post_payload.get('Registration', 'Return')
    
    return {
        "PROVINCE": "NB",
        "FILING DATE": filing_date,
        "TERMINATION DATE": "-",
        "ORGANIZATION": org_name if org_name else "-",
        "CLIENT NAME": client_name if client_name else "-",
        "DESIGNATED FILER": lobbyist_name,
        "GOVERNMENT DEPARTMENT LOBBIED": "; ".join(targets) if targets else "-",
        "PRESCRIBED PROVINCIAL ENTITY LOBBIED": "-",
        "SUBJECT MATTER OF LOBBYING": "; ".join(subjects) if subjects else "-",
        "REGISTRATION NUMBER": return_id,
        "TYPE OF LOBBYIST": lobbyist_type if lobbyist_type else "-",
        "LOBBYISTS": lobbyist_name,
        "TYPE OF REGISTRATION": reg_type,
        "REGISTRATION STATUS": status,
        "EXTRACTED_PDF_DETAILS": focus_text if focus_text else "-"
    }

def run_scraper():
    print("====================================================")
    print("STARTING NEW BRUNSWICK LOBBYIST REGISTRY SCRAPER")
    print("====================================================")
    
    if not os.path.exists(OUTPUT_FILE):
        print("[ERROR] Historical ledger file not found. Run backfill first!")
        return
        
    # Read existing entries
    existing_records = {}
    with open(OUTPUT_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for r in reader:
            existing_records[r["REGISTRATION NUMBER"]] = r
            
    print(f"Loaded {len(existing_records)} existing filings from ledger.")
    
    session = requests.Session()
    
    # Retrieve tokens
    print("Fetching search form...")
    r_init = session.get(SEARCH_URL, headers=HEADERS, verify=False, timeout=15)
    soup_init = BeautifulSoup(r_init.text, 'html.parser')
    
    viewstate = soup_init.find(id="__VIEWSTATE")['value'] if soup_init.find(id="__VIEWSTATE") else ""
    viewstate_gen = soup_init.find(id="__VIEWSTATEGENERATOR")['value'] if soup_init.find(id="__VIEWSTATEGENERATOR") else ""
    event_validation = soup_init.find(id="__EVENTVALIDATION")['value'] if soup_init.find(id="__EVENTVALIDATION") else ""
    
    # Calculate date range for incremental scrape (past 15 days)
    end_date = datetime.now() + timedelta(days=2)
    start_date = datetime.now() - timedelta(days=15)
    
    date_to = end_date.strftime("%Y/%m/%d")
    date_from = start_date.strftime("%Y/%m/%d")
    
    print(f"Querying updates submitted between {date_from} and {date_to}...")
    
    payload = {
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstate_gen,
        "__EVENTVALIDATION": event_validation,
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "Target": "",
        "Client_Name": "",
        "First_Name": "",
        "Last_Name": "",
        "WorkorderStatus": "", # Search all statuses to capture terminations/inactivations
        "Search_Date_from": date_from,
        "Search_Date_to": date_to,
        "_ctl4:btnSubmit": "Search"
    }
    
    r_search = session.post(SEARCH_URL, headers=HEADERS, data=payload, verify=False, timeout=15)
    soup_search = BeautifulSoup(r_search.text, 'html.parser')
    
    # Check if there are matches
    table = None
    for t in soup_search.find_all('table'):
        if 'View Return' in t.text:
            table = t
            break
            
    if not table:
        print("[INFO] No recent transaction updates found in the specified range. Database is up-to-date.")
        return
        
    rows = table.find_all('tr')[1:] # Skip header
    print(f"Found {len(rows)} potential transaction updates.")
    
    updates_made = 0
    
    for row in rows:
        cells = [td.text.strip() for td in row.find_all('td')]
        link_tag = row.find('a')
        if not link_tag:
            continue
            
        href = link_tag.get('href', '')
        match = re.search(r"ReturnID=(\d+)", href)
        if not match:
            continue
            
        return_id = match.group(1)
        grid_date = format_date(cells[0])
        grid_status = cells[5]
        
        # Check if record is new or updated
        needs_scrape = False
        if return_id not in existing_records:
            print(f"  New Return ID detected: {return_id}")
            needs_scrape = True
        else:
            existing = existing_records[return_id]
            if existing["FILING DATE"] != grid_date or existing["REGISTRATION STATUS"] != grid_status:
                print(f"  Updated Return ID detected: {return_id} (Filing Date: {existing['FILING DATE']} -> {grid_date} | Status: {existing['REGISTRATION STATUS']} -> {grid_status})")
                needs_scrape = True
                
        if needs_scrape:
            try:
                record = fetch_lobbyist_details(session, return_id)
                existing_records[return_id] = record
                updates_made += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  [ERROR] Failed to fetch update for {return_id}: {e}")
                
    if updates_made > 0:
        print(f"\n[INFO] Saving {updates_made} updates to database...")
        # Compile final sorted records list
        all_records = list(existing_records.values())
        all_records.sort(key=lambda x: x["FILING DATE"], reverse=True)
        
        with open(OUTPUT_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_records)
            
        print(f"[SUCCESS] Scraper sync complete. Database updated.")
    else:
        print("\n[INFO] No changes needed. Database is fully in sync.")
        
    print("====================================================")

if __name__ == "__main__":
    run_scraper()
