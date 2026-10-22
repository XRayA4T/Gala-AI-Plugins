# gala-ocr

A Claude Code skill that transcribes scanned swimming-gala paperwork into structured JSON:

- **Lane sheets** printed by Hy-Tek Meet Manager, one lane of one event per sheet, filled in by hand: up to three
  timekeeper times per heat, check-in ticks, `N/S` and `DQ`, the Soft Touch box, and the timekeeper's signature.
- **DQ slips**: referees' handwritten disqualification reports (event, heat, lane, the infraction in the official's
  words, names, signatures, announcement time), including what's written on the back.

Claude reads the scans itself, so no API key, cloud OCR service or Tesseract install is needed. When you have the
PDF that Meet Manager printed, it takes the printed names, ages, teams and seed times straight from that, character
for character, and only has to read the handwriting.

## Install

```
/plugin marketplace add XRayA4T/Gala-AI-Plugins
/plugin install gala-ocr@gala-ai-plugins
```

**Requirements:** `python3` and poppler (`pdftoppm`, `pdftotext`, `pdfinfo`):

```bash
sudo apt install poppler-utils   # Debian / Ubuntu
brew install poppler             # macOS
```

## Use

Ask in plain words, or run `/gala-ocr`:

> Transcribe the lane sheets in `pdf/scanned/Lane Sheets.pdf` into `data/ocr`, using the original print in `pdf/original`.

> Read the DQ slips in `scans/DQs.pdf`.

> Redo pages 12 to 15 of the lane sheets.

Claude works through the scan in batches, writes one JSON file per sheet or slip as it goes, and checks every
file with the bundled validator. Then it lists everything a person should check against the paper: low-confidence
or unreadable times, crossed-out corrections, written-in names, N/S and DQ rows, unsigned sheets, and unreadable
slip fields. Pages that already have a file are skipped, so an interrupted run picks up where it stopped.

In a GalaAudit-style project (`pdf/scanned`, `pdf/original`, `data/ocr`) it finds the
files on its own; anywhere else it asks where the scans are and where to write.

## Output

One file per lane sheet, `<scan>-event%02d-lane%d-p%03d.json`:

```json
{
  "meetName": "Example Gala 1 - 2026", "meetDate": "2026/10/10",
  "eventNumber": 14, "eventDescription": "Men 50 LC Meter Backstroke Finals", "lane": 5,
  "rows": [
    {
      "heat": 1, "status": "SWAM", "swimmerName": "Doe, John", "age": "12", "classification": "",
      "team": "SWIM-XX", "seedTime": "42,78",
      "handTimes": [
        {"column": 1, "written": "39:34", "normalized": "39.34", "corrected": false, "confidence": "HIGH"}
      ],
      "checkedIn": true, "softTouch": false, "notes": ""
    }
  ],
  "signed": true
}
```

`status` is `SWAM`, `NO_SWIMMER`, `NO_SHOW` or `DISQUALIFIED`. Each time keeps what was written (`written`) next
to its reading as `SS.hh` / `M:SS.hh` (`normalized`, empty when unreadable), with a `HIGH` / `MEDIUM` / `LOW`
confidence.

One file per DQ slip, `<scan>-event%02d-heat%d-lane%d-p%03d.json`, named for the slip's front page:

```json
{
  "sourceFile": "DQs.pdf", "page": 8, "backPage": 9, "date": "2026-10-10",
  "eventNumber": 8, "heat": 1, "lane": 2,
  "infraction": "Turn not initiated at completion of the arm pull after leaving position on the back 150m turn",
  "back": "2nd arm pull", "official": "A. Official", "referee": "B. Referee",
  "officialSigned": true, "refereeSigned": true, "announcementTime": "12:07", "initialled": true
}
```

All names above are made up. The full field rules are in [`skills/gala-ocr/SKILL.md`](skills/gala-ocr/SKILL.md).

## Bundled scripts

| Script | Does |
|---|---|
| `scripts/original_sheets.py ORIGINAL.pdf [EVENT [LANE]]` | Prints the lane sheets exactly as Meet Manager printed them, as JSON, from the original (digital) PDF |
| `scripts/validate_cache.py FILE_OR_DIR...` | Checks transcription files have exactly the expected fields, types, values and file names; exits 1 on any problem |

Both need only the Python standard library (plus `pdftotext` for the first) and can be run on their own.

## Accuracy

The output feeds an audit of official results, so the skill is told never to guess: a digit it cannot see is
marked `LOW` or left unreadable, and is listed for a person to check. Treat the transcription as a first pass that
points you at the sheets worth a second look, not as the official record.

## Privacy

Scans carry swimmers' names, ages, clubs and times, many of them children's. The skill keeps everything in your
project folder and renders page images to a temporary folder. Don't commit real scans or transcriptions to a public
repository.
