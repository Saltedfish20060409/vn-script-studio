# VN Script Studio — Design Master

> **Source of truth:** `frontend/src/styles/globals.css`  
> This file is a short map for agents. If tokens conflict, **CSS wins**.  
> Never reintroduce teal `#1f6b5a` / `#0D9488`. Recovery: `.\restore-ui.ps1`.

---

**Product:** VN Script Studio  
**Look:** Persona slash HUD + light anime stationery  
**Updated:** 2026-08-09

---

## Brand accents

| Mode | Accent | Role |
|------|--------|------|
| Day | `#002fa7` | Klein blue — primary slash / CTA |
| Night | `#e11d48` | Crimson — primary slash / CTA |
| Hot shard | `#e11d48` (day) / `#ff6b35` (night) | Small ticks only |

CSS: `--accent`, `--accent-hot`, `--slash`, `--shard`.

## Surfaces & type

| Token | Day intent |
|-------|------------|
| `--ink` / `--ink-soft` | Near-black / muted slate |
| `--paper` / `--paper-deep` | Cool paper, not cream-terracotta |
| `--line` | Hard ink edge |
| `--panel-bg` / `--field-bg` | Solid chrome (avoid heavy frost slabs) |
| `--font-display` | Oswald + Noto Sans SC |
| `--font-ui` | Noto Sans SC |
| `--font-mono` | JetBrains Mono |

Radii stay sharp (`--radius-sm/md/lg` ≈ 2–6px). Shadows are offset blocks, not soft blobs.

## Chrome vocabulary

- **Nav stamps:** tab / empty-state codes only (`LIB` / `MAP` / …), not decorative section banners.
- **Slash-in:** `.vnss-slash-in` / `--slash-in` for menu enter.
- **Rails:** `--rail-fill*`, `--rail-border*`, `--rail-grad` — solid panel-based, not dark wallpaper bars.
- **Status:** corner toast (`ok` / `error` / `busy` / `info`); busy reads as `RUN`.
- **Empty:** mascot line, no big empty illustrations.

## Do / Don't

- Do: hard bevels, diagonal cuts, Klein/crimson accents, Oswald display stamps.
- Don't: teal recovery look, purple-indigo AI defaults, warm cream + terracotta stack, broadsheet newspaper density, emoji icons, Agent/menu dark frost rails.

## Pre-check (UI writes)

- [ ] Day `--accent` is still `#002fa7` on disk
- [ ] No `#1f6b5a` / `#0D9488` in touched CSS
- [ ] Writing chrome stays light; focus mode keeps chrome minimal
- [ ] Prefer existing tokens over new one-off hex
