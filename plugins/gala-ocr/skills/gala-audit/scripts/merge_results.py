#!/usr/bin/env python3
"""Write a Hy-Tek Meet Manager merge results file (.hy3) with the audited results: the final times, splits, backup
times, DQs and no-shows worked out by audit_report.py.

Usage: merge_results.py OCR_DIR GEN7 ENTRIES.hy3 RESULTS.hy3 OUT.hy3 [--events 1-12] [--tolerance 0.30]
                        [--codes DQ_CODES.txt] [--age-groups 10U,11,12,13,14,15,16,17O]

GEN7 is the session report PDF or a folder of one session's race-by-race PDFs. For a gala run session by session,
give that session's entries export, merge results export and Gen7 folder; --events limits the file to those events
(by default every event in ENTRIES.hy3).

ENTRIES.hy3 is Meet Manager's meet entries export (the Hfile in "Meet Entries-<meet>.zip"): every swimmer (D1), team
(C1) and entry (E1), with the heat and lane each was seeded in (E2). An export made before seeding (no E2 lines) works
too: each entry is then seeded from the lane sheet it is printed on (same event, matched by name). RESULTS.hy3 is a merge results file Meet Manager
exported for the same meet: its header (A1, B1, B2) is copied, with today's date and time in A1, and its result lines
show the layout written here. Every entry gets its C1, D1 and E1 line copied from ENTRIES.hy3 (the E1 with its event marked done, "A" in column
32, where MM writes 1 for seeded and S for scored), then:
- E2: the final time; the pad (TP) time; up to three backup times: the lane sheet (SW) times when the final time comes
  from them or TP was kept in doubt (two SW times in backups 2 and 3, one in backup 3, with PB in backup 1 when there
  is one), otherwise the Gen7 buttons (as Meet Manager writes them for a pad time), or,
  with no PB time, the SW median (thousandths dropped) as backup 1, or, when TP agrees with the SW median but not
  PB, PB as backup 1 and the SW median as backup 2; the heat, lane, place in the heat and place in the swimmer's age group; "A" when the final
  time is not the pad time. A DQ (a slip in OCR_DIR, coded in dq-codes.json) is "Q" with the code in Hy-Tek's form
  (stroke number and letter: BaG -> 2G); a lane sheet no-show is "R"; an entry not seeded in a heat has no result.
- G1: the Gen7 splits before the finish.
Ages are the D1 age; groups default to the CGA's (10 and under, 11 to 16 each, 17 and over).
Lines are 128 characters plus Hy-Tek's two-digit checksum, CRLF ended. Prints what it could not place: a lane sheet
swimmer who doesn't match the seeded entry, a swim with no time anywhere, a lane sheet swimmer with no entry.
"""
import pathlib
import re
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audit_report as ar  # noqa: E402

# Hy-Tek numbers the strokes; a FINA code's group gives the number, its last letter the rest. Misc (GA false start,
# GK did not finish) is 7, as in Meet Manager's own reserved 7P/7Q; no Meet Manager export with one has been seen.
STROKE_NO = {"free": "1", "back": "2", "breast": "3", "fly": "4", "IM": "5", "Relay": "6", "Misc": "7"}


def read(path):
    with open(path, encoding="latin-1", newline="") as f:
        return [ln for ln in f.read().split("\r\n") if ln]


