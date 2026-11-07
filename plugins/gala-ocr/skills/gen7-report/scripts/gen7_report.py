#!/usr/bin/env python3
"""Read a Colorado Gen7 session report (the PDF Gen7 prints, one race per page) into JSON or CSV. No OCR: the PDF
has a text layer, and each value is placed in its lane column by its position on the page.

Usage: gen7_report.py REPORT.pdf [--event N] [--csv]

JSON (default): a list of races in report order:
  {race, page, meet, session, eventNumber, heat, eventDescription, startTime, manualStart, lanes}
with each lane that has anything recorded:
  {lane, place, time, splits, offTime, buttonOverride, buttonA, buttonB, buttonC, backup, pbDiff, pbFlagged,
   reaction}
`place` is an integer or null; times are as printed ("3:41.12"), "" when blank. `splits` lists the lane's split
rows top to bottom as {row, time, split}: the split row (1 = top; one row per 100 m, or one for a 50), the
cumulative time and, when printed in brackets under it, the split itself. The finish is the race's last row.
`buttonOverride` is true when the Off. Time is underlined: the official time is a push button time that overrode the
touch pad. `pbDiff` is the printed difference between the pads and the backup buttons; `pbFlagged` is true when Gen7
marked it with "*".
--csv: one row per lane, the race fields repeated and splits joined with "; ".
Needs poppler's pdftotext and pdftocairo (for the underlines, which are drawn lines, not text).
"""
import csv
import html
import json
import re
import subprocess
import sys
import tempfile

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')
EVENT = re.compile(r"Event:\s*(\d+)\s+Heat:\s*(\d+)\s+Race\s*#\s*(\d+)")
SPLIT_LABEL = re.compile(r"^\d+m$")  # "100m", "200m": a split row's distance, not a labelled row
TIME = re.compile(r"^\*?-?(\d{1,2}:)?\d{1,2}\.\d{2}$")
LINE = re.compile(r'<path style="([^"]*)" d="M ([\d.-]+) ([\d.-]+) L ([\d.-]+) ([\d.-]+) "\s*'
                  r'(?:transform="matrix\(([^)]*)\)")?')
LABELS = {"Off. Time": "offTime", "Button A": "buttonA", "Button B": "buttonB", "Button C": "buttonC",
          "Backup": "backup", "P:B Diff": "pbDiff", "Start Reac:": "reaction"}


def pages(pdf):
    """Each page's words as lines: [(y, [(x0, x1, text, bottom), ...]), ...] top to bottom."""
    out = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True, check=True).stdout
    for page in out.split("<page ")[1:]:
        lines = []
        for m in WORD.finditer(page):
            x0, y0, x1, y1 = map(float, m.groups()[:4])
            word = (x0, x1, html.unescape(m.group(5)), y1)
            if lines and abs(lines[-1][0] - y0) < 2.5:
                lines[-1][1].append(word)
            else:
                lines.append((y0, [word]))
        lines.sort(key=lambda line: line[0])
        yield [(y, sorted(words)) for y, words in merge_lines(lines)]


def merge_lines(lines):
    """pdftotext does not always emit a line's words together; join lines at the same height."""
    merged = []
    for y, words in lines:
        if merged and abs(merged[-1][0] - y) < 2.5:
            merged[-1][1].extend(words)
        else:
            merged.append((y, list(words)))
    return merged


