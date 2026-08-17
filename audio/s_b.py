# Install SpeechBrain — has excellent speaker encoders
#pip install speechbrain

from speechbrain.inference import EncoderClassifier

# Load pretrained speaker encoder (trained on thousands of speakers)
encoder = EncoderClassifier.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir="pretrained_models/spkrec-ecapa-voxceleb"
)

# Get Priya's voice fingerprint — a 192-dim vector
embeddings = encoder.encode_batch(audio_tensor)
print("Voice fingerprint shape:", embeddings.shape)
# Output: torch.Size([1, 1, 192])
# This 192 numbers = Priya's unique voice identity