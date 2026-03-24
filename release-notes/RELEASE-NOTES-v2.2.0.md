# TinyOlly v2.2.0

**Release Date:** March 2026

Storage and UI improvements focused on data retention and trace usability.

---

## Highlights

- **Space-Based Data Retention** — Replaced time-based TTL with space-based eviction. Data is retained until the database reaches its size limit (default 256 MB), then oldest records are automatically evicted. No more 30-minute TTL — data stays as long as there's room.

- **Click-to-Copy IDs** — Trace and span IDs are now copyable with a single click throughout the UI (trace list, trace detail, spans list, and logs). Works on both HTTPS and HTTP (clipboard API with execCommand fallback).

- **Correlated Log Navigation** — Trace detail view shows correlated logs inline. Click any log row to navigate directly to the Logs tab filtered by that trace ID. Log view trace/span links navigate to the corresponding trace or span detail.

- **Cleaner Trace Waterfall** — ASGI internal sub-spans (`http send`, `http receive`) are automatically filtered from the waterfall view, reducing noise for HTTP traces.

---

## Storage Changes

- Removed `expires_at` filtering from all read queries (traces, spans, logs, metrics, stats)
- Removed time-based DELETE cleanup from the periodic cleanup task
- Retained KV cache TTL expiration (for ephemeral internal caches only)
- Added `span_index`, `trace_index`, and metrics index tables to the space-based trim plan
- Eviction uses 90% high-water / 80% low-water marks on `MAX_DB_SIZE_MB`

## UI Changes

- Added `.copyable-id` CSS class with hover/copied states
- Added `setupCopyableIds()` utility with clipboard API + `execCommand('copy')` fallback
- Filtered `http send` / `http receive` spans from trace waterfall rendering
- Added `correlated-log-row` click handlers for trace-to-logs navigation
- Cross-tab navigation via `navigateToTabWithFilter()` for log↔trace↔span linking
