#!/usr/bin/env python3
"""Build a gala audit report (one HTML page) from the gala-ocr transcriptions and the Gen7 session report.

Usage: audit_report.py OCR_DIR GEN7_REPORT.pdf OUT.html [--tolerance 0.35] [--codes DQ_CODES.txt]

OCR_DIR holds the gala-ocr files: lane sheets (<scan>-eventEE-laneL-pPPP.json), DQ slips
(<scan>-eventEE-heatH-laneL-pPPP.json) and ETD programme pages (<scan>-pPPP.json). The ETD race numbers link each
programme heat to its Gen7 race; without them, a heat is matched to the Gen7 race with its event and heat.

For every event, heat and lane the report lists the touch pad (TP) time, the push button (PB) time, every lane sheet
(SW) time, the final time and audit notes. The final time:
- with a TP time: TP when it is within the tolerance of the SW median (a PB time outside it is noted as bad); TP when
  it is within the tolerance of PB but not of the SW median (poor SW times noted); otherwise the SW median, with the
  TP time noted as bad;
- with no TP time: the SW median (a PB time outside the tolerance of it is noted as bad, and poor SW times are noted
  when adding PB moves the median by more than the tolerance); PB alone when there are no SW times.
A median of an even count is the mean of the middle two, with thousandths dropped for the final time.
DQ codes: OCR_DIR/dq-codes.json, when present, gives each slip its code ({"<slip file>": {"code": "BrK", "note": ""}}).
Codes are checked against the DQ code list (default: the FINA list in ../data/dqcodesFINA.txt, lines of
"code","description","group" with group Misc, free, back, breast, fly, IM or Relay): the code must exist and its
group must be one that can happen in the event. Codes written in a lane sheet's notes are checked the same way.
It also checks DQ slips against the lane sheets and Gen7, lane sheet DQ marks against the slips, and repeats the
lane sheet findings (unsigned sheets, unreadable or corrected times). Needs the gen7-report skill next to this one.
"""
import csv
import html
import json
import pathlib
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "gen7-report" / "scripts"))
import gen7_report  # noqa: E402

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
            slips.append(data)
        elif m := LANE_NAME.match(f.name):
            data["_scan"], data["_page"] = m["scan"] + ".pdf", int(m["page"])
            sheets[(data["eventNumber"], data["lane"])] = data
        elif ETD_NAME.match(f.name):
            for h in data["heats"]:
                etd[(h["eventNumber"], h["heat"])] = h
    return sheets, slips, etd


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
    def __init__(self, sheets, slips, etd, races, tol, codes=None, assigned=None):
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

        final = None
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
            elif pb is not None and abs(tp - pb) <= tol:
                final = tp
                poor_sw(tp, f"the SW median {fmt(med)} is {fmt(med - tp, True)}s from TP, which agrees with PB")
            else:
                final = int(med)
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
        res["diff"] = None if official is None or final is None else official - final
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
details.sheet { margin:24px 0 0; } details.sheet > summary { cursor:pointer; }
details.sheet > summary h2, details.sheet > summary h3 { display:inline; margin:0; }
@media print { body { max-width:none; } h2 { break-after:avoid; } tr { break-inside:avoid; } }
"""


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


def result_row(res, with_event=False):
    row = res["row"] or {}
    final_cls = " bad" if res["serious"] else ""
    diff = res["diff"]
    diff_cls = " bad" if diff is not None and abs(diff) > 35 else (" medium" if diff else "")
    lead = f'<td><a href="#e{res["event"]}">{res["event"]}</a></td>' if with_event else ""
    race = res["race"]["race"] if res["race"] else ""
    return (f'<tr>{lead}<td>{res["heat"]}</td><td>{res["lane"]}</td><td>{swimmer(res)}</td>'
            f'<td>{esc(row.get("team", ""))}</td><td class="t">{race}</td>'
            f'<td class="t">{fmt(res["tp"])}</td><td class="t">{fmt(res["pb"])}</td>{sw_cells(res)}'
            f'<td class="t">{fmt(res["median"])}</td><td class="t{final_cls}"><b class="final">{fmt(res["final"])}</b></td>'
            f'<td class="t">{fmt(res["official"])}{"<sup>PB</sup>" if res["race"] and any(n.startswith("Gen7 official time is a push") for _, n in res["notes"]) else ""}</td>'
            f'<td class="t{diff_cls}">{fmt(diff, True) if diff is not None else ""}</td>'
            f'<td>{findings(res["notes"])}</td></tr>')


HEAD = ("<tr>{lead}<th>Heat</th><th>Lane</th><th>Swimmer</th><th>Team</th><th>Race</th><th>TP</th><th>PB</th>"
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


def build(audit, tol):
    results = audit.results()
    slip_rows, missing = audit.dq_findings(results)
    allres = [r for rs in results.values() for r in rs]
    swims = [r for r in allres if r["final"] is not None]
    meet = next(iter(audit.sheets.values()))
    count = lambda pred: sum(1 for r in allres if pred(r))  # noqa: E731
    has = lambda r, s: any(s in n for _, n in r["notes"])  # noqa: E731
    coded = sum(1 for s in audit.slips if audit.assigned.get(s["_file"], {}).get("code"))
    summary = [
        ("Swims with a final time", len(swims)),
        ("Final time from the touch pad", count(lambda r: r["final"] is not None and r["final"] == r["tp"])),
        ("Final time from the SW median (no TP, or bad TP)", count(lambda r: has(r, "SW median used"))),
        ("Bad TP time (outside the tolerance of both PB and the SW median)", count(lambda r: has(r, "Bad TP time"))),
        ("Bad PB time", count(lambda r: has(r, "Bad PB time"))),
        ("Poor SW time", count(lambda r: has(r, "Poor SW time"))),
        ("Gen7 official time differs from the final time by more than the tolerance",
         count(lambda r: r["diff"] is not None and abs(r["diff"]) > tol)),
        ("Gen7 official time differs from the final time within the tolerance",
         count(lambda r: r["diff"] is not None and 0 < abs(r["diff"]) <= tol)),
        ("Gen7 official time is a push button override", count(lambda r: has(r, "(underlined)"))),
        ("Gen7 time for a lane the sheet has as empty or a no-show", count(lambda r: has(r, "Gen7 has a time ("))),
        ("Swims with lane sheet times but no Gen7 time", count(lambda r: has(r, "Gen7 has no time in this lane")
                                                                 or has(r, "no Gen7 race for this heat"))),
        ("SW time could not be read", count(lambda r: has(r, "could not be read"))),
        ("DQ slips", len(slip_rows)),
        ("DQ slips with a serious finding", sum(1 for _, _, f in slip_rows if any(lv == "serious" for lv, _ in f))),
        ("DQ slips with no DQ code", len(audit.slips) - coded),
        ("DQ marked on a lane sheet with no slip", len(missing)),
        ("Lane sheets not signed", sum(1 for s in audit.sheets.values() if not s["signed"])),
    ]
    serious = [r for r in allres if r["serious"]]
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{esc(meet["meetName"])} Audit</title><style>{CSS}</style></head><body>',
           f'<h1>Gala audit: {esc(meet["meetName"])}</h1>',
           f'<p class="muted">{esc(meet["meetDate"])}. Generated {datetime.now():%Y-%m-%d %H:%M}. Tolerance '
           f'{tol / 100:.2f}s. Sources: lane sheets ({len(audit.sheets)} transcribed), DQ slips ({len(audit.slips)}), '
           f'the ETD programme ({len(audit.etd)} heats) and the Gen7 session report ({len(audit.races)} races). '
           f'DQ codes: {len(audit.codes)} in the code list, {coded} of {len(audit.slips)} slips given one.</p>',
           '<h2>How the final time is chosen</h2><ul>'
           '<li><b>TP</b> is the touch pad finish (the Gen7 split on the race\'s last row), <b>PB</b> the push button '
           'backup time, <b>SW</b> the lane sheet (stopwatch) times; the SW median of two is their mean.</li>'
           '<li>With a TP time: TP when it is within the tolerance of the SW median (a PB outside it is a bad PB); TP '
           'when it agrees with PB but not the SW median (poor SW times); otherwise the SW median, and the TP time is '
           'bad.</li><li>With no TP time: the SW median, thousandths dropped. A PB outside the tolerance of it is a '
           'bad PB; if adding PB moves the median by more than the tolerance, an SW time is poor and is named when '
           'it can be picked out. PB alone when there are no SW times.</li>'
           '<li>The final time is compared with the Gen7 official time (<sup>PB</sup>: Gen7 used a push button '
           'time).</li></ul>',
           '<h2>Summary</h2><table><tr><th>Check</th><th>Count</th></tr>'
           + "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in summary) + "</table>",
           f'<h2>Serious issues</h2><p class="muted">{len(serious)} swims. Select an event number for its results.</p>'
           f'<div class="wrap"><table>{HEAD.format(lead="<th>Event</th>")}'
           + "".join(result_row(r, True) for r in serious) + "</table></div>"]

    out.append(f'<h2 id="dq">DQs</h2><p class="muted">{len(slip_rows)} slips. A slip is checked against the lane '
               f'sheet (is there a swimmer, and did they swim?), Gen7 (a finish in that lane) and the event (an '
               f'infraction or DQ code that cannot happen in it).</p><div class="wrap"><table><tr><th>Event</th><th>Heat</th>'
               f'<th>Lane</th><th>Slip</th><th>Swimmer (lane sheet)</th><th>Team</th><th>Infraction</th><th>Code</th>'
               f'<th>Official</th><th>Referee</th><th>Announced</th><th>Findings</th></tr>')
    for s, row, f in slip_rows:
        who = esc(row["swimmerName"]) if row and row["swimmerName"] else '<span class="muted">none</span>'
        out.append(f'<tr><td><a href="#e{s["eventNumber"]}">{s["eventNumber"]}</a></td><td>{s["heat"]}</td>'
                   f'<td>{s["lane"]}</td><td>p{s["page"]}</td><td>{who}</td><td>{esc(row["team"]) if row else ""}</td>'
                   f'<td>{esc(s["infraction"])}{"<br><span class=muted>Back: " + esc(s["back"]) + "</span>" if s["back"] else ""}</td>'
                   f'<td>{code_cell(audit, s)}</td>'
                   f'<td>{esc(s["official"])}</td><td>{esc(s["referee"])}</td><td class="t">{esc(s["announcementTime"])}</td>'
                   f'<td>{findings(f)}</td></tr>')
    out.append("</table></div>")
    out.append(f'<h3>DQ marked on a lane sheet with no slip</h3>')
    if missing:
        out.append('<div class="wrap"><table><tr><th>Event</th><th>Heat</th><th>Lane</th><th>Swimmer</th>'
                   '<th>Lane sheet</th></tr>' + "".join(
                       f'<tr><td><a href="#e{e}">{e}</a></td><td>{h}</td><td>{ln}</td><td>{esc(r["swimmerName"])}</td>'
                       f'<td>{esc(r["status"].replace("_", " ").lower())}; {esc(r["notes"])}</td></tr>'
                       for e, h, ln, r in missing) + "</table></div>")
    else:
        out.append('<p class="muted">None.</p>')

    out.append(f'<h2 id="results">Full result review</h2><p class="muted">Every swim by event, heat and lane. '
               f'Shaded SW times were read with medium (yellow) or low (orange) confidence; * marks a time overwritten '
               f'on the sheet.</p>')
    for e in sorted(results):
        rs = results[e]
        flags = sum(r["serious"] for r in rs)
        badge = (f'<span class="badge bad">{flags} serious</span>' if flags else '<span class="badge ok">no serious '
                 'issues</span>')
        out.append(f'<details class="sheet" open><summary><h3 id="e{e}">Event {e} {esc(audit.events[e])} {badge}'
                   f'</h3></summary><div class="wrap"><table>{HEAD.format(lead="")}'
                   + "".join(result_row(r) for r in rs) + "</table></div></details>")

    out.append('<h2 id="sheets">Lane sheets</h2><div class="wrap"><table><tr><th>Event</th><th>Lane</th><th>Page</th>'
               '<th>Signed</th><th>Unreadable SW</th><th>Medium/low SW</th><th>Overwritten SW</th></tr>')
    for (e, ln), s in sorted(audit.sheets.items()):
        hts = [t for r in s["rows"] for t in r["handTimes"]]
        out.append(f'<tr><td><a href="#e{e}">{e}</a></td><td>{ln}</td><td>{s["_page"]}</td><td>'
                   + ('<span class="badge ok">signed</span>' if s["signed"] else '<span class="badge bad">NOT SIGNED</span>')
                   + f'</td><td>{sum(1 for t in hts if not t["normalized"]) or ""}</td>'
                   f'<td>{sum(1 for t in hts if t["normalized"] and t["confidence"] != "HIGH") or ""}</td>'
                   f'<td>{sum(1 for t in hts if t["corrected"]) or ""}</td></tr>')
    have = set(audit.sheets)
    lanes = sorted({ln for _, ln in have})
    gone = [(e, ln) for e in sorted(audit.events) for ln in lanes if (e, ln) not in have]
    out.append("</table></div>" + (f'<p>No lane sheet: {", ".join(f"event {e} lane {ln}" for e, ln in gone)}.</p>'
                                    if gone else ""))
    out.append("</body></html>")
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        sys.exit(__doc__)
    tol = round(float(args[args.index("--tolerance") + 1]) * 100) if "--tolerance" in args else 35
    sheets, slips, etd = load(args[0])
    codes = load_codes(args[args.index("--codes") + 1] if "--codes" in args else DQ_CODES)
    given = pathlib.Path(args[0]) / "dq-codes.json"
    assigned = json.loads(given.read_text(encoding="utf-8")) if given.exists() else {}
    audit = Audit(sheets, slips, etd, gen7_report.races(args[1]), tol, codes, assigned)
    pathlib.Path(args[2]).write_text(build(audit, tol), encoding="utf-8")
    print(f"Wrote {args[2]}")


if __name__ == "__main__":
    main()
