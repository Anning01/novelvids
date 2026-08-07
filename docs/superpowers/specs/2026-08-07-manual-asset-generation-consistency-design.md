# Manual Asset Generation Consistency Design

## Goal

Keep character metadata, the selected asset scope, task status, and visible reference images consistent throughout extraction and batch generation without making an additional AI request.

## Data flow

The extraction model already returns fixed `性别` and `年龄` lines in each single-character `base_traits`. A deterministic backend normalizer will parse those returned values, map them to the UI enums (`男`/`女`/`其他（动物）` and `儿童`/`少年`/`青年`/`中年`/`老年`), and persist them in asset metadata during the existing extraction transaction. Group portraits will not receive single-character gender or age metadata. An older chapter result will not overwrite metadata that corresponds to a newer visual description.

Batch generation will retain the active asset scope. Completion and the toolbar refresh action will call the scope-aware asset refresh instead of reloading the whole project. This updates cards in place and avoids replacing a current-chapter list with the project-wide list.

Reference-image tasks may complete only when at least one generated image has been downloaded and persisted. Downloads will follow redirects. Individual download failures remain logged at the service boundary; if every image fails, the handler raises an error so the shared task executor records `FAILED` instead of `COMPLETED` with an empty image list.

## UI behavior

While an asset is generating and has no image, its media area shows a restrained shimmer, a centered spinner, and “正在生成参考图”. The summary count uses a pulsing dot. Motion is disabled under `prefers-reduced-motion: reduce`. Completion refreshes the current list in place.

## Tests

- Backend persistence tests cover Chinese/English gender and age values, numeric age ranges, animals, group portraits, and newer-chapter precedence.
- Reference handler tests prove an empty provider response and total download failure cannot complete successfully, while a persisted image remains successful.
- Frontend tests prove batch completion and toolbar refresh preserve current-chapter filtering.
- A component/source-level UI test verifies the generating placeholder and reduced-motion rule.

## Non-goals

- No additional AI call or extraction schema field.
- No provider-specific fallback.
- No dependency, lockfile, database schema, or API contract change.
