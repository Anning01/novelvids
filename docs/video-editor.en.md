# Episode video editing

[中文](video-editor.md)

The editing workspace has a media library on the left, a bounded preview in the center, selected-clip properties on the right, and video, music, subtitle and sticker tracks below. The preview and timeline can be resized; narrower windows use drawers.

## Workflow

- **Canvas size** controls output dimensions using ordinary resizing and padding. It does not run AI enhancement; use storyboard or canvas enhancement for that.
- Existing episode shots create the initial timeline. Saved edits keep explicit source video IDs, so later generation or enhancement never silently replaces an edited source. Use **Replace with current shot video** when desired.
- Import video, MP3/WAV/M4A music, and static PNG/WebP stickers, or select a team-library video. Media is reusable within the project. Browsing does not insert it: use **+** to add it to the timeline.
- Edit clip timing, source trim points, speed, volume, framing, BGM fades/looping, subtitle content/style and sticker position/opacity. Subtitles support plain text and SRT import. Source files are not modified. Removing a clip only changes the draft.
- Dragging has keyboard and numeric-input alternatives. Main video clips cannot overlap; overlays and audio can use multiple lanes. Undo/redo applies to the current chapter.
- Drafts save automatically with optimistic revisions. A conflict preserves local edits and stops automatic overwrites. Browser-session recovery is scoped to user, team, project and chapter. Export requires a successful save.
- **Shot files ZIP** downloads the existing shot videos in sequence from the browser. **Export video** renders the saved edited timeline into a new file. It calls no generation model and creates no model-usage charges. Export jobs, progress, cancellation, retry and completed downloads are persistent.

## Runtime and storage

The additive `chapter_edit_drafts` and `editor_assets` tables preserve existing chapters, media history, seeds and billing data. Project/team access and viewer restrictions use existing checks. No API accepts source paths, arbitrary URLs, shell commands or FFmpeg filter strings. Imported media is checked by actual content, size, format and duration.

Rendering requires FFmpeg with libx264, AAC, drawtext, overlay and amix, plus Fontconfig and a Chinese-capable font. Backend Dockerfiles include `ffmpeg fontconfig fonts-noto-cjk`; manual installations need equivalent system packages. Python/npm dependencies and lockfiles are unchanged.

Jobs use `AiTask` and `ChapterExport`, with a database lease and a single local encoder. Input media is processed on persistent disk, one video normalization at a time; still-image overlays are batched. Temporary files use `CHAPTER_EXPORT_PATH`, outside public media storage. Downloads retain the existing export access checks. Matching content reuses the same export; retry after failure only repeats deterministic local rendering.

Server limits are configured through `VIDEO_EDITOR_MAX_DURATION_SECONDS`, `VIDEO_EDITOR_MAX_OVERLAYS`, `VIDEO_EDITOR_MAX_AUDIO_TRACKS`, `VIDEO_EDITOR_MAX_SOURCE_MB` and `VIDEO_EDITOR_RENDER_TIMEOUT`, and are returned by the capabilities API.

## Verification and limits

SQLite and an isolated PostgreSQL 14.19 instance were checked for additive initialization, repeat startup, retained legacy data and concurrent-save conflicts. Real local videos were imported, edited, exported and downloaded in the browser across two isolated chapters. A 1280×720, 24fps, six-second H.264/AAC result was decoded successfully and checked for subtitle, sticker and audio output. Multiclip audio uses PCM intermediates to avoid per-clip AAC timestamp overlap.

All 787 frontend tests, type checking and production build passed, alongside 1492 backend tests and 38 permission checks. Light, dark and narrow-screen layouts were checked. The preview adds no extra padding and preserves the canvas aspect ratio.

Production long-form throughput and real OSS transfers have not been separately accepted. The new workflow reuses the existing OSS provider. This release covers desktop-oriented editing with responsive drawers, manual/SRT subtitles and static stickers; transitions, keyframes, automatic transcription, animated stickers and video picture-in-picture are outside its scope. No live generation model was called during acceptance.
