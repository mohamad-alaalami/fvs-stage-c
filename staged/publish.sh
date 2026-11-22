#!/usr/bin/env bash
# Publish a new run/attempt directory, never replace any previous attempt.
set -euo pipefail
SRC="$1"; DEST="$2"; MSG="$3"
cd results
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
test ! -e "$DEST" || { echo "Refusing to overwrite $DEST" >&2; exit 1; }
mkdir -p "$DEST"
cp -r "$SRC"/. "$DEST"/
git add --sparse -- "$DEST"
git commit -q -m "$MSG"
for i in $(seq 1 80); do
 if git push -q origin HEAD:stage-d-results; then exit 0; fi
 sleep $((RANDOM % 25 + 5))
 git pull -q --rebase origin stage-d-results || { git rebase --abort || true; }
done
exit 1
