import os
import csv
import re
import sys
import time
import requests
import concurrent.futures
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(CURRENT_DIR, "manitoba_lobbyists_historical.csv")
BASE_URL = "https://registry.lobbyistregistrar.mb.ca"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def parse_date(date_str):
    if not date_str or date_str.strip() in ['-', '', 'Locale not set']:
        return '-'
    clean_str = " ".join(date_str.split())
    # Replace non-breaking space characters if any
    clean_str = clean_str.replace('\xa0', ' ')
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return clean_str

def get_active_registrations():
    print("Launching Playwright to fetch Manitoba active registrations...")
    url = "https://registry.lobbyistregistrar.mb.ca/lra/reporting/public/advanceSearch.do?method=reset"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        print("Page loaded. Submitting form...")
        
        page.select_option("select#publicReportForm_form_registrationRole", "all")
        page.select_option("select#publicReportForm_form_registrationStatus", "active")
        
        with page.expect_navigation(timeout=45000):
            page.click("img[alt=Search]")
            
        print("Search submitted. Page URL:", page.url)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
        
    soup = BeautifulSoup(html, 'html.parser')
    tbl = soup.find('table', class_='results')
    if not tbl:
        print("[FATAL ERROR] Search results table not found on page.")
        sys.exit(1)
        
    tbody = tbl.find('tbody')
    if not tbody:
        print("[FATAL ERROR] tbody not found in search results table.")
        sys.exit(1)
        
    rows = tbody.find_all('tr', recursive=False)[1:] # Skip header row
    print(f"Found {len(rows)} rows in search results.")
    
    registrations = []
    for idx, tr in enumerate(rows):
        cells = tr.find_all('td', recursive=False)
        if len(cells) < 7:
            continue
            
        link = cells[0].find('a')
        if not link:
            continue
            
        href = link.get('href', '')
        reg_id_match = re.search(r'registrationId=(\d+)', href)
        if not reg_id_match:
            continue
        reg_id = reg_id_match.group(1)
        
        name = link.get_text().strip()
        role = cells[1].get_text().strip()
        reg_type = cells[2].get_text().strip()
        status = cells[3].get_text().strip()
        status_date = parse_date(cells[4].get_text().strip())
        client = cells[5].get_text().strip()
        organization = cells[6].get_text().strip()
        
        firm = ""
        if len(cells) >= 8:
            firm = cells[7].get_text().strip()
            
        registrations.append({
            'registrationId': reg_id,
            'name': name,
            'role': role,
            'reg_type': reg_type,
            'status': status,
            'status_date': status_date,
            'client': client,
            'organization': organization,
            'firm': firm
        })
        
    print(f"Parsed {len(registrations)} registration rows.")
    return registrations

