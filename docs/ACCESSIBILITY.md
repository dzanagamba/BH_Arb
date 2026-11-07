# Localization and accessibility (N2-5)

## Language catalog

The UI copy lives in `frontend/js/i18n.js`. Keys are the English source strings
(gettext-style); `window.I18N.bs` holds the Bosnian copy and `tr()` falls back
to the key. English therefore has no second copy of every label, and an English
build works even with the catalog missing.

- `data-i18n="English text"` translates a text node.
- `data-i18n-aria-label`, `data-i18n-title` and `data-i18n-placeholder`
  translate the matching attribute.
- `data-i18n-html="true"` with `data-i18n="…"` translates trusted copy that
  contains markup. The catalog is local, never feed data.
- Generated HTML uses `tr('English text', {placeholder: value})`. Values are
  still escaped through `escapeHtml()` where the string reaches `innerHTML`.

Only UI chrome is in the catalog. Bookmaker names, team and player names, league
labels, market ids and every other scraped value stay as data and are never
translated.

Views that are generated per scan are repainted on a language change by
`refreshLocalizedViews()`. It repaints through the same filtered path as a
filter change, so the list, the KPI counts and the selected slip cannot
disagree, and it never counts as a user selection: no slip is opened and no
price re-check is launched. The network-backed tabs reload; the list and slip
re-render from the snapshots already held.

### Adding a string

1. Put the English source in the markup or in a `tr()` call.
2. Add its Bosnian translation to `frontend/js/i18n.js`.
3. Run `python -m pytest tests/test_i18n_coverage.py`.

The test fails on a missing key, an empty translation, a lost `{placeholder}`, a
shipped HTML text node outside the catalog, or a missing `*_bs` field in the
no-surebet copy table.

The no-surebet cases keep their English `title`/`body` and a parallel
`title_bs`/`body_bs` (and live variants); `renderCaseCopy()` chooses by the
active language so the diagnostic never mixes languages.

## Automated accessibility

`tests/test_accessibility_axe.py` always runs the offline checks:

- landmarks (`header`, labelled `nav`, `main`, slip `aside`), skip link and live
  regions;
- a programmatic name for every visible button, link, input, select and
  textarea;
- tab semantics (`role=tab`, `aria-selected`, `aria-controls`, six panels with
  matching ids);
- no duplicate ids and no positive `tabindex`;
- keyboard handlers for tabs (arrows/Home/End), list J/K and Escape (drawer, then
  slip), plus the slip's copy/mark controls.

The live audit is `scripts/a11y_audit.py`. It serves `frontend/`, walks the six
main tabs, opens a synthetic slip, and runs:

- a built-in DOM audit that always runs;
- axe-core when `--axe PATH`, `AXE_PATH`, or
  `node_modules/axe-core/axe.min.js` is present.

```bash
python scripts/a11y_audit.py
python scripts/a11y_audit.py --axe node_modules/axe-core/axe.min.js --json /tmp/a11y.json
BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_accessibility_axe.py
```

The browser is optional tooling. Without Chromium the script exits 2 with the
install command, and the offline suite still runs the static checks. CI can run
the live test where a Playwright browser is installed; it is skipped otherwise.

### Allowlist

`scripts/a11y_audit.py` exposes `ALLOWLIST`: `(rule, selector_fragment, reason)`
entries for a reviewed, accepted issue. It is **empty** today: every tab and the
synthetic slip pass both the built-in audit and axe-core (including contrast) in
the light and dark themes. Add an entry only with a measured reason, never to
make a run green. An unlisted violation fails the audit.

The audit checks a synthetic slip shape plus the real static slip, not a live
feed. It is a regression net, not a substitute for a screen-reader session on a
deployed build.

### Keyboard-only path

`BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_accessibility_axe.py` also
runs the path end to end without mouse events, in English and Bosnian:

1. open Settings with Enter (focus moves into the drawer) and choose the language;
2. type a filter;
3. activate **Scan now** with Enter;
4. focus a surebet and open its slip with Enter;
5. focus the stake-copy control and activate it; the clipboard matches;
6. press Escape; the slip closes.
