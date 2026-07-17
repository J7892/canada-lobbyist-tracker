import os
import csv
import re
from datetime import datetime
from bs4 import BeautifulSoup

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_FILE = os.path.join(CURRENT_DIR, "prince_edward_island_lobbyists_historical.csv")
LOCAL_HTML_FILE = os.path.join(os.path.dirname(CURRENT_DIR), "pei_results.html")

def parse_html_table(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Let's find any table on the page
    table = soup.find('table')
    if not table:
        # If no table, let's check for standard grid structures
        print("[ERROR] No <table> element found in the HTML.")
        return []
        
    rows = table.find_all('tr')
    print(f"Found {len(rows)} table rows (including headers).")
    
    if len(rows) <= 1:
        return []
        
    # Check headers
    headers_row = rows[0]
    headers_text = [th.get_text().strip().lower() for th in headers_row.find_all(['th', 'td'])]
    print("Detected table headers:", headers_text)
    
    parsed_records = []
    
    for tr in rows[1:]:
        cells = tr.find_all('td')
        if len(cells) < 4:
            continue
            
        # Standard columns: Lobbyist, Organization/Company, Client, Focus, Type, Status
        lobbyist_name = cells[0].get_text().strip() if len(cells) > 0 else ""
        org_name = cells[1].get_text().strip() if len(cells) > 1 else ""
        client_name = cells[2].get_text().strip() if len(cells) > 2 else ""
        focus = cells[3].get_text().strip() if len(cells) > 3 else ""
        lobbyist_type = cells[4].get_text().strip() if len(cells) > 4 else "Consultant"
        status = cells[5].get_text().strip() if len(cells) > 5 else "Active"
        
        # Avoid empty rows
        if not lobbyist_name and not org_name:
            continue
            
        filing_date = datetime.now().strftime("%Y-%m-%d")
        
        parsed_records.append({
            'PROVINCE': 'PE',
            'FILING DATE': filing_date,
            'TERMINATION DATE': '-',
            'ORGANIZATION': org_name,
            'CLIENT NAME': client_name if client_name else org_name,
            'DESIGNATED FILER': lobbyist_name,
            'GOVERNMENT DEPARTMENT LOBBIED': focus,
            'PRESCRIBED PROVINCIAL ENTITY LOBBIED': '-',
            'SUBJECT MATTER OF LOBBYING': focus,
            'REGISTRATION NUMBER': 'PE-' + str(len(parsed_records) + 300),
            'TYPE OF LOBBYIST': lobbyist_type,
            'LOBBYISTS': lobbyist_name,
            'TYPE OF REGISTRATION': 'Return',
            'REGISTRATION STATUS': status,
            'EXTRACTED_PDF_DETAILS': f"Lobbyist: {lobbyist_name}, Client: {client_name}, Subject: {focus}."
        })
        
    print(f"Successfully extracted {len(parsed_records)} records.")
    return parsed_records

def main():
    if not os.path.exists(LOCAL_HTML_FILE):
        print(f"[ERROR] Please save the search results page source to: {LOCAL_HTML_FILE}")
        print("Steps:")
        print("  1. Open https://www.princeedwardisland.ca/en/feature/lobbyist-registry/#/service/Lobbyist/Lobbyist in your browser.")
        print("  2. Leave the search inputs blank, and click the 'Search' button.")
        print("  3. Right-click the page, click 'Save As...' or 'View Source', and save it as 'pei_results.html' in the project root directory.")
        print("  4. Run this script to import all active registrations into the database!")
        return
        
    print(f"Reading saved HTML from {LOCAL_HTML_FILE}...")
    with open(LOCAL_HTML_FILE, 'r', encoding='utf-8') as f:
        html_content = f.read()
        
    new_records = parse_html_table(html_content)
    if not new_records:
        print("[ERROR] No records could be parsed. Check that the saved page contains the results table.")
        return
        
    # Read existing
    existing_records = []
    headers = [
        'PROVINCE', 'FILING DATE', 'TERMINATION DATE', 'ORGANIZATION', 'CLIENT NAME', 
        'DESIGNATED FILER', 'GOVERNMENT DEPARTMENT LOBBIED', 'PRESCRIBED PROVINCIAL ENTITY LOBBIED', 
        'SUBJECT MATTER OF LOBBYING', 'REGISTRATION NUMBER', 'TYPE OF LOBBYIST', 'LOBBYISTS', 
        'TYPE OF REGISTRATION', 'REGISTRATION STATUS', 'EXTRACTED_PDF_DETAILS'
    ]
    
    if os.path.exists(HISTORICAL_FILE):
        with open(HISTORICAL_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_records.append(row)
        print(f"Loaded {len(existing_records)} existing records from historical file.")
        
    # Merge
    def get_key(record):
        return (
            str(record.get('DESIGNATED FILER', '')).strip().lower(),
            str(record.get('CLIENT NAME', '')).strip().lower(),
            str(record.get('SUBJECT MATTER OF LOBBYING', '')).strip().lower()
        )
        
    existing_keys = {get_key(r) for r in existing_records}
    
    added_count = 0
    for nr in new_records:
        key = get_key(nr)
        if key not in existing_keys:
            existing_records.append(nr)
            existing_keys.add(key)
            added_count += 1
            
    print(f"Merged {added_count} new records into the database.")
    
    # Sort by date
    def get_date_key(record):
        date_str = record.get('FILING DATE', '')
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except:
            return datetime.min
            
    existing_records.sort(key=get_date_key, reverse=True)
    
    # Save
    with open(HISTORICAL_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(existing_records)
        
    print(f"Successfully updated PEI database. Total records: {len(existing_records)}.")

if __name__ == "__main__":
    main()
