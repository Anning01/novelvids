<p align="center">
  <img src="docs/images/logo.png" width="200" alt="NovelVids logo">
</p>

<h1 align="center">NovelVids · 猫影短剧</h1>

<p align="center">
  <strong>An open-source workspace for illustrated stories and short dramas, available online or on your own server.</strong>
</p>

<p align="center">
  Bring stories, character assets, storyboards, AI images, video generation and episode assembly<br>
  into <strong>one project you can edit, track and keep refining</strong>.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <a href="https://shortdramas.xiazq.com"><img src="https://img.shields.io/badge/online-hosted%20service-6864e8" alt="Hosted commercial service"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/language-中文%20%2F%20English-555" alt="Chinese / English"></a>
</p>

<p align="center">
  <strong>English</strong> &nbsp;|&nbsp; <a href="README.md">简体中文</a>
</p>

<p align="center">
  <a href="#join-the-community">Join the community</a> · <a href="#video-tutorial">Video tutorial</a> · <a href="#example-videos">Example videos</a> · <a href="https://shortdramas.xiazq.com">Create online</a> · <a href="#quick-start">Get started</a> · <a href="#local-development">Local development</a> · <a href="#development-and-community">Contribute</a> · <a href="#support-the-project">Support the project</a>
</p>

## Join the community

Join the **NovelVids · 猫影短剧 WeChat group** to discuss AI animation, short dramas, model workflows and open-source deployment.

<p align="center">
  <a href="docs/images/wechat-group-qr.jpg"><img src="docs/images/wechat-group-qr.jpg" width="320" alt="NovelVids WeChat group QR code, valid before November 15, 2026"></a>
</p>

<p align="center">
  Scan with WeChat · <strong>Updated November 8, 2026; valid before November 15.</strong><br>
  Group QR codes expire after 7 days. If this one has expired, check the latest version of the repository home page.
</p>

## Create online