def checksum(line):
    total = sum(ord(c) for c in line[0::2]) + 2 * sum(ord(c) for c in line[1::2])
    v = str(total // 21 + 205)
    return v[-1] + v[-2]


def out_line(line):
    line = line[:128].ljust(128)
    return line + checksum(line)


def put(line, start, text):
    return line[:start] + text + line[start + len(text):]


def tm(h, width=8):
    return f"{h // 100},{h % 100:02d}".rjust(width) if h else "0,00".rjust(width)


def hy_code(code, codes):
    group = codes.get(code, ("", ""))[1]
    return STROKE_NO.get(group, "") + code[-1] if code and group in STROKE_NO else ""


def age_groups(spec):
    out = []
    for g in spec.split(","):
        m = re.fullmatch(r"(\d+)([UO]?)", g.strip())
        n = int(m[1])
        out.append((0, n) if m[2] == "U" else (n, 200) if m[2] == "O" else (n, n))
    return out


def surname(name):
    return re.sub(r"[^a-z]", "", name.split(",")[0].lower())


def first(d1):
    return re.sub(r"[^a-z]", "", d1[28:48].lower())


def first_of(name):
    return re.sub(r"[^a-z]", "", (name.split(",", 1) + [""])[1].split()[0].lower()) if "," in name else ""


def ranks(swims, key):
    """Place each swim with a time among those with the same key; ties share a place."""
    groups = {}
    for s in swims:
        if s["time"] and not s["status"]:
            groups.setdefault(key(s), []).append(s)
    for g in groups.values():
        for s in g:
            yield s, 1 + sum(1 for o in g if o["time"] < s["time"])


def main():
    args = sys.argv[1:]
    if len(args) < 5:
        sys.exit(__doc__)
    opt = lambda k, d: args[args.index(k) + 1] if k in args else d  # noqa: E731
    ocr, gen7, entries, template, out = args[:5]
    tol = round(float(opt("--tolerance", "0.30")) * 100)
    codes = ar.load_codes(opt("--codes", ar.DQ_CODES))
    groups = age_groups(opt("--age-groups", "10U,11,12,13,14,15,16,17O"))
    sheets, slips, etd = ar.load(ocr)
    given = pathlib.Path(ocr) / "dq-codes.json"
    assigned = ar.json.loads(given.read_text(encoding="utf-8")) if given.exists() else {}
    events = ar.parse_events(opt("--events", None))
    audit = ar.Audit(sheets, slips, etd, ar.gen7_report.races(gen7), tol, codes, assigned, events)

    tpl = read(template)
    base = next(ln for ln in tpl if ln.startswith("E2") and ln[12] == " " and ln[11] == "L")
    # An entry with no result: no time, no status and heat 0 (a done event's export has the course on it too).
    unseeded = next((ln for ln in tpl if ln.startswith("E2") and ln[3:11].strip() == "0,00" and ln[12] == " "
                     and not ln[20:23].strip("0 ")), None)
    meet_date = base[87:95]

    # The entries file: C1 (team), D1 (swimmer), E1 (entry) and the E2 with the seeded heat and lane.
    swims, c1, d1 = [], None, None
    ent = read(entries)
    for i, ln in enumerate(ent):
        if ln.startswith("C1"):
            c1 = ln
        elif ln.startswith("D1"):
            d1 = ln
        elif ln.startswith("E1"):
            seed = ent[i + 1] if i + 1 < len(ent) and ent[i + 1].startswith("E2") else ""
            heat = int(seed[20:23] or 0) if seed[20:23].strip() else 0
            lane = int(seed[23:26] or 0) if seed[23:26].strip() else 0
            swims.append({"c1": c1, "d1": d1, "e1": ln, "event": int(ln[38:42]), "heat": heat, "lane": lane,
                          "age": int(d1[96:99]), "time": 0, "status": "", "problems": []})

    if events:
        swims = [s for s in swims if s["event"] in events]

    problems, used = [], set()
    # An entries export made before the session was seeded (no E2 lines, so no heats or lanes): seed each entry
    # from the lane sheets, which are printed with the heat and lane of every swimmer. A sheet row is matched to an
    # entry in the same event by surname and first name, else by surname alone when only one entry has it.
    no_seed = [s for s in swims if not s["heat"]]
    if no_seed:
        taken = {(s["event"], s["heat"], s["lane"]) for s in swims if s["heat"]}
        placed, unmatched = 0, []
        for (e, ln), sheet in sorted(sheets.items()):
            if events and e not in events:
                continue
            for h, row in enumerate(sheet["rows"], start=1):
                name = row["swimmerName"]
                if not name or (e, h, ln) in taken:
                    continue
                pool = [s for s in no_seed if s["event"] == e and not s["heat"]
                        and surname(s["d1"][8:28]) == surname(name)]
                cand = [s for s in pool if first(s["d1"]) == first_of(name)] or (pool if len(pool) == 1 else [])
                if len(cand) == 1:
                    cand[0]["heat"], cand[0]["lane"] = h, ln
                    taken.add((e, h, ln))
                    placed += 1
                elif row["status"] in ("SWAM", "DISQUALIFIED") or row["handTimes"]:
                    unmatched.append(f"E{e} H{h} L{ln} {name}")
        print(f"The entries file has no seeding for {len(no_seed)} entries: {placed} seeded from the lane sheets")
        for u in unmatched:
            problems.append(f"{u}: no entry matches the lane sheet's swimmer, so it couldn't be seeded")
    # A lane sheet swimmer other than the one seeded there: if they have an entry in the event, the swim is theirs.
    for s in swims:
        if not s["heat"]:
            continue
        sheet = sheets.get((s["event"], s["lane"]))
        row = sheet["rows"][s["heat"] - 1] if sheet and s["heat"] <= len(sheet["rows"]) else None
        if not row or not row["swimmerName"] or surname(row["swimmerName"]) == surname(s["d1"][8:28]):
            continue
        swap = [o for o in swims if o["event"] == s["event"] and surname(o["d1"][8:28]) == surname(row["swimmerName"])
                and first(o["d1"]) == first_of(row["swimmerName"])]
        if len(swap) == 1:
            o = swap[0]
            o["heat"], o["lane"], s["heat"], s["lane"] = s["heat"], s["lane"], 0, 0
            problems.append(f"E{o['event']} H{o['heat']} L{o['lane']}: the lane sheet has a different swimmer from "
                            f"the one seeded; the swim is given to the lane sheet's swimmer (also entered in the "
                            f"event), and the seeded swimmer has no result")
    for s in swims:
        if not s["heat"]:
            continue
        key = (s["event"], s["heat"], s["lane"])
        used.add(key)
        res = audit.lane_result(*key)
        row = res["row"]
        who = f"E{s['event']} H{s['heat']} L{s['lane']}"
        if row and row["swimmerName"] and surname(row["swimmerName"]) != surname(s["d1"][8:28]):
            problems.append(f"{who}: the lane sheet swimmer doesn't match the seeded entry; entry kept, check it")
        s["res"] = res
        dq = [sl for sl in slips if (sl["eventNumber"], sl["heat"], sl["lane"]) == key]
        if res["ns"] or (row and row["status"] == "NO_SHOW" and res["final"] is None):
            s["status"] = "R"
        elif res["final"] is None:
            s["status"] = "R"
            problems.append(f"{who}: no time anywhere and not marked N/S on the lane sheet; written as a no-show")
        else:
            s["time"] = res["final"]
            if dq:
                code = next((assigned.get(sl["_file"], {}).get("code") for sl in dq
                             if assigned.get(sl["_file"], {}).get("code")), "")
                s["status"], s["dq"] = "Q", hy_code(code, codes)
                if not s["dq"]:
                    problems.append(f"{who}: DQ with no code that maps to Hy-Tek ({code or 'none'})")

    # Lane sheet swimmers with no seeded entry.
    for (e, ln), sheet in sorted(sheets.items()):
        if events and e not in events:
            continue
        for h, row in enumerate(sheet["rows"], start=1):
            if row["status"] in ("SWAM", "DISQUALIFIED") and row["handTimes"] and (e, h, ln) not in used:
                problems.append(f"E{e} H{h} L{ln}: swam on the lane sheet but has no seeded entry; not in the file")

    def group(s):
        return next((i for i, (lo, hi) in enumerate(groups) if lo <= s["age"] <= hi), -1)

    for s, p in ranks(swims, lambda s: (s["event"], group(s))):
        s["place"] = p
    for s, p in ranks(swims, lambda s: (s["event"], s["heat"])):
        s["heatPlace"] = p

    lines = [out_line(stamp(tpl[0]))] + [out_line(ln) for ln in tpl[1:3]]
    for s in sorted(swims, key=lambda s: s["event"]):
        # E1 column 32 is the event's status in Meet Manager: 1 seeded, S scored, A done. Every event is done.
        lines += [out_line(s["c1"]), out_line(s["d1"]), out_line(put(s["e1"], 31, "A"))]
        # In a done event Meet Manager writes the course on every result, and a 0 in column 100.
        if not s["heat"]:
            e2 = unseeded
            if not e2:
                e2 = put(put(put(base, 3, tm(0)), 12, "   "), 20, f"{0:3d}{0:3d}{0:3d}{0:4d}")
                for k in range(3):
                    e2 = put(e2, 36 + 8 * k, tm(0))
                e2 = put(put(e2, 63, tm(0, 10)), 95, " ")
            lines.append(out_line(put(put(put(e2, 87, meet_date), 11, "L"), 99, "0")))
            continue
        res = s["res"]
        e2 = put(base, 3, tm(s["time"]))
        e2 = put(e2, 11, "L")
        e2 = put(e2, 12, (s["status"] + s.get("dq", "")).ljust(3))
        e2 = put(e2, 20, f"{s['heat']:3d}{s['lane']:3d}{s.get('heatPlace', 0):3d}{s.get('place', 0):4d}")
        # The SW times go in only when the final time comes from them, or TP was kept in doubt; otherwise the Gen7
        # buttons, as Meet Manager writes them for a pad time.
        from_tp = res["tp"] is not None and res["final"] == res["tp"] and not res["swOverride"]
        use_sw = res["sw"] and (not from_tp or res["swDoubt"])
        backups = button_times(res)
        if use_sw:
            # The SW times fill the last backups (two SW times in backups 2 and 3, one in backup 3), so it is plain
            # which backups are watches; PB, when there is one, goes in backup 1.
            sw = [v for _, v, _ in res["sw"]][:3]
            backups = [int(res["pb"] or 0)] * (len(sw) < 3) + [0] * (len(sw) == 1) + sw
        # TP with no PB time to back it: the SW median goes in as backup 1.
        if res["swBackup"]:
            backups = [int(res["median"])]
        # TP backed by the SW median but not PB: PB as backup 1, the SW median as backup 2.
        elif res["swBackup2"]:
            backups = [res["pb"], int(res["median"])]
        for k in range(3):
            e2 = put(e2, 36 + 8 * k, tm(backups[k] if k < len(backups) else 0))
        # A pad time less than half the final time is a stray touch, which Meet Manager drops.
        tp = res["tp"] if res["tp"] and s["time"] and res["tp"] * 2 >= s["time"] else 0
        e2 = put(e2, 63, tm(tp, 10))
        e2 = put(e2, 87, meet_date)
        e2 = put(e2, 99, "0")
        e2 = put(e2, 95, "A" if s["time"] and s["time"] != res["tp"] and s["status"] != "R" else " ")
        if s["status"] == "R":
            for k in range(3):
                e2 = put(e2, 36 + 8 * k, tm(0))
            e2 = put(e2, 63, tm(0, 10))
        lines.append(out_line(e2))
        lines += [out_line(g) for g in split_lines(res, s["event"], audit, s["status"] == "R")]

    pathlib.Path(out).write_bytes(("\r\n".join(lines) + "\r\n").encode("latin-1"))
    counts = {k: sum(1 for s in swims if (s["status"] if s["heat"] else "-") == k) for k in ("", "Q", "R", "-")}
    print(f"Wrote {out}: {len(swims)} entries, {counts['']} with a time, {counts['Q']} DQ, {counts['R']} no-show, "
          f"{counts['-']} not seeded")
    for p in problems:
        print(p)


def stamp(a1):
    """The template's A1 line with now as the file's date and time."""
    m = re.search(r"\d{8} +\d{1,2}:\d{2} [AP]M", a1)  # Meet Manager pads a one-digit hour: "11062026  5:25 PM"
    now = datetime.now()
    text = f"{now:%m%d%Y} {now.strftime('%I:%M %p').lstrip('0').rjust(len(m[0]) - 9)}"
    return a1[:m.start()] + text.ljust(len(m[0])) + a1[m.end():]


def button_times(res):
    gl = res["race"] and next((ln for ln in res["race"]["lanes"] if ln["lane"] == res["lane"]), None)
    return [ar.hundredths(gl[k]) for k in ("buttonA", "buttonB", "buttonC") if gl and ar.hundredths(gl[k])]


def split_lines(res, event, audit, no_show):
    """Every split before the finish, as Meet Manager writes them: 0,00 where there is none."""
    race = res["race"]
    gl = race and not no_show and next((ln for ln in race["lanes"] if ln["lane"] == res["lane"]), None)
    dist = ar.distance(race["eventDescription"] if race else audit.events.get(event, "")) or 0
    last = max([max(dist // 100, 1)] + [sp["row"] for ln in (race["lanes"] if race else []) for sp in ln["splits"]])
    times = {sp["row"]: ar.hundredths(sp["time"]) for sp in (gl["splits"] if gl else [])}
    cells = [f"F{row:2d}{tm(times.get(row) or 0)}" for row in range(1, last)]
    return ["G1" + "".join(cells[i:i + 10]) for i in range(0, len(cells), 10)]


if __name__ == "__main__":
    main()
