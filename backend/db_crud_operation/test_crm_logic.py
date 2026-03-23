def test_logic():
    # Mirrored logic from crm.py
    def is_valid_key(key):
        return (key.endswith("_API_KEY") or 
                key.endswith("_SID") or 
                key.endswith("_TOKEN") or 
                key.endswith("_MODEL") or 
                key.endswith("_VOICE_ID") or 
                key.endswith("_VOICE") or 
                key in ["PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM", "EXOPHONE", "EXOTEL_APP_ID", "ENABLEX_APP_ID", "ENABLEX_APP_KEY", "ENABLEX_FROM_NUMBER"])

    keys_to_test = [
        "MISTRAL_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "PHONE_NUMBER_FROM",
        "WHATSAPP_NUMBER_FROM",
        "EXOTEL_ACCOUNT_SID",
        "EXOTEL_API_KEY",
        "EXOPHONE",
        "ENABLEX_FROM_NUMBER",
        "MISTRAL_MODEL",
        "OPENROUTER_MODEL",
        "ELEVENLABS_VOICE_ID",
        "CARTESIA_VOICE_ID",
        "DEEPGRAM_VOICE",
        "SOME_OTHER_SETTING",
        "DEBUG_MODE"
    ]

    print("Checking key validation logic:")
    for k in keys_to_test:
        print(f"{k}: {is_valid_key(k)}")

    # Check filtering logic (mirrored SQL select part)
    # This is harder to test without SQLModel, but the logic is straightforward
    
if __name__ == "__main__":
    test_logic()
