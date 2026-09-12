#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEST="$ROOT/external-data/m13/DeathStarBench"
COMMIT=6ecb09706140f8730b5385c08f1386c654c3c526

if test ! -d "$DEST/.git"; then
  mkdir -p "$(dirname "$DEST")"
  git clone --filter=blob:none --no-checkout https://github.com/delimitrou/DeathStarBench.git "$DEST"
fi

git -C "$DEST" sparse-checkout init --cone
git -C "$DEST" sparse-checkout set socialNetwork
git -C "$DEST" fetch origin "$COMMIT"
git -C "$DEST" checkout --detach "$COMMIT"
test "$(git -C "$DEST" rev-parse HEAD)" = "$COMMIT"
docker compose -f "$ROOT/deploy/m13/compose.yml" config --quiet
echo "M13 Social Network source pinned at $COMMIT"
