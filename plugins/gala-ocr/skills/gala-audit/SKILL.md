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

## DQ codes

`$SKILL/data/dqcodesFINA.txt` is the FINA DQ code list: one `"code","description","group"` line per code, with
group `Misc`, `free`, `back`, `breast`, `fly`, `IM` or `Relay` (e.g. `"BrK","Stroke cycle not 1 arm stroke to 1 leg
kick in that order","breast"`). Use the meet's own list instead if the user gives one (`--codes FILE`, same format).

Slips carry the official's wording, not a code, so before running give each slip its code: read the infraction (and
the back) against the list and write `<ocr folder>/dq-codes.json`:

```json
{"DQs-event07-heat2-lane8-p008.json": {"code": "BrK", "note": ""},
 "DQs-event12-heat4-lane1-p025.json": {"code": "BrD", "note": "No code for a butterfly kick during the stroke; BrD is closest"}}
```

- Pick from the codes of the event's stroke, plus `Misc`; in an IM, the code of the stroke whose leg it was (not
  `IMC`, which says to use the stroke codes), or `IMA` / `IMB`; `Relay` codes only in relays.
- When no code fits exactly, give the closest and say why in `note`; when two apply, give the main one and name the
  other in `note`. Use `""` for `code` when you can't tell, rather than guess.
- List the codes with a `note` in your report back, for the referee to confirm.
- Write codes in the FINA style (`BaG`, `BfG`) everywhere people read them: the report, summaries, answers. The
  Hy-Tek form (`2G`, `4G`) belongs only inside the .hy3 file; don't give both.

The report shows each slip's code and description, and flags a code that is not in the list, one whose group cannot
happen in the event (a backstroke code in a butterfly race), an IM code on the wrong leg's stroke, and a slip whose
code differs from one written on the lane sheet.

## Run

`$SKILL` is this skill's base directory; it needs `python3` and poppler (`pdftotext`, `pdftocairo`).

```
python3 -I $SKILL/scripts/audit_report.py <ocr folder> "<gen7 report>.pdf" "<out>.html" [--tolerance 0.30] [--codes DQ_CODES.txt] [--scan-url "SCAN.pdf=URL" ...]
```

Every section, and each event in the full result review, starts collapsed. A **Paper** column links each swim to
its lane sheet and DQ slips; the DQ and lane sheet tables link back to the swims. Following a link opens the
sections it lands in (Chromium browsers) and outlines the row. Slip and sheet page numbers open the scan at that
page: `<scan>.pdf#page=N` next to the report, or `URL#page=N` for a scan given with `--scan-url`. Never put an
access key or other secret in a `--scan-url`. Expand/collapse-all buttons appear only where scripts may run, not
in a sandboxed viewer.

Write the report where the user asks; otherwise next to the OCR folder, named after the meet. The page has the
swimmers' names (many of them children): keep it in the user's project, and don't publish or upload it anywhere
the user hasn't asked for.

## Meet Manager merge results file

To load the audited results into Hy-Tek Meet Manager, write a merge results file (.hy3) from the same data, the
meet's entries export (the `Hfile*.hy3` inside `Meet Entries-<meet>.zip`; unzip it into a temp folder) and a merge
results file Meet Manager exported for this meet (its header and layout are copied):

```
python3 -I $SKILL/scripts/merge_results.py <ocr folder> "<gen7 report>.pdf" <entries>.hy3 "<merge results>.hy3" "<out>.hy3"
```

Every entry gets its team, swimmer and entry lines copied from the entries file (each event marked done, as Meet
Manager marks an event whose results are final, not seeded or scored), then its result: the final time,
the pad time, backup times (the lane sheet times when the final time comes from them or TP was kept in doubt:
three in backups 1-3, two in backups 2 and 3, one in backup 3, with PB in backup 1 when there is one;
otherwise the Gen7 buttons, as Meet Manager writes them for a pad time; when TP is the final time and there is
no PB time, the SW median, thousandths dropped, as backup 1; when TP agrees with the SW median but not PB, PB as
backup 1 and the SW median as backup 2), places in the heat and
in the swimmer's age group (`--age-groups`, default `10U,11,12,13,14,15,16,17O`), DQs with their code in Hy-Tek's
form (stroke number and letter: BaG is `2G`, BfG `4G`, IMB `5B`; Meet Manager stores and exports codes this way,
even one entered as BfG, and shows them in the FINA style), no-shows, and the Gen7 splits. Every event is marked
done, and done-event details follow Meet Manager's own export (the course and a `0` in column 100 on every result,
no pad time when the pad touch is less than half the final time); for one event this was checked line for line
against Meet Manager's export of the same results. The A1 header line is the
template's with today's date. Name the output like Meet Manager's (`Merge Meet Results-<meet>-<date>-audit.hy3`).

Report what the script prints (swims it moved to the lane sheet's swimmer, swims with no time, lane sheet swimmers
with no entry) and how the file differs from the Meet Manager results it replaces. The file holds swimmers' dates of
birth and registration numbers: keep it in the user's project, and delete any temp copies.

## What it works out

For every swim (event, heat, lane): **TP**, the touch pad finish (the lane's Gen7 split on the race's last row; none
when the Off. Time is an underlined button override and that split is the same time, since Gen7 copies the
button time into it);
**PB**, the push button backup time; **SW**, every lane sheet time; then the **final time**:

| TP | Condition (tolerance 0.30s) | Final | Note |
|---|---|---|---|
| yes | within tolerance of PB and SW median | TP | |
| yes | outside PB, within SW median | TP | bad PB time |
| yes | outside SW median, in doubt: fewer than two SW times within the tolerance of their median, and PB not within it either | TP | in doubt; the SW times go in the merge file as backups |
| yes | within PB, outside SW median | SW median | TP and PB both outside the watches (listed under SW overrides) |
| yes | outside both | SW median | bad TP time (listed under SW overrides) |
| no | | SW median, thousandths dropped | bad PB if PB is outside tolerance; poor SW time if adding PB moves the median by more than the tolerance |
| no | no SW times | PB | |

A **no-show** on the lane sheet (N/S, no SW times) is recorded as N/S with no time, even when Gen7 has a time; the
report shows `N/S` as the final time and flags the Gen7 time for correction.

Then it compares the final time with the **Gen7 official time** (noting when that was an underlined push button
override), and adds the lane sheet's notes and transcription doubts for the line (unreadable, medium or low
confidence, overwritten times).

**DQs:** each slip is checked against the lane sheet (a swimmer in that heat and lane, and not a no-show), Gen7 (a
finish in that lane) and the event (an IM infraction in a non-IM event, a distance longer than the race), and for
duplicates, missing signatures, announcement time and initial. A DQ marked on a lane sheet with no slip is listed
as a missing slip. Each slip's DQ code (from `dq-codes.json`) is checked against the event, as above.

## Report back

Give the user the file path and the headline numbers from the report's summary: swims, how many finals came from
TP and from the SW median, bad TP and bad PB times, official times that differ from the final time beyond the
tolerance (and the largest), swims with lane sheet times but no Gen7 time (by lane, if one lane stands out), DQ
slips with serious findings, codes you assigned with a note, and missing lane sheets. Don't paste swimmers' names into chat; refer to swims by
event, heat and lane.
