import deepgram
print(dir(deepgram))
try:
    from deepgram import DeepgramClientOptions
    print("DeepgramClientOptions found in root")
except ImportError:
    print("DeepgramClientOptions NOT found in root")

try:
    from deepgram import LiveOptions
    print("LiveOptions found in root")
except ImportError:
    print("LiveOptions NOT found in root")
    
try:
    from deepgram import LiveTranscriptionEvents
    print("LiveTranscriptionEvents found in root")
except ImportError:
    print("LiveTranscriptionEvents NOT found in root")
