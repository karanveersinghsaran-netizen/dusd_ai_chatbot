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

## Migration from MemoryStore — one-time cutover runbook

Order matters. Read once end-to-end before starting.

### 0. Preconditions

- PR merging the `plain_env_vars.REDIS_URL = module.self_hosted_redis.redis_url` change is already merged to master (Cloud Run will pick it up on the next `make deploy`, NOT before). Verify with:
  ```bash
  git -C .. log --oneline -3 | grep -i "self-hosted-redis-cutover"
  ```
- Self-hosted Redis VM is running with the container up (see the SSH + PING check above).
- You know the MemoryStore instance name (`wms-chatbot-redis`) and region (`us-west1`).

### 1. Grant MemoryStore's service agent write access to the snapshot bucket

MemoryStore exports via a Google-managed service agent. It needs write access to the target bucket. One-time IAM grant:

```bash
PROJECT_NUMBER=$(gcloud projects describe wms-chatbot-staging --format='value(projectNumber)')
BUCKET=$(terraform -chdir=envs/staging output -raw self_hosted_redis_snapshot_bucket)
gsutil iam ch \
  "serviceAccount:service-${PROJECT_NUMBER}@cloud-redis.iam.gserviceaccount.com:objectAdmin" \
  "gs://${BUCKET}"
```

### 2. Export MemoryStore to the snapshot bucket

```bash
gcloud redis instances export "gs://${BUCKET}/memorystore-dump-$(date -u +%Y-%m-%d).rdb" \
  wms-chatbot-redis --region=us-west1 --project=wms-chatbot-staging
```

Takes ~30 seconds for our data size (~5 MB). Wait for the command to return before continuing.

### 3. Copy the RDB onto the VM and reload Redis

SSH in via IAP:

```bash
gcloud compute ssh wms-chatbot-redis --zone=us-west1-a --tunnel-through-iap \
  --project=wms-chatbot-staging
```

Then on the VM:

```bash
# 1. Fetch the exported RDB from GCS
BUCKET=$(sudo journalctl -u google-startup-scripts.service | grep -oE 'gs://[^"]*snapshots-[a-f0-9]+' | head -1 | sed 's|gs://||' | awk -F/ '{print $1}')
# Or set manually: BUCKET=wms-chatbot-redis-snapshots-xxxxxxxx

# List available exports:
sudo gsutil ls "gs://${BUCKET}/memorystore-*.rdb"

# Download the newest export to the container's data dir:
DUMP=$(sudo gsutil ls "gs://${BUCKET}/memorystore-*.rdb" | sort | tail -1)
sudo gsutil cp "${DUMP}" /var/lib/redis-data/dump.rdb

# 2. Stop Redis so we can replace its data files cleanly
sudo systemctl stop wms-redis-container

# 3. Redis 7 prefers AOF over RDB when both are present. Delete the AOF so
#    Redis loads the newly-copied RDB on next start.
sudo rm -rf /var/lib/redis-data/appendonly.aof /var/lib/redis-data/appendonlydir

# 4. Ensure the redis user (uid 999 inside the container) owns dump.rdb
sudo chown 999:999 /var/lib/redis-data/dump.rdb

# 5. Start Redis — it'll read dump.rdb on load
sudo systemctl start wms-redis-container

# 6. Verify data loaded: DBSIZE should match MemoryStore's key count
sudo docker exec wms-redis \
  redis-cli -a "$(sudo cat /etc/redis/password.env | cut -d= -f2)" --no-auth-warning DBSIZE
```

Expected `DBSIZE`: matches what MemoryStore had (`gcloud redis instances describe wms-chatbot-redis --region=us-west1 --format='value(currentLocationId)'` doesn't give key count, but if you SSH'd MemoryStore separately or checked the `redis.googleapis.com/keyspace/keys` metric, you know the number).

### 4. Cut Cloud Run over

At this point Cloud Run is still talking to MemoryStore. The Terraform change is applied but Cloud Run's env vars don't refresh until a new revision is deployed:

```bash
cd infra
make apply    # confirms the env-var change is reflected in the service definition
make deploy   # builds + pushes + deploys a fresh revision that reads REDIS_URL = self-hosted VM
```

The new revision starts, drains the old one. Chats now hit the VM.

### 5. Verify /chat works end-to-end

Open the chatbox in a browser (or via `chatbox?token=...`) and send a real message. Then on the VM:

```bash
sudo docker exec wms-redis \
  redis-cli -a "$(sudo cat /etc/redis/password.env | cut -d= -f2)" --no-auth-warning DBSIZE
# ↑ should increment after each chat (conversation history keys)
```

Also check the monitoring dashboard — the "Chat requests" tile should keep populating and the Redis metrics from the VM's Ops Agent should show non-zero activity.

### 6. Delete the migration RDB (optional)

