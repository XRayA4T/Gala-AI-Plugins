#!/usr/bin/env python3
"""Final audit: compare the merge results file we wrote (merge_results.py) with the merge results Meet Manager
exported once the results were final, and list every manual change.

Usage: final_audit.py OURS.hy3 FINAL.hy3 OUT.html [--quick-fixes QUICK_FIXES.json] [--codes DQ_CODES.txt]
                      [--results RESULTS.pdf]

Only the events in OURS.hy3 are compared. Each entry is matched by swimmer ID and event. A change is one of: time
changed, DQ added, DQ removed, DQ code changed, no-show added, no-show removed, moved (another heat or lane), result
added (no result in ours, one in the final file, including a swimmer with no entry in ours) and result removed.
Places, backup and pad times are not compared. QUICK_FIXES.json (from audit_report.py --quick-fixes) marks the
changes made to a swim on the Quick Fix list, and lists the Quick Fix swims left as they were.
--results RESULTS.pdf (Meet Manager's printed Results for the session) adds a Results exceptions section: every swim
of the compared events where our merge results, the final export and the printed results don't all agree (time, N/S,
DQ, no result), matched by event and name (needs pdftotext).
The page has the swimmers' names: keep it where the user asks.
"""
import json
import pathlib
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audit_report as ar  # noqa: E402
import hy3  # noqa: E402

KINDS = ["Time changed", "DQ added", "DQ removed", "DQ code changed", "No-show added", "No-show removed", "Moved",
         "Result added", "Result removed"]


def shown(e, codes):
    if not e or not hy3.has_result(e):
        return "no result"
    if e["status"] == "R":
        return "N/S"
    if e["status"] == "Q":
        return f'DQ {hy3.fina(e["code"], codes) or "(no code)"}, {ar.fmt(e["time"])}'
    return ar.fmt(e["time"])


def changes(ours, final):
    """[(kind, ours entry or None, final entry or None)] for the events in ours."""
    events = {e["event"] for e in ours}
    mine = {(e["id"], e["event"]): e for e in ours}
    theirs = {(e["id"], e["event"]): e for e in final if e["event"] in events}
    out = []
    for key in sorted(set(mine) | set(theirs), key=lambda k: (k[1], k[0])):
        a, b = mine.get(key), theirs.get(key)
        ra, rb = bool(a and hy3.has_result(a)), bool(b and hy3.has_result(b))
        if not ra and not rb:
            continue
        if ra != rb:
            out.append(("Result added" if rb else "Result removed", a, b))
            continue
        if (a["heat"], a["lane"]) != (b["heat"], b["lane"]):
            out.append(("Moved", a, b))
        if (a["status"] == "R") != (b["status"] == "R"):
            out.append(("No-show added" if b["status"] == "R" else "No-show removed", a, b))
            continue
        if a["status"] != "Q" and b["status"] == "Q":
            out.append(("DQ added", a, b))
        elif a["status"] == "Q" and b["status"] != "Q":
            out.append(("DQ removed", a, b))
        elif a["status"] == b["status"] == "Q" and a["code"] != b["code"]:
            out.append(("DQ code changed", a, b))
        if a["status"] != "R" and a["time"] != b["time"]:
            out.append(("Time changed", a, b))
    return out


RES_EVENT = re.compile(r"^\s*\(?Event (\d+) ")
RES_ROW = re.compile(r"^\s*(\*?\d+|---)\s+(\S.*?)\s+(\d{1,2})\s+(\S.*?)\s{2,}(NT|NS|\d[\d:,]*)\s+(.*?)\s*$")
RES_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}),(\d{2})$")


def res_time(t):
    m = RES_TIME.match(t or "")
    return (int(m[1] or 0) * 60 + int(m[2])) * 100 + int(m[3]) if m else 0


def printed_results(path):
    """Meet Manager's printed Results: [{event, surname, first, status ("", "NS", "DQ", "SCR"), time}]."""
    txt = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    out, event = [], None
    for ln in txt.splitlines():
        m = RES_EVENT.match(ln)
        if m:
            event = int(m[1])
            continue
        m = RES_ROW.match(ln)
        if not m or event is None:
            continue
        name, rest = m[2], m[6].split()
        surname, _, first = name.partition(",")
        first = re.sub(r"\s+S[BM]?\d{1,2}$", "", first.strip())
        status, time = "", 0
        if rest and rest[0] in ("NS", "SCR", "DFS"):
            status = "NS" if rest[0] != "SCR" else "SCR"
        elif rest and rest[0] == "DQ":
            status, time = "DQ", res_time(rest[1]) if len(rest) > 1 else 0
        elif rest:
            time = res_time(rest[0])
        out.append({"event": event, "surname": surname.strip(), "first": first, "status": status, "time": time})
    return out


