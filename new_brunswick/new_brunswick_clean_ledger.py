import os
import csv

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(CURRENT_DIR, "new_brunswick_lobbyists_historical.csv")

def clean_ledger():
    print("====================================================")
    print("STARTING NEW BRUNSWICK LEDGER DEDUPLICATION & CLEANING")
    print("====================================================")
    
    if not os.path.exists(LEDGER_FILE):
        print(f"[ERROR] Ledger file not found at: {LEDGER_FILE}")
        return
        
    with open(LEDGER_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
        
    print(f"[LOADED] Found ledger file containing {len(rows)} entries.")
    
    # Deduplicate on registration number (keeping the latest filing date)
    seen_ids = {}
    duplicates_removed = 0
    
    for row in rows:
        reg_num = row.get("REGISTRATION NUMBER", "").strip()
        filing_date = row.get("FILING DATE", "").strip()
        
        if not reg_num:
            continue
            
        if reg_num in seen_ids:
            # Check if this row is newer
            existing_row = seen_ids[reg_num]
            existing_date = existing_row.get("FILING DATE", "").strip()
            
            if filing_date > existing_date:
                seen_ids[reg_num] = row
            duplicates_removed += 1
        else:
            seen_ids[reg_num] = row
            
    cleaned_rows = list(seen_ids.values())
    
    # Sort descending by filing date
    cleaned_rows.sort(key=lambda x: x.get("FILING DATE", ""), reverse=True)
    
    with open(LEDGER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)
        
    print(f"[CLEANED] Removed {duplicates_removed} duplicates.")
    print(f"[SUCCESS] Ledger secure with {len(cleaned_rows)} unique entries in: {LEDGER_FILE}")
    print("====================================================")

if __name__ == "__main__":
    clean_ledger()
