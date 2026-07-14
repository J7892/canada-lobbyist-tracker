import os
import re
import csv
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    # 1. Find checked checkbox IDs from JavaScript block
    checked_ids = []
    scripts = soup.find_all('script')
    for scr in scripts:
        match = re.search(r"var activities\s*=\s*'([^']*)'", scr.text)
        if match:
            checked_ids = [x.strip() for x in match.group(1).split(',') if x.strip()]
            break
            
    # 2. Build mapping of checkboxes to their labels
    cb_labels = {}
    for cb in soup.find_all('input', type='checkbox'):
        cb_id = cb.get('id')
        if cb_id and cb.next_sibling:
            cb_labels[cb_id] = cb.next_sibling.strip()
            
    subjects = []
    targets = []
    
    # 3. Classify checked IDs into subjects and targets
    for cb in soup.find_all('input', type='checkbox'):
        cb_id = cb.get('id')
        cb_name = cb.get('name')
        if cb_id in checked_ids:
            label = cb_labels.get(cb_id, cb_id)
            if cb_name == 'Activity':
                subjects.append(label)
            elif cb_name == 'Target':
                targets.append(label)
                
    # 4. Check for text inputs containing custom target/activities
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
            
    # 5. Extract lobbying focus description text
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

def fetch_lobbyist_details(return_id):
    url = f"{DETAILS_BASE_URL}{return_id}"
    session = requests.Session()
    
    r_detail = session.get(url, headers=HEADERS, verify=False, timeout=25)
    soup_detail = BeautifulSoup(r_detail.text, 'html.parser')
    
    # Extract hidden input values to build subsequent POST
    inputs = soup_detail.find_all('input')
    post_payload = {}
    for inp in inputs:
        name = inp.get('name')
        val = inp.get('value', '')
        if name:
            post_payload[name] = val
            
    # Explicitly set ViewState and Action buttons
    post_payload["__VIEWSTATE"] = soup_detail.find(id="__VIEWSTATE")['value'] if soup_detail.find(id="__VIEWSTATE") else ""
    post_payload["__VIEWSTATEGENERATOR"] = soup_detail.find(id="__VIEWSTATEGENERATOR")['value'] if soup_detail.find(id="__VIEWSTATEGENERATOR") else ""
    post_payload["__EVENTVALIDATION"] = soup_detail.find(id="__EVENTVALIDATION")['value'] if soup_detail.find(id="__EVENTVALIDATION") else ""
    post_payload["__EVENTTARGET"] = ""
    post_payload["__EVENTARGUMENT"] = ""
    post_payload["_ctl4:btnActivity"] = "View More"
    
    # Remove other button names
    for k in list(post_payload.keys()):
        if k.startswith("_ctl4:btn") and k != "_ctl4:btnActivity":
            post_payload.pop(k)
            
    # Post back to retrieve the lobbying activities subpage
    r_act = session.post(url, headers=HEADERS, data=post_payload, verify=False, timeout=25)
    
    subjects, targets, focus_text = parse_activities_subpage(r_act.text)
    
    # Re-extract clean metadata values from hidden detail inputs
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

def run_backfill():
    print("====================================================")
    print("STARTING NEW BRUNSWICK HISTORICAL BACKFILL CRAWLER")
    print("====================================================")
    
    session = requests.Session()
    
    # 1. Retrieve initial search page tokens
    print("Fetching search form...")
    r_init = session.get(SEARCH_URL, headers=HEADERS, verify=False, timeout=25)
    soup_init = BeautifulSoup(r_init.text, 'html.parser')
    
    viewstate = soup_init.find(id="__VIEWSTATE")['value'] if soup_init.find(id="__VIEWSTATE") else ""
    viewstate_gen = soup_init.find(id="__VIEWSTATEGENERATOR")['value'] if soup_init.find(id="__VIEWSTATEGENERATOR") else ""
    event_validation = soup_init.find(id="__EVENTVALIDATION")['value'] if soup_init.find(id="__EVENTVALIDATION") else ""
    
    # 2. POST wide date range query to fetch all active filings
    print("Posting search query for active lobbyist registrations...")
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
        "WorkorderStatus": "Active",
        "Search_Date_from": "2010/01/01",
        "Search_Date_to": "2026/12/31",
        "_ctl4:btnSubmit": "Search"
    }
    
    r_search = session.post(SEARCH_URL, headers=HEADERS, data=payload, verify=False, timeout=25)
    soup_search = BeautifulSoup(r_search.text, 'html.parser')
    
    # 3. Locate results table and compile active list
    table = None
    for t in soup_search.find_all('table'):
        if 'View Return' in t.text:
            table = t
            break
            
    if not table:
        print("[ERROR] Search results table not found. Double check search criteria!")
        return
        
    rows = table.find_all('tr')[1:] # Skip header row
    print(f"Found {len(rows)} active filings in New Brunswick registry search index.")
    
    return_ids = []
    for row in rows:
        link_tag = row.find('a')
        if not link_tag:
            continue
        href = link_tag.get('href', '')
        match = re.search(r"ReturnID=(\d+)", href)
        if match:
            return_ids.append(match.group(1))
            
    records = []
    completed = 0
    total = len(return_ids)
    
    # 4. Fetch details in parallel using ThreadPoolExecutor
    print(f"Spawning thread pool with 12 workers to retrieve {total} detail returns...")
    with ThreadPoolExecutor(max_workers=12) as executor:
        future_to_id = {executor.submit(fetch_lobbyist_details, rid): rid for rid in return_ids}
        
        for future in as_completed(future_to_id):
            rid = future_to_id[future]
            completed += 1
            try:
                record = future.result()
                records.append(record)
                if completed % 10 == 0 or completed == total:
                    print(f"Progress: [{completed}/{total}] detailed pages retrieved ({len(records)} successes).")
            except Exception as e:
                print(f"  [ERROR] Failed to fetch details for ReturnID {rid}: {e}")
                
    # Sort records descending by filing date
    records.sort(key=lambda x: x["FILING DATE"], reverse=True)
    
    # Write to CSV
    headers = [
        "PROVINCE", "FILING DATE", "TERMINATION DATE", "ORGANIZATION", "CLIENT NAME",
        "DESIGNATED FILER", "GOVERNMENT DEPARTMENT LOBBIED", "PRESCRIBED PROVINCIAL ENTITY LOBBIED",
        "SUBJECT MATTER OF LOBBYING", "REGISTRATION NUMBER", "TYPE OF LOBBYIST", "LOBBYISTS",
        "TYPE OF REGISTRATION", "REGISTRATION STATUS", "EXTRACTED_PDF_DETAILS"
    ]
    
    with open(OUTPUT_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(records)
            
    print(f"\n[SUCCESS] Backfill complete. Generated {len(records)} entries in: {OUTPUT_FILE}")
    print("====================================================")

if __name__ == "__main__":
    run_backfill()
