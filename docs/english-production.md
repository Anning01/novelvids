# English dialogue and consistent character voices

[English README](../README.en.md) · [中文 README](../README.md)

## Set the shared language

An administrator selects **English** in **Settings → General settings → System language** and saves. This changes the interface and the language requested for future analysis, extraction, storyboard, assistant and video-generation tasks. Other open pages synchronize when they regain focus or reload.

The setting is shared by all users and projects. Existing content is not automatically translated. A submitted task or assistant turn retains the language captured at submission; retrying that task does not adopt a newly selected language. A new task uses the current system setting.

The public `GET /api/config/locale` endpoint exposes only `data.locale`. Updating the setting still requires the existing administrator permission. Browser storage is a display fallback when the server cannot be reached; it never selects generation language.

## Prepare the story and assets

Use explicit chapter headings, such as `Chapter 1: Arrival`, `Chapter II: The Signal`, or `Episode 2: Return`. Review chapter boundaries and the analysis before generating media.

New descriptions, dialogue, narration and assistant replies are requested in English. Registered character names, aliases and entity references retain their identity. New visual-trait headings follow the selected language; legacy Chinese headings remain readable. Technical reference tokens remain unchanged for compatibility and are not instructions to speak Chinese.

Keep recurring characters as the same project assets across chapters. Assign a voice at the character level. A selected variant can override that voice; without an override, it inherits the character's voice. Assign the narrator voice separately in project story settings. Voice selection does not regenerate previously produced videos.

## Upload and bind an English voice

1. Open the character's voice picker and choose **Upload audio**.
2. Provide an MP3 or WAV recording that you are authorized to use. Uploads accept a 1–30 second reference up to 15 MB. The picker can trim longer recordings into a new WAV copy; the original and existing bindings are retained.
3. Give the reference a recognizable name and select it for the character. Use clear speech from one speaker and minimize music and background noise.
4. Repeat for the other characters. For an American English production, supply references recorded in the desired accent and include the intended delivery in the scripted dialogue.
5. Select a video model whose configured capabilities permit reference audio and synchronized audio generation. Use reference-based generation with audio enabled. The model's per-reference and total-duration limits can be stricter than the upload limits.

Local files are resolved using the existing model capabilities: supported inline audio, configured object storage/public URLs, or an existing temporary-upload adapter. If a model cannot accept the available reference format, the application reports the limitation rather than silently discarding the voice.

## What is supported?

| Question | Behavior |
| --- | --- |
| Can a project produce English dialogue? | English generation requests preserve the intended dialogue meaning and request spoken English. Confirm the actual result using the chosen video model. |
| Are built-in voices English or American English? | The application does not certify a language or accent for every system voice. A Chinese label is not a capability declaration. |
| Can a Chinese voice simply be switched to English? | There is no guaranteed universal switch. Cross-language voice behavior depends on the provider and model. |
| Can I upload my own English reference? | Yes. Upload MP3/WAV and bind the resulting voice asset to the character. |
| Are dialogue and voice references sent to Seedance? | In a supported reference generation mode with audio enabled, the request includes dialogue, reference audio and an explicit speaker-to-audio mapping. |
| Is lip synchronization guaranteed? | The prompt requests synchronized visible speech. Accent, fidelity and lip synchronization require listening and visual inspection of actual results. |
| Do voices persist across chapters? | The same character asset retains its voice binding. Variant overrides remain explicit, and the narrator is bound at project level. |
| Which provider should I use? | Select a configured model that advertises the necessary reference-audio capabilities. No new TTS provider or certified built-in English voice pack is introduced by this release. |

## Two-chapter acceptance sample

Use separate references for Alex Reed, Morgan Lee and the narrator. Keep all three bindings identical in both chapters.

```text
Chapter 1: Arrival
Rain ticked against the station window. Alex Reed held a brass key.
"Did you hear the signal?" Alex asked quietly.
Morgan Lee looked toward the locked door. "Twice. Then it stopped."
For the first time that night, the station clock began to move.

Chapter 2: The Signal
The same clock struck one. Alex still held the brass key.
"Stay here," Alex said. "I'll check the platform."
Morgan shook their head. "We go together."
Outside, three short notes sounded through the rain.
```

Verify:

- Both chapters are detected and keep the same two character identities.
- English analysis and generated shot text retain the story's facts.
- Each chapter uses the same reference IDs; any appearance variant preserves or explicitly overrides the voice.
- Narrator, Alex and Morgan map to the intended final reference-audio positions, including after deduplication.
- Spoken lines are English, recognizable speakers do not swap, and the desired American accent is present.
- Visible speaking mouths follow the dialogue; narration is not assigned to an on-screen speaker by mistake.
- Changing the system language after submission does not alter the running task's language.

Automated request-contract tests verify reference transmission and binding. They do not certify generated sound or lip synchronization. Real-model acceptance needs working local test configuration and authorized recordings; record the model, settings and observed results before making quality claims.

## Translation maintenance

Frontend messages are grouped by feature in `web/src/i18n/messages.json`; each Chinese source message has an English translation. Use `tr(source, { p0: value })` for display text and explicit interpolation. Keep identifiers, persisted enums, reference tokens and user content outside translation calls. The translation tests check placeholder parity.

Backend-owned errors use `utils/messages.json` and `localized_message`. Provider details and user values are interpolated without translation. Editable prompt bodies live separately in `prompts/templates/en/` and `prompts/templates/zh/`. Pure renderers in `prompts/` select the language version; services supply language snapshots and business context explicitly. See [Customizing prompts and rules](../README.en.md#customizing-prompts-and-rules-developers) for the file map, editing rules and restart requirements.
