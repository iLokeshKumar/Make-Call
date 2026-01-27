import requests
import pandas as pd
import io

API_URL = "http://localhost:6060"

def test_upload():
    # Create a dummy CSV
    data = {
        "Name": ["Test Lead 1", "Test Lead 2"],
        "Phone": ["+1234567890", "+0987654321"],
        "Email": ["test1@example.com", "test2@example.com"],
        "Notes": ["Interested in bulk buy", "Urgent"]
    }
    df = pd.DataFrame(data)
    
    # Convert to CSV bytes
    csv_buffer = io.BytesIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    
    files = {'file': ('test_leads.csv', csv_buffer, 'text/csv')}
    
    print("Sending POST /leads/upload...")
    try:
        res = requests.post(f"{API_URL}/leads/upload", files=files)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.json()}")
        
        if res.status_code == 200:
            print("\nUpload successful. Checking GET /leads...")
            res_get = requests.get(f"{API_URL}/leads")
            leads = res_get.json()
            print(f"Found {len(leads)} leads in DB.")
            for l in leads[-2:]: # Show last 2
                print(f"- {l['name']} ({l['phone']}) [Source: {l.get('source')}]")
        else:
            print("Upload failed.")
            
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    test_upload()
