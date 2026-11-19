# Design plan: Repair Invoice Audit

Audience: Techtic analysts (daily, keyboard-heavy) and fleet managers (read the
report once, in under 5 minutes). Neither group is technical.

The one memorable thing is **the money**. Every screen has at most one amber
number, and it is the recoverable-dollars figure. Everything else is quiet.

## 1. Colour

All colours are CSS variables in `web/src/app/globals.css` and mirrored in
`api/app/reports/templates/report.css`. Contrast was measured, not guessed
(script in `docs/contrast-check.py`).

| Token | Hex | Use | Contrast |
|---|---|---|---|
| `--bg` | `#F3F5F8` | Page base, cool grey | — |
| `--surface` | `#FFFFFF` | Tables, invoice canvas, cards | — |
| `--surface-sunken` | `#E9EDF2` | Nav rail, image well | — |
| `--line` | `#D5DCE4` | Hairline dividers (decorative only) | — |
| `--line-strong` | `#7A8899` | Form field borders | 3.5 : 1 on white |
| `--ink` | `#1B2B3A` | Body text, headings (asphalt) | 13.2 : 1 on bg |
| `--ink-muted` | `#4F5F70` | Secondary text, meta | 6.0 : 1 on bg |
| `--primary` | `#1F3A56` | Primary buttons, links, focus ring, chart bars | 11.7 : 1 white-on |
| `--primary-hover` | `#16304A` | Hover | — |
| `--money` | `#8F5A00` | Dollar figures that are recoverable/flagged | 5.8 : 1 on white |
| `--amber` | `#F2A900` | Safety amber: left rule on open flags, hero underline | ink-on 7.2 : 1 |
| `--amber-soft` | `#FFF4D9` | Background of an open flag / highlighted line | ink-on 13.2 : 1 |
| `--confirmed` | `#1E7046` | Accepted flags | 6.1 : 1 on white |
| `--confirmed-soft` | `#E4F2EA` | Accepted row tint | 5.3 : 1 text-on |
| `--dismissed` | `#5F6B78` | Dismissed flags | 5.4 : 1 on white |
| `--dismissed-soft` | `#ECEFF2` | Dismissed row tint | 4.7 : 1 text-on |
| `--danger` | `#B42318` | Form errors and failed uploads only | 6.6 : 1 on white |

Rules:
- Amber is reserved for money and for flags that still need attention. It never
  appears on navigation, headings or decoration.
- Amber fill is 2 : 1 against white, so it is never the only signal: it always
  sits next to text (a status word or a dollar figure).
- Charts use one hue (`--primary`) with the recoverable portion in `--money`.
  No categorical rainbow; categories are told apart by labels, not colour.
- Red appears only for things that broke (failed upload, invalid field).

## 2. Type

- Family: **Figtree** (Google Fonts, via `next/font`), weights 400 / 500 / 700.
  Fallback: `system-ui, sans-serif`.
- Every dollar figure, hour count and quantity uses
  `font-variant-numeric: tabular-nums` through a `.num` utility, right-aligned
  in tables.
- Scale (1.25 ratio, rem based on 16px):

| Step | Size / line-height | Use |
|---|---|---|
| `text-sm` | 14 / 20 | Table meta, helper text |
| `text-base` | 16 / 24 | Body, table cells, buttons |
| `text-lg` | 20 / 28 | Section headings, flag sentence on review |
| `text-xl` | 25 / 32 | Page titles |
| `text-2xl` | 31 / 38 | Secondary figures (total spend reviewed) |
| `text-hero` | 64 / 68 (report cover 88) | Recoverable dollars, once per screen |

- Prose blocks capped at `68ch`. Sentence case everywhere. No all-caps, no
  letter-spaced eyebrow labels.

## 3. Layout

App shell: a 232 px left rail with exactly four items, a roomy main column
(max 1200 px, 40 px gutters). The rail collapses to a 72 px icon+label rail
under 1024 px (tablet). Account and sign-out sit at the foot of the rail, not as
a fifth item.

```
┌──────────────┬──────────────────────────────────────────────────────────┐
│ Techtic      │  Acme Freight                         Switch client ▾   │
│ Invoice Audit│                                                          │
│              │  $48,210 likely recoverable                              │
│ ▸ Clients    │  ─────────── (amber underline, 4px)                      │
│   Upload     │  from $1.24M of repair spend across 1,012 invoices.      │
│   Review     │  37 flags still need a decision.   [Review flags]        │
│   Reports    │                                                          │
│              │  Where it comes from                                     │
│              │  Labour over benchmark   ███████████░░░  $19,400         │
│              │  Warranty missed         ██████░░░░░░░░  $11,050         │
│              │  Repeat repairs          ████░░░░░░░░░░   $8,300         │
│              │  …                                                       │
│              │                                                          │
│              │  Invoices                                     (table)    │
│ ──────────── │  Shop          Invoice   Date      Unit   Total   Status │
│ Priya (admin)│  Lone Star…    48211     Mar 3     T-114  $2,480  Done   │
│ Sign out     │                                                          │
└──────────────┴──────────────────────────────────────────────────────────┘
```

