# Rio CRM — Service Level Objectives

Four SLOs the platform commits to. Surfaced live at `/admin/slo-status`.
Breaches alert via SMTP + Slack (`SLACK_WEBHOOK_URL`) once per 60-min per
SLO. Computed every 15 min per company by the automation worker.

| # | SLO | Target | Window | Source |
|---|---|---|---|---|
| 1 | API availability | ≥ 99.5% | since restart¹ | in-process counter via `_RequestContextMiddleware` |
| 2 | Login → dashboard p95 | ≤ 2000 ms | 7 days | `UiLatencyLog` rows where `event=fmp` and `route=/` |
| 3 | Voice turn-taking p95 | ≤ 800 ms | 7 days | `LatencyLog.total_ms` |
| 4 | Agent-task dead-letter rate | ≤ 0.5% | 7 days | `BackgroundJob.status='dead_letter'` ÷ total |

¹ SLO #1's window is "since last restart" until persistent request logging
lands. The in-process counter resets when the FastAPI process restarts.

## Status rules

For each SLO the endpoint returns one of:

* **`ok`** — within target.
* **`at_risk`** — within 80–100% of target (lower-is-better metrics only).
* **`breach`** — over target (lower-is-better) or under target (higher-is-better).
* **`insufficient_data`** — < 10 samples in the window. Don't false-alarm.

`direction` field marks each SLO as `lower_is_better` (latency / error rate)
or `higher_is_better` (availability / uptime).

## Soft-launch

`SLO_ALERTS_ENABLED_AT` env (ISO timestamp). Until that moment passes,
breach evaluation runs but no alerts fire — useful at first rollout when
voice p95 sits above 800ms. Set 24h ahead of cutover.

## Alert channels

Both fire on breach (independent — failure on one never blocks the other):

* **Slack** — `SLACK_WEBHOOK_URL` env. Free incoming webhook from any
  Slack workspace. No SaaS account on the alerter side.
* **SMTP** — `SLO_ALERT_EMAIL` env (or `ADMIN_ALERT_EMAIL`). Reuses the
  same `email_service.send_smtp_email` path that already powers
  dead-letter alerts.

`docs/SLOs.md` is the single source of truth; targets edit here first,
code follows.

## Manual evaluation

```bash
curl -b cookies.txt http://localhost:6060/admin/slo-status | jq .
```

Returns:

```json
{
  "slos": [
    {"id": "voice_p95_ms", "target": 800, "actual": 1420, "status": "breach",
     "window": "7d", "samples": 142, "unit": "ms", "direction": "lower_is_better"},
    ...
  ],
  "generated_at": "2026-04-25T..."
}
```
