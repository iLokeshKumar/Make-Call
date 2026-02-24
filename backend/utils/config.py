import os
from dotenv import load_dotenv
from cartesia import Cartesia, AsyncCartesia
from sarvamai import SarvamAI, AsyncSarvamAI
from mistralai import Mistral as MistralClient
from twilio.rest import Client as TwilioClient

load_dotenv()

# Telephony
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PHONE_NUMBER_FROM = os.getenv("PHONE_NUMBER_FROM")

EXOTEL_API_KEY = os.getenv("EXOTEL_API_KEY")
EXOTEL_API_TOKEN = os.getenv("EXOTEL_API_TOKEN")
EXOTEL_ACCOUNT_SID = os.getenv("EXOTEL_ACCOUNT_SID")
EXOPHONE = os.getenv("EXOPHONE")

ENABLEX_APP_ID = os.getenv("EnableX_App_ID")
ENABLEX_APP_KEY = os.getenv("EnableX_App_Key")
ENABLEX_FROM_NUMBER = os.getenv("ENABLEX_FROM_NUMBER")

# AI Services
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "CwhOLp6mAE7h9asvUURR")

# Server Config
DOMAIN = os.getenv("DOMAIN", "localhost")
if DOMAIN:
    DOMAIN = DOMAIN.replace("http://", "").replace("https://", "").replace("/", "")
PORT = int(os.getenv("PORT", 6060))

# SDK Clients
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
cartesia_client = Cartesia(api_key=CARTESIA_API_KEY)
async_cartesia_client = AsyncCartesia(api_key=CARTESIA_API_KEY)
sarvam_client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
async_sarvam_client = AsyncSarvamAI(api_subscription_key=SARVAM_API_KEY)
