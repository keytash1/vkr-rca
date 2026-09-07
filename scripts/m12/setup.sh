#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEST="$ROOT/external-data/m12/DeathStarBench"
COMMIT=6ecb09706140f8730b5385c08f1386c654c3c526

if [ ! -d "$DEST/.git" ]; then
  mkdir -p "$(dirname "$DEST")"
  git clone --filter=blob:none --no-checkout https://github.com/delimitrou/DeathStarBench.git "$DEST"
  git -C "$DEST" sparse-checkout init --cone
  git -C "$DEST" sparse-checkout set hotelReservation wrk2 LICENSE README.md
fi
git -C "$DEST" fetch origin "$COMMIT"
git -C "$DEST" checkout --detach "$COMMIT"
test "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT"
docker compose -f "$ROOT/deploy/m12/compose.yml" config --quiet
echo "M12 source pinned at $COMMIT"
