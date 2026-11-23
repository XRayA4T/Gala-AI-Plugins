---
name: gala-audit
description: Build a gala audit report (one HTML page) from gala-ocr transcriptions (lane sheets, DQ slips, ETD programme) and the Colorado Gen7 session report - a full result review listing every swim by event, heat and lane with the touch pad (TP), push button (PB) and lane sheet stopwatch (SW) times, the final time worked out from them, the Gen7 official time and audit notes (bad TP, bad PB, poor SW times), a Quick Fix list of the swims the OCR could not settle, plus touch pad touches by lane (expected and recorded split and finish touches), DQ slip checks (missing or incorrect DQs) and lane sheet findings. Use when asked to audit a gala's results, review or reconcile times, work out final times from pads, buttons and watches, or check DQs, once the scans are transcribed, and for a final audit of the manual changes made in Meet Manager.
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

`$SKILL` is this skill's base directory; it needs `python3` and poppler (`pdftotext`, `pdftocairo`, `pdftoppm`).

```
python3 -I $SKILL/scripts/audit_report.py <ocr folder> <gen7> "<out>.html" [--events 3,5-7] [--tolerance 0.30] [--codes DQ_CODES.txt] [--scans DIR] [--scan-dpi 90] [--scan-quality 40] [--merge "<our merge results>.hy3"] [--quick-fixes "<quick fix>.html"] [--ocr-fixes [--checks CHECKS.json]] [--times TIMES.json] [--dqs DQS.json] [--confirmations CONFIRMATIONS.json]
```

`<gen7>` is the Gen7 session report PDF, or a **folder of Gen7's race-by-race PDFs** for one session (one PDF per
race, as Gen7 prints them during a gala). Race numbers are matched within it, so give one session's races only; a
race printed twice is taken from the newer file. `--events` limits the report to those events.

### During a gala: event by event, session by session

When the audit runs while the gala is still on, the paperwork arrives in pieces: a scan pack of lane sheets per
event, Gen7 PDFs race by race, and per session the meet entries export and a merge results export.

