# Gala AI Plugins

[Claude Code](https://claude.com/claude-code) plugins for running and auditing swimming galas.

The first plugin reads the paperwork that comes back from the pool deck: the lane sheets Hy-Tek Meet Manager
printed, filled in by hand by the timekeepers, and the referees' disqualification slips. It turns them into
structured JSON that can be checked against the official results.

## Plugins

| Plugin | What it does |
|---|---|
| [`gala-ocr`](plugins/gala-ocr) | Transcribes scanned lane sheets (printed entries plus handwritten times, N/S, DQ, soft touch, sign-off) and DQ slips into JSON, with no API key or OCR engine needed |

## Examples

Anonymised real paperwork (made-up swimmers, clubs, officials and signatures, real handwriting), with the JSON
`gala-ocr` should produce for each. See [the walkthrough](plugins/gala-ocr/README.md#examples).

| Original lane sheet ([PDF](plugins/gala-ocr/examples/original-lane-sheets.pdf)) | Scanned lane sheet ([PDF](plugins/gala-ocr/examples/scanned-lane-sheet.pdf)) | DQ slip ([PDF](plugins/gala-ocr/examples/dq-slip.pdf)) |
|---|---|---|
| ![Original lane sheet as printed by Meet Manager](plugins/gala-ocr/examples/original-lane-sheet.png) | ![Lane sheet filled in by the timekeepers](plugins/gala-ocr/examples/scanned-lane-sheet.jpg) | ![Front of a referee's DQ slip](plugins/gala-ocr/examples/dq-slip-front.jpg) |
| Printed by Meet Manager: the exact names, clubs and seed times | Handwritten times, ticks, corrections, N/S and sign-off | Infraction, officials, signatures; continues on the back |

Expected output: [`examples/expected/`](plugins/gala-ocr/examples/expected).

## Install

In any Claude Code session:

```
/plugin marketplace add XRayA4T/Gala-AI-Plugins
/plugin install gala-ocr@gala-ai-plugins
```

Or from a terminal:

```bash
claude plugin marketplace add XRayA4T/Gala-AI-Plugins
claude plugin install gala-ocr@gala-ai-plugins
```

Restart Claude Code (or start a new session) to load it. Update later with
`claude plugin marketplace update gala-ai-plugins` and `claude plugin update gala-ocr@gala-ai-plugins`.

To share the plugin with everyone working in a project, add the marketplace and plugin to the project's
`.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "gala-ai-plugins": {
      "source": { "source": "github", "repo": "XRayA4T/Gala-AI-Plugins" }
    }
  },
  "enabledPlugins": {
    "gala-ocr@gala-ai-plugins": true
  }
}
```

## Repository layout

```
.claude-plugin/marketplace.json     the marketplace: lists the plugins in this repo
plugins/
  gala-ocr/
    .claude-plugin/plugin.json      plugin manifest
    README.md
    examples/                       anonymised inputs and the JSON expected from each
    skills/gala-ocr/
      SKILL.md                      instructions Claude follows
      scripts/                      helper scripts the skill runs
```

## Privacy

Gala results and lane sheets carry personal data about swimmers, many of them children. The plugins work on files
on your own machine and write their output there. Don't commit real scans or transcriptions to a public repository,
including this one.

## License

[MIT](LICENSE): free to use, change and share, including commercially, as long as the copyright notice and
licence text are kept.
