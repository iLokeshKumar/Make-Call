# Voice Latency Tuning

How to read `/analytics` → **Latency** tab and act on the numbers. Roadmap target:
**voice turn-taking p95 ≤ 800ms**. SLO status visible at `/admin/slo-status`.

## What you're looking at

Each call writes one `LatencyLog` row per turn with:

* `stt_ms` — speech-to-text transcription time
* `llm_ms` — LLM stream-to-finished time (includes Mistral throttle)
* `tts_ms` — first byte of TTS audio
* `total_ms` — perceived turn-taking latency (sum + small overhead)
* `engine` — `{stt}-{llm}-{tts}` triplet
* `*_provider` / `*_model` — per-stage breakdown

`/analytics?tab=Latency` aggregates these per engine, per call, per model, plus
a daily trend line. The engine cards now show **p95 total** and **p95 llm**
inline — that is the actionable percentile for SLO target ≤ 800ms.

## Decision tree

### 1. Engine card shows p95 total > 800ms (red)

Find the dominant stage in the stacked bar (STT / LLM / TTS):

| Dominant stage | Action |
|---|---|
| `llm_avg` > 600ms or `llm_p95` > 600ms | Compare engines on the same row. If one engine's p95 LLM beats another's by > 200ms over the window, switch in `/settings`. |
| `stt_avg` > 400ms | Switch STT provider. Deepgram nova-2 ≈ 150ms, Sarvam ≈ 250ms (typical). |
| `tts_avg` > 300ms | Switch TTS provider. Cartesia sonic ≈ 80ms first-byte, ElevenLabs flash-2 ≈ 150ms. |
| All three balanced | Open the **Calls** sub-tab — usually a few outliers (rate-limit retries, network blips) skew p95. |

### 2. Provider comparison

The **Models** sub-tab ranks STT/LLM/TTS models independently by avg latency.
The engine cards ranked by total avg let you see the combined effect.
**A 200ms p95 gap over a week's data is a meaningful signal.**

### 3. Switching providers

`/settings` → General tab → LLM/STT/TTS provider dropdowns. Saves to
`CompanySetting` (`LLM_PROVIDER`, `LLM_MODEL`, `STT_PROVIDER`, `TTS_PROVIDER`).
Next call uses the new provider immediately — no restart.

### 4. Cooldown after switching

Wait at least 24 hours before re-evaluating. Small sample of calls with
new provider can swing p95 wildly.

## Mistral 429 signal

`/health` exposes `mistral_429_last_15min` — count of rate-limit hits in
last 15 minutes. If this stays > 0 across multiple cycles you're
hitting free-tier bucket and should:

1. Switch to different LLM provider, OR
2. Upgrade Mistral plan, OR
3. Throttle harder in `services/call/post_call_service.py` (currently 1.2s
   between LLM calls in post-call pipeline).

## What's NOT auto-failover

Provider selection is **manual + data-driven**. No runtime fallback that
swaps providers mid-call when one rate-limits. If you want that behaviour,
see deferred Week 8.5 section in `docs/ROADMAP.md`.