- **As each event is in** (its lane sheet pack transcribed with gala-ocr, its heats' Gen7 PDFs in the session's
  folder): run the audit for that event (`--events N`) so problems reach the officials while they are still at the
  pool, and again for the session so far (`--events` with the session's events done so far) to keep one up-to-date
  session report. Events still to come are left out, so they are not reported as missing.
- **At the end of the session:** DQ codes for the session's slips, the session report with `--merge` once the merge
  results file is written, then the merge results file for the session (below) from that session's entries export,
  merge results export and Gen7 folder (`--events` with the session's events if the entries export covers more).
- **The final audit** is per session too: our session merge results against Meet Manager's final export.

Once the merge results file is written (below), run the audit again with `--merge` so the Quick Fix section checks it
and shows what it has for each swim; `--quick-fixes` also writes the Quick Fix list on its own, to print (no
swimmers' names), and as JSON next to it (same name, `.json`) for the final audit.

Every section, and each event in the full result review, starts collapsed. A **Paper** column links each swim to
its lane sheet and DQ slips; the DQ and lane sheet tables link back to the swims. Following a link opens the
sections it lands in (Chromium browsers) and outlines the row. Expand/collapse-all buttons appear only where
scripts may run, not in a sandboxed viewer.

The report is **self-contained**: every lane sheet and DQ slip row carries its scanned page, embedded as a grayscale
JPEG under the row (collapsed), and the row's page number jumps to it. The pages come from the scan PDFs the OCR file
names point to (`<scan>.pdf`), looked for in `--scans DIR`, else the OCR folder's parent, then the OCR folder; it
needs poppler's `pdftoppm`. The defaults (90 dpi, JPEG quality 40) keep handwritten times legible at about 25 KB a
page (about 7.5 MB for a 185-page gala); raise `--scan-dpi` if a scan is hard to read. A missing scan PDF is
skipped with a warning, and its rows show the page number only.

Write the report where the user asks; otherwise next to the OCR folder, named after the meet. The page has the
swimmers' names (many of them children): keep it in the user's project, and don't publish or upload it anywhere
the user hasn't asked for.

## Meet Manager merge results file

To load the audited results into Hy-Tek Meet Manager, write a merge results file (.hy3) from the same data, the
meet's entries export (the `Hfile*.hy3` inside `Meet Entries-<meet>.zip`; unzip it into a temp folder) and a merge
results file Meet Manager exported for this meet (its header and layout are copied), or `-` to use the entries export
alone (from 1.6.10: its B1 and B2, an A1 that says Merge Meet Results, and Meet Manager's result line layout):

```
python3 -I $SKILL/scripts/merge_results.py <ocr folder> <gen7> <entries>.hy3 "<merge results>.hy3"|- "<out>.hy3" [--events 1-12]
```

The entries export can be the one made **before the session was seeded** (no heats or lanes in it, often named
"pre-gala"): each entry is then seeded from the lane sheet it is printed on, matched by event and name (surname and
first name, or the surname alone when only that entry has it). The script prints how many it seeded and lists lane
sheet swimmers it couldn't match.

An entry **scratched** in Meet Manager (the entries export's E1 column 80 is `Y`) that didn't swim (a no-show on the
lane sheet) is written with **no result**, as Meet Manager has it, not as a no-show. One that swam keeps its result,
and the audit (given `--merge`) lists it in the Quick Fix list: "Scratched in Meet Manager but swam".

`--not-entered NOT_ENTERED.json` (1.6.15) lists the swims by swimmers **not entered in the race**: a scratched entry
that swam, and a swim confirmed by hand (`"add": true`) for a swimmer with no entry in the event, for which an entry is
added. A fix with `"status": "NS"` on such a swim marks it as **no swim**: the scratched entry gets no result and no
entry is added (it stays in the list with `"noSwim": true`). With `--ocr-fixes` the audit leaves the scratch out of its
Quick Fix list; the gala audit portal confirms these swims (the referee approves, or no swim).

`--hand-times 12` (both scripts) marks events timed by hand only, such as a time trial with no Gen7 race: their swims
are timed from the lane sheet watches and the missing race isn't a problem. A fix with `"swimsEvent": N` on a swim
(`"E-H-L"` in `--fixes`) gives the swim to the swimmer's entry in event N, timed in that race; their entry in the race's
own event has no result.
A fix with `"timedIn": "8-1"` on a swim times it in event 8 heat 1's Gen7 race (the same lane), for a swim such as a time
trial swum in another event's heat.

**Which Gen7 race is a heat.** The ETD programme's race number, when there is one. Without it, the race for the event
and heat: a race with no times (a false start or a technical problem) is passed over, and when two or more races of
the heat have times the lane sheets decide: the race whose touch pad or push button times agree with the median of
the lane's watches (within 1 s) on clearly the most lanes. If they can't tell (no lane sheets yet, or they fit more
than one race, or none), the latest race is used and every lane of the heat goes to Quick Fix ("Several Gen7 races
with times for this heat: ... choose the race"). A person's choice is a heat fix in `--fixes`,
`{"<event>-<heat>": {"race": 51}}`, and wins over the ETD and the lane sheets.

`--fixes FIXES.json` applies fixes made by hand after the audit (the gala audit portal writes them, one per
quick-fix swim): `{"<event>-<heat>-<lane>": {"time": "1:05.32", "status": "OK|NS|DQ", "code": "BaG", "note": ""}}`.
They override the audited time and status of those swims (a no-show, a DQ with its FINA code, or a corrected time),
and the places are worked out with them. Don't edit the file; pass it as it is.
An entry can also fix the lane sheet itself: `"watches": {"2": {"accepted": true}}` accepts a medium or low confidence
reading of timer 2 as read, `"watches": {"2": {"time": "1:05.42"}}` replaces it with the time read off the sheet by
hand, and `"swimmer": {"name": "Surname, First", "id": "..."}` is the entered swimmer chosen for a written-in name.
Pass the same file to `audit_report.py --fixes` too, so the report and its Quick Fix list use the fixed readings. With `"add": true` next to
`"swimmer"` (a swim confirmed by hand, e.g. for "swam on the lane sheet but not in the merge file"), merge_results
gives the swim at that event, heat and lane to that swimmer's entry, and adds an entry from the entries file's
swimmer when they weren't entered in the event.

Every entry gets its team, swimmer and entry lines copied from the entries file (each event marked done, as Meet
Manager marks an event whose results are final, not seeded or scored), then its result: the final time,
the pad time, backup times (the lane sheet times when the final time comes from them or TP was kept in doubt:
three in backups 1-3, two in backups 2 and 3, one in backup 3, with PB in backup 1 when there is one;
otherwise the Gen7 buttons, as Meet Manager writes them for a pad time; when TP is the final time and there is
no PB time, the SW median, thousandths dropped, as backup 1; when TP agrees with the SW median but not PB, PB as
backup 1 and the SW median as backup 2), places in the heat and
in the swimmer's age group (`--age-groups`, default `10U,11,12,13,14,15,16,17O`), DQs with their code in Hy-Tek's
form (stroke number and letter: BaG is `2G`, BfG `4G`, IMB `5B`, a Misc code such as GA (false start) `7A`, which
hasn't yet been checked against a Meet Manager export, so check it after the import; Meet Manager stores and exports codes this way,
even one entered as BfG, and shows them in the FINA style), no-shows, and the Gen7 splits. Every event is marked
done, and done-event details follow Meet Manager's own export (the course and a `0` in column 100 on every result,
no pad time when the pad touch is less than half the final time); for one event this was checked line for line
against Meet Manager's export of the same results. The A1 header line is the
template's with today's date. Name the output like Meet Manager's (`Merge Meet Results-<meet>-<date>-audit.hy3`).

Report what the script prints (swims it moved to the lane sheet's swimmer, swims with no time, lane sheet swimmers
with no entry) and how the file differs from the Meet Manager results it replaces. The file holds swimmers' dates of
birth and registration numbers: keep it in the user's project, and delete any temp copies.

## Quick Fix

A section near the top of the report (and the `--quick-fixes` page) lists **only the swims where the OCR could not
settle the result**, by event, heat and lane, with what the merge file has and what to check, so they can be fixed
quickly in Meet Manager once the merge results are imported:

- a watch time that could not be read;
- a watch read with medium or low confidence, or overwritten on the sheet, that no other watch agrees with, when the
  final time comes from the watches;
- a poor watch time, a watch far from the final time, and a swim in doubt;
- a lane sheet swimmer with no time anywhere, or a Gen7 time for a lane the sheet has as empty or a no-show;
- a swimmer written in over the printed one (the lane sheet notes say the printed name is crossed out);
- a DQ slip with no code, or with a code given with a doubt (a `note` in `dq-codes.json`), and a DQ marked on a
  sheet with no slip;
- with `--merge`: a lane sheet swim missing from the merge file (left out or with no entry), a different swimmer in
  the merge file than on the sheet, and a DQ in it with no code.

Each line's Scan column links to the scan to look at: the DQ slip for a DQ check, the lane sheet for the rest (both
when the swim has both kinds of check). In the report the link opens that page embedded under the sheet or slip; the
`--quick-fixes` page, which has no scans, names the scan file and page instead.

Everything else stays in its own section: Gen7 differences in Serious issues and SW overrides, the other DQ codes in
DQs. Keep it short; it is a to-do list, not a second copy of the report.

`--ocr-fixes` (from 1.6.14) keeps the list to what the OCR has to settle, for a process that confirms the times and
DQs separately (the gala audit portal's confirmations): unreadable or doubtful watches, poor watch times, an SW median
more than 0.40 s from PB (a watch misread), lane sheet and Gen7 disagreeing on whether a lane swam, and swimmers
written in or missing from the merge file. Swims in doubt and every DQ check are left out, and from 1.6.15 so are
watches more than 0.40 s from PB (or more than 1 s from a TP and PB that agree) when two or more of them agree with
their median: no misread can be moving it. `--checks` (1.6.15) writes the other checks that aren't about the reading
(several Gen7 races for a heat, the lane sheet and Gen7 disagreeing on a lane, a scratched entry that swam) for the
confirmations to settle. `--times` writes every
swim's TP, PB, SW times, median and final time with its swimmer and whether it is a no-show or a DQ, and `--dqs`
every DQ (each slip, and each DQ marked on a lane sheet with no slip) with its swimmer, infraction, code and findings.
`--confirmations` (1.6.16) takes what the gala audit portal has for each event (a JSON list, one object per event:
its Quick OCR fixes with who ticked them and the fix made, and its confirmations: DQs, swims not entered, other checks
and each time section's swims with the value confirmed, the reason and who confirmed it). The report then calls the
list **Quick OCR fixes** (with `--ocr-fixes`), adds a *Fixed / ticked* column to it, and adds a **Confirmations**
section: per event, an overview of every section (swims, confirmed, changed from the suggestion, who ticked the
section) and each section's swims with TP, PB, the SW median, the watches, the ΔTP/PB, ΔTP/SW and ΔPB/SW differences
(more than 0.30 s shaded) and what was confirmed (highlighted). The summary counts each event's swims confirmed with
another value than suggested.

## Final audit

After the results are imported and finalised in Meet Manager, the user uploads Meet Manager's merge results export.
Compare it with our merge results file for the same events:

```
python3 -I $SKILL/scripts/final_audit.py "<our merge results>.hy3" "<final merge results>.hy3" "<out>.html" [--quick-fixes "<quick fix>.json"] [--codes DQ_CODES.txt] [--results "<results>.pdf"]
```

`--results` takes Meet Manager's printed Results for the session (PDF) and adds a **Results exceptions** section:
every swim where our merge results, the final export and the printed results don't all agree (time, N/S, DQ, no
result), matched by event and name.

It matches every entry by swimmer and event and lists each manual change: time changed, DQ added, removed or code
changed, no-show added or removed, moved to another heat or lane, result added (including a swimmer with no entry in
ours) or removed, with our value, the final value and whether the swim was on the Quick Fix list; then a summary by
kind, and the Quick Fix swims left as they were. Places, backup and pad times are not compared. The page has
swimmers' names; report back by event, heat and lane.

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
| yes | within PB, outside SW median | TP | SW times disagree with TP and PB; more than 1 s out goes in the Quick Fix (check the sheet: a misread time) |
| yes | outside both | SW median | bad TP time (listed under SW overrides) |
| no | | SW median, thousandths dropped | bad PB if PB is outside tolerance; poor SW time if adding PB moves the median by more than the tolerance |
| no | no SW times | PB | |

From 1.6.13 TP stands when it agrees with PB. Before that the SW median overrode it; for a gala whose results were
published with that rule, pass `--watches-over-pad` to `audit_report.py` and `merge_results.py` to keep it.

A **no-show** on the lane sheet (N/S, no SW times) is recorded as N/S with no time, even when Gen7 has a time; the
report shows `N/S` as the final time and flags the Gen7 time for correction.

Then it compares the final time with the **Gen7 official time** (noting when that was an underlined push button
override). A lane where Gen7 has a push button time but no official time is noted as **TP soft touch / faulty
TP** (the final time still comes from the rules above) and counted in the summary. It then adds the lane sheet's
notes and transcription doubts for the line (unreadable, medium or low confidence, overwritten times).

**Touchpads:** a table by lane (and a total) of the touch pad touches Gen7 recorded against those expected, for
every swim with a final time in a heat with a Gen7 race. Gen7 prints one split row per 100 m, at the touch pad end,
and the finish on the race's last row, so a race of 200 m or more expects a split touch at each 100 m before the
finish (D / 100 - 1: a 200 one, a 400 three, a 1500 fourteen) and a shorter race none; every swim expects a finish
touch. A push button time, or an underlined button override Gen7 copied into the finish, is not a touch. A lane
far under 100% points to a dead or faulty pad. A swimmer who stopped before the finish still counts as expecting
every touch.

**Ignored races**, listed under the summary and not flagged anywhere else:
- a **false start**: a Gen7 race with nothing recorded in any lane (no pad or button time) whose race number is
  not written in the ETD programme (checked only when there are ETD pages);
- a **race not started**: an ETD race number with no Gen7 race and no lane sheet times in that heat.

**DQs:** each slip is checked against the lane sheet (a swimmer in that heat and lane, and not a no-show), Gen7 (a
finish in that lane) and the event (an IM infraction in a non-IM event, a distance longer than the race), and for
duplicates, missing signatures, announcement time and initial. A DQ marked on a lane sheet with no slip is listed
as a missing slip. Each slip's DQ code (from `dq-codes.json`) is checked against the event, as above.

## Report back

Give the user the file path and the headline numbers from the report's summary: swims, how many finals came from
TP and from the SW median, bad TP and bad PB times, official times that differ from the final time beyond the
tolerance (and the largest), swims with lane sheet times but no Gen7 time and TP soft touch / faulty TP lanes (by
lane, if one lane stands out), DQ
slips with serious findings, codes you assigned with a note, missing lane sheets, and from the Touchpads table the
total split and finish touches recorded against expected, with any lane well under 100%, and the ignored races (false starts and races not started) by race number, and how many swims are on the Quick Fix list (by kind). Don't paste swimmers' names into chat; refer to swims by
event, heat and lane.
