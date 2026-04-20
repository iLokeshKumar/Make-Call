# gstack on Rio CRM — implementation & usage guide

Last updated: 2026-04-20

---

## 1. How it's installed

| Aspect | Value |
|---|---|
| Install type | **global-git** (single shared copy) |
| Install path | `~/.claude/skills/gstack/` |
| Version | `v1.4.0.0` (upgraded from v1.0.0.0 on 2026-04-20) |
| Local vendored copy | None (cleaner — updates apply everywhere) |
| Config file | `~/.gstack/config.yaml` |
| Project memory | `~/.gstack/projects/iLokeshKumar-Make-Call/` |
| Project `CLAUDE.md` | Yes — includes skill-routing rules |

### Config (already set)

```yaml
telemetry: community    # anonymous device ID + usage stats
proactive: true         # Claude auto-invokes skills when triggers match
skill_prefix: false     # use /ship, /qa (not /gstack-ship)
```

### To change config

```bash
~/.claude/skills/gstack/bin/gstack-config set <key> <value>
# Examples:
~/.claude/skills/gstack/bin/gstack-config set telemetry off
~/.claude/skills/gstack/bin/gstack-config set proactive false
~/.claude/skills/gstack/bin/gstack-config set auto_upgrade true
```

---

## 2. All 41 skills, grouped by when to use them

### Daily — every bug, every PR

| Skill | What it does | When to use |
|---|---|---|
| `/investigate` | 4-phase structured debugging with root-cause gate | Any bug. Don't debug manually. |
| `/review` | Pre-landing diff review against base branch | Before every merge |
| `/qa` | Headless browser tests → finds bugs → commits fixes | Before major PRs |
| `/qa-only` | Same as above but report-only, no fixes | When you want a bug list without code changes |
| `/ship` | Test + review + bump version + commit + push + PR | Every time you want to ship |
| `/design-review` | Live site audit (visual polish, AI slop) | After any UI change |

### Weekly / on-demand

| Skill | What it does |
|---|---|
| `/health` | Composite 0-10 score (typecheck + lint + tests + dead code) |
| `/retro` | Commit-history retro with team-aware breakdown |
| `/benchmark` | Performance regression (page loads, Core Web Vitals, bundle size) |
| `/cso` | Security audit (OWASP, STRIDE, supply chain, LLM/AI risks) |
| `/canary` | Post-deploy monitoring (console errors, perf, anomalies) |

### Planning before you code

| Skill | What it does |
|---|---|
| `/office-hours` | YC-style forcing questions for new ideas |
| `/plan-ceo-review` | "Think bigger / strip to essentials" scope review |
| `/plan-eng-review` | Architecture + tests + edge cases review |
| `/plan-design-review` | UI/UX plan review (0-10 per dimension) |
| `/plan-devex-review` | Developer experience plan review |
| `/plan-tune` | Tune AskUserQuestion sensitivity + developer profile |
| `/autoplan` | Runs all plan reviews sequentially with auto-decisions |

### Design workflow

| Skill | What it does |
|---|---|
| `/design-consultation` | Creates `DESIGN.md` — project's design source of truth |
| `/design-shotgun` | Multiple AI design variants on a comparison board |
| `/design-html` | Turns approved mockups into production HTML/CSS |

### Session / context management

| Skill | What it does |
|---|---|
| `/context-save` | Save progress to plain markdown (grep-able) |
| `/context-restore` | Resume from saved state or WIP commits |
| `/checkpoint` | Alias (native Claude Code rewind) |
| `/freeze` | Lock edits to one directory (debugging scope) |
| `/unfreeze` | Clear freeze boundary |
| `/careful` | Warn before rm -rf, DROP TABLE, force-push, etc. |
| `/guard` | Careful + freeze combined |

### Deploy

| Skill | What it does |
|---|---|
| `/setup-deploy` | Detects + configures deploy platform |
| `/land-and-deploy` | Merge PR → wait for CI → verify prod via canary |
| `/document-release` | Post-ship docs update (README, CHANGELOG, ARCHITECTURE) |

### Browser / specialized