Once you've confirmed the cutover held for a day, the intermediate `memorystore-dump-*.rdb` in the snapshot bucket can go:

```bash
sudo gsutil rm "gs://${BUCKET}/memorystore-dump-*.rdb"
```

MemoryStore itself stays alive for PR 3 to destroy — that's the bill-dropping apply.

## One-time migration to the persistent data disk

When PR "Persistent Redis data disk" lands, the VM gets a separate 10 GB
`google_compute_disk` (attached, not part of the boot disk). Data on it
survives VM destroy/replace. But the migration requires manually moving
data OFF the boot disk BEFORE the new startup-script logic mounts the
empty new disk on top of `/var/lib/redis-data` and masks the old data.

**Order matters — read all steps before starting.**

### 1. Apply Terraform — creates + attaches the disk

```bash
cd infra
make apply
```

Expected plan:
- `+ google_compute_disk.redis_data` (new)
- `~ google_compute_instance.redis` (in-place update: attaches disk)
- No VM replacement — `metadata_startup_script` is in ignore_changes

After apply, the disk is attached but **NOT mounted** on the VM (the
startup script hasn't run since it was attached).

### 2. Take a fresh RDB snapshot as insurance

```bash
# Right after step 1, in case anything below goes sideways:
gcloud compute ssh wms-chatbot-redis --zone=us-west1-a --tunnel-through-iap \
  --project=wms-chatbot-staging --quiet --command='
  sudo docker exec wms-redis redis-cli \
    -a "$(sudo cat /etc/redis/password.env | cut -d= -f2)" \
    --no-auth-warning SAVE
  sudo gsutil cp /var/lib/redis-data/dump.rdb \
    gs://$(sudo ls /etc/redis/ 2>/dev/null; echo)wms-chatbot-redis-snapshots-*/pre-migration-$(date -u +%Y-%m-%d-%H%M%S).rdb'
```

### 3. On the VM: format + copy data off boot disk

```bash
gcloud compute ssh wms-chatbot-redis --zone=us-west1-a --tunnel-through-iap \
  --project=wms-chatbot-staging
```

Then inside:

```bash
# Verify the disk is attached
lsblk
# expect to see something like: sdb  10G  disk  (unmounted, no partition)

# Format the new disk
sudo mkfs.ext4 -F -L redis-data /dev/disk/by-id/google-redis-data

# Mount TEMPORARILY somewhere else (not /var/lib/redis-data yet)
sudo mkdir -p /mnt/newdisk
sudo mount /dev/disk/by-id/google-redis-data /mnt/newdisk

# Stop Redis so the copy is consistent
sudo systemctl stop wms-redis-container

# Copy current data from boot disk to new disk. Use `cp -a` — the Debian
# GCE image doesn't ship rsync by default, and `cp -a` preserves ownership
# and permissions just as well for a one-shot copy.
sudo cp -a /var/lib/redis-data/. /mnt/newdisk/
ls -la /mnt/newdisk/    # confirm dump.rdb (and appendonly.aof if present) copied

# Unmount the temporary mount
sudo umount /mnt/newdisk
sudo rmdir /mnt/newdisk

# Exit SSH
exit
```

### 4. Reset the VM — startup script mounts the disk properly

```bash
gcloud compute instances reset wms-chatbot-redis \
  --zone=us-west1-a --project=wms-chatbot-staging
```

On boot, the startup script:
- Detects the (now-formatted) data disk
- Sees no fstab entry -> adds one
- Mounts `/dev/disk/by-id/google-redis-data` at `/var/lib/redis-data`
- Starts the Redis container, which loads `dump.rdb` from the (now mounted) disk

### 5. Verify

```bash
gcloud compute ssh wms-chatbot-redis --zone=us-west1-a --tunnel-through-iap \
  --project=wms-chatbot-staging --quiet --command='
  # Data disk mounted?
  mount | grep redis-data
  # Right number of keys?
  sudo docker exec wms-redis redis-cli \
    -a "$(sudo cat /etc/redis/password.env | cut -d= -f2)" \
    --no-auth-warning DBSIZE'
```

Expect: mount line showing the persistent disk mounted at
`/var/lib/redis-data`, and DBSIZE = the same count you had before.

### 6. Recovery from a future VM destroy

Once persistent disk is in place, an accidental VM destroy is no longer
a disaster:

```bash
# Whatever caused the VM to go away (terraform apply with a
# force-replace field, gcloud compute instances delete, etc.)
# Just recreate the instance:
terraform -chdir=envs/staging apply \
  -replace=module.self_hosted_redis.google_compute_instance.redis \
  -var-file=terraform.tfvars

# New VM boots, startup script detects the disk is already formatted +
# has data, adds fstab, mounts, Redis loads its data. No manual
# recovery, no data loss.
```

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
