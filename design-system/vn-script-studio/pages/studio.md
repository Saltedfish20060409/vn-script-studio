# Studio workspace override

> Overrides MASTER for the main writing app (not marketing landing).

**Rationale:** MASTER's mint teal / cinema-dark pattern conflicts with an existing warm editorial studio and the project's anti-pattern list (no generic SaaS mint, no glow-heavy dark). Keep literary typography; use ink–paper–forest tokens.

## Colors (workspace)

| Role | Hex | Token |
|------|-----|-------|
| Ink | `#1c1917` | `--ink` |
| Ink soft | `#57534e` | `--ink-soft` |
| Paper | `#f7f4ef` | `--paper` |
| Paper deep | `#ebe6dc` | `--paper-deep` |
| Line | `#d6d0c4` | `--line` |
| Primary (forest) | `#1f6b5a` | `--accent` |
| Hot (ember) | `#c45c2a` | `--accent-hot` |
| AI | `#3d5a80` | `--ai` |
| Ring | `#1f6b5a` | `--ring` |

## Typography

- Display / brand: **Cormorant Garamond**
- UI: **Public Sans**
- Script editor: **JetBrains Mono**

## Layout

- Sticky chrome header (brand + title + primary actions)
- Fixed-width rail for chapters (248px), collapses under 900px
- Main tabs as underline segment (not pills)
- Writing canvas: soft inset frame, mono editor, min touch 44px
- Motion: 160–280ms, respect `prefers-reduced-motion`
