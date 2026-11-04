# PWA, accessibility and Bosnian UI (P3-4)

## Installable shell

- `frontend/manifest.webmanifest` declares name, short name, start URL `/`,
  standalone display and theme colours.
- `frontend/sw.js` caches only `/`, `index.html`, `style.css`, `app.js` and the
  manifest. It **never** caches `/api/` responses or odds: a stale service-worker
  cache would be a second stale-feed layer.
- The worker uses network-first and falls back to the cached shell; registration
  is optional and guarded by `'serviceWorker' in navigator`.

## Language

`frontend/js/app.js` has `I18N.en` and `I18N.bs` for the main labels: tabs,
Scan now, Settings headings, Staking/Scanning and the sound preference. The
Settings toggle writes `localStorage.language` and `applyLanguage()` sets
`<html lang>` plus every `[data-i18n]` node on load.

Adding a string: put the key in both dictionaries and add
`data-i18n="key"` to the element. The static test fails if the dictionaries or
the toggle disappear.

## Accessibility hooks

- Skip link to `#main` (`tabindex="-1"` on the main region), visible on focus.
- Tab buttons use `role="tab"`, `aria-selected`, `aria-controls` and a roving
  `tabindex`; their keydown handler is in `handleTabKeydown`.
- Live regions: the freshness banner (`role="alert"`), feed-integrity strip,
  slip pane, sweep status and toast (`role="status"`) all use `aria-live`.
- Every generated link/button is a real `<button>`/`<a>` with an accessible
  label; no inline handlers.
- Form controls have a visible `<span>` label or `aria-label`.

### Manual pass (2026-11-04, source review)

Keyboard path reviewed in source and DOM order: skip link → tabs (arrow/Home/End
handling) → filters → surebet rows → slip → mark placed → copy/log. Focus remains
visible on the skip link and the existing `:focus-visible` styles. Contrast uses
the theme tokens; the skip link borrows the same text/border tokens. Screen
reader order follows the DOM: nav, summary, list, slip.

This is a source-level pass, not a substitute for a screen-reader session on the
deployed build.
