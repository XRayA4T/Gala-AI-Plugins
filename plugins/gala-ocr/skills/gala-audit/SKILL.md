---
name: gala-audit
description: Build a gala audit report (one HTML page) from gala-ocr transcriptions (lane sheets, DQ slips, ETD programme) and the Colorado Gen7 session report - a full result review listing every swim by event, heat and lane with the touch pad (TP), push button (PB) and lane sheet stopwatch (SW) times, the final time worked out from them, the Gen7 official time and audit notes (bad TP, bad PB, poor SW times), plus DQ slip checks (missing or incorrect DQs) and lane sheet findings. Use when asked to audit a gala's results, review or reconcile times, work out final times from pads, buttons and watches, or check DQs, once the scans are transcribed.
---

# Gala audit report

Brings together what the other two skills produce:

- **gala-ocr** transcriptions in one folder: lane sheets, DQ slips and ETD programme pages
- the **Gen7 session report** PDF, which `gen7-report` reads (the audit runs its script itself)

and writes one self-contained HTML page. If the scans are not transcribed yet, do that first with gala-ocr. The ETD
pages link each programme heat to its Gen7 race, including events swum together as one race. Without them, heats
are matched by event and heat number, which is wrong for combined events and re-started heats.

## Run

`$SKILL` is this skill's base directory; it needs `python3` and poppler (`pdftotext`, `pdftocairo`).

```
python3 -I $SKILL/scripts/audit_report.py <ocr folder> "<gen7 report>.pdf" "<out>.html" [--tolerance 0.35]
```

Write the report where the user asks; otherwise next to the OCR folder, named after the meet. The page has the
swimmers' names (many of them children): keep it in the user's project, and don't publish or upload it anywhere
the user hasn't asked for.

## What it works out

For every swim (event, heat, lane): **TP**, the touch pad finish (the lane's Gen7 split on the race's last row);
**PB**, the push button backup time; **SW**, every lane sheet time; then the **final time**:

| TP | Condition (tolerance 0.35s) | Final | Note |
|---|---|---|---|
| yes | within tolerance of PB and SW median | TP | |
| yes | outside PB, within SW median | TP | bad PB time |
| yes | within PB, outside SW median | TP | poor SW time (named when one timer stands out) |
| yes | outside both | SW median | bad TP time |
| no | | SW median, thousandths dropped | bad PB if PB is outside tolerance; poor SW time if adding PB moves the median by more than the tolerance |
| no | no SW times | PB | |

Then it compares the final time with the **Gen7 official time** (noting when that was an underlined push button
override), and adds the lane sheet's notes and transcription doubts for the line (unreadable, medium or low
confidence, overwritten times).

**DQs:** each slip is checked against the lane sheet (a swimmer in that heat and lane, and not a no-show), Gen7 (a
finish in that lane) and the event (an IM infraction in a non-IM event, a distance longer than the race), and for
duplicates, missing signatures, announcement time and initial. A DQ marked on a lane sheet with no slip is listed
as a missing slip. Without Meet Manager results the DQ codes cannot be checked; the report says so.

## Report back

Give the user the file path and the headline numbers from the report's summary: swims, how many finals came from
TP and from the SW median, bad TP and bad PB times, official times that differ from the final time beyond the
tolerance (and the largest), swims with lane sheet times but no Gen7 time (by lane, if one lane stands out), DQ
slips with serious findings, and missing lane sheets. Don't paste swimmers' names into chat; refer to swims by
event, heat and lane.
