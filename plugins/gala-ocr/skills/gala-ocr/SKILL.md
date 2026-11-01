---
name: gala-ocr
description: Transcribe scanned swimming-gala paperwork into structured JSON - Hy-Tek Meet Manager lane sheets (printed entries plus handwritten timekeeper times, N/S, DQ, soft touch, sign-off), referees' handwritten disqualification (DQ) slips, and the ETD programme (the meet programme with the timing system's race data record number written by each heat). Use when asked to OCR, read, transcribe or extract lane sheets, timekeeper / hand times, DQ slips, or race numbers from an ETD programme from scanned PDFs, to fill in or redo a transcription cache (e.g. data/ocr in a GalaAudit project), or to prepare gala results for an audit without calling the Claude API from code.
---

# Gala OCR: lane sheets, DQ slips and the ETD programme

You read the scans yourself and write one JSON file per lane sheet, per DQ slip and per ETD programme page. The
lane sheet and DQ slip formats (below) are the transcription cache of the GalaAudit Java project
(`LaneSheetOcr.OcrPage` and `DqSlip`): when every page of a scan has a file there, its audit loads them and makes no
Claude API calls. Any other tool can read the files too.

The output feeds an audit of official results. **Accuracy beats completeness: never guess a digit or word you
cannot see.** Mark it low confidence, or leave `normalized` empty, and say so in your summary.

## Setup

**Helpers.** `scripts/` in this skill's base directory (the folder this SKILL.md is in) holds Python 3 scripts
(standard library only). Call them by absolute path as `python3 -I <skill dir>/scripts/<script>.py`; below,
`$SKILL` means that directory.

**Tools needed:** `python3`, and poppler's `pdftoppm`, `pdftotext` and `pdfinfo` (`apt install poppler-utils`,
`brew install poppler`). Check with `which pdftoppm pdftotext python3`; if they are missing, tell the user what to
install rather than working around it.

**Paths.** Use what the user says; otherwise detect the GalaAudit layout and confirm it in one line:

| What | GalaAudit default |
|---|---|
| Scanned lane sheets | `pdf/scanned/Lane Sheets.pdf` (any scan whose pages are lane sheets) |
| Scanned DQ slips | `pdf/scanned/DQs.pdf` |
| Original print of the lane sheets (the PDF Meet Manager printed; optional but much more accurate) | `pdf/original/*.pdf` |
| Scanned ETD programme (the meet programme with race numbers written on it) | `pdf/scanned/ETD.pdf` |
| Timing system race report (optional; checks the race numbers) | `pdf/original/*Session*.pdf` |
| Output folder (the cache) | `data/ocr/` |

If none of these exist and the user has not said, ask for the scan(s) and an output folder. Render images into
your scratchpad or a temp folder, never into the user's project.