**[Open the NovelVids commercial service →](https://shortdramas.xiazq.com)**

Sign in with Qiling through WeChat. Start with an image or video idea, add reference material, or develop a story into a short drama. The hosted service provides model selection, team collaboration, usage records and top-ups. Generation fees follow the displayed estimates and actual usage.

The hosted service uses the source code and creative rules in this repository. Self-hosting includes the same Qiling sign-in, team management, usage billing and WeChat Pay integrations. Each operator configures their own services.

## Video tutorial

**[Watch the tutorial on Bilibili →](https://www.bilibili.com/video/BV12JW76dEkj/)**

Watch the tutorial to learn how to use NovelVids. For finished creations, see the example videos below.

## Example videos

**Commercial remake example**

[![Commercial remake preview; click to watch on YouTube](docs/videos/demo-preview.gif)](https://youtu.be/fdiw__J19uk)

[Watch the commercial remake on YouTube](https://youtu.be/fdiw__J19uk)

**Illustrated drama example**

[![Illustrated drama preview; click to watch on YouTube](docs/videos/comic-preview.gif)](https://youtu.be/NAuIKfsSero)

[Watch the illustrated drama on YouTube](https://youtu.be/NAuIKfsSero) · Visual style: 3D xianxia; storyboard strategy: narrated storytelling. Generated automatically from story to finished video, without manually editing prompts or AI-generated prompts. Results depend on the material, models and creative revisions.

## Keep the creative process in one project

| Start with | What you can do |
| --- | --- |
| A visual idea | Choose an image or video model on the home page, reference images, video or audio, review the estimate and create a clip |
| A story or manuscript | Import TXT, Markdown, DOCX or PDF, review chapter boundaries and story analysis, then work chapter by chapter |
| Characters, locations and props | Manage reference images, aliases and variants; reuse the same assets and voice bindings |
| A storyboard | Edit shot descriptions, complete prompts, reference media and generation parameters; inspect each result |
| An infinite canvas | Connect assets, videos and enhanced results; switch between storyboard and workflow views |
| A revision in mind | Ask the assistant to change selected objects, inspect diffs and recorded changes, and undo supported edits |
| Generated footage | Track tasks and versions, connect shots, assemble episodes and optionally enhance resolution |

You can also use **Remake studio** to analyze reference videos you are authorized to use and turn their shots into an editable project.

### Why a workspace?

- **Reusable settings.** Characters, variants, locations and voices stay linked to shots across chapters.
- **Editable steps.** Keep prompts and generation versions. Revise one shot before deciding whether to generate it again.
- **Shared capabilities for buttons and chat.** The assistant orchestrates creation; image and video models generate the media. Tasks and usage remain recorded.
- **Customizable creative rules.** One Chinese skill pack guides story analysis, assets, images and storyboards, with Chinese or English output selected by system language.
- **Choose how to use it.** Create online or deploy the same application with your own models and storage.

### Current interface

**Home: select a model, reference material and start with an image or video clip.**

[![Current black home page with image/video creation and the works showcase](docs/images/screenshots/home.jpg)](docs/images/screenshots/home.jpg)

| Storyboards and creation assistant | Infinite canvas workflow |
| --- | --- |
| [![Storyboard workspace and creation assistant](docs/images/screenshots/creation-agent.jpg)](docs/images/screenshots/creation-agent.jpg) | [![Assets, references and video nodes on the canvas](docs/images/screenshots/workbench.jpg)](docs/images/screenshots/workbench.jpg) |

| Project assets | Works library |
| --- | --- |
| [![Character and scene assets](docs/images/screenshots/asset.jpg)](docs/images/screenshots/asset.jpg) | [![Current works library and finished episode archive](docs/images/screenshots/portfolio.jpg)](docs/images/screenshots/portfolio.jpg) |

Screenshots use public example projects in the current Chinese interface. English is also supported.

## Quick start

1. Open the **[NovelVids commercial service](https://shortdramas.xiazq.com)**, read the agreements and sign in with Qiling through WeChat.
2. Choose an image or video model, enter a visual idea, add references and review the estimate. For a series, import a story through Short dramas and continue into assets and storyboards.
3. Review generated versions, revise shots, organize resources and manage finished episodes in the works library. Projects and costs belong to the currently selected team.

### Self-hosting

Local use is anonymous by default. The asset design templates, storyboard speech timing rules and 15 visual styles ship in `prompts/skills/`, where you can edit them.

<details>
<summary>Expand Docker self-hosting and first-run configuration</summary>

You need Docker with Docker Compose and access to model services. **Self-hosting is not offline inference:** AI features call the APIs you configure, and providers may charge for them.

```bash
git clone https://github.com/Anning01/novelvids.git
cd novelvids
docker compose up -d --build
```

Open **[http://localhost:8080](http://localhost:8080)** when startup completes.

Before creating your first project:

1. Under **Settings → Model settings**, enable a text model, select **Creation assistant**, and enable **Multi-turn tool calling**. Enable the assistant in General settings.
2. Configure the image/video models you want and their prices. A text model alone is enough to start planning stories, assets and storyboards.
3. Start with a short story or one chapter. Review extraction and storyboard results before generating media. Explicit generation requests can incur model charges; editing a prompt does not automatically generate images or videos.

The Docker backend image includes FFmpeg. For older images, install and check it in the backend container:

```bash
docker compose exec -u root backend sh -c 'apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*'
docker compose exec backend ffprobe -version
```

Use `docker compose exec backend ffprobe -version` to check that the video tools are ready.

- **Local persistence:** `./data` holds the database and private exports; `./media` holds images, video and audio. Back up both before updating.
- **No login by default:** intended for personal local use. Before public exposure, set `AUTH_ENABLED=true`, `AUTH_PROVIDER=password`, `SUPER_ADMIN_USERNAME` and `SUPER_ADMIN_PASSWORD` through environment variables, and enable HTTPS.
- **Qiling sign-in:** Set `AUTH_ENABLED=true`, `AUTH_PROVIDER=qiling` and `QILING_API_BASE_URL` to your Qiling HTTPS endpoint. To accept new accounts, set `QILING_SIGNUP_ENABLED=true` and fill in the operator, policy and third-party disclosures under `LEGAL_*` in Compose.
- **WeChat Pay and remote media processing:** To enable top-ups, configure the backend with your own `WECHAT_PAY_*` merchant settings and point the callback URL to `/api/payment/wechat/notify` on your site. Use a Compose override to mount the key files read-only at their configured container paths. Remake jobs run locally by default. To use an installed media worker, set `REMAKE_MEDIA_SSH_HOST` and configure backend SSH credentials and a verified host key.
- **Local development:** Python 3.12+, Node.js 22.12+, uv and FFmpeg. See Local development below.

</details>

## Creative workflow

```mermaid
flowchart LR
    A[Story / manuscript] --> B[Analysis and chapters]
    B --> C[Characters · locations · props]
    C --> D[Editable storyboard]
    D --> E[Image and video generation]
    E --> F[Review and revise]
    F --> D
    F --> G[Episode / video enhancement]
```

Use the storyboard to inspect each shot and the canvas to organize references and workflow. Accepted media tasks continue to be collected after you close the page. Uncertain submissions require review rather than an automatic repeat of a paid request.

## Standalone creative skills

Story analysis is built into the workbench. The three installable creative skills are maintained in this repository under `prompts/skills/`, one directory per skill. Install any stage individually in an assistant that loads `SKILL.md`. Available packages cover screenplay adaptation (`novelvids-screenplay`), asset design and storyboarding. Image production, video production and reference-video analysis are available in the workbench. Each skill handles revisions to its own output. The host agent coordinates requests spanning chapters or stages.

From the repository root, use Python's standard library to list, export or install a package:

```bash
python3 scripts/export_skill.py --list
python3 scripts/export_skill.py novelvids-storyboard --dest ./output/skills
python3 scripts/export_skill.py novelvids-screenplay --dest .agents/skills
```

The storyboard skill has a project-wide picture-board switch, off by default. From the production project root, run `python3 .agents/skills/novelvids-storyboard/scripts/storyboard_sheets.py on` (or `off`). When enabled, each video generation segment gets a single black-and-white storyboard image and a companion video prompt. The action determines the panel count.

Storyboard and video skills keep the generic prompt. Install the optional optimizer for your video model: `sd2-pe` for Seedance 2.0 (standard, Mini and Fast), `sd25-pe` for Seedance 2.5, `h3-prompt-writing` for MiniMax H3, or `wan3-pe` for Wan 3.0. Pass the active video model to the skill or set `video_model_type` in the production project’s `novelvids.config.json`. See the [model routing and official installation instructions](prompts/skills/novelvids-video/references/model_optimization.md).

The exported directory contains its entrypoint, referenced rules and MIT license. The last command installs a project-local skill. Invoke it with `$novelvids-screenplay` and supply the source passage and target running time. Each source entrypoint under `prompts/skills/novelvids-*/` explains the inputs and deliverable. The application and exports share the rules under `references/`. Shared resources are included in each export. To update a locally edited package, export to a fresh directory and review the differences.

## Local development

Install Python 3.12+, Node.js 22.12+, uv and FFmpeg.

```bash
uv sync --frozen --dev
make dev PORT=9000
```

Start the frontend in another terminal:

```bash
cd web
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The frontend proxies requests to the local backend on port 9000.

## Development and community

The frontend uses **Vue 3, TypeScript and Vue Flow**; the backend uses **FastAPI, Tortoise ORM, Deep Agents and Pydantic AI**. Creative guidance lives in [`prompts/skills/`](prompts/skills/), separate from model adapters and task execution.

Bring a real creative problem: [report a bug](https://github.com/Anning01/novelvids/issues/new), [discuss an idea](https://github.com/Anning01/novelvids/issues), or [contribute](https://github.com/Anning01/novelvids/pulls). For generation problems, include a shareable minimal example, model configuration type and reproduction steps. Keep keys and private media out of reports.

Directions for discussion include **asset consistency, reproducible workflows, deployment and recovery, model/skill extensibility and production quality checks**.

If NovelVids helps you, consider a Star, report your experience, or share work and production notes you are authorized to publish.

## Support the project

If NovelVids helps you, consider supporting my work through WeChat Pay or Alipay. Your support helps me keep developing and maintaining the project. Thank you!

| WeChat Pay | Alipay |
| :---: | :---: |
| <a href="docs/images/donate-wechat.jpg"><img src="docs/images/donate-wechat.jpg" width="260" alt="WeChat Pay donation QR code"></a> | <a href="docs/images/donate-alipay.jpg"><img src="docs/images/donate-alipay.jpg" width="260" alt="Alipay donation QR code"></a> |

## License

Project code and documentation use the **[MIT License](LICENSE)**. Commercial use, modification and redistribution are permitted with the copyright and license notice retained. The software is provided as is, without warranty.

Third-party dependencies, fonts, media and model services retain their own terms. Demonstration content is not a grant of rights to underlying stories, music or voices. See [third-party notices](NOTICE.md).

## Star history

[![NovelVids Star history](https://novelvids-star-history.864399407.workers.dev/card.svg)](https://github.com/Anning01/novelvids/stargazers)

New creation-assistant conversations use the Python Deep Agents runtime for tool execution, on-demand skills and context compaction. Application services retain permission, version and output-contract checks. Conversation checkpoints default to `data/creation_agent_checkpoints.db`; set `CREATION_AGENT_CHECKPOINT_PATH` to change the location and include this state file in backups when retaining conversation recovery. Historical runs keep their original execution path.

The script workspace stores project visual style, audiovisual direction and an optional line-art storyboard switch (off by default). New shots can generate one storyboard image each; existing shots offer individual generation and retry. Images can be attached as video references with companion guidance. Installed official prompt optimizers are loaded from `CREATION_AGENT_OPTIONAL_SKILLS_PATH` (default `.agents/skills`) for the selected project video model. Generic and model-specific prompts are retained separately.
