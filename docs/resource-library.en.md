# Unified team resource library

[中文](resource-library.md)

The resource library manages videos, images, BGM, sound effects, static stickers, voice references and reusable character settings. Resources can be reused across projects in the same team. The former public character and audio libraries now live here; **Project assets** retains project-specific characters, scenes and props.

## Workflow

Upload resources under their intended type. Supported formats and size limits come from the server capabilities endpoint, and actual file content is validated. Videos retain MP4/MOV support; images use JPG/JPEG/PNG/WebP, BGM and sound effects use MP3/WAV/M4A, and static stickers use PNG/WebP.

**Voice references** are distinct from BGM. Existing nicknames, gender, trimming and voice asset identities are retained. References can be bound to project narration, a character or a particular variant. Built-in resources remain read-only, and personal legacy voices retain their original access scope.

Publish a project setting explicitly with **Save to team library**. Historical `is_global` defaults do not automatically expose project content. Applying a published setting copies its traits and variants while keeping voice references; voices unavailable to the target project block the operation for review. Unrelated characters with the same name are not overwritten.

The editor's media, BGM and sticker panels can browse the team library directly. Audio can be filtered into BGM or sound effects. Previewing does not insert anything; **+** adds the resource to its matching track. Project use registers a stable reference without copying the original media. Each project controls its own timing, volume and overlays. Repeated publication of the same imported project resource reuses its completed library record.

Folders can contain multiple resource types and support two levels. Moving or renaming resources keeps their stable references. Deletion requires confirmation and can break existing references. Characters and voice references must be moved out before deleting a containing folder.

Storyboard and canvas selectors reuse the same catalog, existing nodes and model capability checks. Only compatible images/videos enter video model references. No generation model is called by catalog browsing, upload, publication or project application.

## Compatibility and access

The historical `video_resources` table and IDs are retained; its new `kind` field defaults old records to `video`. Existing video APIs remain compatible. Catalog identities include their source: `media:<id>`, `voice:<id>`, `human:<id>` and `asset:<id>`. New `resource_placements` and `project_resources` tables add organization and project links without rebuilding old voice, character or variant records.

Lists, lookup, upload finalization, edits, project application and export resolve actual team/project ownership on the server. Viewers cannot perform writes. Platform administrators must explicitly select the target team. Existing voice and digital-human APIs remain available. `/assets` and `/videos` retain project navigation; legacy public-scope links redirect to the matching resource category.

Schema changes are additive. Back up the database before deployment; code rollback can retain new fields and tables. Seed records are still initialized only when their table is empty. Billing behavior is unchanged.

## Verification

Real local files were uploaded and used in two isolated SQLite projects through the browser, including shared BGM, stickers, voice upload, character variants and voice binding. A six-second 1280×720, 24fps H.264/AAC export containing team BGM and a sticker was downloaded and decoded successfully. Audio analysis confirmed the BGM test signal in the output. No paid model call was made.

An isolated PostgreSQL 14.19 instance verified legacy field initialization, identity/text retention, repeated startup, unchanged seed data and concurrent project-link uniqueness. Light/dark and narrow layouts were checked. OSS direct upload/finalization is covered with a simulated provider and reuses the existing storage implementation; live OSS account networking and access policies were not separately tested. Stickers currently support static images only.

Engineering checks passed: 805 frontend tests, type checking and production build; 1507 backend tests, with 238 skips in the auth-disabled/environment-dependent run; and 37 separate permission checks with authentication enabled. Measured coverage for the new catalog services/protocol was 84.84%. `git diff --check` passed. No live generation model was called for this resource-library acceptance.
