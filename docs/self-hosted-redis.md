# Self-hosted Redis on Compute Engine

Terraform module: `infra/modules/self_hosted_redis/`.

Replaces the managed MemoryStore Redis instance (~$36/mo, BASIC M1 1 GB) with
a single e2-micro Compute Engine VM running Redis 7 + periodic GCS snapshots
for durability. Motivation: our actual Redis usage is <5 MB of ~63 keys with
~200 commands/day — MemoryStore was ~85% over-provisioned by memory and cost.

## Cost

- VM (e2-micro, us-west1, 24×7): ~$5/mo (potentially $0 if the always-free
  tier e2-micro slot isn't taken by another project)
- Standard persistent disk (10 GB): ~$0.40/mo
- GCS snapshot storage (~5 MB × 20 retained): ~$0.001/mo
- **Total: ~$5–6/mo** vs. $36/mo before, ~85% cut.

## Architecture

```
┌────────────┐   VPC connector /28   ┌──────────────────────────┐
│ Cloud Run  │ ────────────────────► │ e2-micro VM (Debian 12)  │
│            │  10.11.0.0/28 → :6379 │  Redis 7 (systemd)       │
└────────────┘                       │  RDB + AOF persistence   │
                                     │  Ops Agent (metrics/logs)│
                                     └──────────────┬───────────┘
                                                    │ every 6h
                                                    ▼
                                     ┌──────────────────────────┐
                                     │ GCS: <name>-snapshots-xx │
                                     │  dump-YYYY-MM-DD-HHMMSS  │
                                     │  30-day lifecycle prune  │
                                     └──────────────────────────┘
```

Only the Cloud Run VPC access connector's `/28` can reach the VM on `:6379`
(firewall rule). The VM has no external IP. Redis also has a randomly
generated AUTH password (stored in Secret Manager as
`wms-chatbot-redis-password`, fetched by the VM on every boot) so
network-level ACL failures don't hand out unauthenticated access.

### Rotating the password

```bash
# Generate a new 32-char password and add it as a new secret version:
PROJECT=wms-chatbot-staging
NEW=$(python3 -c "import secrets, string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(32)))")
echo -n "$NEW" | gcloud secrets versions add wms-chatbot-redis-password --data-file=- --project=$PROJECT

# Reboot the VM so its startup script re-fetches the new password:
gcloud compute instances reset wms-chatbot-redis --zone=us-west1-a --project=$PROJECT

# Update REDIS_URL wherever consumers store it (Cloud Run secret) — this
# module's redis_url output includes the password, so `make deploy` after
# `make apply` propagates it end-to-end.
```

## Managing the VM

```bash
# Terraform stands the VM up alongside MemoryStore (no cutover yet):
cd infra
make apply

# Get the new REDIS_URL:
make output | grep self_hosted_redis_url
# → self_hosted_redis_url = "redis://10.10.0.X:6379/0"

# Snapshot bucket name (holds the periodic RDB backups):
make output | grep self_hosted_redis_snapshot_bucket
```

## SSH into the VM

Direct SSH is disabled (no public IP). Use IAP TCP tunneling — Google's
identity-verified alternative that runs through the console:

```bash
gcloud compute ssh wms-chatbot-redis \
  --zone=us-west1-a --tunnel-through-iap --project=wms-chatbot-staging
```

Once in:

```bash
# Fetch the password (VM's SA can read the secret):
PASS=$(gcloud secrets versions access latest --secret=wms-chatbot-redis-password --project=wms-chatbot-staging)

# Check Redis (all redis-cli calls need -a "$PASS")
sudo systemctl status redis-server
redis-cli -a "$PASS" --no-auth-warning INFO server | head
redis-cli -a "$PASS" --no-auth-warning DBSIZE
redis-cli -a "$PASS" --no-auth-warning MEMORY STATS | head -20

# Check snapshot timer
sudo systemctl status wms-redis-snapshot.timer
sudo journalctl -u wms-redis-snapshot.service --since "24 hours ago"

# Ops Agent status
sudo systemctl status google-cloud-ops-agent
```

## Restore from a snapshot

```bash
# On your local machine, list snapshots:
BUCKET=$(terraform -chdir=envs/staging output -raw self_hosted_redis_snapshot_bucket)
gsutil ls gs://$BUCKET/

# SSH to the VM
gcloud compute ssh wms-chatbot-redis --zone=us-west1-a --tunnel-through-iap

# On the VM:
sudo systemctl stop redis-server
sudo gsutil cp gs://<bucket>/dump-<timestamp>.rdb /var/redis/dump.rdb
sudo chown redis:redis /var/redis/dump.rdb
sudo systemctl start redis-server
redis-cli DBSIZE   # should match the snapshot's key count
```

## Migration from MemoryStore (PR 2 will automate)

MemoryStore supports RDB export directly to a GCS bucket:

```bash
gcloud redis instances export gs://<bucket>/memorystore-dump.rdb \
  wms-chatbot-redis --region=us-west1
```

Then copy that RDB onto the VM's `/var/redis/dump.rdb` and restart Redis
(see restore steps above).

## Failure modes to know about

| Symptom | Cause | Fix |
|---|---|---|
| Chat responses 500 after a minute of silence | VM rebooted, in-memory state gone | Restore from latest GCS snapshot (see above). AOF file on disk also gives recovery to the last write, so usually just `systemctl start redis-server` is enough. |
| `make apply` shows VM being replaced | Boot disk image changed (Debian version bump) | The lifecycle block ignores this by default; if you see a replace plan anyway, verify the image field is what changed and don't apply — a replace destroys the disk. |
| Ops Agent shows no metrics | Startup script didn't complete | SSH to VM, `bash /var/lib/wms-chatbot-redis-installed` marker missing → re-run startup script by rebooting the VM (`gcloud compute instances reset`). |
| Snapshots stopped landing in GCS | Timer failed or SA lost bucket access | `journalctl -u wms-redis-snapshot.service` on VM. IAM: verify the VM SA still has `roles/storage.objectAdmin` on the bucket. |

## What's NOT in this PR

- Cutover of Cloud Run to point at this VM (PR 2)
- MemoryStore decommission — that's the bill-dropping apply (PR 3)
- Dashboard tiles for the VM's Ops Agent metrics — added when MemoryStore
  goes away in PR 3, since the monitoring module currently filters on the
  MemoryStore instance-id

This PR (1) only stands up the VM alongside MemoryStore so we can test it
in isolation before touching production traffic.
