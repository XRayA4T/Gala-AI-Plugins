---
name: gala-ocr
description: Transcribe scanned swimming-gala paperwork into structured JSON - Hy-Tek Meet Manager lane sheets (printed entries plus handwritten timekeeper times, N/S, DQ, soft touch, sign-off) and referees' handwritten disqualification (DQ) slips. Use when asked to OCR, read, transcribe or extract lane sheets, timekeeper / hand times, or DQ slips from scanned PDFs, to fill in or redo a transcription cache (e.g. data/ocr in a GalaAudit project), or to prepare gala results for an audit without calling the Claude API from code.
---

# Gala OCR: lane sheets and DQ slips

You read the scans yourself and write one JSON file per lane sheet and per DQ slip. The format (below) is the
transcription cache of the GalaAudit Java project (`LaneSheetOcr.OcrPage` and `DqSlip`): when every page of a scan
has a file there, its audit loads them and makes no Claude API calls. Any other tool can read the files too.

The output feeds an audit of official results. **Accuracy beats completeness: never guess a digit or word you
cannot see.** Mark it low confidence, or leave `normalized` empty, and say so in your summary.

## Setup

**Helpers.** `scripts/` in this skill's base directory (the folder this SKILL.md is in) holds two Python 3 scripts
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
| Output folder (the cache) | `data/ocr/` |

If none of these exist and the user has not said, ask for the scan(s) and an output folder. Render images into
your scratchpad or a temp folder, never into the user's project.

**File names** (`<scan>` is the PDF's name without `.pdf`; the page is the 1-based page of the **scan**):

- Lane sheet: `<scan>-event%02d-lane%d-p%03d.json`, e.g. `Lane Sheets-event01-lane4-p004.json`
- DQ slip: `<scan>-event%02d-heat%d-lane%d-p%03d.json`, named for the slip's **front** page, e.g. `DQs-event08-heat1-lane2-p008.json`

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
- `checkedIn`: a handwritten tick by the swimmer's name. `softTouch`: the Soft Touch box is ticked.
- `notes`: any other handwriting on the row that is not a time, verbatim (a written DQ code may be matched against
  the meet's codes), separated with `; `. Empty string when none.
- `signed`: a signature or initials at the bottom of the sheet.
- Every field is present and non-null; use `""` for absent text. No other fields.

Excerpt (names are made up; heats 4 and 5 only, but a real file lists every heat from 1, in order):

```json
{
  "meetName": "Example Gala 1 - 2026",
  "meetDate": "2026/10/10",
  "eventNumber": 14,
  "eventDescription": "Men 50 LC Meter Backstroke Finals",
  "lane": 5,
  "rows": [
    {
      "heat": 4, "status": "SWAM", "swimmerName": "Doe, John", "age": "12", "classification": "",
      "team": "SWIM-XX", "seedTime": "42,78",
      "handTimes": [
        {"column": 1, "written": "39:34", "normalized": "39.34", "corrected": false, "confidence": "HIGH"},
        {"column": 2, "written": "39:22", "normalized": "39.22", "corrected": true, "confidence": "MEDIUM"},
        {"column": 3, "written": "39.44", "normalized": "39.44", "corrected": false, "confidence": "HIGH"}
      ],
      "checkedIn": true, "softTouch": false, "notes": ""
    },
    {
      "heat": 5, "status": "NO_SHOW", "swimmerName": "Roe, Sam", "age": "15", "classification": "",
      "team": "AQUA-XX", "seedTime": "40,09", "handTimes": [], "checkedIn": false, "softTouch": false,
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

## Validate and report

Run the validator on what you wrote (or the whole output folder) and fix every problem it reports. Readers such as
GalaAudit reject unknown or missing fields, and a wrong file name makes a page look unread:

```
python3 -I $SKILL/scripts/validate_cache.py <output folder>
```

Then tell the user how many lane-sheet pages and DQ slips you wrote (and how many you skipped as already done), and
list for checking against the paper: every `LOW` or empty-`normalized` time, every row with `corrected` times or a
written-in name, `N/S` and `DQ` rows, unsigned sheets, and any slip field you could not read. In a GalaAudit project,
mention that the audit can now be run as usual (`AuditMain`).

With many pages (a gala's lane-sheet scan can run past 100 pages), work in batches of about 8 pages, writing files
as you go, and give a short progress line between batches.

Scans hold personal data about swimmers, many of them children: keep the output in the user's project, and do not
paste names or results anywhere else.
