import os
import csv
import shutil

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(CURRENT_DIR, "quebec_lobbyists_historical.csv")

def clean_and_verify_ledger():
    print("====================================================")
    print("STARTING QUEBEC LEDGER DEDUPLICATION & CLEANING")
    print("====================================================\n")
    
    if not os.path.exists(LEDGER_FILE):
        print(f"[FATAL ERROR] Quebec ledger not found at: {LEDGER_FILE}")
        return

    try:
        # Load the current file
        with open(LEDGER_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
            
        initial_row_count = len(rows)
        print(f"[LOADED] Found master file containing {initial_row_count} entries.")
        
        # Deduplicate on base registration number (e.g. "2302253v7" -> "2302253")
        seen_regs = set()
        cleaned_rows = []
        
        for row in rows:
            reg_num = (row.get('REGISTRATION NUMBER') or '').strip()
            # Extract base registration number before the version "v" suffix
            base_reg = reg_num.split('v')[0].strip()
            if base_reg not in seen_regs:
                seen_regs.add(base_reg)
                cleaned_rows.append(row)
        
        # Sort by FILING DATE descending
        cleaned_rows.sort(key=lambda x: x.get('FILING DATE', ''), reverse=True)
        
        cleaned_row_count = len(cleaned_rows)
        removed_count = initial_row_count - cleaned_row_count
        
        if removed_count > 0:
            print(f"[CLEANUP] Found and removed {removed_count} duplicate/older version rows.")
            
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
        print("MAINTENANCE SEQUENCE COMPLETE: QUEBEC LEDGER SECURE")
        print("====================================================")

    except Exception as e:
        print(f"[CRITICAL FAILURE] Cleaning pipeline aborted: {e}")

if __name__ == "__main__":
    clean_and_verify_ledger()
