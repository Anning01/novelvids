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

Buttons create separate task conversations with the current target and project constraints. Open the assistant conversation menu to inspect or continue a task. For remake, upload the source through the existing workflow first; chat can inspect its task or retry failed analysis using the same source and original snapshot. Chat and buttons use the same services and access checks. Read-only requests and viewers cannot generate, and material inside a skill or manuscript cannot grant access to another project.

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

## Authorization and reliability after PR review

Free-text classification proposes tasks. A quoted phrase is audit evidence, not permission to charge. The server derives immediate grants only from a small full-message command vocabulary and the current selection/scope (for example, `Generate image` with selected assets). Other wording presents specific operations and objects for **Confirm generation and charges**. Confirmation keeps the original scope and a stable request ID. All role, ownership, model and balance checks still run.

`agent_submissions` has a database-unique key for actor, team and client request ID. The task and its receipt commit together. Changed payloads under the same ID return 409, including while the original task is active. The UI persists unresolved request IDs across page/browser restarts; it stores hashes and IDs, without credentials or prompt text. Clearing browser storage or changing login sessions can lose the client identifier; check task history before submitting again.

Video settlement uses a unique `billing:video` receipt linking the provider task, internal parent, video and usage record. Ledger writes and balance updates share a transaction. Cancellation does not discard fees for accepted media. Failed settlement retries accounting only. Text model children keep their own usage; the parent summary is display-only. Lost responses with unknown quantities retain `missing_usage` and `submission_uncertain` flags. Known amounts are provisional and require invoice reconciliation; manual task closure preserves those flags.

For an uncertain failed task without a queryable provider ID, an authorized creator or administrator may use `POST /api/task/{task_id}/review` after checking provider records. Submit an `outcome` of `not_submitted`, `provider_failed` or `completed_unrecoverable`, plus a factual `note` of at least 10 characters. The audited result closes the task as `review_closed`; it never replays the original step, invents media/usage or submits replacement work. Provider IDs without a terminal result must be queried normally. A conflict with collected terminal evidence can be rechecked using its evidence ID.

Regressions cover adversarial text and an incorrectly classifying model, confirmation replay, independent SQLite worker processes racing on one key, replay after process restart, language snapshots, cancellation, concurrent settlement and review access controls. PostgreSQL follows the same unique-constraint/transaction path but has not been tested against an external server in this work. Real generation quality still requires valid configuration and an explicit budget.

### Independent certainty after manual review

Review records `submission_outcome_known`, `media_result_recoverable` and `usage_known` separately. Without an independently verified usage record, `not_submitted` confirms the absence of submission; `provider_failed` leaves usage unknown; and `completed_unrecoverable` confirms a completed submission and an unrecoverable result while retaining unknown usage. Media recoverability is null when it is not established or not applicable. Explicitly verified usage records retain their known state.

The compatibility `submission_uncertain` and `missing_usage` flags remain true while usage is unknown, consistently in video metadata and the ledger. Closure updates task, video, audit and existing media ledger flags in one transaction. Delayed accounting checks actual evidence before applying compatible certainty. Repeating an old review can reconcile legacy fields only while no newer provider evidence exists; new evidence uses an appended recheck audit. Booked quantities, prices, amounts and original audit identity stay unchanged. The original external step cannot replay. A separately authorized new generation uses the verified submission outcome, while the original usage uncertainty remains recorded.

### Late provider evidence and rechecks

Images, covers and videos share an evidence policy. Positive usage or completed provider output after `not_submitted`, successful output after `provider_failed`, or a changed result can reopen the task as `needs_review`. The original manual audit stays immutable; new facts are appended to a separate evidence receipt. Consistent reported quantities can fill missing usage knowledge. Configured video duration does not establish reported usage, and a reported zero is preserved.

Existing booked amounts and quantities remain unchanged. Late quantities are stored in `reported_usage.quantity`; differences retain `accounting_needs_review=true` for separate reconciliation. A completed billing receipt does not prevent examining new evidence. Repeated receipts, evidence-write retries and restarts do not generate media or charge again. A first actual usage record, when none exists, is still settled once under the original authorization.

Submission conflicts and accounting differences are independent. When both parties confirm success but the provider reports 3 images against 2 booked, `submission_outcome_known=true` and `accounting_needs_review=true`. `review_conflict` aggregates submission conflicts or accounting differences awaiting acknowledgment; it does not establish an unknown submission outcome. Acknowledging new evidence can clear it while accounting remains pending. The compatibility `submission_uncertain` flag also includes pending accounting, so submission decisions must use `submission_outcome_known`.

Read the current `request_params.review_evidence.id` from the task, then post the finding with `evidence_id` to the existing review endpoint. Recovered media supports `outcome=completed`; confirmed generation with no recoverable file uses `completed_unrecoverable`. A recheck appends a new audit without replacing the original. Stale evidence and findings contradicting provider facts return 409. Replaying an old review cannot clear a new conflict. Operational closure preserves any unresolved accounting difference and never adjusts a booked amount automatically.
