#!/usr/bin/env bash
# Commit one directory into the full-results branch clone ("results/") and push, retrying on races.
# Usage: publish.sh <source dir> <destination path inside branch> <commit message>
set -euo pipefail
SRC="$1"; DEST="$2"; MSG="$3"
cd results
mkdir -p "$DEST"
cp -r "$SRC"/. "$DEST"/
git add --sparse -- "$DEST"
git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -q -m "$MSG"
for i in $(seq 1 60); do
  if git push -q origin HEAD:full-results; then echo "pushed $DEST (try $i)"; exit 0; fi
  sleep $((RANDOM % 25 + 5))
  git pull -q --rebase origin full-results || { git rebase --abort || true; exit 1; }
done
echo "push failed after retries" >&2; exit 1
