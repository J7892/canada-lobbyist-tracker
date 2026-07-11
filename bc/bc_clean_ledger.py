import os
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_FILE = os.path.join(CURRENT_DIR, "bc_lobbyists_historical.csv")

def clean_and_repair_ledger():
    print("====================================================")
    print("STARTING B.C. LEDGER SANITIZATION & MAINTENANCE")
    print("====================================================\n")
    
    if not os.path.exists(LEDGER_FILE):
        print(f"[FATAL ERROR] Target ledger spreadsheet not found at: {LEDGER_FILE}")
        return

    try:
        # Load the current database
        df = pd.read_csv(LEDGER_FILE)
        initial_row_count = len(df)
        print(f"[LOADED] Found master file containing {initial_row_count} total entries.")
        
        # 1. Drop duplicates
        # We define a duplicate as having the same Registration Number, Filing Date and Status
        dedup_keys = ["REGISTRATION NUMBER", "FILING DATE", "REGISTRATION STATUS"]
        df_clean = df.drop_duplicates(subset=dedup_keys, keep="first").copy()
        final_row_count = len(df_clean)
        
        removed_count = initial_row_count - final_row_count
        print(f"[DEDUPLICATE] Removed {removed_count} duplicate filings.")
        
        # 2. Sort by Filing Date descending
        df_clean["FILING DATE"] = pd.to_datetime(df_clean["FILING DATE"], errors="coerce")
        df_clean = df_clean.sort_values(by="FILING DATE", ascending=False)
        # Format back to YYYY-MM-DD
        df_clean["FILING DATE"] = df_clean["FILING DATE"].dt.strftime("%Y-%m-%d")
        
        # Fill missing values
        df_clean = df_clean.fillna("-")
        
        # Backup the old file
        backup_file = LEDGER_FILE + ".bak"
        if os.path.exists(backup_file):
            os.remove(backup_file)
        os.rename(LEDGER_FILE, backup_file)
        print(f"[BACKUP] Safety snapshot preserved at: {backup_file}")
        
        # Rewrite the clean database
        df_clean.to_csv(LEDGER_FILE, index=False)
        print(f"[SUCCESS] Cleaned ledger written safely. File size reset to {final_row_count} rows.")
        print("\n====================================================")
        print("MAINTENANCE SEQUENCE COMPLETE")
        print("====================================================")

    except Exception as maintenance_fault:
        print(f"[CRITICAL FAILURE] Maintenance pipeline aborted: {str(maintenance_fault)}")

if __name__ == "__main__":
    clean_and_repair_ledger()