| Skill | What it does |
|---|---|
| `/connect-chrome` | Launch GStack Browser (headed Chromium + sidebar extension) |
| `/browse` / `/gstack` | Headless browser for QA scripts |
| `/pair-agent` | Let another AI agent share your browser |
| `/setup-browser-cookies` | Import cookies from real browser for authed QA |
| `/codex` | OpenAI Codex CLI wrapper for second opinions |
| `/benchmark-models` | Cross-model benchmark (Claude vs GPT vs Gemini) |
| `/make-pdf` | Markdown → publication-quality PDF |
| `/learn` | Review accumulated project learnings |
| `/gstack-upgrade` | Upgrade to latest gstack |

---

## 3. Recommended rhythm for Rio CRM

### Per-bug workflow

```
1. Hit a bug
2. /investigate            ← Don't debug manually
3. Follow its 4 phases (investigate → analyze → hypothesize → implement)
4. Test the fix
5. Commit
```

### Per-PR workflow

```
1. Finish the feature
2. /review                 ← Pre-landing diff review
3. /qa                     ← Browser tests + auto-fix UI bugs
4. /ship                   ← Tests + commit + push + PR
5. /land-and-deploy        ← After PR approval, merge + verify prod
```

### Per-UI-change workflow

```
1. Ship the change
2. /design-review <url>    ← Visual audit
3. If score is C or below → apply Quick Wins
4. /qa <url>               ← Functional smoke test
```

### Weekly workflow

```
Friday:   /retro            ← what shipped, what stalled
Friday:   /health           ← code quality snapshot
Monthly:  /cso              ← security audit (you handle PII + Twilio creds + call recordings)
```

### One-time setup (do this week)

```
/design-consultation        ← Create DESIGN.md so /design-review evaluates against YOUR system
/setup-deploy               ← Wire up /land-and-deploy end-to-end
```

---

## 4. Today's session cheat-sheet (what we used)

| Skill | Ran it | Result |
|---|---|---|
| `/connect-chrome` | ✅ | GStack Browser running, sidebar extension connected on port 34567 |
| `/design-review` | ✅ | Login page scored **B-** / AI Slop **D**. Report at `C:\Users\User\AppData\Local\Temp\design-audit-login\` |
| `/investigate` | ❌ | Would have reached Mistral TTS's `audio_data` field faster than manual diag |
| `/ship` | ❌ | Yet to use — your WIP is uncommitted |

---

## 5. Anti-patterns to avoid

| Don't | Because |
|---|---|
| Vendor a copy of gstack into the repo | Global install auto-updates; vendored copies go stale |
| Invoke 5 skills in a row blindly | Pick the one skill that matches the moment |
| Skip `/investigate` because "I know the bug" | You usually don't. Today's SSE vs f32le bug is proof. |
| Install duplicate skills per-project | `/skill_prefix: false` default is the right choice |
| Commit WIP without `/review` | Pre-landing review catches SQL / LLM trust boundary issues |

---

## 6. Useful bin tools (under the hood)

At `~/.claude/skills/gstack/bin/`:

| Tool | Purpose |
|---|---|
| `gstack-config` | Get/set config keys |
| `gstack-update-check` | Check for a new version |
| `gstack-learnings-log` | Log a project learning |
| `gstack-learnings-search` | Search past learnings by keyword |
| `gstack-timeline-log` | Local-only session timeline |
| `gstack-slug` | Emit project identifier (`iLokeshKumar-Make-Call`) |
| `gstack-repo-mode` | Detect solo vs collaborative repo mode |

---

## 7. External resources

- Main repo: https://github.com/garrytan/gstack
- Completeness principle: https://garryslist.org/posts/boil-the-ocean
- Each skill's full spec: `~/.claude/skills/gstack/<skill-name>/SKILL.md`

---

## 8. Keep this doc updated

Whenever you try a new skill, add a one-line row to the "Today's session" table. When you change config, update section 1. When you find your own rhythm, adjust section 3.

This doc is for future-you at 2am when you're debugging another voice-pipeline bug and wondering "which skill do I reach for?"
