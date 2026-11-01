#!/usr/bin/env python3
"""Check transcription files have exactly the gala-ocr shape (the GalaAudit Java project's OCR cache).

Usage: validate_cache.py FILE_OR_DIR...   (a directory means every *.json in it)

Lane-sheet files ("<scan>-eventEE-laneL-pPPP.json") must match GalaAudit's LaneSheetOcr.OcrPage, and DQ slip files
("<scan>-eventEE-heatH-laneL-pPPP.json") its DqSlip. ETD programme pages ("<scan>-pPPP.json") list each heat's race
data record number. Unknown fields fail too, as GalaAudit's lane-sheet reader
rejects them. Also checks the file name agrees with the content. Exits 1 when anything is wrong.
"""
import json
import pathlib
import re
import sys

LANE_NAME = re.compile(r"^(?P<scan>.+)-event(?P<event>\d{2,})-lane(?P<lane>\d+)-p(?P<page>\d{3,})\.json$")
ETD_NAME = re.compile(r"^(?P<scan>.+)-p(?P<page>\d{3,})\.json$")
SLIP_NAME = re.compile(r"^(?P<scan>.+)-event(?P<event>\d{2,})-heat(?P<heat>\d+)-lane(?P<lane>\d+)-p(?P<page>\d{3,})\.json$")

STATUS = {"SWAM", "NO_SWIMMER", "NO_SHOW", "DISQUALIFIED"}
CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
TIME = re.compile(r"^(\d{1,2}:)?\d{1,2}\.\d{2}$")
SEED = re.compile(r"^(|NT|\d{1,2}:\d{2},\d{2}|\d{1,2},\d{2})$")

PAGE = {"meetName": str, "meetDate": str, "eventNumber": int, "eventDescription": str, "lane": int, "rows": list,
        "signed": bool}
ROW = {"heat": int, "status": str, "swimmerName": str, "age": str, "classification": str, "team": str,
       "seedTime": str, "handTimes": list, "checkedIn": bool, "softTouch": bool, "notes": str}
HAND = {"column": int, "written": str, "normalized": str, "corrected": bool, "confidence": str}
SLIP = {"sourceFile": str, "page": int, "backPage": (int, type(None)), "date": str, "eventNumber": int, "heat": int,
        "lane": int, "infraction": str, "back": str, "official": str, "referee": str, "officialSigned": bool,
        "refereeSigned": bool, "announcementTime": str, "initialled": bool}
ETD = {"sourceFile": str, "page": int, "meetName": str, "heats": list}
ETD_HEAT = {"eventNumber": int, "heat": int, "written": str, "raceNumber": (int, type(None)), "corrected": bool,
            "confidence": str, "notes": str}


def shape(obj, fields, where, errors):
    """Checks obj's fields; true when obj itself has none of the problems (earlier ones are not counted)."""
    before = len(errors)
    if not isinstance(obj, dict):
        errors.append(f"{where}: expected an object")
        return False
    for k in obj.keys() - fields.keys():
        errors.append(f"{where}: unknown field {k!r}")
    for k, t in fields.items():
        if k not in obj:
            errors.append(f"{where}: missing field {k!r}")
        elif isinstance(obj[k], bool) and t is int or not isinstance(obj[k], t):
            errors.append(f"{where}: {k!r} has the wrong type ({type(obj[k]).__name__})")
    return len(errors) == before


def check_lane_sheet(path, m, data, errors):
    # A page-level problem is reported but does not stop the row checks, unless there are no rows to check
    shape(data, PAGE, path.name, errors)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return
    if data.get("eventNumber") != int(m["event"]) or data.get("lane") != int(m["lane"]):
        errors.append(f"{path.name}: name says event {m['event']} lane {m['lane']}, content says "
                      f"event {data.get('eventNumber')} lane {data.get('lane')}")
    heats = []
    for i, r in enumerate(data["rows"]):
        where = f"{path.name} row {i + 1}"
        heats.append(r.get("heat") if isinstance(r, dict) else None)
        if not shape(r, ROW, where, errors):
            continue
        if r["status"] not in STATUS:
            errors.append(f"{where}: status {r['status']!r} is not one of {sorted(STATUS)}")
        if r["status"] == "NO_SWIMMER" and r["team"]:
            errors.append(f"{where}: NO_SWIMMER but a team is printed; use NO_SHOW (no times) or SWAM")
        if not SEED.match(r["seedTime"]):
            errors.append(f"{where}: seedTime {r['seedTime']!r} is not as printed (NT, 1:01,68 or 33,48)")
        cols = []
        for j, t in enumerate(r["handTimes"]):
            tw = f"{where} time {j + 1}"
            if not shape(t, HAND, tw, errors):
                continue
            cols.append(t["column"])
            if t["confidence"] not in CONFIDENCE:
                errors.append(f"{tw}: confidence {t['confidence']!r} is not one of {sorted(CONFIDENCE)}")
            if t["normalized"] and not TIME.match(t["normalized"]):
                errors.append(f"{tw}: normalized {t['normalized']!r} is not SS.hh or M:SS.hh")
            if not t["written"].strip():
                errors.append(f"{tw}: written is empty; leave the time out instead")
        if cols != sorted(set(cols)) or any(c < 1 or c > 3 for c in cols):
            errors.append(f"{where}: timer columns {cols} must be distinct, ascending, 1 to 3")
    if heats != list(range(1, len(heats) + 1)):
        errors.append(f"{path.name}: heats {heats} must be 1..N in order")


