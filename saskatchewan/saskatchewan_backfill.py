import os
import csv
import sys
import time
import requests
import concurrent.futures

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(CURRENT_DIR, "saskatchewan_lobbyists_historical.csv")
SEARCH_URL = "https://forms.sasklobbyistregistry.ca/api/Search/RegistrationVersions"
DETAIL_URL = "https://forms.sasklobbyistregistry.ca/api/registrationversion/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def fetch_all_versions():
    print("Fetching Saskatchewan registration headers since 2025-01-01...")
    payload = {
        'EffectiveFromDate': '',
        'EffectiveToDate': '',
        'PostedFromDate': '2025-01-01',
        'PostedToDate': '',
        'Keywords': '',
        'DescriptionOfLobbyingActivities': '',
        'Lobbyists': '',
        'ClientOrganization': '',
        'MLA': [],
        'Minister': [],
        'GovernmentInstitution': [],
        'SubjectMatter': [],
        'Category': [],
        'RegistrationStatus': [],
        'start': 0,
        'length': 10000,  # Grab all at once
        'draw': 1
    }
    
    try:
        res = requests.post(SEARCH_URL, headers=HEADERS, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        records = data.get('data', [])
        print(f"Successfully retrieved {len(records)} header records.")
        return records
    except Exception as e:
        print(f"[FATAL ERROR] Failed to retrieve headers: {e}")
        sys.exit(1)

def fetch_detail(record):
    url_str = record.get('Url', '')
    if not url_str or 'id=' not in url_str:
        return None
        
    id_val = url_str.split('id=')[-1].strip()
    
    # Retry loop with backoff
    for attempt in range(4):
        try:
            # Slower concurrent requests to respect server connection limits
            time.sleep(0.15)
            res = requests.get(f"{DETAIL_URL}?id={id_val}", headers=HEADERS, timeout=20)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            if attempt < 3:
                # Wait longer on each attempt
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[WARNING] Failed to fetch details for ID {id_val} after {attempt+1} attempts: {e}")
    return None

def map_record(detail):
    if not detail:
        return None
        
    is_consultant = detail.get('IsConsultant', False)
    
    # 1. Organization & Client Name
    client_dict = detail.get('Client') or {}
    client_name = (client_dict.get('Name') or '').strip()
    
    if is_consultant:
        firm_dict = detail.get('ConsultingFirm') or {}
        org_name = (firm_dict.get('Name') or '').strip()
    else:
        org_name = client_name
        
    # 2. Designated Filer
    df_first = detail.get('DFFirstName') or ''
    df_last = detail.get('DFLastName') or ''
    designated_filer = f"{df_first} {df_last}".strip()
    
    # 3. Government Institutions Lobbied
    ministries_set = set()
    for m in detail.get('Ministries') or []:
        if m: ministries_set.add(m.strip())
        
    for minister in detail.get('Ministers') or []:
        m_name = minister.get('Ministry')
        if m_name: ministries_set.add(m_name.strip())
        
    for oph in detail.get('OtherPublicOfficeHolders') or []:
        list_name = oph.get('List')
        if list_name: ministries_set.add(list_name.strip())
        
    dept_lobbied = "; ".join(sorted(list(ministries_set)))
    
    # 4. MLAs Lobbied (Prescribed Entities)
    mla_list = []
    for mla in detail.get('MLA') or []:
        first = mla.get('FirstName') or ''
        last = mla.get('LastName') or ''
        name = f"{first} {last}".strip()
        if name: mla_list.append(name)
    entity_lobbied = "; ".join(sorted(mla_list))
    
    # 5. Subject Matter
    subjects_set = set()
    activities = detail.get('LobbyingActivities') or []
    for act in activities:
        for sm in act.get('SubjectMatters') or []:
            if sm: subjects_set.add(sm.strip())
    subject_matter = "; ".join(sorted(list(subjects_set)))
    
    # 6. Lobbyists List
    lobbyists_list = []
    for lob in detail.get('Lobbyists') or []:
        first = lob.get('FirstName') or ''
        last = lob.get('LastName') or ''
        name = f"{first} {last}".strip()
        if name: lobbyists_list.append(name)
    lobbyists_str = ", ".join(lobbyists_list)
    
    # 7. Type of registration
    lobbyist_type = "Consultant" if is_consultant else "In-House"
    
    # 8. Date bounds
    filing_date = detail.get('AcceptedDate') or detail.get('EffectiveDate') or ''
    termination_date = detail.get('EndDate') or ''
    
    # Normalize termination date if null/empty
    if termination_date == 'None' or not termination_date:
        termination_date = '-'
        
    # 9. Structured PDF details
    desc_list = [act.get('Description', '').strip() for act in activities if act.get('Description')]
    desc_str = " | ".join(desc_list)
    
    client_desc = (detail.get('ClientBusinessActivityDescription') or '').strip()
    
    poh_list = []
    for oph in detail.get('OtherPublicOfficeHolders') or []:
        first = oph.get('FirstName') or ''
        last = oph.get('LastName') or ''
        title = oph.get('PositionTitle') or ''
        poh_list.append(f"{first} {last} ({title})")
    poh_str = ", ".join(poh_list)
    
    funding_list = []
    for fund in detail.get('GovernmentFunding') or []:
        source = fund.get('GovernmentInstitutionName') or ''
        amount = fund.get('Amount') or ''
        funding_list.append(f"{source}: {amount}")
    funding_str = ", ".join(funding_list)
    
    extracted_text = f"LOBBYING DESCRIPTION: {desc_str}\n" \
                     f"CLIENT BUSINESS ACTIVITY: {client_desc}\n" \
                     f"MLAS LOBBIED: {entity_lobbied}\n" \
                     f"OTHER OFFICE HOLDERS: {poh_str}\n" \
                     f"GOVERNMENT FUNDING: {funding_str}"
    
    return {
        'FILING DATE': filing_date,
        'TERMINATION DATE': termination_date,
        'ORGANIZATION': org_name,
        'CLIENT NAME': client_name,
        'DESIGNATED FILER': designated_filer,
        'GOVERNMENT DEPARTMENT LOBBIED': dept_lobbied,
        'PRESCRIBED PROVINCIAL ENTITY LOBBIED': entity_lobbied,
        'SUBJECT MATTER OF LOBBYING': subject_matter,
        'REGISTRATION NUMBER': detail.get('RegistrationVersionNumber', ''),
        'TYPE OF LOBBYIST': lobbyist_type,
        'LOBBYISTS': lobbyists_str,
        'TYPE OF REGISTRATION': lobbyist_type,
        'REGISTRATION STATUS': detail.get('RegistrationStatus', ''),
        'EXTRACTED_PDF_DETAILS': extracted_text
    }

def run_backfill():
    records = fetch_all_versions()
    if not records:
        print("No records found to backfill.")
        return
        
    print(f"Downloading details for {len(records)} records in parallel...")
    
    detailed_results = []
    # Fetch details concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_rec = {executor.submit(fetch_detail, rec): rec for rec in records}
        count = 0
        for future in concurrent.futures.as_completed(future_to_rec):
            count += 1
            if count % 100 == 0 or count == len(records):
                print(f"  Progress: {count}/{len(records)} details downloaded...")
            try:
                res = future.result()
                if res:
                    detailed_results.append(res)
            except Exception as exc:
                pass

    print(f"Successfully downloaded details for {len(detailed_results)} records. Mapping to CSV...")
    
    mapped_rows = []
    for detail in detailed_results:
        mapped = map_record(detail)
        if mapped:
            mapped_rows.append(mapped)
            
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
        
    print(f"Saskatchewan historical database successfully compiled with {len(mapped_rows)} records!")
    print(f"Database saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    run_backfill()
