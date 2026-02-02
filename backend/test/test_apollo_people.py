import os
import requests
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

def test_apollo_people():
    # Attempt to enrich an organization
    url = "https://api.apollo.io/v1/organizations/enrich"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY
    }
    payload = {
        "domain": "google.com"
    }

    print(f"Testing Apollo Organization Enrich for domain: google.com")
    try:
        response = requests.post(url, headers=headers, json=payload)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(json.dumps(data, indent=2))
        else:
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"API Error: {e}")

if __name__ == "__main__":
    test_apollo_people()
