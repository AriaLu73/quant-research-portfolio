#!/usr/bin/env python3
"""research5: what every public-data recorder needs to survive an unreliable network and its own restarts.

Lessons of 2026-10-02 (all on one evening):
  * a connection can go silent without closing (the process is alive, nothing arrives) -> every recorder needs a stall rule;
  * a watchdog that restarts a recorder which is still alive creates two writers on the same gzip file -> the file is
    unreadable from the first interleaved block on -> one instance per output folder (lock file);
  * appending to a gzip file whose previous writer was killed (no end marker) hides everything written afterwards from
    normal readers -> a (re)started recorder never appends: it takes <HH>b_, <HH>c_, ... when <HH>_ already exists.
"""
import gzip, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts", "research2"))
import kc_l3_recorder as R   # Sink: hour-rotated gzip files per kind (not modified)

SUFFIXES = [""] + [chr(c) for c in range(ord("b"), ord("z") + 1)]


def fresh_gz(folder, hh, name, ext=".jsonl.gz"):
    """Open, for text writing, the first of <hh>_<name>, <hh>b_<name>, <hh>c_<name>, ... that does not exist yet
    (exclusive create: two processes can never get the same file). name may be empty (files called <hh>.csv.gz)."""
    os.makedirs(folder, exist_ok=True)
    for s in SUFFIXES:
        path = os.path.join(folder, f"{hh}{s}_{name}{ext}" if name else f"{hh}{s}{ext}")
        try:
            return gzip.open(path, "xt", compresslevel=5), path
        except FileExistsError:
            continue
    raise RuntimeError(f"no free file name for hour {hh} {name} in {folder}")


class SafeSink(R.Sink):
    """R.Sink that never appends to an existing file (see the module docstring)."""

    def write(self, kind, line, ns=None):
        ns = ns or time.time_ns()
        stamp = time.strftime("%Y%m%d%H", time.gmtime(ns // 1_000_000_000))
        f = self.files.get(kind)
        if f is None or f[0] != stamp:
            if f is not None:
                f[1].close()
            fh, _ = fresh_gz(os.path.join(self.out, stamp[:8]), stamp[8:], kind)
            f = (stamp, fh)
            self.files[kind] = f
        f[1].write(f"{ns}\t{line}\n")
        self.n[kind] = self.n.get(kind, 0) + 1
        if time.time() - self.flushed > 30:                      # bound what a crash can lose to ~30 s
            for g in self.files.values():
                g[1].flush()
            self.flushed = time.time()


def heal_gz(path):
    """Rewrite a gzip file whose writer was killed (no end marker) as a clean one holding every complete line that can still
    be read, so that appending to it afterwards gives a valid file. Returns the number of lines kept. Only call this when no
    process is writing the file (the caller holds the folder lock)."""
    import zlib
    lines = []
    try:
        with gzip.open(path, "rt", errors="replace") as fh:
            for line in fh:
                if line.endswith("\n"):
                    lines.append(line)
    except (EOFError, OSError, zlib.error):
        pass
    tmp = path + ".heal"
    with gzip.open(tmp, "wt", compresslevel=5) as out:
        out.writelines(lines)
    os.replace(tmp, path)
    return len(lines)


def heal_hour(out, now=None):
    """Heal every file of the current UTC hour under out/<day>/ (the only files a restarted R.Sink would append to)."""
    t = time.gmtime(now or time.time())
    day, hh = os.path.join(out, time.strftime("%Y%m%d", t)), time.strftime("%H", t)
    n = 0
    if os.path.isdir(day):
        for name in os.listdir(day):
            if name.startswith(hh + "_") and name.endswith(".jsonl.gz"):
                heal_gz(os.path.join(day, name))
                n += 1
    return n


def single_instance(folder):
    """Take the lock of an output folder or exit quietly: a second recorder on the same folder must not start.
    Returns the open lock file (keep a reference for the life of the process)."""
    import msvcrt
    os.makedirs(folder, exist_ok=True)
    fh = open(os.path.join(folder, "recorder.lock"), "a+")
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print(time.strftime("%F %T"), "another recorder holds", folder, "- not starting", flush=True)
        sys.exit(0)
    return fh


def stalled(last_message_time, now, limit_s):
    """True when nothing has arrived for limit_s seconds (limit_s <= 0 switches the rule off)."""
    return limit_s > 0 and now - last_message_time > limit_s


async def stall_guard(sink, limit_s, stop_at, poll_s=5.0):
    """For recorders whose stream code cannot be changed: leave the process when the total number of written lines has not
    moved for limit_s seconds, so that the watchdog starts a fresh one (connections that went silent do not recover)."""
    import asyncio
    seen, since = -1, time.time()
    while time.time() < stop_at:
        await asyncio.sleep(poll_s)
        total = sum(sink.n.values())
        if total != seen:
            seen, since = total, time.time()
        elif stalled(since, time.time(), limit_s):
            print(time.strftime("%F %T"), f"no data for {limit_s:.0f} s - exiting for a restart", flush=True)
            sink.close()
            os._exit(3)