def fetch_org_details(reg_id, search_row_date):
    detail_url = f"{BASE_URL}/lra/reporting/public/registrar/view.do?method=get&registrationId={reg_id}"
    
    # Use requests Session to maintain JSESSIONID
    session = requests.Session()
    
    for attempt in range(3):
        try:
            time.sleep(0.1) # Small delay to be gentle
            res = session.get(detail_url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            
            soup = BeautifulSoup(res.text, 'html.parser')
            # Check if we got content or empty page template loop
            main_col = soup.find(id='mainColumn')
            if not main_col or 'Senior Officer Contact Information' not in main_col.get_text():
                # If we get no actual content, we fallback to treating it like a consultant row
                return None
                
            # Parse Senior Officer
            filer = ""
            for tr in soup.find_all('tr'):
                cells = [c.get_text().strip() for c in tr.find_all('td') if c.get_text().strip()]
                if len(cells) >= 2:
                    if 'Surname:' in cells[0]:
                        filer = cells[1]
                    elif 'First Name:' in cells[0]:
                        filer = f"{cells[1]} {filer}".strip()
            
            # Parse Organization Summary
            org_summary = ""
            org_desc = ""
            for tr in soup.find_all('tr'):
                cells = [c.get_text().strip() for c in tr.find_all('td') if c.get_text().strip()]
                if len(cells) >= 2:
                    if 'Organization business or activity summary:' in cells[0]:
                        org_summary = cells[1]
                    elif 'Description of Organization:' in cells[0]:
                        org_desc = cells[1]
            
            # Parse Government Funding
            funding_list = []
            funding_tbl = None
            for tbl in soup.find_all('table'):
                headers = [th.get_text().strip() for th in tbl.find_all('th')]
                if 'Amount of Funding' in headers:
                    funding_tbl = tbl
                    break
            if funding_tbl:
                for r in funding_tbl.find_all('tr')[1:]:
                    cells = [c.get_text().strip() for c in r.find_all('td') if c.get_text().strip()]
                    if len(cells) >= 2 and 'No records found' not in cells[0]:
                        funding_list.append(f"{cells[0]}: {cells[1]}")
            funding_str = "; ".join(funding_list)
            
            # Parse Lobbyists Table (Table 13/Checked table)
            lobbyists_table = None
            for tbl in soup.find_all('table'):
                headers = [th.get_text().strip() for th in tbl.find_all('th')]
                if 'Lobbyist Name' in headers and 'Lobbying Activities' in headers:
                    lobbyists_table = tbl
                    break
            
            lobbyist_names = []
            subject_matters = set()
            departments = set()
            entities = set()
            activities_desc_list = []
            
            if lobbyists_table:
                tbody = lobbyists_table.find('tbody')
                rows = tbody.find_all('tr', recursive=False)[1:] if tbody else lobbyists_table.find_all('tr')[1:]
                for row in rows:
                    cells = row.find_all('td', recursive=False)
                    if len(cells) < 5:
                        continue
                    lob_name = cells[0].get_text().strip().replace('\xa0', ' ')
                    active_img = cells[3].find('img', alt='Checked')
                    if active_img or 'checked' in str(cells[3]).lower():
                        lobbyist_names.append(lob_name)
                        
                        # Fetch individual lobbyist popup
                        view_link = cells[4].find('a')
                        if view_link:
                            href = view_link.get('href', '')
                            # Parse seqNo, roleSeqNo, regId
                            params_match = re.search(r"seqNo=(\d+)&roleSeqNo=(\d+)&regId=(\d+)", href)
                            if params_match:
                                seq, role_seq, reg = params_match.groups()
                                popup_url = f"{BASE_URL}/lra/reporting/registrar/orglobbyistpopup.do?seqNo={seq}&roleSeqNo={role_seq}&regId={reg}"
                                try:
                                    popup_res = session.get(popup_url, headers=HEADERS, timeout=15)
                                    if popup_res.status_code == 200 and 'Lobbyists Registry - Organization Lobbyist' in popup_res.text:
                                        p_soup = BeautifulSoup(popup_res.text, 'html.parser')
                                        p_text = p_soup.get_text()
                                        
                                        # Parse Subject Matter
                                        sm_match = re.search(r"Subject Matter:\s*(.*)", p_text)
                                        if sm_match:
                                            subject_matters.add(sm_match.group(1).strip())
                                            
                                        # Parse Details of subject matter
                                        det_match = re.search(r"Details of subject matter and intended outcomes:\s*(.*?)\s*Target Contacts", p_text, re.DOTALL)
                                        if det_match:
                                            activities_desc_list.append(f"{lob_name}: {det_match.group(1).strip()}")
                                            
                                        # Parse Target Contacts
                                        target_tbl = None
                                        for p_tbl in p_soup.find_all('table'):
                                            p_headers = [th.get_text().strip() for th in p_tbl.find_all('th')]
                                            if 'Name of Person Targeted' in p_headers:
                                                target_tbl = p_tbl
                                                break
                                        if target_tbl:
                                            for p_r in target_tbl.find_all('tr')[1:]:
                                                p_cells = [c.get_text().strip() for c in p_r.find_all('td') if c.get_text().strip()]
                                                if len(p_cells) >= 4:
                                                    target_name = p_cells[1]
                                                    target_title = p_cells[2]
                                                    target_agency = p_cells[3]
                                                    if target_name:
                                                        entities.add(target_name)
                                                    if target_agency:
                                                        departments.add(target_agency)
                                except Exception as popup_err:
                                    print(f"      [WARNING] Error fetching popup for {lob_name} under registration {reg_id}: {popup_err}")
            
            lobbyists_str = ", ".join(lobbyist_names)
            subjects_str = "; ".join(sorted(list(subject_matters)))
            depts_str = "; ".join(sorted(list(departments)))
            entities_str = "; ".join(sorted(list(entities)))
            activities_str = " | ".join(activities_desc_list)
            
            extracted_text = f"LOBBYING DESCRIPTION: {activities_str}\n" \
                             f"ORGANIZATION DESCRIPTION: {org_desc}\n" \
                             f"BUSINESS SUMMARY: {org_summary}\n" \
                             f"GOVERNMENT FUNDING: {funding_str}"
            
            return {
                'DESIGNATED FILER': filer,
                'GOVERNMENT DEPARTMENT LOBBIED': depts_str if depts_str else '-',
                'PRESCRIBED PROVINCIAL ENTITY LOBBIED': entities_str if entities_str else '-',
                'SUBJECT MATTER OF LOBBYING': subjects_str if subjects_str else '-',
                'LOBBYISTS': lobbyists_str,
                'EXTRACTED_PDF_DETAILS': extracted_text
            }
            
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"    [WARNING] Error fetching detail for Organization {reg_id}: {e}")
                
    return None

