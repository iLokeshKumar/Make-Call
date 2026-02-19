# Cross-Repo Voice Agent Analysis
_Generated: 2026-02-18_

---

## What Each Repo Contributes

| Repo | Stack | Key Insight |
|------|-------|-------------|
| **Amiga** | Cartesia Line SDK + Claude Sonnet | Basic Cartesia agent structure. Uses Sonnet in main loop (too slow) |
| **voice-agent** | Cartesia Line SDK | **Best two-tier pattern**: Haiku main + Opus background with `is_background=True` |
| **Cartesian hackathon** | Cartesia Line SDK + Claude Sonnet | **Pre-call context fetch pattern**: loads prospect data before returning agent |
| **cartesia-voice-agent2** | Flask + WebRTC + Claude | **Anti-pattern**: Planner→Executor→Critic = 3 LLM calls per turn. Avoid |
| **memoryCatcher** | Cartesia Line SDK + Claude Sonnet | **Proactive injection**: monkey-patches ConversationRunner to speak after silence |
| **addy** | Cartesia TTS only | Not a voice agent. Skip |
| **Keto** | Node.js + Deepgram Flux + Cartesia TTS | **Best latency engineering**: EagerEndOfTurn + persistent TTS WebSocket + sentence streaming |
| **Make-Call** | FastAPI + Deepgram + Mistral/Gemini | Our app. Has 6 concrete latency problems identified below |

---

## Make-Call's 6 Latency Problems + Fixes

### Problem 1: Wrong Model in Mistral Pipeline
**Current**: `mistral-large-latest` — slowest Mistral model, ~800-1200ms TTFT

**Fix**: Swap to `mistral/mistral-small-latest` or better, use `gemini-2.0-flash-exp` (your Gemini pipeline already does this). If staying with Mistral, use `mistral-small`:

```python
# In mistral_voice_pipeline()
response = mistral_client.chat.stream(
    model="mistral-small-latest",  # was: mistral-large-latest
    messages=messages
)
```

Or just **deprecate the Mistral pipeline entirely** and route everything through your Gemini pipeline — it's already one WebSocket session (STT+LLM+TTS in one).

---

### Problem 2: Three Separate WebSocket Connections Per Call
**Current**: Deepgram WS (STT) + Mistral HTTP + ElevenLabs WS (TTS) — reconnected on each `speak()` call

**Fix from Keto**: Create a persistent TTS connection at session start, reuse it:

```python
# Create once per call session
eleven_ws = await create_elevenlabs_connection(voice_id)

async def speak(text: str):
    # Send text to already-open connection — no reconnect overhead
    await eleven_ws.send(json.dumps({"text": text}))
```

Or even better: **Gemini Live API already does this in one connection.** Route all calls through `gemini_voice_pipeline`.

---

### Problem 3: No Streaming — Waits for Full LLM Response Before TTS
**Current**: Waits for entire Mistral response → sends to ElevenLabs → user hears silence during LLM generation

**Fix from Keto**: Stream LLM tokens → detect sentence boundaries → send each sentence to TTS immediately:

```python
sentence_buffer = ""
sentence_endings = re.compile(r'(?<=[.!?])\s+')

async for chunk in mistral_client.chat.stream(model=..., messages=messages):
    token = chunk.data.choices[0].delta.content or ""
    sentence_buffer += token

    # Check if we have a complete sentence
    sentences = sentence_endings.split(sentence_buffer)
    if len(sentences) > 1:
        complete_sentence = sentences[0]
        sentence_buffer = " ".join(sentences[1:])
        # Send complete sentence to TTS immediately — don't wait!
        asyncio.create_task(speak(complete_sentence))
```

This means audio starts playing ~100-200ms into LLM generation instead of after it completes.

---

### Problem 4: All Tools Are Blocking Sync Functions
**Current**: `check_inventory`, `book_demo_tool`, `update_lead_tool` all use synchronous SQLModel sessions — blocks the event loop

