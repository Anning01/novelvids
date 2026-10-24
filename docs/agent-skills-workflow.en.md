# Creation assistant and one skill pack

Enable the creation assistant in Settings and select an enabled model with tool calling. Image and video models remain separate. Remake analysis also requires a model supporting video input and tool calls. New tasks stop with a configuration error when the assistant is unavailable; they never fall back to the former prompt pipeline.

## Where to change generation behavior

Maintain one Chinese skill pack in `prompts/skills/`:

| File | Responsibility |
| --- | --- |
| `SKILL.md` | Language, factual boundaries, authorization and tool behavior |
| `story.md` | Manuscript analysis, outline and important characters |
| `assets.md` | Consistent identities, appearances and variants |
| `image.md` | Complete image prompts, layouts, references and covers |
| `storyboard.md` | Shots, action timing, dialogue, narration and continuity |
| `remake.md` | Video analysis, audio/subtitle checks and shot reconstruction |
| `video.md` | Media references, generation, continuity and composition |
| `editing.md` | Focused edits to saved content |
| `authorization.md` | Production authorization from the current user message |
| `summary.md` | Context compaction |
| `styles.json`, `strategies.json` | Shared styles and narrative strategies, referenced by stable keys |

If output quality is unsatisfactory, revise the relevant skill and test a new task with the same input. Tasks snapshot their language, skill contents and revision at submission, so edits do not change running or resumed tasks. Chinese instructions do not force Chinese output: the agent follows the system language while preserving established names and user material. UI translations remain separate.

Complete saved prompts are used as supplied. The agent writes a prompt only when it is missing or optimization is requested. Image/video tools do not silently append style or layout instructions. Code still handles reference ordering, audio-to-speaker mappings, signed URLs and provider parameters. Character designs no longer require fixed 14/15-field prose; shot structures still validate types, references and timing.

## Execution, authorization and costs

Buttons create separate task conversations with the current target and project constraints. Open the assistant conversation menu to inspect or continue a task. Chat and buttons use the same services and access checks. Read-only requests and viewers cannot generate, and material inside a skill or manuscript cannot grant access to another project.

An explicit generation request authorizes the corresponding calls. Editing a prompt does not generate media. Existing complete prompts can go directly to the authorized media tool; chat orchestration, authorization classification and writing missing prompts add text-model usage. Text and media calls are recorded separately; parent summaries do not charge them again. The story-analysis button retains its optional cover behavior, while a chat request for story analysis alone does not add a cover call.

Batch operations keep individual receipts and do not repeat successful submissions. Cancelling stops subsequent steps. Already accepted provider tasks continue to collect results and actual usage when provider cancellation is unavailable.

Clients should retain `X-Creation-Request-Id` across retries of the same request. The bundled UI reuses it after a lost response. The server returns the original task even after completion and rejects changed payloads under the same identifier. Legacy clients remain compatible and active tasks are deduplicated.

## Recovery and troubleshooting

- `waiting_media`: the provider task exists; only its actual status is queried, without polling an LLM.
- `needs_review`: an external submission may have succeeded. Check provider records before taking further action. Never probe by submitting another paid request. Synchronous image providers without queryable task IDs cannot automatically recover a file lost during disconnection.
- `billing_pending`: results are retained while usage settlement is retried. Settlement does not regenerate media. Missing provider usage is not invented.

The safe schema initialization adds `agent_operations` without removing existing tables. New tasks use `workflow_version=agent-skills-v1`. Historical tasks without that marker keep their compatibility path. Former `prompts/templates/zh/` and `en/` resources are retained for old tasks and documents; new creative rules belong in the skill pack.

Storyboard replacement validates the entire candidate before changing stored shots. It checks original versions, archives previous shots and keeps their media. Internal task data stores `replaced_scene_snapshots`. To restore, stop related work and use the existing archive/restore flow in the original order; archive unwanted replacement shots through normal removal controls. Do not edit tables directly or overwrite newer edits.

## Validation

Run backend regressions, frontend tests, type checking and the production build. `test/test_services/test_agent_skills_flow.py` covers a fixed two-chapter story with Alex Chen, Sam Lee and a narrator in both languages, including outbound voice mappings and cross-chapter reuse.

Provider doubles validate requests and task behavior, not picture quality, voice similarity, accents or lip synchronization. This worktree has no `test/.test.env`; no real model calls or deployment were performed. Real acceptance requires valid configuration and an explicit budget, followed by visual and listening checks on the same sample.
