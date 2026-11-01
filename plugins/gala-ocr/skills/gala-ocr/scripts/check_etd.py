#!/usr/bin/env python3
"""Check ETD programme race numbers against their sequence and the Gen7 session report.

Usage: check_etd.py ETD_DIR GEN7_REPORT.pdf

ETD_DIR holds the ETD page files (<scan>-pPPP.json). Race numbers run up in programme order, one per race, so:
- each number should be higher than the one before it (combined heats share one; a heat swum out of programme
  order breaks the run, and is listed so you can check it);
- every race number missing from the run (a gap) should be a Gen7 race with no finishes (a false or manual start),
  and every Gen7 race with finishes should be written somewhere;
- the Gen7 race with a heat's number should be that event and heat, or a heat combined with it.
Prints one line per problem and exits 1 if there are any. Needs the gen7-report skill next to this one.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "gen7-report" / "scripts"))
import gen7_report  # noqa: E402

PAGE = re.compile(r"^(?!.*-event\d).+-p(\d{3,})\.json$")  # not lane sheets or DQ slips


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    files = sorted(f for f in pathlib.Path(sys.argv[1]).glob("*.json") if PAGE.search(f.name))
    heats = [h for f in files for h in json.loads(f.read_text(encoding="utf-8"))["heats"]]
    races = {r["race"]: r for r in gen7_report.races(sys.argv[2])}
    problems = []

    numbered = [h for h in heats if h["raceNumber"] is not None]
    # A heat combined with one earlier in the programme repeats its number; it doesn't break the run.
    run = [h for i, h in enumerate(numbered) if h["raceNumber"] not in {g["raceNumber"] for g in numbered[:i]}]
    for prev, h in zip(run, run[1:]):
        if h["raceNumber"] < prev["raceNumber"]:
            problems.append(f"E{h['eventNumber']} H{h['heat']}: {h['raceNumber']} comes after "
                            f"{prev['raceNumber']} (E{prev['eventNumber']} H{prev['heat']}); out of order")

    written = {h["raceNumber"] for h in numbered}
    for n, r in sorted(races.items()):
        finished = any(ln["time"] or ln["offTime"] for ln in r["lanes"])
        if n not in written and finished:
            problems.append(f"race {n} (E{r['eventNumber']} H{r['heat']}) has finishes but no heat has its number")
        if n in written and not finished:
            problems.append(f"race {n} (E{r['eventNumber']} H{r['heat']}) has no finishes but is written on a heat")
    for n in sorted(written - races.keys()):
        problems.append(f"race {n} is written but is not in the Gen7 report")

    for h in numbered:
        r = races.get(h["raceNumber"])
        if r and (r["eventNumber"], r["heat"]) != (h["eventNumber"], h["heat"]):
            same = [g for g in numbered if g["raceNumber"] == h["raceNumber"] and g is not h]
            if not any((g["eventNumber"], g["heat"]) == (r["eventNumber"], r["heat"]) for g in same):
                problems.append(f"E{h['eventNumber']} H{h['heat']}: race {h['raceNumber']} is E{r['eventNumber']} "
                                f"H{r['heat']} in Gen7")
            elif "combined" not in h["notes"]:
                problems.append(f"E{h['eventNumber']} H{h['heat']}: shares race {h['raceNumber']} with "
                                f"E{r['eventNumber']} H{r['heat']} but notes don't say it was combined")

    for p in problems:
        print(p)
    empty = sorted(n for n, r in races.items() if not any(ln["time"] or ln["offTime"] for ln in r["lanes"]))
    print(f"{len(heats)} heats, {len(numbered)} numbered, {len(races)} Gen7 races ({len(empty)} with no finishes: "
          f"{', '.join(map(str, empty)) or 'none'}), {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