**File names** (`<scan>` is the PDF's name without `.pdf`; the page is the 1-based page of the **scan**):

- Lane sheet: `<scan>-event%02d-lane%d-p%03d.json`, e.g. `Lane Sheets-event01-lane4-p004.json`
- DQ slip: `<scan>-event%02d-heat%d-lane%d-p%03d.json`, named for the slip's **front** page, e.g. `DQs-event08-heat1-lane2-p008.json`
- ETD programme page: `<scan>-p%03d.json`, e.g. `ETD-p001.json`

A page is done when any file of that scan in the output folder ends in its `-pNNN.json` (a DQ back page is done when
a slip lists it as `backPage`). **Start by listing the output folder and skip finished pages**, unless the user asks
to redo some: then delete just those files first. Write each file as soon as its page is read, so an interrupted
run resumes cleanly. `pdfinfo <pdf> | grep Pages` gives the page count.

## Lane sheets

Each scanned page is one lane of one event: a header (meet name and date, "Event 14 Men 50 LC Meter Backstroke
Finals"), then one row per heat: `Lane N  Heat M`, swimmer `Last, First M age` (para swimmers have a sport class
such as S7, SB6 or S15 before the age), team `CODE-LSC`, seed time (`NT`, or a decimal comma: `1:01,68`, `33,48`),
blank timer columns and a Soft Touch box. Handwritten: up to three times, a tick by the name when the swimmer
reported, `N/S` or `DQ`, "No Swimmer" on empty heats, a Soft Touch tick, and a signature at the bottom.

For each page not yet done:

1. **Look at the page.** `pdftoppm -r 150 -png -f P -l P "<scan>.pdf" <tmp>/ls` then read the PNG. Note the event
   number and lane from the header.
2. **Take the printed fields from the original print when there is one.**
   `python3 -I $SKILL/scripts/original_sheets.py <original>.pdf EVENT LANE` prints that sheet's `meetName`,
   `meetDate`, `eventDescription` and each row's `swimmerName`, `age`, `classification`, `team`, `seedTime` in the
   exact formats below. Copy them verbatim (row count and heats too). With no original, or none matching, transcribe
   the printed text from the scan in the same formats.
3. **Read the handwriting, zooming in on anything unclear.** At 300 dpi a landscape A5 sheet is about 2480 x 1700
   px, and the timer columns and Soft Touch box are in its right ~45%. Crop with pdftoppm, e.g.
   `pdftoppm -r 300 -png -f P -l P -x 1400 -y 350 -W 1080 -H 700 "<scan>.pdf" <tmp>/zoom` (shift `-y`, shrink `-H`
   to isolate a row). Zoom before giving any digit less than HIGH confidence.
4. **Write the file** (shape below), then validate it (last section).

### Lane sheet rules

- **Times.** `written` keeps the timekeeper's exact characters, separators included (`"5,42,57"`, `"39:34"`).
  `normalized` is `SS.hh` or `M:SS.hh`. Timekeepers use a colon, comma, full stop or space for the decimal point;
  use the event distance and the seed time to tell minutes from hundredths: `"39:34"` on a 50 m → `"39.34"`;
  `"5,42,57"` on a 400 m → `"5:42.57"`; `"1.09.56"` → `"1:09.56"`; `"47 29"` → `"47.29"`. A digit you cannot
  read: `normalized` = `""` and confidence `LOW`. Do not guess.
- `column` is the timer column, 1-3 left to right, as positioned on the sheet (a lone time in the third column is
  column 3). Leave out empty columns; never emit a time with an empty `written`.
- **Corrections.** Crossed out and rewritten → only the final value, with `corrected: true`.
- **Confidence:** `HIGH` every digit is unambiguous; `MEDIUM` readable, but one digit could be another
  (4/9, 1/7, 3/8, 5/6); `LOW` you are guessing at a digit.
- **Status** (exactly one of these four):

  | Status | When |
  |---|---|
  | `SWAM` | A swimmer is printed (or written in) and there is no N/S or DQ. Also when no times are written; readers treat that as "not recorded" |
  | `NO_SWIMMER` | Nothing printed for the heat and no name written in ("No Swimmer" handwritten, or nothing at all). Never for a row with a printed team |
  | `NO_SHOW` | `N/S` (or "no show", "did not swim") written on a printed swimmer's row |
  | `DISQUALIFIED` | `DQ` written on the row; still record any times |

- **Written-in names.** If the printed name is crossed out and another written in, or a name is written on an empty
  row, set `swimmerName` to the written name (keep the printed `age`, `team`, `seedTime`) and start `notes` with
  `printed name <printed name> crossed out` or `name written in`.
- **Scan and original disagree.** The original print may have been made later (after scratchings), so a row can
  be empty there but have a swimmer printed on the scanned paper. The handwriting belongs to the paper: take that
  row's printed fields from the scan, give it the status its handwriting shows (usually `NO_SHOW`), and add
  `printed on the scan but not in the original print` to `notes`. Same for any other printed field that differs.
- `checkedIn`: a handwritten tick by the swimmer's name. `softTouch`: the Soft Touch box is ticked.
- `notes`: any other handwriting on the row that is not a time, verbatim (a written DQ code may be matched against
  the meet's codes), separated with `; `. Empty string when none.
- `signed`: a signature or initials at the bottom of the sheet.
- Every field is present and non-null; use `""` for absent text. No other fields.

Excerpt from the worked example in `../../examples` (names are made up; heats 4 and 5 only, but a real file lists
every heat from 1, in order):

```json
{
  "meetName": "Example Gala 1 - 2026",
  "meetDate": "2026/10/10",
  "eventNumber": 14,
  "eventDescription": "Men 50 LC Meter Backstroke Finals",
  "lane": 5,
  "rows": [
    {
      "heat": 4, "status": "SWAM", "swimmerName": "Williams, Jordan", "age": "12", "classification": "",
      "team": "EELS-XX", "seedTime": "42,78",
      "handTimes": [
        {"column": 1, "written": "39:34", "normalized": "39.34", "corrected": false, "confidence": "HIGH"},
        {"column": 2, "written": "39:22", "normalized": "39.22", "corrected": true, "confidence": "MEDIUM"},
        {"column": 3, "written": "39.44", "normalized": "39.44", "corrected": false, "confidence": "HIGH"}
      ],
      "checkedIn": true, "softTouch": false, "notes": ""
    },
    {
      "heat": 5, "status": "NO_SHOW", "swimmerName": "Davies, Kyle", "age": "15", "classification": "",
      "team": "TUNA-XX", "seedTime": "40,09", "handTimes": [], "checkedIn": false, "softTouch": false,
      "notes": "N/S written in timer column 1"
    }
  ],
  "signed": true
}
```

## DQ slips

The scan holds each slip's front (a printed "Disqualification Report" form: date, event no., heat / final no.,
lane no., infraction, official's name and signature, referee's name and signature, time of announcement and
initial), followed by its back when something is written there. Blank pages may be in between.

1. **Group the pages.** Render every page small (`pdftoppm -r 50 -png "<scan>.pdf" <tmp>/dq`) and look at them in
   order: a page with the printed title is a front; a page without it but with writing is the back of the front
   before it; a blank page (or show-through only) belongs to no slip and gets no file.
2. **Read each slip** at 150 dpi (`-r 150 -f P -l P`), front and back, zooming at 300 dpi on unclear digits.
3. **Write one file per slip**, named for the front page, event, heat and lane.

### DQ slip rules

- `sourceFile` is the scan's file name (`"DQs.pdf"`); `page` the front's page; `backPage` the back's page, or
  `null` when the back is blank. `back` is everything written on the back (`""` when none).
- `date` exactly as written; officials use several formats (`"2026-10-10"`, `"10/10/2026"`).
- `eventNumber`, `heat`, `lane` as integers. If one is unreadable, say so in your summary rather than guess.
- `infraction`: the official's wording, kept word for word, on one line; block capitals become sentence case
  ("TURN NOT INITIATED AT COMPLETION OF THE ARM PULL" → "Turn not initiated at completion of the arm pull ...").
- `official` / `referee`: the printed name as written (`"A. Official"`), `""` if none. `officialSigned` /
  `refereeSigned`: there is a signature in the signature space.
- `announcementTime` as written (`"12:07"`), `""` if blank; `initialled`: the initial space is filled in.

Example (names are made up):

```json
{
  "sourceFile": "DQs.pdf",
  "page": 8,
  "backPage": 9,
  "date": "2026-10-10",
  "eventNumber": 8,
  "heat": 1,
  "lane": 2,
  "infraction": "Turn not initiated at completion of the arm pull after leaving position on the back 150m turn",
  "back": "2nd arm pull",
  "official": "A. Official",
  "referee": "B. Referee",
  "officialSigned": true,
  "refereeSigned": true,
  "announcementTime": "12:07",
  "initialled": true
}
```

## ETD programme

The ETD programme is the Meet Manager meet programme (`#3 Men 100 LC Meter Backstroke`, then `Heat 1 of 9 Finals
Starts at 09:08 AM` and its lanes, two or three columns to a page) on which the timing operator has written, circled
or not, the **race data record number** beside each heat: the number the timing system (e.g. Colorado Gen7) gave
the race. It links each programme heat to its record in the timing system. The numbers run **in sequence** down the
programme, one per race, with gaps only where the timing system has a race with no finishes (a false or manual
start whose re-start got the next number). Beyond that: a heat started twice (a false start, a re-swim) gets two numbers, or only the second is written;
events swum together as one race share a number; and a heat not swum has none, or a crossed-out one.

Check the scan is the one the user named (`pdfinfo` for the page count and size). If it is missing, ask; don't pick
another file that looks likely. For each page not yet done:

1. **Look at the page.** `pdftoppm -r 110 -png -f P -l P "<scan>.pdf" <tmp>/etd` and read the PNG to find the
   columns and heat headers.
2. **Read every heat header and every number, column by column at 200 dpi.** An A4 page at 200 dpi is about
   1650 x 2340 px; crop one column at a time with some overlap, since numbers are often written across the age and
   team columns or in the gutter: e.g. `pdftoppm -r 200 -png -f P -l P -x 0 -y 200 -W 600 -H 1100`, then step `-x`
   by about 540 for the next column (fewer, wider steps for two columns) and `-y` by about 1000 for the lower half. Zoom to 300 dpi on any number you are not sure
   of.
3. **If there is a Gen7 race report** (the session report the timing system prints), read it with the
   gen7-report skill's script, `python3 -I $SKILL/../gen7-report/scripts/gen7_report.py <report>.pdf` (each race's
   number, event, heat, start time and lanes). Use it, with the sequence, to check each number and to tell which heat
   a number beside a column break belongs to. Races with no finishes (a manual or false start, e.g. race 1 before
   race 2 of the same heat) are the gaps in the sequence and usually have no number written: note them in your
   summary, don't add them to `written`.
