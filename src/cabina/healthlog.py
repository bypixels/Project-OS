"""History of `cabina check` results, for the Health tab's trend view. Writes ONLY
<state_dir>/health.jsonl — one line per check run, appended, never rewritten in place except
by the periodic prune (tmp + os.replace, same pattern as docs.py's atomic write).

Called from exactly two places (never from check.run() itself, so `cabina mcp`, the guard hook
and `check --repo` stay pure): cli.py's `check` branch and server.py's api_health. A write here
must never break either caller — append() catches everything and returns False on failure.
"""
import json, os, time
from datetime import datetime, timedelta


def path(cfg):
    return os.path.join(cfg["state_dir"], "health.jsonl")


def _now():
    return datetime.now().astimezone()


def _counts(findings):
    c = {"crit": 0, "warn": 0, "info": 0}
    for f in findings or ():
        sev = f.get("sev")
        if sev in c:
            c[sev] += 1
    return c


def _last_line(p):
    """Last well-formed line of the log, or None (missing file / empty / unreadable)."""
    try:
        with open(p, encoding="utf-8") as f:
            last = None
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    last = json.loads(raw)
                except Exception:
                    continue
            return last
    except Exception:
        return None


def _should_append(last, counts, now):
    """True unless `last` has the same (crit, warn, info) as `counts` AND is less than 24h old
    — in which case appending would be a pure duplicate of an unchanged state. Any failure to
    parse/compare `last["when"]` (missing, malformed, or a naive datetime that can't be diffed
    against `now`'s tz-aware clock) means "append" rather than get permanently stuck refusing to
    write over a line it can no longer make sense of."""
    if last is None:
        return True
    if (last.get("crit"), last.get("warn"), last.get("info")) != (counts["crit"], counts["warn"], counts["info"]):
        return True
    try:
        when = datetime.fromisoformat(last["when"])
        return (now - when) >= timedelta(hours=24)
    except Exception:
        return True


def _prune(p, days):
    """Drop lines older than `days`, rewritten via tmp + os.replace — only called when at
    least one line actually qualifies, so the common append path stays a pure append."""
    cutoff = _now() - timedelta(days=days)
    kept = []
    dropped = False
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                    when = datetime.fromisoformat(d["when"])
                except Exception:
                    kept.append(raw)  # malformed: never silently drop
                    continue
                if when < cutoff:
                    dropped = True
                else:
                    kept.append(raw)
    except Exception:
        return
    if not dropped:
        return
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for raw in kept:
            f.write(raw + "\n")
    os.replace(tmp, p)


def append(cfg, findings, now=None):
    """Append one line {when, crit, warn, info} to health.jsonl if it differs from (or is 24h+
    newer than) the last stored line, then prune to cfg['check']['history_days']. Returns True
    if a line was written, False otherwise (including on any internal failure — this must never
    break a caller)."""
    try:
        now = now or _now()
        p = path(cfg)
        counts = _counts(findings)
        last = _last_line(p)
        if not _should_append(last, counts, now):
            return False
        os.makedirs(os.path.dirname(p), exist_ok=True)
        line = json.dumps({"when": now.isoformat(timespec="seconds"), **counts}, ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        _prune(p, (cfg.get("check") or {}).get("history_days", 180))
        return True
    except Exception:
        return False


def read(cfg, days=None):
    """Parsed lines from health.jsonl, oldest first. Malformed lines are skipped silently; a
    missing file returns []. `days` optionally filters to lines newer than that many days ago."""
    p = path(cfg)
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except Exception:
                    continue
    except Exception:
        return []
    if days is not None:
        cutoff = _now() - timedelta(days=days)
        def _keep(d):
            try:
                return datetime.fromisoformat(d["when"]) >= cutoff
            except Exception:
                return False
        out = [d for d in out if _keep(d)]
    return out