```python
# Current (blocks event loop):
def check_inventory(product_name: str) -> str:
    with Session(engine) as session:  # sync DB call
        ...
```

**Fix**: Wrap with `asyncio.to_thread()`:

```python
async def check_inventory(product_name: str) -> str:
    def _db_query():
        with Session(engine) as session:
            result = session.exec(select(Product)...).all()
            return result

    result = await asyncio.to_thread(_db_query)
    return format_result(result)
```

Or migrate to `asyncpg`/`SQLAlchemy async` entirely.

---

### Problem 5: DB Reads on Every WebSocket Connection
**Current**: `SystemSettings` fetched fresh on every call connection

**Fix**: Cache at startup:

```python
_settings_cache = None

@app.on_event("startup")
async def load_settings():
    global _settings_cache
    with Session(engine) as session:
        _settings_cache = session.exec(select(SystemSettings)).first()

async def get_system_settings():
    return _settings_cache  # instant
```

---

### Problem 6: `save_transcript()` Called on Every Message (Sync DB Write)
**Current**: Every single message triggers a synchronous database write during the live call

**Fix**: Buffer and write async after call ends:

```python
# During call — just append to list (memory, instant)
transcript_buffer = []

def buffer_transcript(speaker: str, text: str):
    transcript_buffer.append({"speaker": speaker, "text": text, "ts": time.time()})

# After call ends — write all at once asynchronously
async def flush_transcript(call_id: str):
    await asyncio.to_thread(save_transcript_batch, call_id, transcript_buffer)
```

---

## Priority Order (Highest Impact First)

| Priority | Fix | Latency Saved |
|----------|-----|---------------|
| 1 | **Route all calls through Gemini pipeline** (kill Mistral pipeline) | ~600-800ms |
| 2 | **Sentence-level streaming to TTS** | ~400-700ms perceived latency |
| 3 | **Persistent TTS WebSocket** | ~150-300ms per turn |
| 4 | **Async tools** (wrap sync DB calls) | ~100-300ms |
| 5 | **Cache SystemSettings at startup** | ~50-100ms |
| 6 | **Buffer transcript writes** | ~20-50ms |

---

## Bonus: Two Patterns From Other Repos to Add

### From `voice-agent`: Two-tier model selection
If you want to keep the Mistral pipeline, use a fast model for most turns but a smarter model for complex objection handling:

```python
# Fast model for: greetings, basic Q&A, confirmations
# Smart model for: pricing objections, technical questions, closing

@loopback_tool(is_background=True)
async def handle_complex_objection(ctx, objection: str) -> AsyncIterable[str]:
    yield "Let me think about the best way to address that..."
    # Run Claude Sonnet/Opus in background while Haiku keeps talking
    response = await call_smart_model(objection)
    yield response
```

### From `Cartesian hackathon`: Pre-fetch prospect data before call connects
Instead of querying CRM on first tool call (during live call), fetch it before the call starts:

```python
async def start_outbound_call(prospect_id: str):
    # Fetch BEFORE starting call — user isn't on the line yet
    prospect_data = await fetch_prospect(prospect_id)

    # Pass as metadata in call request
    await twilio_client.calls.create(
        url=f"{WEBHOOK_URL}?prospect_id={prospect_id}&name={prospect_data.name}&company={prospect_data.company}",
        ...
    )

# In WebSocket handler — data is already available instantly
prospect_name = request.query_params.get("name")
```

---

## TL;DR

**Quickest wins for Make-Call:**
1. Kill the Mistral pipeline, route everything through Gemini (already built)
2. Add sentence-level streaming so TTS starts before LLM finishes
3. Wrap all DB calls in `asyncio.to_thread()`
4. Cache SystemSettings at startup

The Gemini Live API (already in your codebase) is genuinely the most latency-optimal architecture for your stack — one WebSocket handles everything natively. The Mistral+ElevenLabs pipeline has fundamental structural latency that's hard to optimize away.
