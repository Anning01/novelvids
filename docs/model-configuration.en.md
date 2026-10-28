# Model configuration and first run

[README](../README.en.md) · [中文](model-configuration.md)

## First-run checklist

1. Open Settings and configure an enabled text model, including its API endpoint, Key, model ID and prices.
2. Select **Creation assistant** as a capability and enable **Multi-turn tool calling**. Enable the assistant in General settings; with authentication enabled, the global assistant setting is managed by a super administrator.
3. Configure the image and video services you intend to use separately. Model access and billing are provided by those services.
4. Import one short chapter, review extraction, then try a small storyboard before submitting paid media generation.

Empty model presets do not include API access. The assistant is a prerequisite for new creation tasks; image and video keys alone do not configure it. A text model alone can start the analysis, asset and storyboard planning path.

## Model categories

Model configurations are stored in the database and managed under **Settings → Model settings**. Configure task capabilities, pricing, discounts and activation there.

### Language and video-understanding models

The text-model integration uses the OpenAI-compatible protocol. Configure the display name, base URL, API key, model ID and supported capabilities.

| Setting | Purpose |
| --- | --- |
| Capabilities | Select extraction, storyboard planning, project analysis, remake or creation assistant as appropriate. |
| JSON output | Enables structured JSON response mode for compatible models. |
| Multi-turn tool calling | Required for the creation assistant; JSON output alone is insufficient. |
| Context characters / output tokens | Set limits supported by the provider or proxy. |
| Thinking mode | Use the model default or explicitly enable/disable supported reasoning behavior. |
| Concurrency | Controls parallel requests, including remake shot analysis. |

Select **Remake** only for models that support video input. The model name alone does not establish its capabilities.

### Image models

| Configured type | Protocols |
| --- | --- |
| Doubao Seedream 5.0 Lite / Pro / Flash | `volcengine_ark`, `openrouter_compatible` |
| GPT Image 2 | `openai_compatible`, `openrouter_compatible` |

### Video models

The selected `video_model_type` determines the adapter. Backend capabilities validate media, duration, aspect ratio, resolution and protocol.

| Configured family | Integration | Protocol |
| --- | --- | --- |
| Doubao Seedance 2.0 / Fast / Mini | Reference media, keyframes and synchronized audio | `volcengine_ark` |
| Doubao Seedance 2.5 | Extended reference limits and system audio assets | `volcengine_ark` |
| MiniMax H3 | Image/video/audio references and keyframes | `minimax` |
| Wan3 | Text/image/keyframe/reference modes and temporary media uploads | `dashscope` |

Available settings and limits come from the configured capabilities. Provider availability and generated quality must be verified for your deployment. Multiple configurations can be enabled for the same task type.

## Assistant budgets

These are application presets for long-context conversations, not universal provider limits. Adjust them under **Advanced settings** to match the configured model.

| Setting | Default |
| --- | --- |
| Working context budget | 840,000 estimated input tokens |
| Context character limit | 2,000,000 characters |
| Compaction trigger / target | 70% / 45% |
| Output per call / total per turn | 64,000 / 2,000,000 tokens |
| Model calls / tool calls per turn | 20 / 50 |
| Objects per turn / run timeout | 32 / 600 seconds |
| Recent history turns / text page length | 12 / 4,000 characters |
| Summary output / timeout | 4,000 tokens / 30 seconds |

Lower model-level limits still apply. Per-turn usage includes multiple calls; compaction does not refund consumed tokens. Original conversation records remain available. Cache usage and charges depend on provider reports and configured prices.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Assistant is not configured | Enabled text model, Creation assistant capability, tool-calling support and the global assistant switch |
| No image/video model is selectable | Correct task category, provider protocol, model type, enabled status and team model source |
| Authentication or IP restriction from a provider | Endpoint, Key permissions and provider IP allowlist; do not paste the Key in an issue |
| Long requests or truncated JSON | Actual context/output limits of the configured model or proxy, assistant budgets and provider error code |
| Video probe/merge/remake/enhancement fails | FFmpeg and ffprobe must be available in the backend runtime, and media must be reachable |
| A target resolution is disabled | Enable and price it in the enhancement service; the target must exceed actual source dimensions |

The current backend Dockerfile does not install FFmpeg. In the running container, install it with `docker compose exec -u root backend sh -c 'apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*'`, then check `docker compose exec backend ffprobe -version`. Repeat after rebuilding that image. Local development requires FFmpeg on the backend host's PATH.

Existing complete prompts are reused by default. If you change a style or skill, optimize and save the prompt before regenerating existing assets. See [skill customization](agent-skills-workflow.en.md).

MediaKit is a separate **Video enhancement** configuration, not a video-generation model. See [video enhancement](video-enhancement.en.md).
