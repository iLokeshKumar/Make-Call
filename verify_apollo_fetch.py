import requests
import json
import time

API_URL = "http://localhost:6060"

def test_fetch():
    print("Sending POST /leads/fetch-apollo...")
    payload = {"keywords": "Apollo"}
    
    try:
        res = requests.post(f"{API_URL}/leads/fetch-apollo", json=payload)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.json()}")
        
        if res.status_code == 200:
            print("\nFetch successful. Checking GET /leads...")
            res_get = requests.get(f"{API_URL}/leads")
            leads = res_get.json()
            print(f"Found {len(leads)} leads in DB.")
            # Check for Apollo source
            apollo_leads = [l for l in leads if l.get('source') == 'Apollo API']
            print(f"Apollo Leads found: {len(apollo_leads)}")
            if apollo_leads:
                print(f"Sample: {apollo_leads[0]['name']} - {apollo_leads[0]['notes']}")
        else:
            print("Fetch failed.")
            
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    # Wait a bit for server to start if we just ran it
    time.sleep(2) 
    test_fetch()
