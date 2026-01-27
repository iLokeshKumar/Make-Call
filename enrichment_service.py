import os
import requests
from sqlmodel import Session, select
from database import engine, Lead
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

def enrich_lead_cascade(lead_id: int):
    """
    Sequentially enrich a lead using the waterfall logic:
    Local -> Apollo -> Lusha (Stub)
    """
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            return {"error": "Lead not found"}

        print(f"Starting enrichment for Lead: {lead.name} (ID: {lead_id})")

        # Step 1: Apollo Enrichment (Organization Level)
        # ---------------------------------------------
        if lead.enrichment_status == "Not Enriched":
            try:
                # Extract domain from email if possible, or name
                domain = None
                if lead.email and "@" in lead.email:
                    domain = lead.email.split("@")[-1]
                
                # If no domain, we can't do much with Apollo organizations/enrich easily without search
                # For now, let's assume we have a domain or try to match it.
                
                if domain:
                    url = "https://api.apollo.io/v1/organizations/enrich"
                    headers = {
                        "X-Api-Key": APOLLO_API_KEY,
                        "Content-Type": "application/json"
                    }
                    resp = requests.post(url, headers=headers, json={"domain": domain})
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        org = data.get("organization", {})
                        if org:
                            # Update lead info from org data
                            if not lead.phone and org.get("phone"):
                                lead.phone = org.get("phone")
                            
                            # Update notes with org metadata
                            meta = f"\n[Apollo] Org: {org.get('name')}, Industry: {org.get('industry')}, Employees: {org.get('estimated_num_employees')}"
                            lead.notes = (lead.notes or "") + meta
                            lead.enrichment_status = "Apollo Enriched"
                            print("Enriched via Apollo Organizations.")
                        else:
                            print("Apollo Enrichment: No organization found for domain.")
            except Exception as e:
                print(f"Apollo Enrichment Error: {e}")

        # Step 2: Lusha Enrichment (Stub)
        # ------------------------------
        if lead.enrichment_status in ["Not Enriched", "Apollo Enriched"]:
            # Placeholder for Lusha logic
            # Once API key is provided, we can add logic here to find direct person info
            pass

        session.add(lead)
        session.commit()
        session.refresh(lead)
        
        return {
            "id": lead.id,
            "status": lead.enrichment_status,
            "email": lead.email,
            "phone": lead.phone
        }

if __name__ == "__main__":
    # Quick test logic
    import sys
    if len(sys.argv) > 1:
        print(enrich_lead_cascade(int(sys.argv[1])))