def underlines(pdf):
    """Each page's solid horizontal lines as (x0, x1, y), from an SVG rendering of the PDF."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftocairo", "-svg", pdf, f"{tmp}/r.svg"], check=True)
        with open(f"{tmp}/r.svg", encoding="utf-8") as f:
            svg = f.read()
    # A one-page PDF's SVG has no <page> elements.
    for page in svg.split("<page>")[1:] or [svg]:
        lines = []
        for m in LINE.finditer(re.sub(r"<symbol.*?</symbol>", "", page, flags=re.S)):
            style, x0, y0, x1, y1, tf = m.groups()
            if "dasharray" in style or "stroke:none" in style:
                continue
            a, _, _, d, e, f = map(float, (tf or "1,0,0,1,0,0").split(","))
            if abs(float(y0) - float(y1)) < 0.5:
                xs = sorted((a * float(x0) + e, a * float(x1) + e))
                lines.append((xs[0], xs[1], d * float(y0) + f))
        yield lines


def underlined(word, lines):
    """A line just below the word that runs under most of it."""
    x0, x1, _, y1 = word
    return any(y1 - 2 <= y <= y1 + 3 and min(x1, lx1) - max(x0, lx0) > 0.5 * (x1 - x0) for lx0, lx1, y in lines)


def text(words):
    return " ".join(w[2] for w in words)


def mid(w):
    return (w[0] + w[1]) / 2


def nearest(w, columns):
    """The key of the column whose heading's centre is closest to the word's centre."""
    return min(columns, key=lambda k: abs(columns[k] - mid(w)))


def race(lines, page_no, rules=()):
    joined = [text(w) for _, w in lines]
    at = next((i for i, t in enumerate(joined) if EVENT.search(t)), None)
    if at is None:
        return None
    ev = EVENT.search(joined[at])
    meet, _, session = joined[0].partition("Session:")
    start = next((t.split("Start Time:", 1)[1].strip() for t in joined[at:] if "Start Time:" in t), "")
    r = {"race": int(ev.group(3)), "page": page_no, "meet": meet.strip(), "session": session.strip(),
         "eventNumber": int(ev.group(1)), "heat": int(ev.group(2)),
         "eventDescription": joined[at - 1].strip() if at else "",
         "startTime": re.sub(r"\s*\(Manual Start\)\s*$", "", start), "manualStart": "(Manual Start)" in start,
         "lanes": {}}

    def lane(n):
        return r["lanes"].setdefault(n, {"lane": n, "place": None, "time": "", "splits": [], "offTime": "",
                                         "buttonOverride": False, "buttonA": "", "buttonB": "", "buttonC": "", "backup": "", "pbDiff": "",
                                         "pbFlagged": False, "reaction": ""})

    # By Lane table: the left half under "Lane Place Time"; By Place, on the right, repeats it.
    head = next(i for i, t in enumerate(joined) if "Lane Place" in t)
    grid = next(i for i in range(head + 1, len(joined)) if len(re.findall(r"\bLane \d+\b", joined[i])) >= 2)
    hw = lines[head][1]
    by_place = next(w[0] for w in hw if w[2] == "Place" and w[0] > hw[0][1] + 40)
    cols = {w[2]: mid(w) for w in hw if w[0] < by_place}
    for _, words in lines[head + 1:grid]:
        cells = {}
        for w in words:
            if w[1] < by_place - 5:
                cells[nearest(w, cols)] = w[2]
        if cells.get("Lane", "").isdigit():
            ln = lane(int(cells["Lane"]))
            ln["place"] = int(cells["Place"]) if cells.get("Place", "").isdigit() else None
            ln["time"] = cells.get("Time", "")

    # The lane grid: "Lane 1 ... Lane 10", split rows, then the labelled rows.
    gw = lines[grid][1]
    lane_cols = {int(gw[i + 1][2]): (gw[i][0] + gw[i + 1][1]) / 2 for i in range(len(gw) - 1)
                 if gw[i][2] == "Lane" and gw[i + 1][2].isdigit()}
    first = min(w[0] for w in gw)
    row = 0
    for _, words in lines[grid + 1:]:
        label = text([w for w in words if w[1] < first - 2 and not TIME.match(w[2].strip("()"))])
        values = [w for w in words if not (w[1] < first - 2 and not TIME.match(w[2].strip("()")))]
        if SPLIT_LABEL.match(label):
            label = ""
        if label.startswith("Gen7"):
            break
        if not label and any(TIME.match(w[2]) for w in values):
            row += 1
        for w in values:
            v = w[2]
            n = nearest(w, lane_cols)
            if label in LABELS:
                key = LABELS[label]
                if key == "pbDiff":
                    lane(n)["pbFlagged"] = v.startswith("*")
                    v = v.lstrip("*")
                lane(n)[key] = v
                if key == "offTime":
                    lane(n)["buttonOverride"] = underlined((w[0], w[1], None, w[3]), rules)
            elif not label and v.startswith("(") and lane(n)["splits"]:
                lane(n)["splits"][-1]["split"] = v.strip("()")
            elif not label and TIME.match(v):
                lane(n)["splits"].append({"row": row, "time": v, "split": ""})
    blank = lane(0)
    del r["lanes"][0]
    r["lanes"] = [r["lanes"][k] for k in sorted(r["lanes"]) if {**r["lanes"][k], "lane": 0} != blank]
    return r


def races(pdf):
    out = []
    for no, (lines, rules) in enumerate(zip(pages(pdf), underlines(pdf)), start=1):
        if lines and (r := race(lines, no, rules)):
            out.append(r)
    return out


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        sys.exit(__doc__)
    found = races(args[0])
    if "--event" in args:
        found = [r for r in found if r["eventNumber"] == int(args[args.index("--event") + 1])]
    if "--csv" not in args:
        print(json.dumps(found, indent=1))
        return
    head = ["race", "page", "eventNumber", "heat", "eventDescription", "startTime", "manualStart", "lane", "place",
            "time", "splits", "offTime", "buttonOverride", "buttonA", "buttonB", "buttonC", "backup", "pbDiff", "pbFlagged", "reaction"]
    w = csv.writer(sys.stdout)
    w.writerow(head)
    for r in found:
        for ln in r["lanes"]:
            out = {**r, **ln, "splits": "; ".join(f"{s['row']}: {s['time']}" + (f" ({s['split']})" if s["split"] else "")
                                                  for s in ln["splits"])}
            w.writerow([out[k] for k in head])


if __name__ == "__main__":
    main()
