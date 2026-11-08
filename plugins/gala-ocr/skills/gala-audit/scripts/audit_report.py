#!/usr/bin/env python3
"""Build a gala audit report (one HTML page) from the gala-ocr transcriptions and the Gen7 session report.

Usage: audit_report.py OCR_DIR GEN7 OUT.html [--events 3,5-7] [--fixes FIXES.json] [--tolerance 0.30] [--codes DQ_CODES.txt]
                       [--scans DIR] [--scan-dpi 90] [--scan-quality 40] [--merge OUR_MERGE.hy3]
                       [--quick-fixes QUICK_FIXES.html]

GEN7 is the Gen7 session report PDF, or a folder of Gen7's race-by-race PDFs for one session (race numbers are
matched within the folder, so give one session's races).
--events limits the report to those events (e.g. during a gala, the events swum so far, or one event); the other
lane sheets and slips in OCR_DIR are left out. ETD pages for other events are still read, for combined races.

OCR_DIR holds the gala-ocr files: lane sheets (<scan>-eventEE-laneL-pPPP.json), DQ slips
(<scan>-eventEE-heatH-laneL-pPPP.json) and ETD programme pages (<scan>-pPPP.json). The ETD race numbers link each
programme heat to its Gen7 race; without them, a heat is matched to the Gen7 race with its event and heat.

For every event, heat and lane the report lists the touch pad (TP) time, the push button (PB) time, every lane sheet
(SW) time, the final time and audit notes. The final time:
- with a TP time: TP when it is within the tolerance of the SW median (a PB time outside it is noted as bad);
  otherwise the SW median overrides it: the TP time is noted as bad, or, when TP agrees with PB, as TP and PB both
  outside the SW median; TP alone when there are no SW times. In doubt (fewer than two SW times within the tolerance of
  their median, and PB not within it either), TP stands and is noted "In doubt";
- with no TP time: the SW median (a PB time outside the tolerance of it is noted as bad, and poor SW times are noted
  when adding PB moves the median by more than the tolerance); PB alone when there are no SW times.
A no-show on the lane sheet with no SW times is recorded as N/S with no time, even when Gen7 has one.
Touchpads: by lane, the split and finish touches Gen7 recorded on the pads against those expected (a race of 200 m or
more expects one split touch per 100 m before the finish, a shorter race none; every swim with a final time expects
a finish touch).
Ignored races, listed under the summary and not flagged anywhere else: a false start (a Gen7 race with nothing recorded
in any lane whose race number is not in the ETD programme) and a race not started (an ETD race number with no Gen7
race and no lane sheet times).
Quick Fix: only the swims whose result rests on something the OCR could not settle (unreadable watches; watches
read with low confidence or overwritten when the final time comes from them; poor watch times, swims in doubt, lane
sheet and Gen7 disagreeing on whether a lane swam, swimmers written in; DQ slips with no code or a code given with a
doubt), so they can be fixed quickly in Meet Manager once the merge results are imported. With --merge (our merge
results file) it also lists lane sheet swims missing from it or given to another swimmer, and DQs in it with no code,
and shows what the file has for each swim. --quick-fixes writes the list on its own (HTML to print, no swimmers'
names) and as JSON next to it, for final_audit.py.
A median of an even count is the mean of the middle two, with thousandths dropped for the final time.
DQ codes: OCR_DIR/dq-codes.json, when present, gives each slip its code ({"<slip file>": {"code": "BrK", "note": ""}}).
Codes are checked against the DQ code list (default: the FINA list in ../data/dqcodesFINA.txt, lines of
"code","description","group" with group Misc, free, back, breast, fly, IM or Relay): the code must exist and its
group must be one that can happen in the event. Codes written in a lane sheet's notes are checked the same way.
It also checks DQ slips against the lane sheets and Gen7, lane sheet DQ marks against the slips, and repeats the
lane sheet findings (unsigned sheets, unreadable or corrected times). Needs the gen7-report skill next to this one.
Every section starts collapsed. Each swim links to its lane sheet and DQ slips in the report. The report is self-
contained: each lane sheet and DQ slip row carries its scanned page as an embedded grayscale JPEG (collapsed under
the row), drawn with poppler's pdftoppm from <scan>.pdf in --scans DIR (default: OCR_DIR's parent, then OCR_DIR) at
--scan-dpi and --scan-quality. A scan that can't be found is skipped with a warning; its rows show the page only.
"""
import csv
import html
import json
import pathlib
import re
import base64
import subprocess
import tempfile
import statistics
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "gen7-report" / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gen7_report  # noqa: E402
import hy3  # noqa: E402

LANE_NAME = re.compile(r"^(?P<scan>.+)-event(?P<event>\d{2,})-lane(?P<lane>\d+)-p(?P<page>\d{3,})\.json$")
SLIP_NAME = re.compile(r"^(?P<scan>.+)-event(?P<event>\d{2,})-heat(?P<heat>\d+)-lane(?P<lane>\d+)-p(?P<page>\d{3,})\.json$")
ETD_NAME = re.compile(r"^(?P<scan>.+)-p(?P<page>\d{3,})\.json$")
DQ_CODES = pathlib.Path(__file__).resolve().parents[1] / "data" / "dqcodesFINA.txt"
STROKES = {"butterfly": "fly", "backstroke": "back", "breaststroke": "breast", "freestyle": "free"}
TIME = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2})\.(\d{2})$")


def hundredths(t):
    m = TIME.match((t or "").strip().lstrip("*"))
    return (int(m.group(1) or 0) * 60 + int(m.group(2))) * 100 + int(m.group(3)) if m else None


def fmt(h, signed=False):
    """Hundredths (possibly .5 for a median) as M:SS.hh, or ±S.hh for a difference."""
    if h is None:
        return ""
    if signed:
        s = f"{abs(h) / 100:.3f}".rstrip("0")
        s = s if len(s.split(".")[1]) >= 2 else f"{abs(h) / 100:.2f}"
        return ("+" if h >= 0 else "-") + s
    whole, half = divmod(round(h * 2), 2)
    m, rest = divmod(whole, 6000)
    sec = f"{rest // 100:02d}.{rest % 100:02d}" if m else f"{rest // 100}.{rest % 100:02d}"
    return (f"{m}:" if m else "") + sec + ("5" if half else "")


def median(values):
    return statistics.median(values) if values else None


def esc(s):
    return html.escape(str(s), quote=True)


