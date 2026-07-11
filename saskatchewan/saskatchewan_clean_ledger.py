import os
import csv
import shutil

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(CURRENT_DIR, "saskatchewan_lobbyists_historical.csv")

def clean_and_verify_ledger():
    print("====================================================")
    print("STARTING SASKATCHEWAN LEDGER DEDUPLICATION & CLEANING")
    print("====================================================\n")
    
    if not os.path.exists(LEDGER_FILE):
        print(f"[FATAL ERROR] Saskatchewan ledger not found at: {LEDGER_FILE}")
        return

    try:
        # Load the current file using built-in csv module
        with open(LEDGER_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
            
        initial_row_count = len(rows)
        print(f"[LOADED] Found master file containing {initial_row_count} entries.")
        
        # Drop duplicates on REGISTRATION NUMBER (keep first seen)
        seen_regs = set()
        cleaned_rows = []
        
        # Since the records are loaded, let's keep the first occurrence of each registration number
        # Note: if the rows are sorted chronologically, keeping the first occurrence keeps the newest version of each registration!
        for row in rows:
            reg_num = (row.get('REGISTRATION NUMBER') or '').strip()
            if reg_num not in seen_regs:
                seen_regs.add(reg_num)
                cleaned_rows.append(row)
        
        # Sort by FILING DATE descending
        # Ensure we parse dates safely. Filing dates are in YYYY-MM-DD format
        cleaned_rows.sort(key=lambda x: x.get('FILING DATE', ''), reverse=True)
        
        cleaned_row_count = len(cleaned_rows)
        removed_count = initial_row_count - cleaned_row_count
        
        if removed_count > 0:
            print(f"[CLEANUP] Found and removed {removed_count} duplicate rows.")
            
            # Backup the old file
            backup_file = LEDGER_FILE + ".bak"
            if os.path.exists(backup_file):
                os.remove(backup_file)
            shutil.copy2(LEDGER_FILE, backup_file)
            print(f"[BACKUP] Safety snapshot preserved at: {backup_file}")
            
            # Save clean file
            with open(LEDGER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(cleaned_rows)
            print(f"[SUCCESS] Cleaned ledger written safely. File size is now {cleaned_row_count} rows.")
        else:
            print("[INFO] No duplicate rows detected. Ledger is clean.")
            
        print("\n====================================================")
        print("MAINTENANCE SEQUENCE COMPLETE: SASKATCHEWAN LEDGER SECURE")
        print("====================================================")

    except Exception as e:
        print(f"[CRITICAL FAILURE] Cleaning pipeline aborted: {e}")

if __name__ == "__main__":
    clean_and_verify_ledger()
