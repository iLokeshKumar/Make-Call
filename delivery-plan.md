# Voice Agent — Task Delivery Plan
_Generated: 2026-02-19_

---

## Phase 1 — Unblock Everything (Day 1, no code)

**SK-8** — Indian voice evaluation and selection

This is not a coding task. Go to cartesia.ai/india, test voices, pick one, get the voice ID. Everything else is blocked until this decision is made. Do it first, do it today.

---

## Phase 2 — Core Pipeline (Week 1, highest impact)

**SK-4 → SK-5 → SK-6** in sequence, they're one logical unit

| Card | What it delivers | Latency saved |
|------|-----------------|---------------|
| SK-4 | New pipeline: Deepgram + Gemini Flash + Cartesia | ~600-800ms |
| SK-5 | Sentence streaming — audio starts mid-generation | ~400-700ms |
| SK-6 | Persistent Cartesia WebSocket | ~150-300ms |

Don't ship SK-4 without SK-5 and SK-6. The pipeline alone without streaming and persistent connections is only half the fix. These three ship together as one release.

---

## Phase 3 — Quick Wins (Week 1, run in parallel with Phase 2)

**SK-1, SK-2, SK-7** — any developer can do these alongside the pipeline work

| Card | What it delivers | Effort |
|------|-----------------|--------|
| SK-7 | Async DB tools — one pattern applied four times | ~half a day |
| SK-1 | Cache SystemSettings at startup | ~30 minutes |
| SK-2 | Buffer transcript writes | ~30 minutes |

No dependencies, no risk. Ship these as a batch.

---

## Phase 4 — Voice Integration (After Phase 2 ships)

**SK-3** — wire the selected Cartesia voice into the persistent WebSocket

This is a small card but it depends on SK-8 (voice ID) and SK-4 (new pipeline) both being done. Don't start until Phase 2 is fully shipped and tested.

---

## Phase 5 — Architecture Upgrades (Week 2-3, after core is stable)

Only start these once the latency is fixed and you've verified the call quality is good.

| Card | What it delivers | Complexity |
|------|-----------------|------------|
| SK-10 | Pre-fetch prospect data before call connects | Low — changes trigger function only |
| SK-11 | Proactive silence handling | Medium — ConversationRunner patch |
| SK-9 | Two-tier model (Haiku + Sonnet for objections) | High — agent class refactor |

Do SK-10 first — highest value for lowest effort. SK-11 next. SK-9 last because it's the most structural change.

---

## Summary Timeline

```
Day 1       → SK-8  (pick the voice, unblocks everything)

Week 1      → SK-4 + SK-5 + SK-6  (ship together — new pipeline)
              SK-1 + SK-2 + SK-7  (ship as a batch, parallel work)

After W1    → SK-3  (wire voice into pipeline)

Week 2-3    → SK-10 → SK-11 → SK-9
```

---

## The One Non-Negotiable

Phase 2 (SK-4, SK-5, SK-6) is the most important delivery. Everything else is incremental. If only one thing ships, it should be those three cards together — that's where 80% of the latency lives.
