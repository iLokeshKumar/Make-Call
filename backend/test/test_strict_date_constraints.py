import asyncio
from datetime import datetime, timedelta
import logging
import sys
import os

# Add parent directory to path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.date_normalizer import normalize_date_ai

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_strict_dates")

async def test_strict_parsing():
    now = datetime.now()
    print(f"\n--- Strict Date Constraints Verification Test ---")
    print(f"Reference Time (Now): {now}")
    print(f"Reference Weekday:    {now.strftime('%A')}\n")

    test_cases = [
        ("Yesterday at 2 PM", "Should shift to future"),
        ("Today at 9 AM", "Should shift to tomorrow or future"),
        ("This coming Saturday at 10 AM", "Should shift to Next Monday"),
        ("This coming Sunday at 4 PM", "Should shift to Next Monday"),
        ("Next Friday at 11 AM", "Should stay on Friday (if future)"),
        ("March 1st, 2020", "Should shift to future")
    ]
    
    for tc, expectation in test_cases:
        try:
            parsed = await normalize_date_ai(tc)
            
            print(f"Input:       '{tc}'")
            print(f"Expectation: {expectation}")
            print(f"Result:      {parsed} ({parsed.strftime('%A') if parsed else 'N/A'})")
            
            is_valid = True
            if parsed:
                if parsed <= now:
                    print("❌ [FAIL] Result is NOT in the future")
                    is_valid = False
                if parsed.weekday() >= 5:
                    print("❌ [FAIL] Result falls on a WEEKEND")
                    is_valid = False
            else:
                print("❌ [FAIL] Parsing returned None")
                is_valid = False
                
            if is_valid:
                print("✅ [OK] Success")
            print("-" * 30)
            
        except Exception as e:
            print(f"Input:   '{tc}'")
            print(f"Error:   {e}")
            print(f"Status:  [ERROR]")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(test_strict_parsing())
