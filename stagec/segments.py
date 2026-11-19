"""Segment streams written by StageC.cpp: lossless compression and ordered reading.

A run directory holds three streams: snapshots/, events/, continuations/.
Each contains seg-NNNNNN.<ext> (raw, possibly still open) or seg-NNNNNN.<ext>.zz
(zlib, verified). Concatenating segments in index order gives the logical stream
that the local edition wrote to a single file. manifest.jsonl in each stream
directory records raw size/SHA-256 and stored size for every compressed segment.
A raw segment is deleted only after its compressed copy has been decompressed
and matched by length and SHA-256.
"""
import hashlib, json, os, pathlib, re, threading, zlib
from concurrent.futures import ThreadPoolExecutor

STREAMS = {'snapshots': '.bin', 'events': '.jsonl', 'continuations': '.jsonl'}
PAT = re.compile(r'^seg-(\d{6})\.(bin|jsonl)(\.zz)?$')
CHUNK = 1 << 20


def segments(stream_dir):
    """Sorted list of (index, path, compressed) for one stream."""
    out = {}
    d = pathlib.Path(stream_dir)
    if not d.exists():
        return []
    for p in d.iterdir():
        m = PAT.match(p.name)
        if not m:
            continue
        i = int(m.group(1))
        if i in out and out[i][1]:
            continue  # both exist only transiently; prefer the verified .zz
        out[i] = (p, bool(m.group(3)))
    return [(i, out[i][0], out[i][1]) for i in sorted(out)]


def compress_one(path, level=6):
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + '.zz.tmp')
    final = path.with_name(path.name + '.zz')
    h = hashlib.sha256(); raw = 0
    c = zlib.compressobj(level)
    with path.open('rb') as f, tmp.open('wb') as o:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk); raw += len(chunk); o.write(c.compress(chunk))
        o.write(c.flush())
    h2 = hashlib.sha256(); n = 0; d = zlib.decompressobj()
    with tmp.open('rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            out = d.decompress(chunk); h2.update(out); n += len(out)
        out = d.flush(); h2.update(out); n += len(out)
    if not (d.eof and n == raw and h.hexdigest() == h2.hexdigest()):
        tmp.unlink()
        raise RuntimeError(f'compression round-trip failed for {path}')
    entry = dict(segment=path.name, raw_bytes=raw, raw_sha256=h.hexdigest(),
                 stored=final.name, stored_bytes=tmp.stat().st_size, codec=f'zlib-{level}')
    with _MANIFEST_LOCK, (path.parent / 'manifest.jsonl').open('a') as m:
        m.write(json.dumps(entry) + '\n'); m.flush(); os.fsync(m.fileno())
    os.replace(tmp, final)
    path.unlink()
    return entry


WORKERS = max(1, min(3, (os.cpu_count() or 2) - 1))  # leave one core for the solver
_POOL = ThreadPoolExecutor(WORKERS)  # zlib releases the GIL
_MANIFEST_LOCK = threading.Lock()


def compress_closed(run_dir, final=False):
    """Compress every closed raw segment (all of them when final=True), in parallel."""
    todo = []
    for stream in STREAMS:
        segs = segments(pathlib.Path(run_dir) / stream)
        if not segs:
            continue
        top = segs[-1][0]
        for i, p, compressed in segs:
            if compressed or (i == top and not final):
                continue
            if p.stat().st_size == 0 and i == top:
                continue  # keep an empty trailing segment raw; nothing to compress
            todo.append(p)
    return list(_POOL.map(compress_one, todo))


class Compressor(threading.Thread):
    """Background sidecar used while the solver runs."""
    def __init__(self, run_dir, interval=2.0):
        super().__init__(daemon=True)
        self.run_dir = run_dir; self.interval = interval
        self.stop_event = threading.Event(); self.error = None; self.count = 0

    def run(self):
        try:
            while not self.stop_event.wait(self.interval):
                self.count += len(compress_closed(self.run_dir))
        except Exception as e:  # surfaced by the runner; never silently ignored
            self.error = repr(e)

    def finish(self):
        self.stop_event.set(); self.join()
        if self.error:
            raise RuntimeError('compressor failed: ' + self.error)
        self.count += len(compress_closed(self.run_dir, final=True))
        return self.count


def iter_chunks(stream_dir):
    for _, p, compressed in segments(stream_dir):
        with p.open('rb') as f:
            if not compressed:
                yield from iter(lambda: f.read(CHUNK), b'')
                continue
            d = zlib.decompressobj()
            for chunk in iter(lambda: f.read(CHUNK), b''):
                out = d.decompress(chunk)
                if out:
                    yield out
            out = d.flush()
            if out:
                yield out
            if not d.eof:
                raise RuntimeError(f'truncated compressed segment {p}')


def iter_lines(stream_dir):
    """Yield (line_without_newline, complete_flag). A trailing unterminated line
    (only possible after a hard kill) is yielded once with complete_flag=False."""
    rest = b''
    for chunk in iter_chunks(stream_dir):
        rest += chunk
        *lines, rest = rest.split(b'\n')
        for line in lines:
            yield line, True
    if rest:
        yield rest, False


class ByteReader:
    def __init__(self, stream_dir):
        self.it = iter_chunks(stream_dir); self.buf = b''; self.pos = 0; self.offset = 0

    def read(self, n):
        parts = []
        while n:
            if self.pos == len(self.buf):
                self.buf = next(self.it, b''); self.pos = 0
                if not self.buf:
                    raise RuntimeError('snapshot stream ended early')
            k = min(n, len(self.buf) - self.pos)
            parts.append(self.buf[self.pos:self.pos + k]); self.pos += k; n -= k; self.offset += k
        return b''.join(parts)

    def remaining(self):
        total = len(self.buf) - self.pos
        for chunk in self.it:
            total += len(chunk)
        return total


def sizes(run_dir):
    """Logical (raw) and stored bytes per stream."""
    result = {}
    for stream in STREAMS:
        d = pathlib.Path(run_dir) / stream
        raw = stored = 0; manifest = {}
        if (d / 'manifest.jsonl').exists():
            for line in (d / 'manifest.jsonl').open():
                e = json.loads(line); manifest[e['stored']] = e
        for _, p, compressed in segments(d):
            try:
                s = p.stat().st_size
            except FileNotFoundError:
                continue  # raw segment removed by the sidecar between listing and stat
            stored += s
            raw += manifest[p.name]['raw_bytes'] if compressed else s
        result[stream] = dict(raw_bytes=raw, stored_bytes=stored, segments=len(segments(d)))
    return result
