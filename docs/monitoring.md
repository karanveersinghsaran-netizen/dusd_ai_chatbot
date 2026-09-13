# Monitoring — dashboard, log-based metrics, and alerts

Terraform-managed Cloud Monitoring setup for the `wms-chatbot` service.
Replaces the ad-hoc `gcloud logging read` queries in past sessions with a
single bookmarkable dashboard, and pages on the four failure modes most
likely to matter.

Module: `infra/modules/monitoring/`
Wired in: `infra/envs/staging/main.tf`

---

## Applying

```bash
# From infra/, first time or after changes:
make plan   # confirm the diff
make apply  # provisions the dashboard, alerts, notification channel, log metrics
make output # prints the dashboard URL under `monitoring_dashboard_url`
```

Everything under this module is free (Cloud Monitoring dashboards + log-based
metrics have generous free tiers; four alert policies is well under the free
limit) — no billing impact.

## Opening the dashboard

After `make apply`, the top-level output `monitoring_dashboard_url` is a
direct link. Bookmark it.

Layout is 3 rows × 3 tiles:

| Row | Purpose |
|---|---|
| **Ops** | Request rate (by status class), latency p50/p95/p99, Cloud Run instance count |
| **Adoption** | Chat requests/hour (log-based), unique users/day (distinct IPs, log-based), feedback submissions/day |
| **Resources** | Cloud SQL CPU %, Redis memory %, Redis key count |

## Alerts

Four policies, all with 30-min auto-close:

| Policy | Fires when | Why |
|---|---|---|
| **Elevated 5xx rate** | 5xx ratio > 5% for 5 min | Real server errors, not a single blip |
| **/chat p95 > 30s** | p95 latency > 30s for 5 min | Usually means Claude API is degraded |
| **Cloud SQL CPU > 80%** | for 15 min | Sustained DB pressure — db-f1-micro can spike briefly on autovacuum |
| **Redis memory > 80%** | for 5 min | At current usage (~5 MB / 1 GB) this = 200× growth. Almost always a leaked key or runaway loop. |

### Notification channel

- Pass `alert_email = "..."` in `terraform.tfvars` to have alerts email that
  address.
- **Google sends a verification email on first apply. The recipient must
  click the link before any alert actually delivers**; the channel stays in
  "unverified" status otherwise.
- Alerts still exist and are visible in the console with no email set — they
  just don't page anyone.

## Log-based metrics

Two custom counters shipped by the module:

- `wms_chatbot/chat_requests_by_ip` — one per successful `/chat` response,
  with a `remote_ip` label. The dashboard aggregates this as
  `count_distinct(remote_ip)` per day to get unique-user counts. Free tier is
  generous (a few $ / month at 10× current volume).
- `wms_chatbot/feedback_submissions` — one per successful
  `/feedback/{thanks,report}` POST, labeled by which endpoint. Adds a
  visible "is feedback happening?" chart without querying Postgres.

Log-based metrics take ~5 minutes to start showing data after apply — Cloud
Logging batches its metric extractions.

## Cost note

Everything in this module is on Cloud Monitoring's free tier for our volume:

- Dashboards: unlimited
- Log-based metric datapoints: 100 MB / month included; we're at < 1 MB
- Alert policies: 5 included; we use 4
- Notification channels: 100 included; we use 1
