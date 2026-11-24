"""Read `git ls-tree --name-only` lines on stdin, print sorted graph IDs (names only; no file is opened)."""
import sys
ids = sorted(line.strip().rsplit('/', 1)[-1][:-len('.graph')] for line in sys.stdin if line.strip().endswith('.graph'))
assert len(ids) == len(set(ids))
print('\n'.join(ids))
