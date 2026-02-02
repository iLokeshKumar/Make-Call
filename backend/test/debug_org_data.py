import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('APOLLO_API_KEY')

def debug_org_search():
    url = 'https://api.apollo.io/v1/organizations/search'
    headers = {
        'X-Api-Key': key,
        'Content-Type': 'application/json'
    }
    payload = {
        'q_organization_keyword_tags': ['software'],
        'page': 1,
        'per_page': 1
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 200:
        data = resp.json()
        orgs = data.get('organizations', [])
        if orgs:
            print(json.dumps(orgs[0], indent=2))
        else:
            print("No organizations found.")
    else:
        print(f"Error {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    debug_org_search()
