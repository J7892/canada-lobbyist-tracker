import os
import csv
import re
from datetime import datetime, timedelta

def parse_date(date_str):
    if not date_str or date_str.strip() in ('-', '', 'N/A', 'present'):
        return None
    date_str = date_str.strip()
    
    # Try various date formats
    for fmt in ('%Y-%m-%d', '%d-%b-%Y', '%d-%B-%Y', '%Y/%m/%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            pass
            
    # Regex parser for DD-MMM-YYYY (e.g. 15-Jul-2026 or 15-July-2026)
    m = re.match(r'(\d{1,2})[-/]([a-zA-Z]{3,10})[-/](\d{4})', date_str)
    if m:
        day = int(m.group(1))
        mon_str = m.group(2)[:3].lower()
        year = int(m.group(3))
        months = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        if mon_str in months:
            try:
                return datetime(year, months[mon_str], day)
            except ValueError:
                pass
    return None

def main():
    import sys
    csv.field_size_limit(10000000)
    print("Consolidating recent and active lobbyist filings...")
    
    # Inputs
    files = {
        'BC': 'bc/bc_lobbyists_historical.csv',
        'AB': 'alberta/alberta_lobbyists_historical.csv',
        'SK': 'saskatchewan/saskatchewan_lobbyists_historical.csv',
        'MB': 'manitoba/manitoba_lobbyists_historical.csv',
        'ON': 'ontario/ontario_lobbyists_historical.csv',
        'QC': 'quebec/quebec_lobbyists_historical.csv',
        'NB': 'new_brunswick/new_brunswick_lobbyists_historical.csv',
        'PE': 'prince_edward_island/prince_edward_island_lobbyists_historical.csv'
    }
    
    # Target date: last 60 days for any filings, last 180 days for active ones
    limit_date = datetime.now() - timedelta(days=60)
    active_limit_date = datetime.now() - timedelta(days=180)
    print(f"Filtering criteria: Filing Date >= {limit_date.strftime('%Y-%m-%d')} OR (Status contains 'active' AND Filing Date >= {active_limit_date.strftime('%Y-%m-%d')})")
    
    output_rows = []
    
    headers = [
        'PROVINCE', 'FILING DATE', 'TERMINATION DATE', 'ORGANIZATION', 'CLIENT NAME', 
        'DESIGNATED FILER', 'GOVERNMENT DEPARTMENT LOBBIED', 'PRESCRIBED PROVINCIAL ENTITY LOBBIED', 
        'SUBJECT MATTER OF LOBBYING', 'REGISTRATION NUMBER', 'TYPE OF LOBBYIST', 'LOBBYISTS', 
        'TYPE OF REGISTRATION', 'REGISTRATION STATUS', 'EXTRACTED_PDF_DETAILS'
    ]
    
    for prov, path in files.items():
        if not os.path.exists(path):
            print(f"Warning: File not found {path}")
            continue
            
        print(f"Processing {prov} ({path})...")
        
        with open(path, mode='r', encoding='utf-8-sig', errors='replace') as infile:
            reader = csv.DictReader(infile)
            
            count_recent = 0
            count_active = 0
            count_total_processed = 0
            
            for raw_row in reader:
                count_total_processed += 1
                
                # Normalize keys: strip BOM, whitespace, and convert to uppercase
                row = { (k.strip().upper() if k else ''): v for k, v in raw_row.items() }
                
                filing_date_str = row.get('FILING DATE', '')
                status_str = (row.get('REGISTRATION STATUS', '') or '').lower()
                termination_date_str = (row.get('TERMINATION DATE', '') or '').lower()
                
                is_recent = False
                is_active = False
                
                # Find the lobbyist type header (spelled differently in BC)
                type_header = 'TYPE OF LOBBYIST'
                if 'TYPE OF LOBBIIST' in row:
                    type_header = 'TYPE OF LOBBIIST'
                
                # Check date
                f_date = parse_date(filing_date_str)
                if f_date:
                    if f_date >= limit_date:
                        is_recent = True
                        count_recent += 1
                
                    # Check active status with date limit
                    if ('active' in status_str or 'present' in termination_date_str) and f_date >= active_limit_date:
                        is_active = True
                        count_active += 1
                    
                if is_recent or is_active:
                    # Map to unified row
                    unified_row = {
                        'PROVINCE': prov,
                        'FILING DATE': (row.get('FILING DATE', '') or '').strip(),
                        'TERMINATION DATE': (row.get('TERMINATION DATE', '') or '').strip(),
                        'ORGANIZATION': (row.get('ORGANIZATION', '') or '').strip(),
                        'CLIENT NAME': (row.get('CLIENT NAME', '') or '').strip(),
                        'DESIGNATED FILER': (row.get('DESIGNATED FILER', '') or '').strip(),
                        'GOVERNMENT DEPARTMENT LOBBIED': (row.get('GOVERNMENT DEPARTMENT LOBBIED', '') or '').strip(),
                        'PRESCRIBED PROVINCIAL ENTITY LOBBIED': (row.get('PRESCRIBED PROVINCIAL ENTITY LOBBIED', '') or '').strip(),
                        'SUBJECT MATTER OF LOBBYING': (row.get('SUBJECT MATTER OF LOBBYING', '') or '').strip(),
                        'REGISTRATION NUMBER': (row.get('REGISTRATION NUMBER', '') or '').strip(),
                        'TYPE OF LOBBYIST': (row.get(type_header, '') or '').strip(),
                        'LOBBYISTS': (row.get('LOBBYISTS', '') or '').strip(),
                        'TYPE OF REGISTRATION': (row.get('TYPE OF REGISTRATION', '') or '').strip(),
                        'REGISTRATION STATUS': (row.get('REGISTRATION STATUS', '') or '').strip(),
                        'EXTRACTED_PDF_DETAILS': (row.get('EXTRACTED_PDF_DETAILS', '') or '').strip()[:200]
                    }
                    output_rows.append(unified_row)
                    
            print(f"  Finished {prov}: Processed {count_total_processed} rows. Found {count_recent} recent, {count_active} active (some overlaps).")
            
    # Write consolidated output
    out_path = 'recent_lobbyists.csv'
    with open(out_path, mode='w', encoding='utf-8', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=headers)
        writer.writeheader()
        writer.writerows(output_rows)
        
    print(f"Successfully consolidated {len(output_rows)} records into {out_path} (Size: {os.path.getsize(out_path) / 1024 / 1024:.2f} MB)")

if __name__ == '__main__':
    main()
