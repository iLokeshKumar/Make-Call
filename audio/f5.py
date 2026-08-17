import torchaudio, soundfile as sf, torch

def _sf_load(path, *a, **kw):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr  # (channels, samples)

torchaudio.load = _sf_load

from f5_tts.api import F5TTS

REF_AUDIO = r"E:\something_new\audio\dataset\wavs\seg_00098.wav"
REF_TEXT  = "Sir, I am Aswini here, sir, from Yexis Electronics, regional distributors of Samsung. So, yesterday I called you that you were in PF office. Now is it..."
GEN_TEXT  = "Hello sir, good morning. This is Aswini calling from Yexis Electronics. How can I assist you today?"
OUT_FILE  = r"E:\something_new\audio\f5_output.wav"

tts = F5TTS()
tts.infer(
    ref_file=REF_AUDIO,
    ref_text=REF_TEXT,
    gen_text=GEN_TEXT,
    file_wave=OUT_FILE,
    show_info=print,
)
print(f"Saved: {OUT_FILE}")
