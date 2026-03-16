import os
import logging
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_whatsapp_message(to_phone: str, body: str, account_sid: str = None, auth_token: str = None, from_whatsapp_number: str = None):
    """
    Sends a WhatsApp message using Twilio.
    Args:
    - to_phone: The recipient's phone number (e.g., '+919876543210').
    - body: The message content.
    - account_sid: Optional Twilio SID (fallback to env)
    - auth_token: Optional Twilio Token (fallback to env)
    - from_whatsapp_number: Optional sender number (fallback to env)
    """
    account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp_number = from_whatsapp_number or os.getenv("WHATSAPP_NUMBER_FROM", "whatsapp:+14155238886")

    if not all([account_sid, auth_token, from_whatsapp_number]):
        logger.error("Missing Twilio/WhatsApp configuration in .env.")
        return False

    try:
        client = Client(account_sid, auth_token)
        
        # Twilio WhatsApp numbers MUST have the 'whatsapp:' prefix
        if not to_phone.startswith("whatsapp:"):
            target_phone = f"whatsapp:{to_phone}"
        else:
            target_phone = to_phone

        if not from_whatsapp_number.startswith("whatsapp:"):
            sender_phone = f"whatsapp:{from_whatsapp_number}"
        else:
            sender_phone = from_whatsapp_number

        message = client.messages.create(
            from_=sender_phone,
            body=body,
            to=target_phone
        )
        
        logger.info(f"WhatsApp message sent to {target_phone}. SID: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {str(e)}")
        return False

if __name__ == "__main__":
    # Test script (requires .env configuration)
    print("Testing WhatsApp Service...")
    # Replace with a real number for manual test
    success = send_whatsapp_message("+919876543210", "This is a test WhatsApp message from the Rio CRM Service. 🚀")
    if success:
        print("Test WhatsApp message sent!")
    else:
        print("Test WhatsApp message failed. Check .env configuration and console logs.")