4. **Use the sequence as a hint for an ambiguous digit.** When a digit could be one of two (1/7, 3/8, 4/9, 6/0) and
   only one reading fits between the numbers before and after it, and is the Gen7 race for that event and heat, take
   that reading, keep `confidence` at `MEDIUM`, and add `read with the sequence` to `notes`. Never use the sequence
   or the report to supply a number that is not written, or to read a digit you cannot see at all (that stays
   `LOW`).
5. **Write the file** (shape below), then validate it. When every page is done and there is a race report, run
   `python3 -I $SKILL/scripts/check_etd.py <output folder> <report>.pdf`. It lists numbers out of sequence, gaps
   that are not empty Gen7 races, Gen7 races with finishes that no heat has, and numbers whose Gen7 race is another
   heat. Look again at each one on the page; fix only what you misread, and report the rest.

### ETD programme rules

- `heats` lists **every heat whose header is printed on this page**, in printed order (down each column, columns
  left to right), with or without a number. A heat whose lanes run on to the next column or page is still listed
  once, on the page of its header.
- A number belongs to the heat whose lanes it sits beside. One written in the gutter between columns, or beside a
  heat header, belongs to the heat it is level with; if it is level with heats in both columns, use the race report
  and the sequence of numbers either side to decide, and say so in `notes`.
