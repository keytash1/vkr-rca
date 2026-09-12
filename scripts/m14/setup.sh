#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_dir="$root/external-data/m14/opentelemetry-demo"
expected=8c47d47c9ac27710d2b2a153bcd53e483bffe66d

if [[ ! -d "$source_dir/.git" ]]; then
  mkdir -p "$(dirname "$source_dir")"
  git clone --filter=blob:none --no-checkout https://github.com/open-telemetry/opentelemetry-demo.git "$source_dir"
fi

git -C "$source_dir" checkout --detach "$expected"
actual=$(git -C "$source_dir" rev-parse HEAD)
[[ "$actual" == "$expected" ]] || { echo "unexpected Astronomy Shop commit: $actual" >&2; exit 1; }
git -C "$source_dir" diff --quiet
git -C "$source_dir" diff --cached --quiet
echo "Astronomy Shop source locked at $actual"
