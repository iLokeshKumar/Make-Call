import whisper, os, csv

model = whisper.load_model("base")
wavs = [f for f in os.listdir("wavs") if f.endswith(".wav")]

with open("metadata.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        for wav in sorted(wavs):
            result = model.transcribe(f"wavs/{wav}")
            text = result["text"].strip()
            name = wav.replace(".wav", "")
            writer.writerow([name, text])
            print(f"{name} {wav}: {text}")

print("Done! Check metadata.csv for the transcriptions.")