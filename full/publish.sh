#!/usr/bin/env bash
# Commit one directory into the full-results branch clone ("results/") and push, retrying on races.
# Usage: publish.sh <source dir> <destination path inside branch> <commit message>
# The identity is set in the clone's config (not only for the first commit) because a lost push race
# is resolved by `git pull --rebase`, which re-creates the commit and needs a committer identity.
set -euo pipefail
SRC="$1"; DEST="$2"; MSG="$3"
cd results
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
mkdir -p "$DEST"
cp -r "$SRC"/. "$DEST"/
git add --sparse -- "$DEST"
git commit -q -m "$MSG"
for i in $(seq 1 80); do
  if git push -q origin HEAD:full-results; then echo "pushed $DEST (try $i)"; exit 0; fi
  sleep $((RANDOM % 25 + 5))
  if ! git pull -q --rebase origin full-results; then
    echo "rebase failed on try $i; aborting rebase and retrying" >&2
    git rebase --abort || true
  fi
done
echo "push failed after retries" >&2; exit 1
