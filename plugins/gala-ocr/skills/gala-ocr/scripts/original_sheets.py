#!/usr/bin/env python3
"""Print the lane sheets exactly as Meet Manager printed them, from the original (digital) lane-sheet PDF.

Usage: original_sheets.py ORIGINAL.pdf [EVENT [LANE]]

Prints JSON: a list of sheets {page, meetName, meetDate, eventNumber, eventDescription, lane, rows}, each row
{heat, swimmerName, age, classification, team, seedTime} with "" where nothing is printed. Field values follow
galaaudit.ocr.OriginalLaneSheets, so they can be copied straight into a lane-sheet cache file.
Needs pdftotext (poppler-utils).
"""
import json
import re
import subprocess
import sys

MEET = re.compile(r"^(.*?) - (\d{4}/\d{2}/\d{2})$")
EVENT = re.compile(r"^Event (\d+) (.*?)(?:\s{2,}Soft Touch \?)?$")
ROW = re.compile(r"^Lane (\d+)\s+Heat (\d+)\s*(.*)$")
# "Doe, John 17", or with a para sport class "Roe, Sam M SB6 21"
NAME_AGE = re.compile(r"^(.*?)\s+(?:(S[BM]?\d{1,2})\s+)?(\d{1,3})$")
TEAM = re.compile(r"^[A-Z0-9]{2,6}-[A-Z]{2}$")
SEED = re.compile(r"^(NT|\d{1,2}:\d{2},\d{2}|\d{1,2},\d{2})$")


def page_texts(pdf):
    text = subprocess.run(["pdftotext", "-layout", pdf, "-"], check=True, capture_output=True, text=True).stdout
    return text.split("\f")


def row(heat, rest):
    out = {"heat": heat, "swimmerName": "", "age": "", "classification": "", "team": "", "seedTime": ""}
    cells = [c for c in re.split(r"\s{2,}", rest.strip()) if c and not c.startswith("_")]
    if not cells:
        return out
    m = NAME_AGE.match(cells[0])
    if m:
        out["swimmerName"], out["classification"], out["age"] = m.group(1).strip(), m.group(2) or "", m.group(3)
    else:
        out["swimmerName"] = cells[0]
    for c in cells[1:]:
        if not out["team"] and TEAM.match(c):
            out["team"] = c
        elif not out["seedTime"] and SEED.match(c):
            out["seedTime"] = c
    return out


def sheets(pdf):
    result = []
    for page_no, text in enumerate(page_texts(pdf), start=1):
        meet_name = meet_date = ""
        current = None
        for line in (l.strip() for l in text.splitlines()):
            if not line:
                continue
            if m := MEET.match(line):
                meet_name, meet_date = m.group(1), m.group(2)
            elif m := EVENT.match(line):
                current = {"page": page_no, "meetName": meet_name, "meetDate": meet_date,
                           "eventNumber": int(m.group(1)), "eventDescription": m.group(2).strip(), "lane": 0,
                           "rows": []}
                result.append(current)
            elif current is not None and (m := ROW.match(line)):
                current["lane"] = int(m.group(1))
                current["rows"].append(row(int(m.group(2)), m.group(3)))
    return result


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    found = sheets(sys.argv[1])
    if len(sys.argv) > 2:
        found = [s for s in found if s["eventNumber"] == int(sys.argv[2])]
    if len(sys.argv) > 3:
        found = [s for s in found if s["lane"] == int(sys.argv[3])]
    json.dump(found, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
