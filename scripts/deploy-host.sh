#!/usr/bin/env bash
# Host must be provisioned explicitly; see docs/deployment.md.
set -euo pipefail
image=${1:?image digest required}
sha=${2:?commit required}
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
[[ "$image" =~ ^ghcr.io/[a-z0-9/._-]+@sha256:[a-f0-9]{64}$ ]] || exit 2
root=/opt/quantum-route-core
release="$root/releases/$sha"
test -f "$root/.env"
ln -sfn "$root/.env" "$release/.env"
previous_image=''
if [ -f "$root/current-image" ]; then previous_image=$(cat "$root/current-image"); fi
export QROUTE_IMAGE="$image"
docker pull "$image"
if [ -L "$root/current" ] && [ -n "$previous_image" ]; then
  # Pause admission using the existing release/image before draining.
  QROUTE_IMAGE="$previous_image" QROUTE_ADMISSION_ENABLED=false docker compose -f "$root/current/deploy/compose.yaml" up -d --no-deps api
  if ! docker compose -f "$root/current/deploy/compose.yaml" exec -T api python scripts/drain.py; then
    QROUTE_IMAGE="$previous_image" QROUTE_ADMISSION_ENABLED=true docker compose -f "$root/current/deploy/compose.yaml" up -d --no-deps api
    echo 'Drain failed; existing release resumed, no migrations performed.' >&2
    exit 1
  fi
  docker compose -f "$root/current/deploy/compose.yaml" stop api worker
fi
cd "$release"
mkdir -p "$root/backups"
# SQLite backup API copies a consistent snapshot, including WAL contents.
docker compose -f deploy/compose.yaml run --rm --no-deps -T migrate python scripts/backup.py
docker compose -f deploy/compose.yaml run --rm --no-deps -T migrate alembic upgrade head
export QROUTE_ADMISSION_ENABLED=true
if ! docker compose -f deploy/compose.yaml up -d --wait api worker; then
  echo 'Startup failed. Previous image not restored automatically: verify schema compatibility.' >&2
  exit 1
fi
if ! docker compose -f deploy/compose.yaml exec -T api python scripts/smoke.py || ! docker compose -f deploy/compose.yaml exec -T api python scripts/smoke.py --road; then
  QROUTE_ADMISSION_ENABLED=false docker compose -f deploy/compose.yaml up -d --no-deps api
  echo 'Release verification failed. Admission paused; inspect before manual recovery.' >&2
  exit 1
fi
printf '%s\n' "$previous_image" > "$root/previous-image"
printf '%s\n' "$image" > "$root/current-image"
ln -sfn "$release" "$root/current"