def norm_name(s):
    return re.sub(r"[^a-z]", "", s.lower())


def exceptions(ours, final, printed, codes):
    """Rows where our merge results, the final export and the printed results don't all agree, for our events."""
    events = {e["event"] for e in ours}

    def state(e):
        if not e or not hy3.has_result(e):
            return ("none", 0)
        if e["status"] == "R":
            return ("NS", 0)
        return ("DQ" if e["status"] == "Q" else "", e["time"])

    def pstate(r):
        if not r:
            return ("none", 0)
        return ("none", 0) if r["status"] == "SCR" else (r["status"], r["time"] if r["status"] != "NS" else 0)

    def show(st):
        kind, t = st
        return {"none": "no result", "NS": "N/S"}.get(kind) or (("DQ " if kind == "DQ" else "") + ar.fmt(t))

    mine = {(e["id"], e["event"]): e for e in ours}
    theirs = {(e["id"], e["event"]): e for e in final if e["event"] in events}
    pr = [r for r in printed if r["event"] in events]
    used, rows = set(), []
    for key in sorted(set(mine) | set(theirs), key=lambda k: (k[1], k[0])):
        a, b = mine.get(key), theirs.get(key)
        who = b or a
        cands = [i for i, r in enumerate(pr) if i not in used and r["event"] == key[1]
                 and norm_name(r["surname"]) == norm_name(who["surname"])
                 and norm_name(r["first"].split()[0] if r["first"] else "") in
                 (norm_name(who["first"].split()[0] if who["first"] else ""),
                  norm_name(who.get("legalFirst", "").split()[0] if who.get("legalFirst") else ""))]
        if len(cands) > 1:   # the same name twice: the one with the final time
            cands = [i for i in cands if pstate(pr[i]) == state(b)] or cands[:1]
        r = pr[cands[0]] if cands else None
        if cands:
            used.add(cands[0])
        sa, sb, sp = state(a), state(b), pstate(r)
        if sa == sb == sp:
            continue
        what = []
        if sa != sb:
            what.append("final export differs from ours")
        if sb != sp:
            what.append("printed results differ from the final export" if r or sb[0] != "none" else "")
        if not r and sb[0] != "none":
            what = [w for w in what if w] + ["not in the printed results"]
        rows.append((key[1], (b or a)["heat"], (b or a)["lane"], who, show(sa), show(sb), show(sp),
                     "; ".join(w for w in what if w)))
    for i, r in enumerate(pr):
        if i not in used and r["status"] != "SCR":
            rows.append((r["event"], 0, 0, {"surname": r["surname"], "first": r["first"], "team": ""}, "no result",
                         "no result", show(pstate(r)), "in the printed results only (no entry matched)"))
    return sorted(rows, key=lambda x: (x[0], x[1], x[2]))


