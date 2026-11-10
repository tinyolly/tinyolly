# Trace Accuracy & Waterfall Plan

Date: 2026-11-09 · Status: in progress (item 1 done, rest not started) · Branch: `modernize/phase-4-otel-demo` (follow-up; fits modernization Phase 5 "UI gaps")

## Goal

Be able to *prove* that what the trace waterfall shows matches what the services emitted, and fix the places where it
does not. "It looks right" is not evidence: a waterfall can be drawn confidently from wrong or incomplete data.

## Verification layers

| Layer | Question | Method | Status |
|---|---|---|---|
| 1. Stored data | Is what TinyOlly stored internally consistent? | `scripts/check-trace-integrity.py` (API only): unique span ids, one root, parents present, child inside parent window, summary count/duration/start == real spans | **Done** — 300 live demo traces / 2,503 spans: no hard failures |
| 2. Independent reference | Did TinyOlly store what was actually sent? | Run Jaeger all-in-one (~100 MB) fed by a second exporter on the same collector; diff span-by-span (ids, parent, start offset, duration, status, attributes) via both APIs | Planned (A) |
| 3. Rendering | Does the drawn bar match the data? | Headless-browser test comparing each `.span-bar` `left`/`width` to values computed from the API | Planned (B) |

## Findings so far

1. **Sticky table header was transparent** — rows scrolled visibly through it. Cause: `.data-table-header` used `var(--bg-secondary)`, which is **not defined in either theme** (9 other uses). **Fixed** (header now `var(--bg-hover)`, opaque). The other 8 uses of `--bg-secondary` still resolve to nothing; audit in item F.
2. Waterfall is a **flat list in API order (chronological by start)** — no parent/child nesting.
3. Waterfall draws only the **first 100 spans**; demo checkouts reach 136–168 spans, so 36–68 are hidden (a warning is shown). The time axis is computed from the truncated list although the code comment says "use all spans". In the 3 big traces measured the axis was still correct (root is in the first 100), but it is wrong whenever a late-ending span is in the hidden part.
4. Span timestamps are **nanosecond strings coerced to `Number`** (> 2^53): ~256 ns error — negligible at ms scale, visible for µs-scale spans.
5. **In-flight traces** are shown without their root (load-generator roots are long-running and export late; they appeared ~20 s later) and nothing tells the user.
6. One child ended 1.09 ms after its parent (frontend-proxy → frontend): proxy/async timing, not a TinyOlly bug — keep as a tolerance case.

## Work items (in order)

| # | Item | Detail | Acceptance |
|---|---|---|---|
| 1 | **Sticky header fix** | Opaque header background | **Done** (verify visually in light + dark theme) |
| 2 | **Nest spans by parent** | Build the tree from `parentSpanId`; indent by depth; order siblings by start time; collapse/expand a subtree; keep a flat fallback when the tree can't be built | A 50-span checkout shows the real call hierarchy; orphan spans are grouped under a "missing parent" row instead of being dropped |
| 3 | **Fix the 100-span cap** | Compute axis from *all* spans; render all rows with virtual scrolling or "load more" (+100) instead of silently hiding; show "N of M spans" | 168-span trace: all spans reachable; axis identical whether or not rows are expanded |
| 4 | **BigInt timestamps** | Parse `startTimeUnixNano`/`endTimeUnixNano` as BigInt, convert *offsets* to Number only after subtracting | 123 µs span offsets exact to the ns in a unit test |
| 5 | **Incomplete-trace indicator** | Backend adds `missing_parent_count` / `is_complete` to the trace summary; UI badge "partial — N spans pending" and auto-refresh while partial | The 4 rootless traces seen in testing show the badge and clear it when the root arrives |
| 6 | **Min visible bar width / selected-span detail** | Very short spans get a 1–2 px minimum so they are not invisible; hover tooltip with start offset + duration | Sub-ms spans in a 100 ms trace are visible |
| F | **Undefined CSS variable audit** | Define or replace `--bg-secondary` (8 remaining uses); add a CI check that every `var(--x)` used in `templates/`+`static/` is defined | Check fails on an undefined variable |
| A | **Jaeger reference diff** | Add `jaeger` service (compose profile `verify`, not on by default) + second exporter in a verify-only collector preset; `scripts/diff-with-jaeger.py` compares N traces; reports missing/extra spans and any start/duration/parent/status differences beyond tolerance | 200 demo traces: zero differences except documented tolerances |
| B | **Render test** | Playwright (or similar) test that loads a trace, reads each bar's computed style and compares to `check-trace-integrity`-style expected positions (±0.5 px); runs against a canned trace fixture, not live data | CI-able; fails if offset/width math regresses |
| C | **Fixture traces** | Hand-built OTLP traces covering: deep nesting, siblings overlapping, µs spans, clock-skewed child, orphan span, 200+ spans, duplicate span id | Used by items 2–5 and B |
| D | **Integrity script in CI** | Run `check-trace-integrity.py` against the compose smoke test (Phase 6) | CI job green on demo traffic |

## Notes / constraints

* 8 GB host: Jaeger and a headless browser are optional and must not run together with the full demo; use the `verify` profile.
* Layer 2 validates ingest + storage + API against a source TinyOlly does not control, but not how the UI draws. Layer 3 covers drawing. Both are needed to claim the waterfall is accurate.
* Items 2–5 change `docker/apps/tinyolly-ui/static/traces.js` (+ a small backend field for item 5); keep `utils.js` helpers pure so they can be unit-tested with Node.

## Order of attack

1 (done) → C (fixtures) → 4 → 2 → 3 → 5 → 6 → A → B → F → D.