def check_slip(path, m, data, errors):
    if not shape(data, SLIP, path.name, errors):
        return
    expect = (int(m["event"]), int(m["heat"]), int(m["lane"]), int(m["page"]))
    actual = (data["eventNumber"], data["heat"], data["lane"], data["page"])
    if expect != actual:
        errors.append(f"{path.name}: name says event/heat/lane/page {expect}, content says {actual}")
    if data["sourceFile"] != m["scan"] + ".pdf":
        errors.append(f"{path.name}: sourceFile {data['sourceFile']!r} should be {m['scan'] + '.pdf'!r}")
    if data["backPage"] is not None and data["backPage"] <= data["page"]:
        errors.append(f"{path.name}: backPage must come after the front page")
    if data["backPage"] is None and data["back"]:
        errors.append(f"{path.name}: back text given but backPage is null")


def check_etd(path, m, data, errors):
    shape(data, ETD, path.name, errors)
    if not isinstance(data, dict) or not isinstance(data.get("heats"), list):
        return
    if data.get("page") != int(m["page"]):
        errors.append(f"{path.name}: name says page {int(m['page'])}, content says {data.get('page')}")
    if data.get("sourceFile") != m["scan"] + ".pdf":
        errors.append(f"{path.name}: sourceFile {data.get('sourceFile')!r} should be {m['scan'] + '.pdf'!r}")
    seen = set()
    for i, h in enumerate(data["heats"]):
        where = f"{path.name} heat {i + 1}"
        if not shape(h, ETD_HEAT, where, errors):
            continue
        key = (h["eventNumber"], h["heat"])
        if key in seen:
            errors.append(f"{where}: event {key[0]} heat {key[1]} is listed twice")
        seen.add(key)
        if h["confidence"] not in CONFIDENCE:
            errors.append(f"{where}: confidence {h['confidence']!r} is not one of {sorted(CONFIDENCE)}")
        if not h["written"].strip() and h["raceNumber"] is not None:
            errors.append(f"{where}: raceNumber given but nothing written")
        if h["raceNumber"] is not None and str(h["raceNumber"]) not in re.findall(r"\d+", h["written"]):
            errors.append(f"{where}: raceNumber {h['raceNumber']} is not one of the numbers written ({h['written']!r})")
        if h["written"].strip() and h["raceNumber"] is None and h["confidence"] != "LOW" and not h["corrected"]:
            errors.append(f"{where}: a number is written but raceNumber is null; give it, mark it LOW, or mark it "
                          f"corrected when every number is crossed out")


def check(path):
    errors = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path.name}: {e}"]
    if m := SLIP_NAME.match(path.name):
        check_slip(path, m, data, errors)
    elif m := LANE_NAME.match(path.name):
        check_lane_sheet(path, m, data, errors)
    elif m := ETD_NAME.match(path.name):
        check_etd(path, m, data, errors)
    else:
        errors.append(f"{path.name}: name is none of <scan>-eventEE-laneL-pPPP.json, "
                      f"<scan>-eventEE-heatH-laneL-pPPP.json and <scan>-pPPP.json")
    return errors


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    files = []
    for arg in map(pathlib.Path, sys.argv[1:]):
        files += sorted(arg.glob("*.json")) if arg.is_dir() else [arg]
    errors = [e for f in files for e in check(f)]
    for e in errors:
        print(e)
    print(f"{len(files)} files checked, {len(errors)} problems")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