def load(ocr_dir):
    sheets, slips, etd = {}, [], {}
    for f in sorted(pathlib.Path(ocr_dir).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if f.name == "dq-codes.json":
            continue
        if m := SLIP_NAME.match(f.name):
            data["_file"] = f.name
            data["_scan"], data["_page"] = m["scan"] + ".pdf", int(m["page"])
            slips.append(data)
        elif m := LANE_NAME.match(f.name):
            data["_scan"], data["_page"] = m["scan"] + ".pdf", int(m["page"])
            sheets[(data["eventNumber"], data["lane"])] = data
        elif ETD_NAME.match(f.name):
            for h in data["heats"]:
                etd[(h["eventNumber"], h["heat"])] = h
    return sheets, slips, etd


def parse_events(spec):
    """"3,5-7" -> {3, 5, 6, 7}; None or "" -> None (every event)."""
    if not spec:
        return None
    out = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        lo, _, hi = part.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out


def apply_hand_fixes(sheets, path):
    """Apply the lane sheet fixes made by hand (the gala audit portal's fixes.json) to the transcriptions, so the
    audit and the merge results use them: {"<event>-<heat>-<lane>": {"watches": {"<column>": {"accepted": true} or
    {"time": "1:05.32"}}, "swimmer": {"name": "Surname, First", "id": "..."}}}.
    A watch accepted as read gets high confidence; a watch captured by hand replaces the reading. A swimmer chosen
    for a written-in name becomes the row's swimmer (and the written-in note is settled). Returns how many applied."""
    if not path:
        return 0
    given = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    n = 0
    for k, f in given.items():
        m = re.fullmatch(r"(\d+)-(\d+)-(\d+)", k)
        if not m or not isinstance(f, dict):
            continue
        e, h, ln = (int(x) for x in m.groups())
        sheet = sheets.get((e, ln))
        if not sheet or h > len(sheet["rows"]):
            continue
        row = sheet["rows"][h - 1]
        for col, w in (f.get("watches") or {}).items():
            if not isinstance(w, dict) or not str(col).isdigit():
                continue
            t = next((x for x in row["handTimes"] if x["column"] == int(col)), None)
            if w.get("time"):
                if hundredths(w["time"]) is None:
                    continue
                if t is None:
                    t = {"column": int(col)}
                    row["handTimes"].append(t)
                    row["handTimes"].sort(key=lambda x: x["column"])
                t.update(written=w["time"], normalized=w["time"], corrected=False, confidence="HIGH")
                n += 1
            elif w.get("accepted") and t is not None and t.get("normalized"):
                t["confidence"] = "HIGH"
                n += 1
        sw = f.get("swimmer")
        if isinstance(sw, dict) and sw.get("name"):
            row["swimmerName"] = sw["name"]
            row["notes"] = ("swimmer confirmed by hand: %s; " % sw["name"]) + WRITTEN_IN.sub("", row["notes"] or "")
            if row["status"] == "NO_SWIMMER":
                row["status"] = "SWAM"
            n += 1
    return n


def load_codes(path):
    """{code: (description, group)} from a list of "code","description","group" lines."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r[0].strip(): (r[1].strip(), r[2].strip()) for r in csv.reader(f) if len(r) >= 3 and r[0].strip()}


def code_groups(description):
    """The code groups that can apply in an event: Misc, plus its stroke (all four in a medley), plus IM or Relay."""
    d = description.lower()
    groups = {"Misc"}
    if re.search(r"\bim\b|medley", d):
        groups |= set(STROKES.values()) | {"Relay" if "relay" in d else "IM"}
    else:
        groups |= {v for k, v in STROKES.items() if k in d} or {"free"}
        if "relay" in d:
            groups.add("Relay")
    return groups


def code_problems(code, desc, codes, infraction=""):
    """Findings for a DQ code given in an event."""
    if code not in codes:
        return [("serious", f"DQ code {code} is not in the code list")]
    text, group = codes[code]
    if group not in code_groups(desc):
        return [("serious", f"DQ code {code} ({group}: {text}) cannot apply in {desc}")]
    out = []
    if code == "IMC":
        out.append(("warn", "IMC says to use the stroke's own code"))
    leg = re.search(r"\b(butterfly|backstroke|breast\w*|freestyle)\s+leg\b", infraction.lower())
    if leg and group in STROKES.values():
        stroke = "breast" if leg.group(1).startswith("breast") else STROKES[leg.group(1)]
        if stroke != group:
            out.append(("warn", f"The infraction is on the {leg.group(1)} leg but code {code} is a {group} code"))
    return out


def distance(description):
    m = re.search(r"(\d+)\s*(?:LC|SC)?\s*Meter", description)
    return int(m.group(1)) if m else None


class Audit:
    def __init__(self, sheets, slips, etd, races, tol, codes=None, assigned=None, events=None):
        self.only = set(events) if events else None
        if self.only:
            sheets = {k: v for k, v in sheets.items() if k[0] in self.only}
            slips = [s for s in slips if s["eventNumber"] in self.only]
        self.sheets, self.slips, self.etd, self.tol = sheets, slips, etd, tol
        self.codes, self.assigned = codes or {}, assigned or {}
        self.races = {r["race"]: r for r in races}
        self.by_heat = defaultdict(list)
        for r in races:
            self.by_heat[(r["eventNumber"], r["heat"])].append(r)
        self.events = {}
        for (e, _), s in sorted(sheets.items()):
            self.events.setdefault(e, s["eventDescription"])
        self.slip_keys = defaultdict(list)
        for s in slips:
            self.slip_keys[(s["eventNumber"], s["heat"], s["lane"])].append(s)

    def race_for(self, event, heat):
        """The Gen7 race of a programme heat, and how it was found."""
        h = self.etd.get((event, heat))
        if h is not None:
            if h["raceNumber"] is None:
                return None, "ETD: no race number" + (f" ({h['notes']})" if h["notes"] else "")
            r = self.races.get(h["raceNumber"])
            return r, (f"race {h['raceNumber']}" if r else f"ETD race {h['raceNumber']} is not in the Gen7 report")
        finished = [r for r in self.by_heat.get((event, heat), []) if any(ln["offTime"] for ln in r["lanes"])]
        return (finished[-1], f"race {finished[-1]['race']} (by event and heat)") if finished else (None, "no Gen7 race")

    def lane_result(self, event, heat, lane):
        """Every number the review needs for one swim, the final time and the notes."""
        sheet = self.sheets.get((event, lane))
        row = sheet["rows"][heat - 1] if sheet and heat <= len(sheet["rows"]) else None
        race, race_note = self.race_for(event, heat)
        gl = next((ln for ln in race["lanes"] if ln["lane"] == lane), None) if race else None
        res = {"event": event, "heat": heat, "lane": lane, "row": row, "race": race, "raceNote": race_note,
               "notes": [], "serious": False, "warn": False}
        tol = self.tol

        def note(text, level="minor"):
            res["notes"].append((level, text))
            res["serious"] |= level == "serious"
            res["warn"] |= level == "warn"

        # Touch pad: the lane's split on the race's last row; push buttons: the backup time.
        tp = pb = official = None
        if gl:
            dist = distance(race["eventDescription"]) or 0
            last = max([max(dist // 100, 1)] + [s["row"] for ln in race["lanes"] for s in ln["splits"]])
            tp = next((hundredths(s["time"]) for s in gl["splits"] if s["row"] == last), None)
            buttons = [hundredths(gl[k]) for k in ("buttonA", "buttonB", "buttonC") if hundredths(gl[k]) is not None]
            pb = hundredths(gl["backup"]) if hundredths(gl["backup"]) is not None else median(buttons)
            official = hundredths(gl["offTime"])
            if gl["buttonOverride"]:
                note("Gen7 official time is a push button time (underlined)")
                # Gen7 may copy the override into the finish split; a finish split equal to it is no pad touch.
                if tp is not None and tp == official:
                    tp = None
            if gl.get("faultyTouch"):
                note("TP soft touch / faulty TP: Gen7 has a PB time but no official time", "warn")
        sw = []
        if row:
            for t in row["handTimes"]:
                v = hundredths(t["normalized"])
                if v is None:
                    note(f"SW timer {t['column']} \"{t['written']}\" could not be read", "warn")
                else:
                    sw.append((t["column"], v, t))
                    if t["confidence"] != "HIGH":
                        note(f"SW timer {t['column']} \"{t['written']}\" read as {fmt(v)} ({t['confidence'].lower()} "
                             f"confidence)")
                    if t["corrected"]:
                        note(f"SW timer {t['column']} was overwritten on the sheet")
        med = median([v for _, v, _ in sw])
        res.update(tp=tp, pb=pb, sw=sw, median=med, official=official)

        def poor_sw(ref, why):
            """Name the SW time that is out when the others agree with ref."""
            if len(sw) < 2:
                return note(f"Poor SW time: {why}", "warn")
            col, v, t = max(sw, key=lambda x: abs(x[1] - ref))
            others = [o for c, o, _ in sw if c != col]
            if abs(v - ref) > tol and all(abs(o - ref) <= tol for o in others):
                note(f"Poor SW time: timer {col} \"{t['written']}\" ({fmt(v)}) is {fmt(v - ref, True)}s from "
                     f"{fmt(ref)}; {why}", "warn")
            else:
                note(f"Poor SW time: {why}; no single timer can be picked out", "warn")

        # A no-show on the lane sheet with no SW times is recorded as N/S, whatever Gen7 has.
        res["ns"] = bool(row) and row["status"] == "NO_SHOW" and not row["handTimes"]
        before = len(res["notes"])
        final, res["swOverride"], res["swDoubt"] = None, False, False
        if tp is not None:
            if med is None:
                final = tp
                if pb is not None and abs(tp - pb) > tol:
                    note(f"TP {fmt(tp)} and PB {fmt(pb)} differ by {fmt(tp - pb, True)}s and there are no SW times "
                         f"to decide; TP used", "warn")
            elif abs(tp - med) <= tol:
                final = tp
                if pb is not None and abs(tp - pb) > tol:
                    note(f"Bad PB time: {fmt(pb)} is {fmt(pb - tp, True)}s from TP", "warn")
            elif sum(abs(v - med) <= tol for _, v, _ in sw) < 2 and not (pb is not None and abs(pb - med) <= tol):
                # In doubt (fewer than two SW times agree with their median, and PB does not back it): TP stands,
                # and the merge file carries the SW times for a referee to see.
                why = "there is only one SW time" if len(sw) < 2 else "no two SW times agree with their median"
                final, res["swDoubt"] = tp, True
                note(f"In doubt: TP {fmt(tp)} is {fmt(tp - med, True)}s from the SW median, but {why}"
                     + (" and PB does not agree with them" if pb is not None else "")
                     + "; TP kept, SW times copied to the merge file", "warn")
            elif pb is not None and abs(tp - pb) <= tol:
                final, res["swOverride"] = int(med), True
                note(f"TP and PB agree but are outside the SW median: TP {fmt(tp)} is {fmt(tp - med, True)}s and PB "
                     f"{fmt(pb)} {fmt(pb - med, True)}s from it; SW median used", "warn")
            else:
                final, res["swOverride"] = int(med), True
                note(f"Bad TP time: {fmt(tp)} is {fmt(tp - med, True)}s from the SW median"
                     + (f" and {fmt(tp - pb, True)}s from PB" if pb is not None else "")
                     + "; SW median used", "serious")
                if pb is not None and abs(pb - med) > tol:
                    note(f"Bad PB time: {fmt(pb)} is {fmt(pb - med, True)}s from the SW median", "warn")
        elif med is not None:
            final = int(med)
            if pb is not None:
                if abs(pb - med) > tol:
                    note(f"Bad PB time: {fmt(pb)} is {fmt(pb - med, True)}s from the SW median", "warn")
                with_pb = median([v for _, v, _ in sw] + [pb])
                if abs(with_pb - med) > tol:
                    poor_sw(pb, f"adding PB moves the median from {fmt(med)} to {fmt(with_pb)}")
            note("No TP time; SW median used")
        elif pb is not None:
            final = pb
            note("No TP or SW time; PB used", "warn")
        # TP kept with no PB to back it: the merge file carries the SW median as its backup.
        res["swBackup"] = (final is not None and final == tp and not res["swDoubt"] and pb is None
                           and med is not None)
        if res["swBackup"]:
            note(f"No PB time; SW median {fmt(int(med))} written as backup 1 in the merge file")
        # TP kept with the SW median but not PB: the merge file carries PB as backup 1 and the SW median as backup 2.
        res["swBackup2"] = (final is not None and final == tp and not res["swDoubt"] and pb is not None
                            and med is not None and abs(tp - med) <= tol and abs(tp - pb) > tol)
        if res["swBackup2"]:
            note(f"PB disagrees with TP; SW median {fmt(int(med))} written as backup 2 in the merge file")
        if res["ns"]:
            del res["notes"][before:]
            final = None
            res["swBackup"] = res["swBackup2"] = False
        res["final"] = final

        # A single SW time far from the final time is probably a misread or a slip of the pen.
        if final is not None and len(sw) >= 2:
            for col, v, t in sw:
                if abs(v - final) > 100 and not any(f"timer {col} " in n for _, n in res["notes"]):
                    note(f"SW timer {col} \"{t['written']}\" ({fmt(v)}) is {fmt(v - final, True)}s from the final "
                         f"time; check the sheet", "warn")

        status = row["status"] if row else "NO_SWIMMER"
        if not sheet and official is not None:
            note(f"Gen7 has a time ({fmt(official)}) and there is no lane sheet for event {event} lane {lane} in the "
                 f"scan; the PB/TP check stands alone", "warn")
        elif res["ns"] and official is not None:
            note(f"Gen7 has a time ({fmt(official)}) but the lane sheet has a no-show: recorded as N/S with no time",
                 "serious")
        elif status in ("NO_SHOW", "NO_SWIMMER") and official is not None:
            note(f"Gen7 has a time ({fmt(official)}) but the lane sheet has "
                 + ("a no-show" if status == "NO_SHOW" else "no swimmer"), "serious")
        if status == "SWAM" and row and row["swimmerName"] and official is None and final is None:
            note("Lane sheet has a swimmer but there is no time anywhere", "warn")
        if status == "SWAM" and race is None and sw:
            note(f"Lane sheet has times but there is no Gen7 race for this heat ({race_note})", "serious")
        elif status == "SWAM" and race is not None and official is None and sw:
            note(f"Gen7 has no time in this lane (race {race['race']}) but the lane sheet has times", "serious")
        if official is not None and final is not None and official != final:
            d = official - final
            note(f"Gen7 official {fmt(official)} differs from the final time by {fmt(d, True)}s",
                 "serious" if abs(d) > tol else "warn")
        res["diff"] = None if official is None or res["ns"] or final is None else official - final
        if row and row["notes"]:
            note(f"Lane sheet: {row['notes']}")
            if row["status"] == "DISQUALIFIED" or re.search(r"\bDQ\b", row["notes"]):
                for c in self.written_codes(row):
                    for lv, t in code_problems(c, self.events.get(event, ""), self.codes):
                        note(f"Lane sheet: {t}", lv)
        dq = self.slip_keys.get((event, heat, lane))
        res["dq"] = dq
        return res

    def combined_with(self, event, heat):
        """Programme heats swum in the same race as this one (they share an ETD race number)."""
        h = self.etd.get((event, heat))
        if not h or h["raceNumber"] is None:
            return []
        return [k for k, g in self.etd.items() if g["raceNumber"] == h["raceNumber"] and k != (event, heat)]

    def ignored_races(self):
        """Races left out of the audit: (race, event, heat, description, reason), by race number.

        A false start is a Gen7 race with nothing recorded in any lane (no pad or button time) whose race number is
        not written in the ETD programme (only checked when there is one). A race not started is an ETD race number
        with no Gen7 race and no lane sheet time in that heat."""
        written = {h["raceNumber"] for h in self.etd.values() if h["raceNumber"] is not None}
        out = []
        if written:
            for n, r in self.races.items():
                if n not in written and not any(
                        ln["offTime"] or ln["splits"] or ln["backup"] or ln["buttonA"] or ln["buttonB"] or ln["buttonC"]
                        for ln in r["lanes"]):
                    out.append((n, r["eventNumber"], r["heat"], r["eventDescription"], "false start"))
        for (e, h), g in self.etd.items():
            n = g["raceNumber"]
            if n is not None and n not in self.races and not any(
                    h <= len(s["rows"]) and s["rows"][h - 1]["handTimes"]
                    for (ev, _), s in self.sheets.items() if ev == e):
                out.append((n, e, h, self.events.get(e, ""), "race not started"))
        if self.only:
            out = [x for x in out if x[1] in self.only]
        return sorted(out)

    def swimmer_in(self, event, heat, lane):
        sheet = self.sheets.get((event, lane))
        row = sheet["rows"][heat - 1] if sheet and heat <= len(sheet["rows"]) else None
        return bool(row and row["status"] != "NO_SWIMMER")

    def results(self):
        out = defaultdict(list)
        for e in sorted(self.events):
            heats = max(len(s["rows"]) for (ev, _), s in self.sheets.items() if ev == e)
            lanes = sorted({ln for (ev, ln) in self.sheets if ev == e}
                           | {g["lane"] for h in range(1, heats + 1) for r in [self.race_for(e, h)[0]] if r
                              for g in r["lanes"]})
            for h in range(1, heats + 1):
                for ln in lanes:
                    # In a combined race, a lane belongs to the event whose sheet has a swimmer in it.
                    if not self.swimmer_in(e, h, ln) and any(self.swimmer_in(*k, ln) for k in self.combined_with(e, h)):
                        continue
                    res = self.lane_result(e, h, ln)
                    row = res["row"]
                    if (row and row["status"] != "NO_SWIMMER") or res["official"] is not None or res["sw"]:
                        out[e].append(res)
        return out

    def dq_findings(self, results):
        by_key = {(r["event"], r["heat"], r["lane"]): r for rs in results.values() for r in rs}
        rows = []
        for s in sorted(self.slips, key=lambda s: (s["eventNumber"], s["heat"], s["lane"], s["page"])):
            key = (s["eventNumber"], s["heat"], s["lane"])
            sheet = self.sheets.get((s["eventNumber"], s["lane"]))
            row = sheet["rows"][s["heat"] - 1] if sheet and s["heat"] <= len(sheet["rows"]) else None
            res = by_key.get(key)
            desc = self.events.get(s["eventNumber"], "")
            f = []
            if not row or row["status"] == "NO_SWIMMER":
                f.append(("serious", "No swimmer in this heat and lane on the lane sheet: wrong event, heat or lane?"))
            elif row["status"] == "NO_SHOW":
                f.append(("serious", "The lane sheet has this swimmer as a no-show"))
            if res is None or res["official"] is None:
                f.append(("serious", "Gen7 has no finish for this lane"))
            inf = s["infraction"].lower()
            if not re.search(r"medley|\bim\b", desc.lower()) and re.search(r"\bim\b|medley|\bleg\b", inf):
                f.append(("serious", f"The infraction speaks of an IM, but event {s['eventNumber']} is {desc}"))
            dist = distance(desc)
            for m in re.finditer(r"(\d+)\s*m\b", inf):
                if dist and int(m.group(1)) > dist:
                    f.append(("serious", f"The infraction mentions {m.group(1)}m in a {dist}m event"))
            same = self.slip_keys[key]
            if len(same) > 1:
                f.append(("minor", f"{len(same)} slips for this swim (pages "
                                   f"{', '.join(str(x['page']) for x in same)})"))
            if not s["announcementTime"] or not s["initialled"]:
                f.append(("minor", "No announcement time or initial"))
            if not s["officialSigned"] or not s["refereeSigned"]:
                f.append(("serious", "Not signed by the official and the referee"))
            code = self.assigned.get(s["_file"], {}).get("code", "")
            if not code:
                f.append(("warn", "No DQ code given"))
            elif self.codes:
                f += code_problems(code, desc, self.codes, s["infraction"] + " " + s["back"])
            if code and row:
                written = self.written_codes(row)
                if written and code not in written:
                    f.append(("warn", f"The lane sheet has {', '.join(written)}; the slip's code is {code}"))
            rows.append((s, row, f))
        # A DQ marked on a lane sheet needs a slip.
        missing = []
        for (e, ln), sheet in sorted(self.sheets.items()):
            for i, row in enumerate(sheet["rows"], start=1):
                marked = row["status"] == "DISQUALIFIED" or re.search(r"\bDQ\b", row["notes"])
                if marked and (e, i, ln) not in self.slip_keys:
                    missing.append((e, i, ln, row))
        return rows, missing

    def written_codes(self, row):
        """DQ codes from the code list written in a lane sheet row's notes."""
        return [c for c in self.codes if re.search(rf"(?<![A-Za-z]){re.escape(c)}(?![A-Za-z0-9])", row["notes"])]


CSS = """:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#d9d9de; --head:#f4f4f6;
        --medium:#fff3c4; --low:#ffd8a8; --bad:#ffd6d6; --bad-fg:#a50e0e; --ok:#1a7f37; --warn-fg:#8a5a00; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#161618; --fg:#ececf1; --muted:#9a9aa3; --line:#3a3a40;
          --head:#222226; --medium:#4d4214; --low:#5c3a12; --bad:#5a1d1d; --bad-fg:#ff9b9b; --ok:#5fd17f;
          --warn-fg:#f2c14e; color-scheme:dark; }
}
:root[data-theme="dark"] { --bg:#161618; --fg:#ececf1; --muted:#9a9aa3; --line:#3a3a40; --head:#222226;
        --medium:#4d4214; --low:#5c3a12; --bad:#5a1d1d; --bad-fg:#ff9b9b; --ok:#5fd17f; --warn-fg:#f2c14e;
        color-scheme:dark; }
body { background:var(--bg); color:var(--fg); margin:0 auto; max-width:1280px; padding:24px 16px;
       font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; } h3 { font-size:15px; margin:20px 0 6px; }
.muted { color:var(--muted); }
table { border-collapse:collapse; width:100%; margin:8px 0; }
th, td { border-bottom:1px solid var(--line); padding:5px 8px; text-align:left; vertical-align:top; }
th { background:var(--head); font-weight:600; white-space:nowrap; }
td.t { font-variant-numeric:tabular-nums; white-space:nowrap; }
.medium { background:var(--medium); } .low { background:var(--low); }
.bad { background:var(--bad); color:var(--bad-fg); font-weight:600; }
.badge { display:inline-block; border-radius:4px; padding:1px 7px; font-size:12px; font-weight:600; }
.badge.ok { color:var(--ok); border:1px solid var(--ok); }
.badge.bad { color:var(--bad-fg); border:1px solid var(--bad-fg); }
.badge.minor { color:var(--muted); border:1px solid var(--muted); }
ul.findings { margin:0; padding-left:16px; } ul.findings li { margin:0; }
li.serious { color:var(--bad-fg); font-weight:600; } li.warn { color:var(--warn-fg); } li.minor { color:var(--muted); }
b.final { font-weight:700; }
a { color:inherit; }
.wrap { overflow-x:auto; }
details.sec { margin:20px 0 0; } details.sheet { margin:12px 0 0 16px; }
details > summary { cursor:pointer; }
details > summary h2, details > summary h3 { display:inline; margin:0; }
.bar { display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center; margin:12px 0; }
.bar button { font:inherit; padding:3px 10px; border:1px solid var(--line); border-radius:4px; background:var(--head);
              color:var(--fg); cursor:pointer; }
.links a { white-space:nowrap; margin-right:6px; }
tr.scan > td { padding:0 8px 6px; border-bottom:1px solid var(--line); }
tr.scan img { display:block; max-width:100%; height:auto; margin:6px 0; border:1px solid var(--line); background:#fff; }
tr:target, tr.hit { outline:2px solid var(--warn-fg); outline-offset:-2px; }
@media print { body { max-width:none; } h2 { break-after:avoid; } tr { break-inside:avoid; } .bar { display:none; } }
"""

# Sections start collapsed. Browsers open the sections around a link's target; where scripts may run (not in a
# sandboxed viewer), this also offers expand/collapse all and marks the row a link went to.
JS = """
document.querySelectorAll('button[data-all]').forEach(b => b.hidden = false);
function openTo(id) {
  const el = id && document.getElementById(decodeURIComponent(id));
  if (!el) return;
  for (let d = el.closest('details'); d; d = d.parentElement.closest('details')) d.open = true;
  document.querySelectorAll('.hit').forEach(x => x.classList.remove('hit'));
  if (el.tagName === 'TR') el.classList.add('hit');
  el.scrollIntoView({block: 'center'});
}
document.addEventListener('click', e => {
  const a = e.target.closest('a[href^="#"]');
  if (a) { e.preventDefault(); history.pushState(null, '', a.hash); openTo(a.hash.slice(1)); }
  const b = e.target.closest('button[data-all]');
  if (b) document.querySelectorAll('details').forEach(d => d.open = b.dataset.all === 'open');
});
window.addEventListener('popstate', () => openTo(location.hash.slice(1)));
openTo(location.hash.slice(1));
"""


def section(sid, title, body, extra=""):
    return f'<details class="sec" id="{sid}"><summary><h2>{title}</h2>{extra}</summary>{body}</details>'


def swim_id(e, h, ln):
    return f"r{e}-{h}-{ln}"


def sheet_id(e, ln):
    return f"ls{e}-{ln}"


def slip_id(slip):
    return "dq-" + re.sub(r"[^A-Za-z0-9]+", "-", slip["_file"].removesuffix(".json")).strip("-")


class Scans:
    """Scanned pages as embedded JPEG data URIs, rendered once each with pdftoppm."""

    def __init__(self, dirs, dpi=90, quality=40):
        self.dirs, self.dpi, self.quality, self.cache, self.missing = dirs, dpi, quality, {}, set()

    def image(self, scan, page):
        if (scan, page) not in self.cache:
            pdf = next((d / scan for d in self.dirs if (d / scan).is_file()), None)
            if pdf is None:
                if scan not in self.missing:
                    print(f"Warning: {scan} not found in {', '.join(map(str, self.dirs))}; its pages are not embedded",
                          file=sys.stderr)
                    self.missing.add(scan)
                self.cache[(scan, page)] = None
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    subprocess.run(["pdftoppm", "-gray", "-jpeg", "-jpegopt", f"quality={self.quality}", "-r", str(self.dpi),
                                    "-f", str(page), "-l", str(page), "-singlefile", str(pdf), f"{tmp}/p"], check=True)
                    data = pathlib.Path(tmp, "p.jpg").read_bytes()
                self.cache[(scan, page)] = "data:image/jpeg;base64," + base64.b64encode(data).decode()
        return self.cache[(scan, page)]


def scan_id(row_id):
    return "scan-" + row_id


def page_link(scans, doc, row_id):
    """The page number, linking to the row's embedded scan when there is one."""
    label = f'p{doc["_page"]}'
    if not scans.image(doc["_scan"], doc["_page"]):
        return label
    return f'<a href="#{scan_id(row_id)}" title="{esc(doc["_scan"])} page {doc["_page"]}">{label}</a>'


def scan_row(scans, doc, row_id, cols):
    """A full-width row under a sheet or slip with its scanned page, collapsed."""
    src = scans.image(doc["_scan"], doc["_page"])
    if not src:
        return ""
    return (f'<tr class="scan"><td colspan="{cols}"><details><summary class="muted">Scan: {esc(doc["_scan"])} page '
            f'{doc["_page"]}</summary><img id="{scan_id(row_id)}" src="{src}" loading="lazy" '
            f'alt="{esc(doc["_scan"])} page {doc["_page"]}"></details></td></tr>')


def findings(notes, levels=("serious", "warn", "minor")):
    items = [f'<li class="{lv}">{esc(t)}</li>' for lv, t in notes if lv in levels]
    return f'<ul class="findings">{"".join(items)}</ul>' if items else ""


def sw_cells(res):
    cells = []
    times = {c: (v, t) for c, v, t in res["sw"]}
    unread = {t["column"]: t for t in (res["row"] or {}).get("handTimes", []) if hundredths(t["normalized"]) is None}
    for c in (1, 2, 3):
        if c in times:
            v, t = times[c]
            cls = {"MEDIUM": " medium", "LOW": " low"}.get(t["confidence"], "")
            cells.append(f'<td class="t{cls}" title="written: {esc(t["written"])}, {t["confidence"].lower()} confidence'
                         f'{", overwritten" if t["corrected"] else ""}">{fmt(v)}{"*" if t["corrected"] else ""}</td>')
        elif c in unread:
            cells.append(f'<td class="t low" title="unreadable">{esc(unread[c]["written"])}?</td>')
        else:
            cells.append("<td></td>")
    return "".join(cells)


def swimmer(res):
    row = res["row"]
    if not row:
        return '<span class="muted">no lane sheet</span>'
    if row["status"] == "NO_SWIMMER":
        return '<span class="muted">no swimmer on the sheet</span>'
    s = esc(f'{row["swimmerName"]} {row["age"]}'.strip())
    if row["status"] == "NO_SHOW":
        s += ' <span class="badge minor">N/S</span>'
    if row["status"] == "DISQUALIFIED" or res["dq"]:
        s += ' <span class="badge bad">DQ</span>'
    return s


def paper_links(audit, res):
    e, h, ln = res["event"], res["heat"], res["lane"]
    links = []
    if (e, ln) in audit.sheets:
        links.append(f'<a href="#{sheet_id(e, ln)}">sheet</a>')
    for s in sorted(audit.slip_keys.get((e, h, ln), []), key=lambda s: s["_page"]):
        links.append(f'<a href="#{slip_id(s)}">DQ p{s["_page"]}</a>')
    return f'<td class="links">{"".join(links)}</td>'


def result_row(audit, res, with_event=False):
    row = res["row"] or {}
    final_cls = " bad" if res["serious"] else ""
    diff = res["diff"]
    diff_cls = " bad" if diff is not None and abs(diff) > audit.tol else (" medium" if diff else "")
    key = swim_id(res["event"], res["heat"], res["lane"])
    lead = f'<td><a href="#{key}">{res["event"]}</a></td>' if with_event else ""
    rid = "" if with_event else f' id="{key}"'
    race = res["race"]["race"] if res["race"] else ""
    return (f'<tr{rid}>{lead}<td>{res["heat"]}</td><td>{res["lane"]}</td><td>{swimmer(res)}</td>{paper_links(audit, res)}'
            f'<td>{esc(row.get("team", ""))}</td><td class="t">{race}</td>'
            f'<td class="t">{fmt(res["tp"])}</td><td class="t">{fmt(res["pb"])}</td>{sw_cells(res)}'
            f'<td class="t">{fmt(res["median"])}</td><td class="t{final_cls}"><b class="final">{"N/S" if res["ns"] and res["official"] is not None else fmt(res["final"])}</b></td>'
            f'<td class="t">{fmt(res["official"])}{"<sup>PB</sup>" if res["race"] and any(n.startswith("Gen7 official time is a push") for _, n in res["notes"]) else ""}</td>'
            f'<td class="t{diff_cls}">{fmt(diff, True) if diff is not None else ""}</td>'
            f'<td>{findings(res["notes"])}</td></tr>')


HEAD = ("<tr>{lead}<th>Heat</th><th>Lane</th><th>Swimmer</th><th>Paper</th><th>Team</th><th>Race</th><th>TP</th><th>PB</th>"
        "<th>SW 1</th><th>SW 2</th><th>SW 3</th><th>SW median</th><th>Final</th><th>Gen7 official</th>"
        "<th>Official − final</th><th>Audit notes</th></tr>")


def code_cell(audit, slip):
    given = audit.assigned.get(slip["_file"], {})
    code = given.get("code", "")
    if not code:
        return ""
    text = audit.codes.get(code, ("not in the code list", ""))[0]
    note = f'<br><span class="muted">{esc(given["note"])}</span>' if given.get("note") else ""
    return f'<b>{esc(code)}</b> <span class="muted">{esc(text)}</span>{note}'


def touchpads(results):
    """Touch pad touches by lane: expected and recorded split and finish touches.

    Gen7 prints one split row per 100 m, at the touch pad end, and the finish on the race's last row: a race of
    200 m or more expects one split touch per 100 m before the finish (D / 100 - 1), a shorter race none. Only swims
    with a final time in a heat with a Gen7 race count; a split or finish touch is one Gen7 recorded on the pad
    (a button time, or an underlined button override copied into the finish, is not one).
    """
    lanes = defaultdict(lambda: [0, 0, 0, 0, 0])  # swims, expected splits, splits, expected finishes, finishes
    no_race = 0
    for r in results:
        if r["final"] is None:
            continue
        race = r["race"]
        if not race:
            no_race += 1
            continue
        dist = distance(race["eventDescription"]) or 0
        last = max([max(dist // 100, 1)] + [s["row"] for ln in race["lanes"] for s in ln["splits"]])
        gl = next((ln for ln in race["lanes"] if ln["lane"] == r["lane"]), None)
        row = lanes[r["lane"]]
        row[0] += 1
        row[1] += dist // 100 - 1 if dist >= 200 else 0
        row[2] += len({s["row"] for s in gl["splits"] if s["row"] < last and s["time"]}) if gl and dist >= 200 else 0
        row[3] += 1
        row[4] += r["tp"] is not None
    return dict(sorted(lanes.items())), no_race


def touchpad_table(lanes):
    """The Touchpads table: one row per lane and a total."""
    def pct(got, want):
        return f'{round(100 * got / want)}%' if want else ""

    def cls(got, want):
        return "" if not want or got >= want else (" bad" if got < 0.8 * want else " medium")

    def cells(v):
        return (f'<td class="t">{v[0]}</td><td class="t">{v[1] or ""}</td><td class="t{cls(v[2], v[1])}">'
                f'{v[2] if v[1] else ""}</td><td class="t{cls(v[2], v[1])}">{pct(v[2], v[1])}</td>'
                f'<td class="t">{v[3]}</td><td class="t{cls(v[4], v[3])}">{v[4]}</td>'
                f'<td class="t{cls(v[4], v[3])}">{pct(v[4], v[3])}</td>')

    total = [sum(v[i] for v in lanes.values()) for i in range(5)]
    return ('<div class="wrap"><table><tr><th>Lane</th><th>Swims</th><th>Expected split touches</th>'
            '<th>Actual split touches</th><th>%</th><th>Expected finish touches</th><th>Actual finish touches</th>'
            '<th>%</th></tr>' + "".join(f"<tr><td>{ln}</td>{cells(v)}</tr>" for ln, v in lanes.items())
            + f'<tr><td><b>Total</b></td>{cells(total)}</tr></table></div>')


WRITTEN_IN = re.compile(r"\bname\b.*crossed out.*\bwritten\b")


def surname_key(name):
    return re.sub(r"[^a-z]", "", (name or "").split(",")[0].lower())


def quick_fixes(audit, allres, slip_rows, missing, merge=None):
    """The swims whose result rests on something the OCR could not settle, by (event, heat, lane): what the merge
    file has, and what to check. A watch that could not be read; a watch read with medium or low confidence, or
    overwritten on the sheet, that no other watch agrees with, when the final time comes from the watches; a poor or stray watch time; a swim in
    doubt; a lane sheet swimmer with no time anywhere, or a Gen7 time for a lane the sheet has as empty or a no-show;
    a swimmer written in over the printed one; a DQ slip with no code, or with a code given with a doubt (a note in
    dq-codes.json), and a DQ marked on a sheet with no slip; and, given our merge file (by_swim from hy3), a lane sheet swim not in it, a different
    swimmer there, or a DQ with no code."""
    fixes = defaultdict(list)
    slips = defaultdict(list)  # the DQ slips a swim's checks are about
    on_sheet = set()  # swims with a check about the lane sheet
    for r in allres:
        key = (r["event"], r["heat"], r["lane"])
        from_sw = r["final"] is not None and (r["final"] != r["tp"] or r["swDoubt"])
        for col, v, t in r["sw"] if from_sw else []:
            # An uncertain reading matters only when no other watch backs it up.
            if (t["confidence"] != "HIGH" or t["corrected"]) and not any(
                    c != col and abs(o - v) <= audit.tol for c, o, _ in r["sw"]):
                why = (f'read as {fmt(v)} ({t["confidence"].lower()} confidence)' if t["confidence"] != "HIGH"
                       else f"{fmt(v)}, overwritten on the sheet")
                fixes[key].append(f'SW timer {col} "{t["written"]}" {why}, and no other watch agrees with it: '
                                  f'the final time comes from the watches; check the reading')
        for _, n in r["notes"]:
            if "could not be read" in n:
                fixes[key].append(f"{n}: read the watch on the sheet")
            elif n.startswith(("Poor SW time", "In doubt")) or n.endswith("check the sheet") \
                    or "no time anywhere" in n or "but the lane sheet has a no-show" in n \
                    or "but the lane sheet has no swimmer" in n:
                fixes[key].append(n)
        row = r["row"]
        if row and row["status"] != "NO_SHOW" and WRITTEN_IN.search(row["notes"] or ""):
            fixes[key].append("A swimmer is written in over the printed one: check the entry the swim is given to")
    on_sheet.update(fixes)
    slip_of = {(s["eventNumber"], s["heat"], s["lane"]): s for s, _, _ in slip_rows}
    for s, row, f in slip_rows:
        key = (s["eventNumber"], s["heat"], s["lane"])
        before = len(fixes.get(key, []))
        given = audit.assigned.get(s["_file"], {})
        code = given.get("code", "")
        if code and given.get("note"):
            # Only a code picked with a doubt; the others are in the DQs section.
            text = audit.codes.get(code, ("not in the code list", ""))[0]
            fixes[key].append(f"DQ {code} ({text}): confirm the code with the referee; {given['note']}")
        elif not code:
            fixes[key].append("DQ slip with no code: enter the code in Meet Manager")
        for lv, t in f:
            if lv == "serious" and ("lane sheet" in t or "Not signed" in t):
                fixes[key].append(f"DQ slip: {t}")
        if len(fixes.get(key, [])) > before:
            slips[key].append(s)
    for e, h, ln, _ in missing:
        fixes[(e, h, ln)].append("DQ marked on the lane sheet but there is no slip")
        on_sheet.add((e, h, ln))
    if merge is not None:
        for (e, ln), sheet in audit.sheets.items():
            for h, row in enumerate(sheet["rows"], start=1):
                if row["status"] not in ("SWAM", "DISQUALIFIED") or not row["handTimes"]:
                    continue
                m = merge.get((e, h, ln))
                if m is None:
                    fixes[(e, h, ln)].append("Swam on the lane sheet but not in the merge file: enter the swim")
                    on_sheet.add((e, h, ln))
                elif surname_key(row["swimmerName"]) != surname_key(m["surname"]):
                    fixes[(e, h, ln)].append("The lane sheet swimmer is not the one in the merge file: check the swimmer")
                    on_sheet.add((e, h, ln))
        for key, m in merge.items():
            if m["status"] == "Q" and not m["code"]:
                fixes[key].append("DQ in the merge file with no code: enter the code in Meet Manager")
                if key in slip_of and slip_of[key] not in slips[key]:
                    slips[key].append(slip_of[key])
                else:
                    on_sheet.add(key)
    by_key = {(r["event"], r["heat"], r["lane"]): r for r in allres}
    out = []
    for key in sorted(fixes):
        checks = list(dict.fromkeys(fixes[key]))
        r = by_key.get(key)
        if merge is not None:
            m = merge.get(key)
            has = ("not in the file" if m is None else "N/S" if m["status"] == "R"
                   else f'DQ {hy3.fina(m["code"], audit.codes) or "(no code)"}, {fmt(m["time"])}' if m["status"] == "Q"
                   else fmt(m["time"]))
        else:
            has = ("N/S" if r and r["ns"] else fmt(r["final"]) if r and r["final"] is not None else "no time")
        # The scans to look at: the DQ slip for a DQ check, the lane sheet for the rest.
        sheet = audit.sheets.get((key[0], key[2]))
        scans = [{"label": "DQ slip", "id": slip_id(s), "scan": s["_scan"], "page": s["_page"]} for s in slips[key]]
        if sheet and (key in on_sheet or not scans):
            scans.insert(0, {"label": "Lane sheet", "id": sheet_id(key[0], key[2]), "scan": sheet["_scan"],
                             "page": sheet["_page"]})
        times = None
        if r:
            f = lambda v: fmt(v) if v is not None else ""  # noqa: E731
            times = {"tp": f(r["tp"]), "pb": f(r["pb"]), "median": f(r["median"]), "final": f(r["final"]),
                     "official": f(r["official"]), "tolerance": audit.tol / 100,
                     "sw": [{"column": c, "time": fmt(v), "written": t.get("written", ""), "confidence":
                             t.get("confidence", ""), "corrected": bool(t.get("corrected"))} for c, v, t in r["sw"]]}
        out.append({"event": key[0], "heat": key[1], "lane": key[2], "inFile": has, "checks": checks, "scans": scans,
                    "times": times})
    return out


def quick_fix_table(items, scans=None, done=False):
    """The Quick Fix table: event, heat, lane, what the merge file has, what to check, and the scan to look at. In the
    report (not done) the event links to the swim and the scan to its page embedded under the sheet or slip; the list on
    its own names the scan file and page, and has a Done box instead."""
    def ev(i):
        return str(i["event"]) if done else f'<a href="#{swim_id(i["event"], i["heat"], i["lane"])}">{i["event"]}</a>'

    def scan(x):
        text = f'{x["label"]} p{x["page"]}'
        if done or not scans.image(x["scan"], x["page"]):
            return f'{text} ({esc(x["scan"])})'
        return f'<a href="#{scan_id(x["id"])}" title="{esc(x["scan"])} page {x["page"]}">{text}</a>'
    if not items:
        return '<p class="muted">None.</p>'
    return ('<div class="wrap"><table><tr><th>Event</th><th>Heat</th><th>Lane</th><th>In the merge file</th>'
            '<th>Check</th><th>Scan</th>' + ('<th>Done</th>' if done else '') + '</tr>' + "".join(
                f'<tr><td>{ev(i)}</td><td>{i["heat"]}</td><td>{i["lane"]}</td><td class="t">{esc(i["inFile"])}</td>'
                f'<td><ul class="findings">{"".join(f"<li>{esc(c)}</li>" for c in i["checks"])}</ul></td>'
                f'<td class="links">{"<br>".join(scan(x) for x in i.get("scans", []))}</td>'
                + ('<td class="box">&#9744;</td>' if done else '') + '</tr>' for i in items) + '</table></div>')


QUICK_FIX_NOTE = ('Only the swims where the OCR could not settle the result, for a quick fix in Meet Manager once the '
                  'merge results are imported: watches that could not be read, or were read with low confidence or '
                  'overwritten with no other watch to back them up, when the final time comes from the watches; poor '
                  'watch times and swims in doubt; lane sheet and Gen7 disagreeing on whether a lane swam; swimmers '
                  'written in; DQs with no code or a code given with a doubt; and lane sheet swims missing from the '
                  'merge file or given to another swimmer. Everything else stays in its own section (Gen7 differences '
                  'in Serious issues and SW overrides, the other DQ codes in DQs).')


def _runs(evs):
    """[101, 102, 103, 105] -> [(101, 103), (105, 105)]."""
    out = []
    for e in evs:
        if out and e == out[-1][1] + 1:
            out[-1] = (out[-1][0], e)
        else:
            out.append((e, e))
    return out


def quick_fix_page(meet, items, events):
    """The Quick Fix list on its own, to print: no swimmers' names."""
    span = ("events " + ", ".join(f"{a}" if a == b else f"{a}&ndash;{b}" for a, b in _runs(events))
            if len(events) > 1 else f"event {events[0]}")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Quick Fix ({span.replace("&ndash;", "-")})</title>'
            f'<style>{CSS} td.box {{ font-size:18px; text-align:center; }}</style></head><body>'
            f'<h1>Quick Fix: {esc(meet["meetName"])} ({span})</h1>'
            f'<p class="muted">{esc(meet["meetDate"])}. Generated {datetime.now():%Y-%m-%d %H:%M}. '
            f'{len(items)} swim{"s" if len(items) != 1 else ""}. {QUICK_FIX_NOTE}</p>'
            + quick_fix_table(items, done=True) + '</body></html>')


def build(audit, tol, scans, merge=None):
    results = audit.results()
    slip_rows, missing = audit.dq_findings(results)
    allres = [r for rs in results.values() for r in rs]
    swims = [r for r in allres if r["final"] is not None]
    meet = next(iter(audit.sheets.values()))
    count = lambda pred: sum(1 for r in allres if pred(r))  # noqa: E731
    has = lambda r, s: any(s in n for _, n in r["notes"])  # noqa: E731
    coded = sum(1 for s in audit.slips if audit.assigned.get(s["_file"], {}).get("code"))
    ignored = audit.ignored_races()
    fixes = quick_fixes(audit, allres, slip_rows, missing, merge)
    summary = [
        ("Swims with a final time", len(swims)),
        ("Final time from the touch pad", count(lambda r: r["final"] is not None and r["final"] == r["tp"])),
        ("Final time from the SW median (no TP, or TP outside the SW median)", count(lambda r: has(r, "SW median used"))),
        ("SW median overrides the TP time (see SW overrides)", count(lambda r: r["swOverride"])),
        ("TP and PB agree but are outside the SW median", count(lambda r: has(r, "TP and PB agree"))),
        ("In doubt: TP kept, SW times copied to the merge file", count(lambda r: r["swDoubt"])),
        ("Bad TP time (outside the tolerance of both PB and the SW median)", count(lambda r: has(r, "Bad TP time"))),
        ("Bad PB time", count(lambda r: has(r, "Bad PB time"))),
        ("Poor SW time", count(lambda r: has(r, "Poor SW time"))),
        ("Gen7 official time differs from the final time by more than the tolerance",
         count(lambda r: r["diff"] is not None and abs(r["diff"]) > tol)),
        ("Gen7 official time differs from the final time within the tolerance",
         count(lambda r: r["diff"] is not None and 0 < abs(r["diff"]) <= tol)),
        ("Gen7 official time is a push button override", count(lambda r: has(r, "(underlined)"))),
        ("TP soft touch / faulty TP (Gen7 PB time but no official time)", count(lambda r: has(r, "faulty TP"))),
        ("Gen7 time for a no-show on the lane sheet (recorded as N/S, no time)",
         count(lambda r: has(r, "recorded as N/S"))),
        ("Gen7 time for a lane the sheet has as empty, or a no-show with SW times",
         count(lambda r: has(r, "but the lane sheet has a no-show") and not has(r, "recorded as N/S")
                   or has(r, "but the lane sheet has no swimmer"))),
        ("Swims with lane sheet times but no Gen7 time", count(lambda r: has(r, "Gen7 has no time in this lane")
                                                                 or has(r, "no Gen7 race for this heat"))),
        ("SW time could not be read", count(lambda r: has(r, "could not be read"))),
        ("DQ slips", len(slip_rows)),
        ("DQ slips with a serious finding", sum(1 for _, _, f in slip_rows if any(lv == "serious" for lv, _ in f))),
        ("DQ slips with no DQ code", len(audit.slips) - coded),
        ("DQ marked on a lane sheet with no slip", len(missing)),
        ("Lane sheets not signed", sum(1 for s in audit.sheets.values() if not s["signed"])),
        ("Ignored races (false starts and races not started)", len(ignored)),
        ("Quick Fix: swims the OCR could not settle", len(fixes)),
    ]
    serious = [r for r in allres if r["serious"]]
    pads, no_race = touchpads(allres)
    # The events the report covers, in the heading when it isn't the whole gala (an audit event by event or of the
    # session so far): "Event 102 Mixed 100 LC Meter Butterfly Finals", or "Events 101-103".
    evs = sorted(audit.events)
    if audit.only and len(evs) == 1:
        which = f"Event {evs[0]} {audit.events[evs[0]]}".strip()
    elif audit.only and evs:
        which = "Events " + ", ".join(f"{a}" if a == b else f"{a}&ndash;{b}" for a, b in _runs(evs))
    else:
        which = ""
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{esc(which.replace("&ndash;", "-")) + " · " if which else ""}{esc(meet["meetName"])} Audit</title>'
           f'<style>{CSS}</style></head><body>',
           f'<h1>Gala audit: {esc(meet["meetName"])}{" &middot; " + which if which else ""}</h1>',
           f'<p class="muted">{esc(meet["meetDate"])}. Generated {datetime.now():%Y-%m-%d %H:%M}. Tolerance '
           f'{tol / 100:.2f}s. Sources: lane sheets ({len(audit.sheets)} transcribed), DQ slips ({len(audit.slips)}), '
           f'the ETD programme ({len(audit.etd)} heats) and the Gen7 session report ({len(audit.races)} races). '
           f'DQ codes: {len(audit.codes)} in the code list, {coded} of {len(audit.slips)} slips given one.</p>',
           '<div class="bar"><button data-all="open" hidden>Expand all</button><button data-all="close" hidden>Collapse all</button>'
           '<a href="#rules">Final time</a><a href="#summary">Summary</a><a href="#quickfix">Quick Fix</a><a href="#touchpads">Touchpads</a><a href="#serious">Serious issues</a><a href="#overrides">SW overrides</a>'
           '<a href="#dq">DQs</a><a href="#results">Full result review</a><a href="#sheets">Lane sheets</a></div>',
           '<p class="muted">Sections start collapsed. In the results, <b>Paper</b> links each swim to its lane sheet '
           'and DQ slips; event, heat and lane links lead back to the swim, and page numbers open the scan.</p>',
           section("rules", "How the final time is chosen", '<ul>'
           '<li><b>TP</b> is the touch pad finish (the Gen7 split on the race\'s last row, unless it is the same as an '
           'underlined button override, which Gen7 copies into it), <b>PB</b> the push button '
           'backup time, <b>SW</b> the lane sheet (stopwatch) times; the SW median of two is their mean.</li>'
           '<li>With a TP time: TP when it is within the tolerance of the SW median (a PB outside it is a bad PB); '
           'otherwise the SW median overrides it, even when TP agrees with PB (both are noted as outside the SW '
           'median; a TP that agrees with neither is a bad TP). TP alone when there are no SW times. In doubt (fewer '
           'than two SW times within the tolerance of their median, and PB not within it either), TP '
           'stays the final time and the SW times are copied to the merge file. When TP is the final time and there is '
           'no PB time, the SW median (thousandths dropped) is written as backup 1 in the merge file; when TP agrees '
           'with the SW median but not PB, PB is backup 1 and the SW median backup 2.</li><li>With no TP time: the SW median, thousandths dropped. A PB outside the tolerance of it is a '
           'bad PB; if adding PB moves the median by more than the tolerance, an SW time is poor and is named when '
           'it can be picked out. PB alone when there are no SW times.</li>'
           '<li>A no-show on the lane sheet (N/S, no SW times) is recorded as N/S with no time, even when Gen7 has '
           'one.</li>'
           '<li>The final time is compared with the Gen7 official time (<sup>PB</sup>: Gen7 used a push button '
           'time).</li></ul>'),
           section("summary", "Summary", '<table><tr><th>Check</th><th>Count</th></tr>'
                   + "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in summary) + "</table>"
                   + ('<h3>Ignored races</h3><p class="muted">Left out of the audit. A false start is a Gen7 race with '
                      'nothing recorded in any lane whose race number is not written in the ETD programme; a race not '
                      'started is an ETD race number with no Gen7 race and no lane sheet times.</p><table><tr>'
                      '<th>Race</th><th>Event</th><th>Heat</th><th>Reason</th></tr>'
                      + "".join(f'<tr><td>{n}</td><td>{esc(f"{e} {d}".strip() if e in audit.events or not d else d)}</td>'
                                f'<td>{h}</td><td>{why}</td></tr>'
                                for n, e, h, d, why in ignored) + "</table>" if ignored else "")),
           section("quickfix", "Quick Fix", f'<p class="muted">{QUICK_FIX_NOTE}'
                   + ('' if merge is not None else ' Run with --merge to check the merge file too.') + '</p>'
                   + quick_fix_table(fixes, scans), f' <span class="badge {"bad" if fixes else "ok"}">{len(fixes)} swims</span>'),
           section("touchpads", "Touchpads",
                   '<p class="muted">Touch pad touches Gen7 recorded, by lane, against those expected for every swim '
                   'with a final time. Gen7 prints one split row per 100 m, at the touch pad end: a race of 200 m or '
                   'more expects a split touch at each 100 m before the finish (a 200 one, a 400 three, a 1500 '
                   'fourteen), a shorter race none. Every swim expects a finish touch. A push button time, or an '
                   'underlined button override, is not a touch. Orange: under 80% recorded; yellow: 80% or more but '
                   'not all.</p>' + touchpad_table(pads)
                   + ('<p class="muted">A swimmer who stopped before the finish (a DNF) still counts as expecting every '
                      'touch; check DQ slips that say a swimmer stopped.</p>')
                   + (f'<p class="muted">Not counted: {no_race} swim{"s" if no_race != 1 else ""} in a heat with no '
                      f'Gen7 race.</p>' if no_race else "")),
           section("serious", "Serious issues",
                   f'<p class="muted">Select an event number to go to the swim in the full result review.</p>'
                   f'<div class="wrap"><table>{HEAD.format(lead="<th>Event</th>")}'
                   + "".join(result_row(audit, r, True) for r in serious) + "</table></div>",
                   f' <span class="badge {"bad" if serious else "ok"}">{len(serious)} swims</span>')]

    dq = [f'<p class="muted">A slip is checked against the lane sheet (is there a swimmer, and did they swim?), Gen7 '
          f'(a finish in that lane) and the event (an infraction or DQ code that cannot happen in it). Event, heat '
          f'and lane go to the swim; the slip page opens its scan, under the row.</p><div class="wrap"><table><tr><th>Event</th>'
          f'<th>Heat</th><th>Lane</th><th>Slip</th><th>Swimmer (lane sheet)</th><th>Team</th><th>Infraction</th>'
          f'<th>Code</th><th>Official</th><th>Referee</th><th>Announced</th><th>Findings</th></tr>']
    for s, row, f in slip_rows:
        e, h, ln = s["eventNumber"], s["heat"], s["lane"]
        swim = f'href="#{swim_id(e, h, ln)}"'
        who = esc(row["swimmerName"]) if row and row["swimmerName"] else '<span class="muted">none</span>'
        sheet = f' <a href="#{sheet_id(e, ln)}" class="muted">sheet</a>' if (e, ln) in audit.sheets else ""
        dq.append(f'<tr id="{slip_id(s)}"><td><a {swim}>{e}</a></td><td><a {swim}>{h}</a></td><td><a {swim}>{ln}</a>'
                  f'</td><td>{page_link(scans, s, slip_id(s))}</td><td>{who}{sheet}</td><td>{esc(row["team"]) if row else ""}</td>'
                  f'<td>{esc(s["infraction"])}{"<br><span class=muted>Back: " + esc(s["back"]) + "</span>" if s["back"] else ""}</td>'
                  f'<td>{code_cell(audit, s)}</td>'
                  f'<td>{esc(s["official"])}</td><td>{esc(s["referee"])}</td><td class="t">{esc(s["announcementTime"])}</td>'
                  f'<td>{findings(f)}</td></tr>' + scan_row(scans, s, slip_id(s), 12))
    dq.append("</table></div>")
    if missing:
        nos = ('<div class="wrap"><table><tr><th>Event</th><th>Heat</th><th>Lane</th><th>Swimmer</th>'
               '<th>Lane sheet</th></tr>' + "".join(
                   f'<tr><td><a href="#{swim_id(e, h, ln)}">{e}</a></td><td>{h}</td><td>{ln}</td>'
                   f'<td>{esc(r["swimmerName"])}</td><td><a href="#{sheet_id(e, ln)}">sheet</a> '
                   f'{esc(r["status"].replace("_", " ").lower())}; {esc(r["notes"])}</td></tr>'
                   for e, h, ln, r in missing) + "</table></div>")
    else:
        nos = '<p class="muted">None.</p>'
    dq.append(f'<details class="sheet" id="dq-noslip"><summary><h3>DQ marked on a lane sheet with no slip</h3> '
              f'<span class="badge {"bad" if missing else "ok"}">{len(missing)}</span></summary>{nos}</details>')
    overrides = [r for r in allres if r["swOverride"]]
    out.append(section("overrides", "SW overrides",
                       f'<p class="muted">Swims with a TP time outside the tolerance of the SW median, where the SW '
                       f'median is the final time. Select an event number to go to the swim.</p>'
                       f'<div class="wrap"><table>{HEAD.format(lead="<th>Event</th>")}'
                       + "".join(result_row(audit, r, True) for r in overrides) + "</table></div>",
                       f' <span class="badge minor">{len(overrides)} swims</span>'))
    out.append(section("dq", "DQs", "".join(dq), f' <span class="badge minor">{len(slip_rows)} slips</span>'))

    review = [f'<p class="muted">Every swim by event, heat and lane. Shaded SW times were read with medium (yellow) or '
              f'low (orange) confidence; * marks a time overwritten on the sheet.</p>']
    for e in sorted(results):
        rs = results[e]
        flags = sum(r["serious"] for r in rs)
        badge = (f'<span class="badge bad">{flags} serious</span>' if flags else '<span class="badge ok">no serious '
                 'issues</span>')
        review.append(f'<details class="sheet" id="e{e}"><summary><h3>Event {e} {esc(audit.events[e])} {badge}'
                      f'</h3></summary><div class="wrap"><table>{HEAD.format(lead="")}'
                      + "".join(result_row(audit, r) for r in rs) + "</table></div></details>")
    out.append(section("results", "Full result review", "".join(review),
                       f' <span class="badge minor">{len(results)} events</span>'))

    sheets = ['<p class="muted">The event goes to its results, the page opens its scan under the row, and a heat goes to '
              'the swim.'
              '</p><div class="wrap"><table><tr><th>Event</th><th>Lane</th><th>Page</th><th>Heats</th>'
              '<th>Signed</th><th>Unreadable SW</th><th>Medium/low SW</th><th>Overwritten SW</th></tr>']
    for (e, ln), s in sorted(audit.sheets.items()):
        hts = [t for r in s["rows"] for t in r["handTimes"]]
        heats = " ".join(f'<a href="#{swim_id(e, h, ln)}">{h}</a>' for h, r in enumerate(s["rows"], 1)
                         if r["status"] != "NO_SWIMMER")
        sheets.append(f'<tr id="{sheet_id(e, ln)}"><td><a href="#e{e}">{e}</a></td><td>{ln}</td>'
                      f'<td>{page_link(scans, s, sheet_id(e, ln))}</td><td class="links">{heats}</td><td>'
                      + ('<span class="badge ok">signed</span>' if s["signed"] else '<span class="badge bad">NOT SIGNED</span>')
                      + f'</td><td>{sum(1 for t in hts if not t["normalized"]) or ""}</td>'
                      f'<td>{sum(1 for t in hts if t["normalized"] and t["confidence"] != "HIGH") or ""}</td>'
                      f'<td>{sum(1 for t in hts if t["corrected"]) or ""}</td></tr>' + scan_row(scans, s, sheet_id(e, ln), 8))
    have = set(audit.sheets)
    lanes = sorted({ln for _, ln in have})
    gone = [(e, ln) for e in sorted(audit.events) for ln in lanes if (e, ln) not in have]
    sheets.append("</table></div>" + (f'<p>No lane sheet: {", ".join(f"event {e} lane {ln}" for e, ln in gone)}.</p>'
                                       if gone else ""))
    unsigned = sum(1 for s in audit.sheets.values() if not s["signed"])
    out.append(section("sheets", "Lane sheets", "".join(sheets),
                       f' <span class="badge minor">{len(audit.sheets)} sheets</span>'
                       + (f' <span class="badge bad">{unsigned} not signed</span>' if unsigned else "")))
    out.append(f"<script>{JS}</script></body></html>")
    return "\n".join(out), fixes


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        sys.exit(__doc__)
    tol = round(float(args[args.index("--tolerance") + 1]) * 100) if "--tolerance" in args else 30
    sheets, slips, etd = load(args[0])
    if "--fixes" in args:
        print(f"Applied {apply_hand_fixes(sheets, args[args.index('--fixes') + 1])} lane sheet fixes made by hand")
    codes = load_codes(args[args.index("--codes") + 1] if "--codes" in args else DQ_CODES)
    given = pathlib.Path(args[0]) / "dq-codes.json"
    assigned = json.loads(given.read_text(encoding="utf-8")) if given.exists() else {}
    ocr = pathlib.Path(args[0]).resolve()
    dirs = [pathlib.Path(args[args.index("--scans") + 1])] if "--scans" in args else [ocr.parent, ocr]
    opt = lambda name, default: int(args[args.index(name) + 1]) if name in args else default  # noqa: E731
    scans = Scans(dirs, opt("--scan-dpi", 90), opt("--scan-quality", 40))
    events = parse_events(args[args.index("--events") + 1]) if "--events" in args else None
    audit = Audit(sheets, slips, etd, gen7_report.races(args[1]), tol, codes, assigned, events)
    if not audit.sheets:
        sys.exit("No lane sheets" + (" for events %s" % args[args.index("--events") + 1] if events else "")
                 + " in " + args[0])
    merge = hy3.by_swim(args[args.index("--merge") + 1]) if "--merge" in args else None
    page, fixes = build(audit, tol, scans, merge)
    pathlib.Path(args[2]).write_text(page, encoding="utf-8")
    print(f"Wrote {args[2]}: {len(fixes)} swims in Quick Fix")
    if "--quick-fixes" in args:
        out = pathlib.Path(args[args.index("--quick-fixes") + 1])
        meet = next(iter(audit.sheets.values()))
        out.write_text(quick_fix_page(meet, fixes, sorted(audit.events)), encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(fixes, indent=1), encoding="utf-8")
        print(f"Wrote {out} and {out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
