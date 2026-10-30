# Creation guide

[README](../README.en.md) · [中文](creation-guide.md)

Start with one short chapter, review analysis and asset identities, then generate a small number of shots. Convert legacy DOC files to DOCX or plain text first; scanned PDFs need OCR before import. The storyboard and canvas edit the same project objects; you do not need two copies of your settings.

## Features

### Manuscripts and projects

- Paste text or import DOCX, TXT, PDF and Markdown files.
- Analyze the story, identify chapter boundaries and plan reusable assets.
- Set the project's aspect ratio, resolution, visual style and storyboard strategy.
- Switch between light, dark and system appearance, with locally saved preferences.

### Chinese and English

- One administrator-controlled **System language** setting governs the interface and future generation tasks across the installation.
- New installations default to English; existing saved language settings are retained.
- Existing manuscripts, assets, prompts, conversation history and media are not automatically translated.
- Submitted tasks and assistant turns retain their language snapshot, including on retry.
- English chapter headings, dialogue, narration and uploaded voice references are supported. See the [English production guide](english-production.md) for setup, limitations and a two-chapter acceptance sample.

### Remake studio

- Start from one MP4/MOV video, a folder of episode videos, or an eligible existing project.
- Each source video can be up to 500 MB and 20 minutes. Folder mode recognizes episode numbers such as `EP12`, `E12`, `第12集`, `第12话` and `12集`, then sorts the episodes.
- Extract global characters, locations and props before detecting shot boundaries and generating detailed shot prompts.
- Reuse the existing asset editor, storyboard view and infinite canvas.
- Background analysis continues when the browser closes. Reopen the project to recover saved progress.
- Stream episode and stage progress through SSE; retry failed episodes independently.
- Configure video understanding as an LLM's **Remake** capability, with controlled concurrency and a ten-minute per-request timeout.

### Assets and variants

- Extract characters, locations and props, consolidating aliases for the same entity.
- Generate all three asset types in a batch, or use uploaded images and image-to-image references.
- Retain generation history and select the current image version.
- Create character outfits, age or state changes, location states and prop variants, each with its own references and optional voice override.
- Merge assets and bind them to chapters. Storyboard and canvas views share the same relationships.

### Storyboards and prompts

- Choose **Cinematic narrative** or **Narrated story** at project creation or while editing story settings.
- Use a project narrator voice, with narration and inner monologue scheduled outside character dialogue.
- Produce self-contained shot prompts covering time, environment, positions, action timing, camera movement and sound.
- Reference assets with `@{Asset Name}` and audio with `@音频N`. Technical reference tokens remain stable across interface languages.
- Edit prompts visually and preview referenced images or play audio from their tags.

### Storyboard view and infinite canvas

- Edit shot descriptions, assets, prompts, generation parameters and results together.
- Pan, zoom, select, arrange, copy, paste, undo, redo, collapse and group nodes on a Vue Flow canvas.
- Drag in reference media using the same multimodal protocol as the storyboard view.
- Persist selected models, aspect ratios, resolutions and canvas viewport settings.

### Voices and audio references

- Choose system voices or upload MP3/WAV voice references.
- Preview duration and trim longer recordings into a new copy without changing the original.
- Assign voices to base characters, individual variants and the project narrator.
- Send an explicit speaker-to-audio mapping with supported video generation requests.
- Resolve local or remote audio according to the configured model's capabilities and storage setup.

Voice bindings persist across chapters when the same project assets are reused. They do not guarantee identical sound, a particular accent or perfect lip synchronization. Built-in voice names are not language capability declarations; verify the selected model with authorized English recordings.

### Video generation and episode composition

- Use a configuration-driven factory for reference-based or first/last-frame video generation.
- Set each shot's model, duration, aspect ratio, resolution, audio and continuity options.
- Generate selected shots in bulk. Sequential mode feeds each shot's last frame into the next shot automatically.
- Extract a last frame with FFmpeg when the provider does not return one.
- In reference mode, upload that image and bind its first-frame purpose to its final image index. This guides continuity without strictly locking the opening frame. For strict keyframes, use the model's first-frame or first/last-frame mode; the modes cannot be mixed. Legacy `first_frame_reference` JSON is converted for submission without rewriting saved shots.
- Reconcile queued and running provider tasks in the background even after the browser closes.
- Compose available shot videos in episode order and download the result.
- Browse images, audio, videos and generation versions in the media library.

### Models and costs

- Configure and enable multiple text, image and video models.
- Keep capabilities, limits, protocols, defaults and pricing in backend configuration.
- Record tokens, image counts, video duration, input references, pricing snapshots, discounts, costs and request duration.
- Filter costs by project and inspect paginated usage records.
- Group assistant costs by conversation while retaining original call records and avoiding duplicate billing.
- In team mode, check balances before submission and charge completed usage. Currency units are preserved when switching language.

## Creation assistant

### Capabilities

- **Find, create, edit and remove:** manage characters, locations, props, variants and shots within selected-object, chapter or project scope.
- **Shared prompt standards:** reuse the application's image and storyboard rules. Precise edits preserve unrelated actions, audio and references.
- **Memory:** retain recent conversation and save explicit ongoing user requirements for the relevant project, chapters or objects.
- **Bounded context:** query objects as needed, read long text in pages and compact older working context while retaining original records.
- **Inspectable changes:** show diffs and undo actions. Idempotent requests avoid duplicate writes; version conflicts prevent overwriting newer edits.

The assistant coordinates settings, storyboards, images, videos and composition. Existing workspace buttons and chat share the same skills and execution boundaries. An explicit generation request authorizes the corresponding model calls.

### Enable and use

1. Add an LLM under **Settings → Model settings**. Select **Creation assistant** and enable **Multi-turn tool calling**.
2. Enable the assistant under **Settings → General settings → Creation assistant**. With authentication enabled, global assistant configuration is managed by the super administrator.
3. Open the assistant from the settings workspace, storyboard or canvas. **Edit with assistant** can reference a specific object directly.
4. Select the scope and describe your request, such as “Make only this shot's lighting warmer; preserve the action and sound.”
5. Review the recorded changes, expand diffs or undo. Conversations can be created, switched, deleted and restored.

On desktop, the assistant sits beside the workspace. Messages, query results, changes, memory, usage and references can be collapsed. See the [UI attribution notice](../web/src/features/creation-agent/beautiful-ui.NOTICE.md).

### Page routes

Routes use hash navigation: append `/#` followed by a path to the application URL.

| Page | Path |
| --- | --- |
| Short drama creation | `/create/short-drama` |
| Remake studio | `/create/remake` |
| Agent workspace | `/create/short-drama/agent/:projectId` |
| Manual workspace | `/create/short-drama/manual/:projectId` |
| Storyboard / canvas | `/create/short-drama/storyboard/:projectId` |
| Settings | `/settings` |
| Cost dashboard | `/billing` |

## More guidance

- [Model configuration and budgets](model-configuration.en.md)
- [English dialogue and uploaded voices](english-production.md)
- [Video enhancement](video-enhancement.en.md)
- [Customize one skill pack](agent-skills-workflow.en.md)