def process_registration(reg, unique_dates):
    reg_id = reg['registrationId']
    reg_type = reg['reg_type']
    
    # 1. Common mapped values
    filing_date = reg['status_date'] if reg['status_date'] != '-' else unique_dates.get(reg_id, '-')
    
    # Normalize registration status
    status = 'Active' if reg['status'] == 'Active' else 'Terminated'
    
    # Format client/organization
    client_name = reg['client'] if reg['client'] else reg['organization']
    org_name = reg['organization'] if reg['organization'] else reg['firm']
    if not org_name:
        org_name = client_name
        
    lob_type = "Consultant" if 'Consultant' in reg_type else "In-House"
    
    # Default values
    filer = reg['name']
    depts_str = "-"
    entities_str = "-"
    subjects_str = "-"
    lobbyists_str = reg['name']
    extracted_text = f"LOBBYIST: {reg['name']} | CLIENT: {client_name} | FIRM: {reg['firm']} | STATUS: Active"
    
    # 2. Fetch full details for Organization filings
    if lob_type == "In-House":
        details = fetch_org_details(reg_id, filing_date)
        if details:
            filer = details['DESIGNATED FILER'] or filer
            depts_str = details['GOVERNMENT DEPARTMENT LOBBIED']
            entities_str = details['PRESCRIBED PROVINCIAL ENTITY LOBBIED']
            subjects_str = details['SUBJECT MATTER OF LOBBYING']
            lobbyists_str = details['LOBBYISTS'] or lobbyists_str
            extracted_text = details['EXTRACTED_PDF_DETAILS']
            
    return {
        'FILING DATE': filing_date,
        'TERMINATION DATE': '-',
        'ORGANIZATION': org_name,
        'CLIENT NAME': client_name,
        'DESIGNATED FILER': filer,
        'GOVERNMENT DEPARTMENT LOBBIED': depts_str,
        'PRESCRIBED PROVINCIAL ENTITY LOBBIED': entities_str,
        'SUBJECT MATTER OF LOBBYING': subjects_str,
        'REGISTRATION NUMBER': reg_id,
        'TYPE OF LOBBYIST': lob_type,
        'LOBBYISTS': lobbyists_str,
        'TYPE OF REGISTRATION': lob_type,
        'REGISTRATION STATUS': status,
        'EXTRACTED_PDF_DETAILS': extracted_text
    }

def run_backfill():
    registrations = get_active_registrations()
    if not registrations:
        print("No active registrations parsed.")
        return
        
    # Group by registrationId to find unique filings
    unique_regs = {}
    unique_dates = {}
    for r in registrations:
        reg_id = r['registrationId']
        # Keep the one with the latest date if duplicate
        if reg_id not in unique_regs:
            unique_regs[reg_id] = r
            unique_dates[reg_id] = r['status_date']
        else:
            # Overwrite if we find a later date
            existing_date = unique_dates[reg_id]
            current_date = r['status_date']
            if current_date != '-' and (existing_date == '-' or current_date > existing_date):
                unique_regs[reg_id] = r
                unique_dates[reg_id] = current_date
                
    print(f"Found {len(unique_regs)} unique registration IDs. Scraping details in parallel...")
    
    mapped_rows = []
    # Fetch details concurrently using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_reg = {
            executor.submit(process_registration, reg, unique_dates): reg 
            for reg in unique_regs.values()
        }
        
        count = 0
        total = len(unique_regs)
        for future in concurrent.futures.as_completed(future_to_reg):
            count += 1
            if count % 20 == 0 or count == total:
                print(f"  Progress: {count}/{total} details fetched...")
            try:
                mapped = future.result()
                if mapped:
                    mapped_rows.append(mapped)
            except Exception as exc:
                reg_obj = future_to_reg[future]
                print(f"Error processing registration {reg_obj['registrationId']}: {exc}")
                
    # Sort by filing date descending
    mapped_rows.sort(key=lambda x: x['FILING DATE'], reverse=True)
    
    # Save to CSV
    headers = [
        'FILING DATE', 'TERMINATION DATE', 'ORGANIZATION', 'CLIENT NAME', 'DESIGNATED FILER',
        'GOVERNMENT DEPARTMENT LOBBIED', 'PRESCRIBED PROVINCIAL ENTITY LOBBIED', 'SUBJECT MATTER OF LOBBYING',
        'REGISTRATION NUMBER', 'TYPE OF LOBBYIST', 'LOBBYISTS', 'TYPE OF REGISTRATION',
        'REGISTRATION STATUS', 'EXTRACTED_PDF_DETAILS'
    ]
    
    with open(OUTPUT_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(mapped_rows)
        
    print(f"\nManitoba historical database compiled successfully with {len(mapped_rows)} records!")
    print(f"Database saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    run_backfill()
