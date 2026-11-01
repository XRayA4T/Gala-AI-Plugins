---
name: gen7-report
description: Read a Colorado Gen7 timing system session report (the PDF Gen7 prints, one race per page with Event / Heat / Race #, start time, By Lane and By Place results, splits, Off. Time, Button A/B/C, Backup, P:B Diff and Start Reac) into JSON or CSV with no OCR, since the PDF has a text layer. Use when asked to parse, extract, list or load a Gen7 (or Colorado timing) session report or race report, to get the official pad times, backup button times, splits or reaction times per race and lane, or to match race numbers to events and heats.
---

# Gen7 session report

Colorado Gen7 prints a session report with one race per page:

- a heading with the meet and session (`CGA Summer 2 (10/31/2026 - 10/30/2026)` … `Session: 1, Saturday`)
- the event title (`Men's 200 Meter Indiv. Medley Finals`), then `Event: 7  Heat: 2  Race # 44`
- the start time, with `(Manual Start)` when the start was not from the starter
- the results **By Lane** (lane, place, time) and **By Place**
- a grid, one column per lane: the split rows (cumulative times, with each split in brackets under it), then
  `Off. Time` (the official time; **underlined when a push button time overrode the touch pad**), `Button A`,
  `Button B`, `Button C`, `Backup`, `P:B Diff` (pads against backup, marked `*` by Gen7 when out of tolerance) and
  `Start Reac:`

The PDF is generated, not scanned, so **do not read it by eye or OCR it**: run the bundled script, which reads the
text layer and puts each value in its lane by its position on the page. The underlines are drawn lines, not text, so
it also renders the PDF to SVG (poppler's `pdftocairo`) to find them.

## Use

Needs `python3` and poppler's `pdftotext` and `pdftocairo` (`apt install poppler-utils`, `brew install poppler`);
check with `which pdftotext pdftocairo python3` and tell the user what to install if any is missing. `$SKILL` is
this skill's base directory (the folder this SKILL.md is in).

```
python3 -I $SKILL/scripts/gen7_report.py "<report>.pdf"               # JSON, every race
python3 -I $SKILL/scripts/gen7_report.py "<report>.pdf" --event 7     # one event's races
python3 -I $SKILL/scripts/gen7_report.py "<report>.pdf" --csv         # one row per lane, for a spreadsheet
```

Write the output where the user asks (e.g. `> data/gen7/session1.json`); with no instruction, write it next to the
report with the same name and `.json` / `.csv`, and say where it went.

## Output

A list of races in report order:

```json
{
  "race": 44, "page": 44,
  "meet": "CGA Summer 2 (10/31/2026 - 10/30/2026)", "session": "1, Saturday",
  "eventNumber": 7, "heat": 2, "eventDescription": "Men's 200 Meter Indiv. Medley Finals",
  "startTime": "Saturday, 31 October 2026 10:48:50", "manualStart": false,
  "lanes": [
    {"lane": 3, "place": 6, "time": "3:28.23",
     "splits": [{"time": "1:40.74", "split": ""}, {"time": "3:28.23", "split": "1:47.49"}],
     "offTime": "3:28.23", "buttonOverride": false, "buttonA": "3:24.36", "buttonB": "", "buttonC": "",
     "backup": "3:24.36", "pbDiff": "3.87", "pbFlagged": true, "reaction": ""}
  ]
}
```

- Only lanes with something recorded are listed. Times are exactly as printed; `""` when blank; `place` is `null`
  when none is printed.
- `buttonOverride` is true when the Off. Time is underlined: the official time came from the push buttons, overriding
  the touch pad (usually a missed or soft touch; the lane then has no final pad split, and P:B Diff is 0.00).
- `splits` are the lane's split rows top to bottom; `split` is the bracketed value under a cumulative time, `""`
  when none is printed.
- A heat started twice (a false start, a recall) has two races with the same event and heat; events swum together
  as one race appear under one event only. Don't merge or drop races: report them as they are.

## Report

Tell the user how many races and lanes were read and where the output went, then point out, briefly:

- heats with more than one race (and which race numbers), and any race number missing from the sequence
- manual starts
- lanes with `buttonOverride` (how many, and per race), lanes with `pbFlagged`, and a lane with a place but no time
  (or the reverse)
- a lane whose Off. Time matches neither its final pad split nor its buttons, without an underline: it may have been
  typed in by hand
- any page the script skipped (the count of races should match the report's page count; `pdfinfo` gives it)

If the script fails or a page comes out wrong, the report layout may differ from the one it was written for: show
the user the page's `pdftotext -layout` text and the script's output for it, rather than reading the values by eye.
