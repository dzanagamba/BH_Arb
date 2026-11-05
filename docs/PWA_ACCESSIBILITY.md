# PWA, accessibility and Bosnian UI

The N2-5 localization and accessibility work is documented in
[`ACCESSIBILITY.md`](ACCESSIBILITY.md). This file keeps the installable-shell
facts that predate it.

## Installable shell

- `frontend/manifest.webmanifest` declares name, short name, start URL `/`,
  standalone display and theme colours.
- `frontend/sw.js` caches only `/`, `index.html`, `style.css`, `i18n.js`,
  `app.js` and the manifest. It **never** caches `/api/` responses or odds: a
  stale service-worker cache would be a second stale-feed layer.
- The worker uses network-first and falls back to the cached shell; registration
  is optional and guarded by `'serviceWorker' in navigator`.

## Language

The full catalog is `frontend/js/i18n.js`; `tr()` and
`refreshLocalizedViews()` in `app.js` apply it. The Settings toggle writes
`localStorage.language`, sets `<html lang>` and repaints generated views.
`tests/test_i18n_coverage.py` enforces coverage; see `ACCESSIBILITY.md` for the
conventions.

## Accessibility hooks

- Skip link to `#main` (`tabindex="-1"` on the main region), visible on focus.
- Tab buttons use `role="tab"`, `aria-selected`, `aria-controls` and a roving
  `tabindex`; their keydown handler is in `handleTabKeydown`.
- Live regions: the freshness banner (`role="alert"`), feed-integrity strip,
  slip pane, sweep status and toast (`role="status"`) all use `aria-live`.
- Every generated link/button is a real `<button>`/`<a>` with an accessible
  label; no inline handlers.
- Form controls have a visible `<span>` label or `aria-label`.

The machine checks, axe runner and keyboard path are in
`tests/test_accessibility_axe.py` and `scripts/a11y_audit.py`.
