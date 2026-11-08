"""Read the results in a Hy-Tek merge results file (.hy3): one entry per E1 line, with its swimmer (D1), team (C1)
and result (E2).

Columns (0-based): E1 the swimmer's ID in 2-8 and the event in 38-42; E2 the time in 3-11 ("1214,01"), the course in
11, the status in 12 ("Q" DQ, "R" no-show) with the DQ code in Hy-Tek's form in 13-15 ("4G"), the heat in 20-23 and the
lane in 23-26; D1 the surname in 8-28, the first name in 28-48 and the preferred name in 48-68; C1 the team code in
2-7. A swimmer's "first" is their preferred name when the file has one (a nickname in place of the legal first name), else their
first name ("legalFirst" keeps the first name).
"""
import re

# Hy-Tek numbers the strokes; a FINA code's group gives the number, its last letter the rest. Misc (GA false start,
# GK did not finish) is 7, as in Meet Manager's own reserved 7P/7Q; no Meet Manager export with one has been seen.
STROKE_NO = {"free": "1", "back": "2", "breast": "3", "fly": "4", "IM": "5", "Relay": "6", "Misc": "7"}


def lines(path):
    with open(path, encoding="latin-1", newline="") as f:
        return [ln for ln in f.read().split("\r\n") if ln]


def hundredths(field):
    m = re.fullmatch(r"\s*(\d+),(\d{2})\s*", field)
    return int(m[1]) * 100 + int(m[2]) if m else 0


def entries(path):
    """Every entry: {id, event, surname, first, team, heat, lane, time, status, code}. An entry with no heat, or no time
    and no status, has no result."""
    out, c1, d1 = [], "", ""
    for ln in lines(path):
        tag = ln[:2]
        if tag == "C1":
            c1 = ln
        elif tag == "D1":
            d1 = ln
        elif tag == "E1":
            out.append({"id": ln[2:8].strip(), "event": int(ln[38:42]), "surname": d1[8:28].strip(),
                        "first": d1[48:68].strip() or d1[28:48].strip(), "legalFirst": d1[28:48].strip(), "team": c1[2:7].strip(), "heat": 0, "lane": 0, "time": 0,
                        "status": "", "code": ""})
        elif tag == "E2" and out:
            e = out[-1]
            heat, lane = ln[20:23].strip(), ln[23:26].strip()
            e.update(heat=int(heat) if heat.isdigit() else 0, lane=int(lane) if lane.isdigit() else 0,
                     time=hundredths(ln[3:11]), status=ln[12].strip(), code=ln[13:15].strip())
    return out


def has_result(e):
    return bool(e["heat"]) and bool(e["time"] or e["status"])


def fina(code, codes):
    """A Hy-Tek DQ code ("4G") in the FINA style ("BfG"); the Hy-Tek form when no code in the list matches."""
    for c, (_, group) in codes.items():
        if STROKE_NO.get(group) and STROKE_NO[group] + c[-1] == code:
            return c
    return code


def by_swim(path):
    """Entries with a result by (event, heat, lane)."""
    return {(e["event"], e["heat"], e["lane"]): e for e in entries(path) if has_result(e)}
