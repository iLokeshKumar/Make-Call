import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("APOLLO_API_KEY")
BASE_URL = "https://api.apollo.io/v1"

def test_apollo_auth():
    if not API_KEY:
        print("❌ Error: APOLLO_API_KEY not found in .env")
        return

    url = f"{BASE_URL}/auth/health" # Or checking a search
    # Apollo usually takes api_key in query or body. Let's try search as a auth check.
    url = f"{BASE_URL}/organizations/search"
    
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": API_KEY
    }
    
    payload = {
        "q_organization_name": "Apollo",
        "page": 1,
        "per_page": 1
    }
    
    try:
        print(f"Testing Apollo API connection...")
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print("Connection Successful!")
            print(f"Found {data.get('pagination', {}).get('total_entries', 0)} potential leads.")
            people = data.get('people', [])
            if people:
                print(f"Sample: {people[0].get('first_name')} {people[0].get('last_name')}")
        else:
            print(f"API Request Failed: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_apollo_auth()

#These endpoint work
#api/v1/contacts/search
#api/v1/accounts/search
#api/v1/contacts/create
#api/v1/contacts/update
#api/v1/contacts/bulk_create
#api/v1/contacts/bulk_update
#api/v1/accounts/bulk_create
#api/v1/organizations/search
#api/v1/organizations/enrich
#api/v1/organizations/bulk_enrich
#api/v1/organizations/job_postings
#api/v1/mixed_people/organization_top_people
#api/v1/reports/sync_report
#api/v1/fields/create