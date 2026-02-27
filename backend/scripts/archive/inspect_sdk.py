import cartesia
import inspect

def inspect_cartesia():
    c = cartesia.AsyncCartesia(api_key='test')
    
    print("--- STT Inspection ---")
    stt_methods = [a for a in dir(c.stt) if not a.startswith('_')]
    print("STT methods:", stt_methods)
    
    for method_name in stt_methods:
        try:
            method = getattr(c.stt, method_name)
            if callable(method):
                print(f"STT.{method_name} signature: {inspect.signature(method)}")
        except Exception as e:
            print(f"Failed to get STT.{method_name} signature: {e}")
        
    print("\n--- TTS Inspection ---")
    tts_methods = [a for a in dir(c.tts) if not a.startswith('_')]
    print("TTS methods:", tts_methods)
    
    for method_name in tts_methods:
        try:
            method = getattr(c.tts, method_name)
            if callable(method):
                print(f"TTS.{method_name} signature: {inspect.signature(method)}")
        except Exception as e:
            print(f"Failed to get TTS.{method_name} signature: {e}")

if __name__ == "__main__":
    inspect_cartesia()