def build(ours_path, final_path, changed, fixes, codes, results=None):
    ours = hy3.entries(ours_path)
    meet = hy3.lines(final_path)[1][2:47].strip()
    fix_keys = {(f["event"], f["heat"], f["lane"]): f for f in fixes or []}

    def where(a, b):
        e = b if b and hy3.has_result(b) else a
        return e["event"], e["heat"], e["lane"]

    def on_list(a, b):
        return any(e and (e["event"], e["heat"], e["lane"]) in fix_keys for e in (a, b))

    counts = Counter(k for k, _, _ in changed)
    touched = {(e["event"], e["heat"], e["lane"]) for _, a, b in changed for e in (a, b) if e}
    left = [f for k, f in sorted(fix_keys.items()) if k not in touched]
    events = sorted({e["event"] for e in ours})
    rows = []
    for kind, a, b in sorted(changed, key=lambda c: (where(c[1], c[2]), KINDS.index(c[0]))):
        e, h, ln = where(a, b)
        who = b or a
        diff = (ar.fmt(b["time"] - a["time"], True) if kind == "Time changed" and a["time"] and b["time"] else "")
        rows.append(f'<tr><td>{e}</td><td>{h or ""}</td><td>{ln or ""}</td>'
                    f'<td>{ar.esc(who["surname"] + ", " + who["first"])}</td><td>{ar.esc(who["team"])}</td>'
                    f'<td>{kind}</td><td class="t">{ar.esc(shown(a, codes))}</td><td class="t">{ar.esc(shown(b, codes))}</td>'
                    f'<td class="t">{diff}</td>'
                    f'<td>{"yes" if on_list(a, b) else ""}</td></tr>')
    summary = "".join(f"<tr><td>{k}</td><td>{counts[k]}</td></tr>" for k in KINDS) + (
        f'<tr><td><b>All changes</b></td><td><b>{len(changed)}</b></td></tr>'
        + (f'<tr><td>Changes to swims on the Quick Fix list</td><td>{sum(on_list(a, b) for _, a, b in changed)}</td></tr>'
           f'<tr><td>Changes to swims not on it</td><td>{sum(not on_list(a, b) for _, a, b in changed)}</td></tr>'
           f'<tr><td>Quick Fix swims left as they were</td><td>{len(left)}</td></tr>' if fixes is not None else ""))
    span = f"events {events[0]}&ndash;{events[-1]}" if len(events) > 1 else f"event {events[0]}"
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Final Audit</title>'
           f'<style>{ar.CSS}</style></head><body>',
           f'<h1>Final audit: {ar.esc(meet)} ({span})</h1>',
           f'<p class="muted">Generated {datetime.now():%Y-%m-%d %H:%M}. Our merge results file '
           f'({ar.esc(pathlib.Path(ours_path).name)}) against the final results Meet Manager exported '
           f'({ar.esc(pathlib.Path(final_path).name)}), entry by entry (swimmer and event). Places, backup and pad '
           f'times are not compared.</p>',
           '<h2>Summary of the manual changes</h2><table><tr><th>Change</th><th>Count</th></tr>' + summary + '</table>',
           '<h2>Manual changes</h2>' + ('<div class="wrap"><table><tr><th>Event</th><th>Heat</th><th>Lane</th>'
                                        '<th>Swimmer</th><th>Team</th><th>Change</th><th>Ours</th><th>Final</th>'
                                        '<th>Final − ours</th><th>Quick Fix</th></tr>' + "".join(rows)
                                        + '</table></div>' if rows else '<p class="muted">None: the final results '
                                        'are the same as ours.</p>')]
    if results:
        ex = exceptions(ours, hy3.entries(final_path), printed_results(results), codes)
        rrows = "".join(f'<tr><td>{e}</td><td>{h or ""}</td><td>{ln or ""}</td>'
                        f'<td>{ar.esc(w["surname"] + ", " + w["first"])}</td><td>{ar.esc(w["team"])}</td>'
                        f'<td class="t">{ar.esc(x)}</td><td class="t">{ar.esc(y)}</td><td class="t">{ar.esc(z)}</td>'
                        f'<td>{ar.esc(why)}</td></tr>' for e, h, ln, w, x, y, z, why in ex)
        out.append(f'<h2>Results exceptions</h2><p class="muted">Every swim where our merge results, the final export '
                   f'and the printed results ({ar.esc(pathlib.Path(results).name)}) don\'t all agree: time, N/S, DQ or '
                   f'no result. Matched by event and name.</p>'
                   + ('<div class="wrap"><table><tr><th>Event</th><th>Heat</th><th>Lane</th><th>Swimmer</th><th>Team</th>'
                      '<th>Ours</th><th>Final export</th><th>Printed results</th><th>What differs</th></tr>' + rrows
                      + '</table></div>' if ex else '<p class="muted">None: all three agree.</p>'))
    if fixes is not None:
        out.append('<h2>Quick Fix swims left as they were</h2>'
                   + (ar.quick_fix_table(left, done=True).replace("<th>Done</th>", "<th></th>")
                      .replace('<td class="box">&#9744;</td>', "<td></td>") if left else '<p class="muted">None.</p>'))
    out.append("</body></html>")
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        sys.exit(__doc__)
    opt = lambda k: args[args.index(k) + 1] if k in args else None  # noqa: E731
    codes = ar.load_codes(opt("--codes") or ar.DQ_CODES)
    fixes = json.loads(pathlib.Path(opt("--quick-fixes")).read_text(encoding="utf-8")) if opt("--quick-fixes") else None
    changed = changes(hy3.entries(args[0]), hy3.entries(args[1]))
    results = opt("--results")
    pathlib.Path(args[2]).write_text(build(args[0], args[1], changed, fixes, codes, results), encoding="utf-8")
    counts = Counter(k for k, _, _ in changed)
    ex = (f", {len(exceptions(hy3.entries(args[0]), hy3.entries(args[1]), printed_results(results), codes))} "
          f"results exceptions") if results else ""
    print(f"Wrote {args[2]}: {len(changed)} changes" + "".join(f", {counts[k]} {k.lower()}" for k in KINDS if counts[k]) + ex)


if __name__ == "__main__":
    main()
