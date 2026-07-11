import os
import sys
import re
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_FILE = os.path.join(CURRENT_DIR, "bc_lobbyists_historical.csv")
BASE_URL = "https://www.lobbyistsregistrar.bc.ca/app/secure/orl/lrs/do/rcntRgstrns"

def send_email_digest(html_content, subject_text="Daily B.C. Lobbyist Registry Update"):
    """Connects to Gmail SMTP backbone to transmit the compiled HTML dataset."""
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL")
    
    if not all([username, password, recipient]):
        print("[WARNING] Email credentials missing from GitHub secrets environment. Skipping notification.")
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

def parse_detail_html(html_content, reg_id):
    soup = BeautifulSoup(html_content, "html.parser")
    
    organization = ""
    client = "-"
    filer = ""
    status = "Active"
    reg_num = "-"
    firm_name = ""
    lobbyist_type = "In-House Lobbyist (Organization)"
    reg_type = "Org"
    
    # Identify registration type from H1
    h1 = soup.find("h1")
    if h1 and "Consultant" in h1.text:
        reg_type = "Cons"
        lobbyist_type = "Consultant Lobbyist"
        
    # 1. Organization & Senior Officer / Filer
    if reg_type == "Org":
        org_el = soup.find(string=lambda val: val and "Organization name:" in val)
        if org_el:
            org_strong = org_el.find_next("strong")
            if org_strong:
                organization = org_strong.text.strip()
        so_el = soup.find(string=lambda val: val and "Senior Officer Name:" in val)
        if so_el:
            so_strong = so_el.find_next("strong")
            if so_strong:
                filer = " ".join(so_strong.text.split()).strip()
                if "," in filer:
                    filer = filer.split(",")[0].strip()
    else:
        # Consultant
        client_el = soup.find(string=lambda val: val and "Client name:" in val)
        if client_el:
            client_strong = client_el.find_next("strong")
            if client_strong:
                client = client_strong.text.strip()
        lob_el = soup.find(string=lambda val: val and "Lobbyist name:" in val)
        if lob_el:
            lob_strong = lob_el.find_next("strong")
            if lob_strong:
                filer = " ".join(lob_strong.text.split()).strip()
                if "," in filer:
                    filer = filer.split(",")[0].strip()
        # Find Firm
        firm_el = soup.find(string=lambda val: val and "Firm:" in val)
        if firm_el:
            parent_text = firm_el.find_parent().text.strip()
            if ":" in parent_text:
                firm_name = parent_text.split(":", 1)[1].strip()
        organization = firm_name if firm_name else client
        
    # 2. Registration Status, Number
    status_el = soup.find(string=lambda val: val and "Registration status:" in val)
    if status_el:
        status_strong = status_el.find_next("strong")
        if status_strong:
            status = status_strong.text.strip()
            
    reg_num_el = soup.find(string=lambda val: val and "Registration number:" in val)
    if reg_num_el:
        reg_num_strong = reg_num_el.find_next("strong")
        if reg_num_strong:
            reg_num = reg_num_strong.text.strip()
            
    # Projected End Date or End Date
    end_date = "-"
    end_el = soup.find(string=lambda val: val and "Projected end date:" in val)
    if end_el:
        end_strong = end_el.find_next("strong")
        if end_strong:
            end_date_raw = end_strong.text.strip()
            if "No date provided" not in end_date_raw:
                end_date = end_date_raw
                
    # If the registration is inactive, status is Inactive
    if status == "Inactive":
        # we can look for end date under a termination block or use projected end date
        term_date = end_date
    else:
        term_date = "present"
            
    # 3. Subject Matter of Lobbying
    subjects = []
    for table in soup.find_all("table"):
        headers = [th.text.strip() for th in table.find_all("th", recursive=False)]
        if "Associated Subject Matters" in headers:
            sub_idx = headers.index("Associated Subject Matters")
            # Find tbody or rows
            tbody = table.find("tbody", recursive=False)
            rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr", recursive=False)
            for r in rows:
                cells = r.find_all("td", recursive=False)
                if len(cells) > sub_idx:
                    sub_text = cells[sub_idx].text.strip()
                    for s in sub_text.split(";"):
                        s_clean = " ".join(s.split()).strip()
                        if s_clean and s_clean not in subjects:
                            subjects.append(s_clean)
                            
    # 4. BC Ministries/Provincial Entities (Lobbied)
    entities = []
    ent_header = soup.find(string=lambda val: val and "BC Ministries/Provincial Entities" in val)
    if ent_header:
        ul = ent_header.find_next("ul")
        if ul:
            entities = [" ".join(li.text.strip().split()).strip() for li in ul.find_all("li")]
            
    # 5. Lobbyists
    lobbyists = []
    lob_header = soup.find(string=lambda val: val and "Lobbyists Details" in val)
    if not lob_header:
        lob_header = soup.find(string=lambda val: val and "Lobbyists Employed" in val)
    if lob_header:
        table = lob_header.find_next("table")
        if table:
            rows = table.find_all("tr")[1:]
            for r in rows:
                cells = r.find_all("td")
                if cells:
                    strong = cells[0].find("strong")
                    if strong:
                        name = " ".join(strong.text.split()).strip()
                        if name and name not in lobbyists:
                            lobbyists.append(name)
                            
    if not lobbyists and filer:
        lobbyists.append(filer)
        
    # 6. Full Text
    form_text = ""
    main = soup.find("main")
    if main:
        form_text = main.get_text(separator=" ").replace("\n", " ").replace("\t", " ")
        form_text = " ".join(form_text.split())
        
    # Structure details search text block
    full_text = f"Registration - {reg_type} {organization} / {filer} Registration Information Organization name: {organization} Senior Officer Name: {filer} Registration status: {status} Registration number: {reg_num} Subject Matter of the Lobbying Activities Specific Topics of Lobbying Communications: {'; '.join(subjects)} BC Ministries/Provincial Entities: {', '.join(entities)} Lobbyists Details Lobbyists Employed: {', '.join(lobbyists)}"
    if form_text:
        full_text += f" | {form_text}"
        
    return {
        "FILER": filer,
        "TERMINATION_DATE": term_date,
        "ORGANIZATION": organization,
        "CLIENT": client,
        "SUBJECTS": "; ".join(subjects) if subjects else "-",
        "DEPARTMENTS": ", ".join(entities) if entities else "-",
        "LOBBYISTS": ", ".join(lobbyists),
        "REG_NUMBER": reg_num if reg_num and reg_num != "-" else reg_id,
        "STATUS": status,
        "TYPE_OF_LOBBIIST": lobbyist_type,
        "REG_TYPE": reg_type,
        "FULL_TEXT": full_text
    }