Upload: one large drop zone, then a per-file table that updates live.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Upload invoices                                                          │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │      Drop PDFs or photos here, or choose files                       │ │
│ │      PDF, JPG, PNG, HEIC · or email them to acme@in.techtic.audit    │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ File                       Pages  Status                                 │
│ shop-march.pdf             3      Reading  ▓▓▓▓▓▓░░░░                    │
│ IMG_2231.HEIC              1      Needs review (2 fields)                │
│ batch-07.pdf               1      Already uploaded on Mar 3 (skipped)    │
└──────────────────────────────────────────────────────────────────────────┘
```

Review: the invoice image is the biggest thing (≈60 % width). The right panel
is a single scrolling column: the current flag as a sentence, the money, two
big buttons, then the extracted fields.

```
┌──────┬───────────────────────────────────────┬──────────────────────────┐
│ rail │  ┌─────────────────────────────────┐  │ Flag 4 of 37   J ↓  K ↑  │
│      │  │                                 │  │                          │
│      │  │    original invoice page        │  │ Billed 8.0 hrs for a job │
│      │  │    (zoom, page 1/2)             │  │ that typically takes 5.0 │
│      │  │ ▒▒▒ flagged line highlighted ▒▒ │  │ hrs. Possible            │
│      │  │                                 │  │ overbilling of $330.     │
│      │  │                                 │  │                          │
│      │  │                                 │  │ $330 possible recovery   │
│      │  │                                 │  │ [ Accept flag  A ]       │
│      │  │                                 │  │ [ Dismiss flag D ]       │
│      │  └─────────────────────────────────┘  │ Edit amount · Add note   │
│      │                                       │ ─────────────────────────│
│      │                                       │ Invoice 48211 · Lone Star│
│      │                                       │ Unit [T-114]  VIN [....] │
│      │                                       │ Odometer [412,0?0] ⚠ 0.62│
│      │                                       │ Lines (flagged one tinted)│
│      │                                       │ [Re-run checks]          │
└──────┴───────────────────────────────────────┴──────────────────────────┘
```

Report (web and PDF share content and order):

```
Cover:      Acme Freight · Repair invoice audit · Nov 2026
            $48,210
            likely recoverable from $1.24M reviewed (3.9 %)
Page 2:     What we found (3 short sentences) · Top 5 findings (table)
Page 3:     By type · by shop · by vehicle (single-hue bar lists)
Page 4:     What to do next · Techtic ongoing-service block
Appendix:   Every confirmed flag with invoice references
```

## 4. Principles

1. One hero per screen. Recoverable dollars is big and amber; nothing else
   competes.
2. Sentences over codes. A flag reads as a sentence with "likely" or
   "possible"; the VMRS code is secondary meta.
3. Cards only for real objects (an invoice, a flag). Lists are tables with
   56 px rows and hairline dividers.
4. Same verb everywhere: "Upload invoices", "Accept flag", "Dismiss flag",
   "Re-run checks", "Generate report".
5. Empty states say what to do next. Errors say what happened and how to fix it.
6. Motion only in response to an action (progress bar fill, row tint fade on
   accept, panel slide). Disabled under `prefers-reduced-motion`.
7. Keyboard first on review: A, D, J, K, E (edit), N (note), visible focus ring
   (3 px `--primary`, 2 px offset).

## 5. Review against the brief: what I changed

My first draft had generic defaults. I caught and replaced them:

| First instinct (generic) | Changed to | Why |
|---|---|---|
| A row of four identical KPI cards on the dashboard | One hero figure with a plain sentence beneath it | Brief: money is the only memorable element |
| Coloured pill badge per flag type | Plain-text type names; colour only for status (amber open, green accepted, grey dismissed) | Avoid a rainbow; keep amber meaningful |
| Donut chart for breakdown by type | Horizontal single-hue bar list with dollar labels | Easier to scan, no legend, prints well |
| Tailwind default blue `#2563EB` and Inter | Asphalt `#1F3A56` and Figtree | Brief's palette; Inter reads as default SaaS |
| Uppercase, letter-spaced table headers | Sentence-case 14 px medium headers | Brief: no all-caps |
| Zebra-striped dense tables | 56 px rows, hairlines, no stripes | Calm, scannable |
| Settings as a 5th nav item | Warranty rules and thresholds live on the client page | Brief: exactly 4 nav items |
| Amber `#F2A900` text for dollars | `#8F5A00` text, `#F2A900` only as a rule/fill next to text | Bright amber text fails AA (2 : 1) |
| Light field borders `#D5DCE4` | `#7A8899` for inputs | Form controls need 3 : 1 |
| Numbered step markers on upload | Removed | Upload is not a strict sequence |
