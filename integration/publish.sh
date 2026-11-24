#!/usr/bin/env bash
# Publish SRC into a NEW directory DEST of branch BRANCH in ./results (a sparse clone); never replace an attempt, never force.
# Usage: bash integration/publish.sh SRC DEST "message" [BRANCH]
set -euo pipefail
SRC="$1"; DEST="$2"; MSG="$3"; BRANCH="${4:-integration-results}"
cd results
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
test ! -e "$DEST" || { echo "Refusing to overwrite $DEST" >&2; exit 1; }
mkdir -p "$DEST"
cp -r "$SRC"/. "$DEST"/
git add --sparse -- "$DEST"
git commit -q -m "$MSG"
for i in $(seq 1 80); do
  if git push -q origin "HEAD:$BRANCH"; then exit 0; fi
  sleep $((RANDOM % 25 + 5))
  git pull -q --rebase origin "$BRANCH" || { git rebase --abort || true; }
done
exit 1
