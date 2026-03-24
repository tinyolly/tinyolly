# TinyOlly v2.3.0

**Release Date:** March 2026

Deep linking, trace map visualization, expanded query limits, and UI polish.

---

## Highlights

- **Deep Linking** — Shareable URLs that open directly to a specific trace, span, or filtered view. Copy Link buttons generate URLs from trace and span detail views. Browser back/forward navigation preserves trace detail state.

- **Trace Map** — Per-trace service dependency graph rendered automatically above the waterfall. Uses Cytoscape.js with dagre layout. Detects inferred external clients from orphan parent span IDs (e.g., test clients that propagate trace context without exporting spans).

- **Expanded Query Limits** — API and UI limits raised significantly to leverage 256 MB storage. Traces, spans, and logs fetch up to 1,000 by default (API max 5,000). Service catalog scans up to 10,000 spans. RED metrics window expanded to 5 minutes, metric series window to 1 hour.

- **Smart Auto-Refresh** — Auto-refresh pauses automatically when a search filter is active on the current tab, preventing result disruption. Resumes when the search is cleared.

---

## Deep Linking

Shareable URLs for traces, spans, and search queries:

| URL Pattern | Behavior |
|-------------|----------|
| `?tab=traces&traceId=<id>` | Opens directly to trace detail with waterfall |
| `?tab=spans&spanId=<id>` | Opens spans tab filtered by span ID |
| `?tab=<tab>&search=<query>` | Opens tab with search pre-filled |

**Copy Link buttons** added to:
- Trace detail view action bar
- Span detail view action bar

**Browser navigation**: URL updates when viewing a trace detail and is removed when returning to the list. Back/forward buttons restore trace detail state via `popstate` handler.

---

## Trace Map

Automatic per-trace service dependency visualization:

- Renders above the waterfall in trace detail view (no toggle button)
- Cytoscape.js with dagre directed-graph layout
- Nodes sized 28×28 with 11px labels, compact 300px container
- Dark mode support via `getComputedStyle()` for theme-aware colors
- **Inferred client detection**: Orphan parent span IDs (where the caller didn't export spans) generate an "Inferred Client" node with explanatory labels

---

## Query & Search Improvements

### Expanded Limits

| Resource | Previous Default | New Default | API Max |
|----------|-----------------|-------------|---------|
| Traces | 50 | 1,000 | 5,000 |
| Spans | 50 | 1,000 | 5,000 |
| Logs | 100 | 1,000 | 5,000 |
| Metrics | — | — | 5,000 |
| Service catalog span scan | 1,000 | 10,000 | — |

### Time Windows

| Query | Previous | New |
|-------|----------|-----|
| RED metrics | 60 seconds | 5 minutes |
| Metric series | 10 minutes | 1 hour |

### Smart Auto-Refresh

- Auto-refresh (5-second interval) checks for active search filters before refreshing
- If any search input has text on the current tab (traces, spans, logs, metrics), refresh is skipped
- Resumes automatically when the search is cleared

---

## Service Catalog

- **Traces button** — New "Traces" action button alongside Spans, Logs, and Metrics
- Navigates to the traces tab with the service name pre-filled in the search filter

---

## UI Polish

### Scrollable Lists

- Trace, span, and log list containers now support vertical scrolling with `max-height: 1900px` (~50 rows visible)
- Header rows are sticky (`position: sticky; top: 0`) so column labels remain visible while scrolling
- Removed "Showing last 50..." limit note messages from all list views

### Browser Cache Busting

- Dynamic `cache_bust` template variable (server startup timestamp) on script tags
- `Cache-Control: no-cache` middleware for static JS and CSS files

---

## Files Changed

### Frontend (static/)
- `tinyolly.js` — Deep link handler, `showTraceDetail` import, `filterTraces` on window
- `traces.js` — URL state management, Copy Link button, auto trace map render, removed toggle
- `spans.js` — Copy Link button in span detail
- `tabs.js` — Search-aware auto-refresh, deep link popstate handler, traceId-aware initTabs
- `api.js` — Fetch limits raised to 1,000 for traces/spans/logs
- `serviceCatalog.js` — Traces button + `viewServiceTraces` handler
- `traceMap.js` — Per-trace graph visualization (created in v2.2.0, refined sizing)
- `serviceMap.js` — Dark mode fix with `getComputedStyle()`

### Backend (app/)
- `query.py` — API max limits raised to 5,000, defaults to 1,000. Metric time windows expanded
- `main.py` — `cache_bust` template global

### Storage
- `storage_sqlite.py` — Service catalog span scan 10,000, RED metrics 300s window, metric series 3,600s window

### Templates
- `styles.html` — Scrollable list containers, sticky headers, trace map CSS
- `tinyolly.html` — Dynamic cache bust on script tag

### Infrastructure
- `middleware.py` — Cache-Control headers for static files

### Documentation
- `README.md` — Updated key features
- `docs/index.md` — New feature bullets
- `docs/technical.md` — Expanded UI Features section
- `.gitignore` — Comprehensive update