def execute_daily_scrape():
    print("Initiating incremental B.C. lobbyist monitoring check...")
    
    if not os.path.exists(HISTORICAL_DATA_FILE):
        print(f"[FATAL] Reference historical ledger not found: {HISTORICAL_DATA_FILE}")
        sys.exit(1)
        
    historical_df = pd.read_csv(HISTORICAL_DATA_FILE)
    
    # Load all existing signatures and check for REG_ID references
    # To check if a registry ID has been scraped, we search if the R-XXX is in EXTRACTED_PDF_DETAILS
    existing_details_cat = historical_df["EXTRACTED_PDF_DETAILS"].fillna("").astype(str).str.cat()
    
    new_records_captured = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            viewport={'width': 1440, 'height': 900}
        )
        page = context.new_page()
        
        global_headers = [
            "FILING DATE", "TERMINATION DATE", "ORGANIZATION", "CLIENT NAME", "DESIGNATED FILER",
            "GOVERNMENT DEPARTMENT LOBBIED", "PRESCRIBED PROVINCIAL ENTITY LOBBIED", "SUBJECT MATTER OF LOBBYING",
            "REGISTRATION NUMBER", "TYPE OF LOBBIIST", "LOBBYISTS", "TYPE OF REGISTRATION",
            "REGISTRATION STATUS", "EXTRACTED_PDF_DETAILS"
        ]
        
        page_number = 1
        
        try:
            print(f"Navigating to live search page: {BASE_URL}")
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector("ul.list-group li.list-group-item", state="attached", timeout=15000)
            page.wait_for_timeout(2000)
            
            while True:
                # Find all list group items (registrations)
                items = page.locator("ul.list-group li.list-group-item")
                item_count = items.count()
                print(f"\n--- SCRAPER ACTIVE: PAGE {page_number} ({item_count} items found) ---")
                
                if item_count == 0:
                    print("No items found. Exiting pagination loop.")
                    break
                    
                valid_rows_to_process = []
                contains_new_records = False
                
                for idx in range(item_count):
                    item = items.nth(idx)
                    
                    # Extract date and details link
                    # Posted date layout: "Posted date: 2026-07-07"
                    text = item.text_content()
                    posted_date = "-"
                    date_match = re.search(r'Posted date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', text, re.IGNORECASE)
                    if date_match:
                        posted_date = date_match.group(1).strip()
                        
                    # Find link with vwRg in href
                    link_loc = item.locator("a[href*=vwRg]")
                    if link_loc.count() > 0:
                        href = link_loc.first.get_attribute("href")
                        link_text = link_loc.first.text_content().strip()
                        
                        # Extract regId
                        reg_id_match = re.search(r'regId=([0-9]+)', href)
                        if reg_id_match:
                            reg_id_val = reg_id_match.group(1)
                            reg_id_str = f"R-{reg_id_val}"
                            
                            is_new = reg_id_str not in existing_details_cat
                            if is_new:
                                contains_new_records = True
                                
                            valid_rows_to_process.append({
                                "reg_id": reg_id_str,
                                "url": "https://www.lobbyistsregistrar.bc.ca" + href,
                                "posted_date": posted_date,
                                "link_text": link_text,
                                "is_new": is_new
                            })
                            
                if not valid_rows_to_process:
                    print(f"Page {page_number} contains no valid registration links.")
                    break
                    
                if not contains_new_records:
                    print(f" >> [CATCH-UP COMPLETE] Hit baseline records on Page {page_number}. Halting search cleanly.")
                    break
                    
                # Process only new records on this page
                for row_info in valid_rows_to_process:
                    if not row_info["is_new"]:
                        continue
                        
                    print(f"  -> Frontier Alert: Syncing brand-new filing update: {row_info['reg_id']}")
                    
                    detail_success = False
                    detail_data = {}
                    
                    # Open detail page in new tab or page to prevent main list session disruption
                    detail_page = context.new_page()
                    try:
                        detail_page.goto(row_info["url"], wait_until="domcontentloaded")
                        detail_page.wait_for_selector(".panel-body.bg-info", timeout=15000)
                        detail_page.wait_for_timeout(1000)
                        
                        html_content = detail_page.content()
                        detail_data = parse_detail_html(html_content, row_info["reg_id"])
                        detail_success = True
                    except Exception as click_err:
                        print(f"      * Could not load details for {row_info['reg_id']}: {str(click_err)}")
                    finally:
                        detail_page.close()
                        
                    if detail_success:
                        record = [
                            row_info["posted_date"],                  # FILING DATE
                            detail_data.get("TERMINATION_DATE", "-"),  # TERMINATION DATE
                            detail_data.get("ORGANIZATION", "-"),      # ORGANIZATION
                            detail_data.get("CLIENT", "-"),            # CLIENT NAME
                            detail_data.get("FILER", "-"),             # DESIGNATED FILER
                            detail_data.get("DEPARTMENTS", "-"),       # GOVERNMENT DEPARTMENT LOBBIED
                            "-",                                       # PRESCRIBED PROVINCIAL ENTITY LOBBIED
                            detail_data.get("SUBJECTS", "-"),          # SUBJECT MATTER OF LOBBYING
                            detail_data.get("REG_NUMBER", "-"),        # REGISTRATION NUMBER
                            detail_data.get("TYPE_OF_LOBBIIST", "-"),  # TYPE OF LOBBIIST
                            detail_data.get("LOBBYISTS", "-"),         # LOBBYISTS
                            detail_data.get("REG_TYPE", "-"),          # TYPE OF REGISTRATION
                            detail_data.get("STATUS", "-"),            # REGISTRATION STATUS
                            detail_data.get("FULL_TEXT", "")           # EXTRACTED_PDF_DETAILS
                        ]
                        new_records_captured.append(record)
                        
                    time.sleep(1.5)
                    
                # Paginate to next page
                next_link = page.locator("a:has-text('Next')")
                if next_link.count() > 0:
                    href_next = next_link.first.get_attribute("href")
                    if href_next:
                        print(f"Paginating to Next page: {href_next}")
                        page.goto("https://www.lobbyistsregistrar.bc.ca" + href_next, wait_until="domcontentloaded")
                        page.wait_for_selector("ul.list-group li.list-group-item", state="attached", timeout=15000)
                        page.wait_for_timeout(2000)
                        page_number += 1
                    else:
                        print("Next link has no href. Reached end of registry list.")
                        break
                else:
                    print("Reached end of registry list completely.")
                    break
                    
            # Process outputs and send emails if there are additions
            if new_records_captured:
                new_df = pd.DataFrame(new_records_captured, columns=global_headers)
                
                display_df = new_df.copy()
                if "EXTRACTED_PDF_DETAILS" in display_df.columns:
                    display_df["EXTRACTED_PDF_DETAILS"] = display_df["EXTRACTED_PDF_DETAILS"].str.slice(0, 180) + "..."
                
                html_table = display_df.to_html(index=False, classes="dataframe")
                
                email_body = f"""
                <html>
                <head>
                    <style>
                        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #333333; line-height: 1.5; }}
                        table.dataframe {{ border-collapse: collapse; width: 100%; margin-top: 15px; font-size: 13px; }}
                        th {{ background-color: #0d6efd; color: white; border: 1px solid #0d6efd; padding: 12px; text-align: left; font-weight: 600; }}
                        td {{ border: 1px solid #e0e0e0; padding: 10px; }}
                        tr:nth-child(even) {{ background-color: #f8f9fa; }}
                        .alert-header {{ color: #0d6efd; font-weight: bold; font-size: 20px; border-bottom: 2px solid #0d6efd; padding-bottom: 8px; }}
                    </style>
                </head>
                <body>
                    <div class="alert-header">B.C. Lobbyist Registry: New Disclosures Located</div>
                    <p>The daily monitor pipeline isolated the following brand-new filings within the live index:</p>
                    {html_table}
                    <br>
                    <p style="font-size: 11px; color: #888888; border-top: 1px solid #eeeeee; padding-top: 8px;">
                        This is an automated report delivered securely via your automated GitHub Actions infrastructure pipeline.
                    </p>
                </body>
                </html>
                """
                
                send_email_digest(email_body, subject_text=f"Alert: {len(new_records_captured)} New B.C. Lobbyist Registrations Detected")
                
                # Prepend to CSV
                consolidated_df = pd.concat([new_df, historical_df], ignore_index=True)
                consolidated_df.to_csv(HISTORICAL_DATA_FILE, index=False)
                print(f"[SUCCESS] Prepended {len(new_records_captured)} new files to top of ledger and triggered email.")
            else:
                print("[IDLE] Index clean. 0 new disclosures discovered today.")
                
        except Exception as e:
            print(f"[CRITICAL ERROR] Daily monitor execution fault: {str(e)}")
            sys.exit(1)
        finally:
            browser.close()

if __name__ == "__main__":
    execute_daily_scrape()
