#!/usr/bin/env python3
"""Final audit: compare the merge results file we wrote (merge_results.py) with the merge results Meet Manager
exported once the results were final, and list every manual change.

Usage: final_audit.py OURS.hy3 FINAL.hy3 OUT.html [--quick-fixes QUICK_FIXES.json] [--codes DQ_CODES.txt]

Only the events in OURS.hy3 are compared. Each entry is matched by swimmer ID and event. A change is one of: time
changed, DQ added, DQ removed, DQ code changed, no-show added, no-show removed, moved (another heat or lane), result
added (no result in ours, one in the final file, including a swimmer with no entry in ours) and result removed.
Places, backup and pad times are not compared. QUICK_FIXES.json (from audit_report.py --quick-fixes) marks the
changes made to a swim on the Quick Fix list, and lists the Quick Fix swims left as they were.
The page has the swimmers' names: keep it where the user asks.
"""
import json
import pathlib
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


def build(ours_path, final_path, changed, fixes, codes):
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
    pathlib.Path(args[2]).write_text(build(args[0], args[1], changed, fixes, codes), encoding="utf-8")
    counts = Counter(k for k, _, _ in changed)
    print(f"Wrote {args[2]}: {len(changed)} changes" + "".join(f", {counts[k]} {k.lower()}" for k in KINDS if counts[k]))


if __name__ == "__main__":
    main()
