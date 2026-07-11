import os
import csv
import sys
import time
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "saskatchewan_lobbyists_historical.csv")
SEARCH_URL = "https://forms.sasklobbyistregistry.ca/api/Search/RegistrationVersions"
DETAIL_URL = "https://forms.sasklobbyistregistry.ca/api/registrationversion/"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def send_email_digest(html_content, subject_text="Daily Saskatchewan Lobbyist Registry Update"):
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

def fetch_detail(id_val):
    for attempt in range(4):
        try:
            time.sleep(0.2)  # Rate limiting delay
            res = requests.get(f"{DETAIL_URL}?id={id_val}", headers=HEADERS, timeout=20)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
            else:
                print(f"[WARNING] Failed to fetch details for ID {id_val}: {e}")
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
        
    # 9. Structured details for searching
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

def execute_daily_scrape():
    print("Initiating incremental Saskatchewan lobbyist scraper check...")
    
    if not os.path.exists(HISTORICAL_DATA_FILE):
        print(f"[FATAL] Reference historical ledger not found: {HISTORICAL_DATA_FILE}")
        sys.exit(1)
        
    with open(HISTORICAL_DATA_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        historical_rows = list(reader)
        
    existing_versions = set((row.get("REGISTRATION NUMBER") or '').strip() for row in historical_rows)
    print(f"Loaded master archive. Found {len(existing_versions)} unique registration versions.")

    # Fetch recent records (last 15 days)
    start_date = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')
    print(f"Fetching updates posted since {start_date}...")
    
    payload = {
        'EffectiveFromDate': '', 'EffectiveToDate': '', 'PostedFromDate': start_date, 'PostedToDate': '',
        'Keywords': '', 'DescriptionOfLobbyingActivities': '', 'Lobbyists': '', 'ClientOrganization': '',
        'MLA': [], 'Minister': [], 'GovernmentInstitution': [], 'SubjectMatter': [], 'Category': [], 'RegistrationStatus': [],
        'start': 0, 'length': 200, 'draw': 1
    }
    
    try:
        res = requests.post(SEARCH_URL, headers=HEADERS, json=payload, timeout=20)
        res.raise_for_status()
        recent_records = res.json().get('data', [])
    except Exception as e:
        print(f"[ERROR] Failed to query registry search API: {e}")
        return

    new_filings = []
    for rec in recent_records:
        url_str = rec.get('Url', '')
        if not url_str or 'id=' not in url_str:
            continue
            
        id_val = url_str.split('id=')[-1].strip()
        
        # Details page key fields logic
        version_num = rec.get('Version', '')
        reg_num = ''
        
        # Let's hit the details endpoint for any registry version we don't have
        # Since we don't have the version number direct in header list, we will fetch detail if it might be new
        # Wait, can we extract ID directly or do we fetch?
        # Let's fetch the detail and check if its RegistrationVersionNumber is in existing_versions!
        detail = fetch_detail(id_val)
        if not detail:
            continue
            
        ver_num = (detail.get('RegistrationVersionNumber') or '').strip()
        if ver_num and ver_num not in existing_versions:
            mapped = map_record(detail)
            if mapped:
                new_filings.append(mapped)
                existing_versions.add(ver_num)
                print(f"  [NEW ROW FOUND] Version: {ver_num} | Organization: {mapped['ORGANIZATION']}")

    if not new_filings:
        print("No new registrations found. Saskatchewan database is up to date.")
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
        <h2>Daily Saskatchewan Lobbyist Registry Scrape Digest</h2>
        <p>Found <strong>{len(new_filings)}</strong> new filing disclosures posted in the Saskatchewan Registry in the last 15 days.</p>
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
