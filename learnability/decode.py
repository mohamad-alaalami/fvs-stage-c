"""StageC1 snapshot decoding: the pinned stagec/snapshot.py decoder plus defensive checks.

The binary format is defined by the pinned decoder (loaded from a file whose SHA-256 is
recorded), not re-implemented with guessed offsets. This module adds structural checks
that the pinned decoder does not perform.
"""
import hashlib
import importlib.util
import pathlib

VARIANTS = ('8', '5', 'LP')
PER_VERTEX_FIELDS = ('neighbours', 'neighDouble', 'doubleNum', 'posAtNeigh', 'status', 'stageNames')


class SnapshotError(ValueError):
    pass


def load_pinned_decoder(path):
    """Import decode() from a pinned stagec/snapshot.py; returns (decode, sha256)."""
    path = pathlib.Path(path)
    data = path.read_bytes()
    spec = importlib.util.spec_from_file_location('pinned_stagec_snapshot', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decode, hashlib.sha256(data).hexdigest()


def decode_checked(decode, blob, expected_variant=None):
    """Decode with the pinned decoder, then apply defensive structural checks.

    Raises SnapshotError on any violation. Never mutates or repairs the decoded state."""
    try:
        s = decode(blob)
    except Exception as e:  # pinned decoder uses assertions / struct errors
        raise SnapshotError(f'pinned decoder rejected snapshot: {e!r}') from e
    n = s['N']
    if s['magic'] != 'STAGEC1':
        raise SnapshotError('bad magic')
    if s['variant'] not in VARIANTS:
        raise SnapshotError(f'unknown variant {s["variant"]!r}')
    if expected_variant is not None and s['variant'] != expected_variant:
        raise SnapshotError(f'variant {s["variant"]} != expected {expected_variant}')
    if n < 0:
        raise SnapshotError('negative N')
    for f in PER_VERTEX_FIELDS:
        if len(s[f]) != n:
            raise SnapshotError(f'{f} has length {len(s[f])}, expected N={n}')
    for v in range(n):
        if not (len(s['neighbours'][v]) == len(s['neighDouble'][v]) == len(s['posAtNeigh'][v])):
            raise SnapshotError(f'adjacency arrays of vertex {v} have unequal lengths')
    if any(x not in (-2, -1, 0, 1) for x in s['status']):
        raise SnapshotError('status outside {-2,-1,0,1}')
    if not 0 <= s['pivot'] < n:
        raise SnapshotError('pivot out of range')
    for name in ('X', 'sol', 'branching_hints'):
        if any(not 0 <= x < n for x in s[name]):
            raise SnapshotError(f'{name} entry out of range')
    if s['variant'] == 'LP' and s['phase'] == 2 and not 0 <= s['root'] < n:
        raise SnapshotError('LP root out of range')
    return s