- `written` keeps exactly what is written (`"7"`, `"11"`), `""` when nothing is. `raceNumber` is that number as an
  integer, or `null` when nothing is written, a digit cannot be read (then `confidence` is `LOW`), or every number
  written is crossed out with none rewritten (a heat not swum: `corrected: true`, confidence as legible, and the
  words beside it, such as `"NO START"`, in `notes`).
- Stray marks in another pen or style (a lone uncircled digit by a header when the rest are circled, a tick) are
  not race numbers: put them in `notes`.
- **Combined events** (two events swum as one race, e.g. a men's and a women's 200 fly in one heat) **have the same
  race number**. List each event's heat with that number, and say in each one's `notes` which heat it was swum with
  (`"combined with event 2 heat 1"`). When the number is written once for both (beside one, or with a bracket or
  arrow joining them), give it to both, and to the one it is not written beside add `"number written at event 1
  heat 1"` to `notes`. The race report shows a combined race under one event only, and the other event may not
  appear in it at all: match the race's lanes with a time against the programme's lanes to see which heats were in
  it.
- **Two or more numbers on one heat** (a re-swim): `written` gives them all, top to bottom, separated by `, `;
  `raceNumber` is the one not crossed out, or the last one when none is; `notes` says what you saw
  (`"1 crossed out, 2 written beside it"`).
- **Corrections:** crossed out or overwritten and rewritten → `corrected: true`, and the final number.
- **Confidence:** `HIGH` every digit is unambiguous; `MEDIUM` readable, but one digit could be another (1/7, 4/9,
  6/0, 3/8, a circle hiding part of a digit); `LOW` you are guessing, or there is a mark you cannot read. Writing
  over the printed text does not lower the confidence by itself; only a digit it makes ambiguous does.
- `notes`: anything else written by the heat that bears on its race number, verbatim (`"no race"`, a time, an
  arrow to another heat), and any disagreement with the race report (`"race report has race 4 for event 3 heat
  2"`). Empty string when none.
- Every field is present; `raceNumber` is the only one that may be `null`. No other fields.

```json
{
  "sourceFile": "ETD.pdf",
  "page": 1,
  "meetName": "Example Gala 1 - 2026",
  "heats": [
    {"eventNumber": 1, "heat": 1, "written": "1, 2", "raceNumber": 2, "corrected": true, "confidence": "HIGH",
     "notes": "1 crossed out, 2 written beside it"},
    {"eventNumber": 2, "heat": 1, "written": "2", "raceNumber": 2, "corrected": false, "confidence": "HIGH",
     "notes": "combined with event 1 heat 1"},
    {"eventNumber": 3, "heat": 1, "written": "3", "raceNumber": 3, "corrected": false, "confidence": "HIGH",
     "notes": ""},
    {"eventNumber": 3, "heat": 2, "written": "", "raceNumber": null, "corrected": false, "confidence": "HIGH",
     "notes": ""}
  ]
}
```

`meetName` is the meet name as printed in the page heading (`"CGA Summer 2 - 2026"`).

## Validate and report

Run the validator on what you wrote (or the whole output folder) and fix every problem it reports. Readers such as
GalaAudit reject unknown or missing fields, and a wrong file name makes a page look unread:

```
python3 -I $SKILL/scripts/validate_cache.py <output folder>
```

Then tell the user how many lane-sheet pages, DQ slips and ETD pages you wrote (and how many you skipped as already
done), and list for checking against the paper: every `LOW` or empty-`normalized` time, every row with `corrected`
times or a written-in name, `N/S` and `DQ` rows, unsigned sheets, any slip field you could not read, and every ETD
heat with no number, a `LOW` or `MEDIUM` number, more than one number, or a number that disagrees with the race
report or with the numbers either side. In a GalaAudit project,
mention that the audit can now be run as usual (`AuditMain`).

With many pages (a gala's lane-sheet scan can run past 100 pages), work in batches of about 8 pages, writing files
as you go, and give a short progress line between batches.

Scans hold personal data about swimmers, many of them children: keep the output in the user's project, and do not
paste names or results anywhere else.
