# Frome Town Eagles design language

Source references: `screenshots/sample-03-parent-share-card.png`, `screenshots/sample-04-fixtures-dark-standard.png`, and `screenshots/sample-05-team-generator-dark-standard.png`.

## Design idea
The app should feel like a junior football match board: dark dugout UI around practical paper team sheets. Keep it direct, rounded, tactile, and useful. Avoid the generic SaaS look: no gradients, no glass panels, no emoji-led hierarchy. Use soft card shadows sparingly so the paper sheets feel lifted from the dark dugout background.

## Core tokens
| Role | Token | Hex | Use |
|---|---:|---:|---|
| Dugout background | `--fte-dugout` | `#1e1f28` | App/page background |
| Deep edge | `--fte-dugout-deep` | `#111217` | Darkest contrast only |
| Panel | `--fte-panel` | `#252731` | Buttons, nav, dark cards |
| Raised panel | `--fte-panel-raised` | `#2b2e39` | Dividers, secondary panels |
| Slate utility | `--fte-slate` | `#364b64` | Team-generator/data utility blocks |
| Paper | `--fte-paper` | `#efe5d8` | Main content sheets/cards |
| Fresh paper | `--fte-paper-fresh` | `#f7efe5` | Form panels and positive sections |
| Paper line | `--fte-paper-line` | `#d2c5b6` | Borders/table rules |
| Muted text | `--fte-muted` | `#756d66` | Supporting copy |
| Match red | `--fte-red` | `#c41e3a` | Warnings, live state, unavailable players |
| Gold selection | `--fte-gold` | `#d4af37` | Selected/ready/primary positive actions |
| Pitch green | `--fte-pitch` | `#39583c` | Pitch surfaces only |
| Control radius | `--fte-radius-control` | `12px` | Buttons, fields, compact controls |
| Panel radius | `--fte-radius-panel` | `16px` | Team sections and form panels |
| Card radius | `--fte-radius-card` | `22px` | Major cards and page panels |

## Typography
- Display: Georgia, tight tracking, used for page titles and match/team headings.
- UI/body: Aptos/Segoe UI/system sans, compact and practical.
- Avoid all-caps except small utility labels and table headings.

## Layout rules
- Rounded geometry is part of the samples: major cards use `22px`, panels use `16px`, controls use `12px`, and chips/badges use pill corners.
- Cards are paper sheets on a dark dugout, not floating glass. Use a modest shadow plus a paper border; avoid heavy glow effects.
- Standard button colours: dark slate for default, gold for primary/ready/playing, red for destructive/live/not-playing, green only for WhatsApp/share.
- Gold means selected/ready/playing. Red means destructive, live, warning, or not available.
- Keep content dense enough for a coach on a phone before kick-off; do not add decorative empty space.

## Updating later
Update `static/design-language.css` first. The legacy inline template CSS should be treated as page-specific layout only; shared colour, type, radius, and state styling belongs in the design-language stylesheet.
