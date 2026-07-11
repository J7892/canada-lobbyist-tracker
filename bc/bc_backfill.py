import os
import pandas as pd
import numpy as np

# Paths
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, "ORL_Registration_Data")
OUTPUT_FILE = os.path.join(CURRENT_DIR, "bc_lobbyists_historical.csv")

def run_backfill():
    print("Starting B.C. Lobbyist Registry Backfill Pipeline...")
    
    # 1. Load Primary Registrations
    primary_path = os.path.join(DATA_DIR, "Registration_Primary_Export.csv")
    if not os.path.exists(primary_path):
        print(f"Error: {primary_path} not found.")
        return
        
    print("Loading primary registration details...")
    # Load only necessary columns to save memory
    primary_cols = [
        "REG_ID", "REG_TYPE", "REG_NUM", "FIRM_NAME", "FILER_FIRST_NAME", "FILER_LAST_NAME",
        "CLIENT_ORG_NAME", "REG_START_DATE", "REG_END_DATE", "REG_POSTED_DATE"
    ]
    df_primary = pd.read_csv(primary_path, usecols=primary_cols)
    print(f"Loaded {len(df_primary)} primary records.")
    
    # Clean string columns
    for col in df_primary.columns:
        if df_primary[col].dtype == object:
            df_primary[col] = df_primary[col].fillna("").astype(str).str.strip()
            
    # 2. Map Public Agencies
    agency_path = os.path.join(DATA_DIR, "BC_Public_Agencies_Export.csv")
    reg_agency_path = os.path.join(DATA_DIR, "Registration_BCPublicAgency_Export.csv")
    
    agencies_dict = {}
    if os.path.exists(agency_path) and os.path.exists(reg_agency_path):
        print("Mapping BC Public Agencies...")
        df_agencies = pd.read_csv(agency_path)
        # Create mapping of ID -> Name
        agency_map = dict(zip(df_agencies["BC_PUBLIC_AGENCY_ID"].astype(str), df_agencies["BC_PUBLIC_AGENCY"].astype(str)))
        
        df_reg_agency = pd.read_csv(reg_agency_path)
        for _, row in df_reg_agency.iterrows():
            reg_id = str(row["REG_ID"]).strip()
            agency_ids_str = str(row["BC_PUBLIC_AGENCY_IDS"]).strip()
            if agency_ids_str and agency_ids_str != "nan":
                agency_names = []
                # IDs are comma separated and potentially quoted
                for a_id in agency_ids_str.replace('"', '').split(','):
                    a_id = a_id.strip()
                    if a_id in agency_map:
                        agency_names.append(agency_map[a_id])
                    else:
                        agency_names.append(a_id)
                agencies_dict[reg_id] = ", ".join(agency_names)
                
    # 3. Map Subject Matters
    subject_path = os.path.join(DATA_DIR, "Subject_Matters_Export.csv")
    reg_subject_path = os.path.join(DATA_DIR, "Registration_SubjectMatterDetails_Export.csv")
    
    subjects_dict = {}
    if os.path.exists(subject_path) and os.path.exists(reg_subject_path):
        print("Mapping Subject Matters...")
        df_subjects = pd.read_csv(subject_path)
        subject_map = dict(zip(df_subjects["SUBJECT_MATTER_ID"].astype(str), df_subjects["SUBJECT_MATTER"].astype(str)))
        
        # Load only necessary columns
        df_reg_subject = pd.read_csv(reg_subject_path, usecols=["REG_ID", "SUBJECT_MATTER_IDS", "TOPIC_OF_LOBBYING"])
        
        # Group by REG_ID to combine multiple topics
        grouped_subjects = df_reg_subject.groupby("REG_ID")
        for reg_id, group in grouped_subjects:
            reg_id = str(reg_id).strip()
            unique_subjects = set()
            topics = []
            
            for _, row in group.iterrows():
                sub_ids_str = str(row["SUBJECT_MATTER_IDS"]).strip()
                if sub_ids_str and sub_ids_str != "nan":
                    for s_id in sub_ids_str.replace('"', '').split(','):
                        s_id = s_id.strip()
                        if s_id in subject_map:
                            unique_subjects.add(subject_map[s_id])
                            
                topic = str(row["TOPIC_OF_LOBBYING"]).strip()
                if topic and topic != "nan" and topic not in topics:
                    topics.append(topic)
                    
            sub_part = "; ".join(sorted(unique_subjects))
            topic_part = " | ".join(topics)
            if sub_part and topic_part:
                subjects_dict[reg_id] = f"{sub_part} ({topic_part})"
            elif sub_part:
                subjects_dict[reg_id] = sub_part
            elif topic_part:
                subjects_dict[reg_id] = topic_part
                
    # 4. Map Lobbyists
    inhouse_path = os.path.join(DATA_DIR, "Registration_InHouseLobbyists_Export.csv")
    consultant_path = os.path.join(DATA_DIR, "Registration_ConsultantLobbyists_Export.csv")
    
    lobbyists_dict = {}
    
    def process_lobbyists_file(file_path):
        if os.path.exists(file_path):
            print(f"Mapping lobbyists from {os.path.basename(file_path)}...")
            df_lob = pd.read_csv(file_path, usecols=["REG_ID", "LOBBYIST_FIRST_NAME", "LOBBYIST_LAST_NAME"])
            for _, row in df_lob.iterrows():
                reg_id = str(row["REG_ID"]).strip()
                first = str(row["LOBBYIST_FIRST_NAME"]).strip()
                last = str(row["LOBBYIST_LAST_NAME"]).strip()
                if first and last and first != "nan" and last != "nan":
                    fullname = f"{first} {last}"
                    if reg_id not in lobbyists_dict:
                        lobbyists_dict[reg_id] = []
                    if fullname not in lobbyists_dict[reg_id]:
                        lobbyists_dict[reg_id].append(fullname)
                        
    process_lobbyists_file(inhouse_path)
    process_lobbyists_file(consultant_path)
    
    # Convert lobbyists lists to comma-separated strings
    lobbyists_str_dict = {k: ", ".join(v) for k, v in lobbyists_dict.items()}
    
    # Filter primary registrations to 2025-01-01 onwards
    print("Filtering registrations to 2025-01-01 onwards...")
    # Check if posted date or start date is 2025 or later
    df_primary = df_primary[
        (df_primary["REG_POSTED_DATE"] >= "2025-01-01") | 
        ((df_primary["REG_POSTED_DATE"] == "") & (df_primary["REG_START_DATE"] >= "2025-01-01"))
    ]
    print(f"Filtered primary records: {len(df_primary)}")
    
    # 5. Build Unified Dataset
    print("Compiling final ledger data...")
    records = []
    
    for idx, row in df_primary.iterrows():
        reg_id = row["REG_ID"]
        reg_type = row["REG_TYPE"]
        reg_num = row["REG_NUM"]
        firm_name = row["FIRM_NAME"]
        first_name = row["FILER_FIRST_NAME"]
        last_name = row["FILER_LAST_NAME"]
        client_org = row["CLIENT_ORG_NAME"]
        start_date = row["REG_START_DATE"]
        end_date = row["REG_END_DATE"]
        posted_date = row["REG_POSTED_DATE"]
        
        # Filer
        filer = f"{first_name} {last_name}".strip()
        if not filer:
            filer = "-"
            
        # Organization
        # For Org type, ORGANIZATION is client_org
        # For Cons type, ORGANIZATION is firm_name or client_org if no firm
        if reg_type == "Org":
            org = client_org
            client = "-"
            lobbyist_type = "In-House Lobbyist (Organization)"
        else:
            org = firm_name if firm_name else client_org
            client = client_org
            lobbyist_type = "Consultant Lobbyist"
            
        # Status
        # If there is an end date and it's not empty, status is Inactive
        if end_date and end_date != "nan" and end_date != "":
            status = "Inactive"
            term_date = end_date
        else:
            status = "Active"
            term_date = "present"
            
        # Relational mappings
        agencies = agencies_dict.get(reg_id, "-")
        subjects = subjects_dict.get(reg_id, "-")
        lobbyists = lobbyists_str_dict.get(reg_id, "")
        if not lobbyists:
            lobbyists = filer
            
        # Synthesize EXTRACTED_PDF_DETAILS
        full_text = f"Registration - {reg_type} {client_org} / {filer} Registration Information Organization name: {client_org} Senior Officer Name: {filer} Initial registration start date: {start_date} Registration status: {status} Registration number: {reg_num} Subject Matter of the Lobbying Activities Specific Topics of Lobbying Communications: {subjects} BC Ministries/Provincial Entities: {agencies} Lobbyists Details Lobbyists Employed: {lobbyists}"
        
        record = {
            "FILING DATE": posted_date if posted_date else start_date,
            "TERMINATION DATE": term_date,
            "ORGANIZATION": org,
            "CLIENT NAME": client,
            "DESIGNATED FILER": filer,
            "GOVERNMENT DEPARTMENT LOBBIED": agencies,
            "PRESCRIBED PROVINCIAL ENTITY LOBBIED": "-",
            "SUBJECT MATTER OF LOBBYING": subjects,
            "REGISTRATION NUMBER": reg_num if reg_num else reg_id,
            "TYPE OF LOBBIIST": lobbyist_type,
            "LOBBYISTS": lobbyists,
            "TYPE OF REGISTRATION": reg_type,
            "REGISTRATION STATUS": status,
            "EXTRACTED_PDF_DETAILS": full_text
        }
        records.append(record)
        
    df_out = pd.DataFrame(records)
    
    # Sort by FILING DATE descending to match scraper convention
    df_out = df_out.sort_values(by=["FILING DATE", "REGISTRATION NUMBER"], ascending=[False, False])
    
    # Save to file
    df_out.to_csv(OUTPUT_FILE, index=False)
    print(f"Success! Master ledger saved to {OUTPUT_FILE} ({len(df_out)} total entries, file size: {os.path.getsize(OUTPUT_FILE)} bytes).")

if __name__ == "__main__":
    run_backfill()
