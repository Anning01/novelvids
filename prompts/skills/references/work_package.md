# 作品包与 MCP 同步 v1

三个技能可独立安装、独立交稿，也可接收已有上游文件。写作与同步分开：用户仅要求创作、修订或交付文件时，不调用写入工具。只有用户明确说同步到猫影，才调用本地 MCP；不要求猫影配置模型或启动创作助手。未连接 MCP 时仍交付文件，不宣称已入库。

## 文件交接

一集目录内：`episode.json` 轻量清单（有本集小说原文时用可选字段 source_text 指向包内 UTF-8 原文文件）、可阅读的 `screenplay.md`、`assets.json`、`storyboard.json`，可选 `media/`。还未做完的阶段保留已完成文件，后续技能接着写；不要为满足整集导入而编造未完成的资产或镜头。没有镜头时可用空 shots；资产设计未完成时保留原始材料，确认后才填写 assets。

- screenplay 技能将导演稿写入 screenplay.md。随包交付本集小说原文时，另存 source.txt，在 episode.json 指定 `"source_text": "source.txt"`；只有导演稿时省略 source_text。originals 是归档附录，以 source_text 指定阅读页的原文。收到上游材料时保留已有标识。
- assets 技能接收剧本与资产连续性记录，交付 assets.json；形态 ID 独立于资产 ID。
- storyboard 技能接收剧本、资产或已有分镜，交付 storyboard.json；保留八栏通用稿与已完成专项稿，每镜 drafts.general 对应本镜 prompt；专项稿以目标模型为键，挂回同一稳定镜头 ID。旧专项稿通过其随附通用底稿唯一定位，无法确认归属时保留原件，等用户确认。

`episode.json` 示例：

```json
{
  "format_version": 1,
  "work": {"id": "work-example", "name": "示例作品"},
  "episode": {"id": "ep-001", "name": "第一集"},
  "number": 1,
  "aspect_ratio": "16:9",
  "style_key": "xianxia-3d",
  "storyboard_enabled": true,
  "language": "zh",
  "screenplay": "screenplay.md",
  "assets": "assets.json",
  "storyboard": "storyboard.json",
  "originals": ["original.md", "general-eight-columns.md", "specialized.md"]
}
```

新作品在清单中写入用户确认的作品默认 style_key 或 custom_style_prompt，逐镜故事版开关写 storyboard_enabled。局部场次的不同画风保留在相应镜头。续导分集时沿用猫影中已保存的作品设置。

## 视频重制

普通剧本省略 workflow_kind（默认 script）。已完成视频拆解的重制作品使用同一套文件与 MCP 工具，在 episode.json 增加：

```json
{
  "workflow_kind": "remake",
  "remake_source": {"path": "media/source.mp4"}
}
```

将实际来源视频复制到上述包内相对路径，只支持可读取的 MP4/MOV。原视频的时长、尺寸和校验和由服务端读取，不能填写猜测值。沿用作品包单文件 256 MiB、总计 1 GiB 的限制，来源视频不超过 20 分钟。每集一份来源视频；多集按同一 work.id、不同 episode.id 和 number 逐集导入，不能在同一作品中混用 script 与 remake。

重制包必须已有拆解镜头。每镜额外提供 `"source_range":{"start":0,"end":2.5}`，单位为秒、相对本集原视频，且结束时间不超出原视频时长。它记录原片出处，独立于改编后镜头 duration。资产、形态、视觉与声音引用仍遵循下文协议；完整拆解稿写 screenplay.md，额外原始分析文件显式列入 originals，结构化结果保留在 structure、drafts。不能为导入而编造时间段或未完成的拆解结果。

重制导入保存原视频和已完成的资产、分镜，将本集标记为分镜就绪，不调用模型、不创建拆解任务、不触发扣费。单镜修改仍用 update_shot，可更新 source_range；来源视频不可通过单镜修改替换。只改文字时不需要原视频继续留在包目录。整集重传、替换来源或覆盖已有集不会自动执行。

work、episode、场、镜头、资产、形态均用持久 ID（字母数字、点、短横线、下划线，最长120字符）。首次创建可用 UUID；显示名、数组位置、镜头编号和猫影数据库主键不能当 ID。插镜、改名、改序保留 ID；复制为新作品才新建 ID。同作品跨集复用相同资产/形态 ID；新集导入不会修改已有资产。

`assets.json`：顶层 `assets` 数组；每项字段为 `id,name,kind,description,prompt,aliases,variants,media`。kind 只用 person/group/scene/item；prompt 必须符合当前资产协议，完整提示词原样保存。variants 每项为 `id,name,description,prompt,media`，形态 ID 在作品内唯一。media 为 `[{"path":"media/person.png","role":"main"}]`，资产图片用途 main/angle_1/angle_2/reference，其他文件用途 video/audio/blocking。群像用 group，动物用 person。不要添加商品或真人数字人。

资产和形态均可提供 `image_references`，每项为 `{"asset_id":"资产稳定ID","variant_id":null}` 或指向该资产已登记形态的稳定 ID。衍生形态默认引用所属资产主形象，即使旧包省略该字段也如此；字段可增加其他参考来源。主形象也可引用另一资产/形态。引用必须在同一作品包登记，不能引用自己、错配资产与形态或形成依赖循环。数组顺序不代表生成顺序。

例如赵无垢主形象为64岁，“十六年前”形态约48岁：先保存两份完整设定，在衍生形态写 `"image_references":[{"asset_id":"zhao-wugou","variant_id":null}]`。导入时保存稳定关系，不要求图片已存在，也不会调用生图服务。后续批量生成会补齐缺图的上游任务，等引用图生成后才启动下游图生图；上游失败时下游等待，补图后继续。已有主图和衍生图沿用，不因导入重复生成。该字段与出镜 visual、实际图片文件 media 分工不同。

`storyboard.json`：

```json
{
  "scenes": [{"id":"sc-a","name":"牛棚·内·薄暮"}],
  "shots": [{
    "id":"shot-a", "name":"第四镜", "scene_id":"sc-a",
    "description":"少年听见门外喊声，扬声回应。", "duration":14,
    "prompt":"已确认的完整视频提示词原文",
    "structure":{},
    "drafts":{"general":"八栏通用稿原文", "specialized":"已有专项稿原文"},
    "visual":[{"asset_id":"boy","variant_id":null}],
    "voices":[
      {"asset_id":"woman","mode":"offscreen","text":"开饭了！","start":10,"end":12},
      {"asset_id":"boy","mode":"dialogue","text":"来了！","start":12.5,"end":13.5}
    ],
    "media":[]
  }]
}
```

visual 与通用提示词的角色、道具、场景参考栏使用同一份出镜名单。同一镜头可为同一 asset_id 列出不同 variant_id 的多条 visual 引用，基础形象用 variant_id=null；每个实际出镜的形态分别登记，仅相同 (asset_id, variant_id) 组合去重。例：`[{"asset_id":"boy","variant_id":null},{"asset_id":"boy","variant_id":"boy-child"}]` 表示基础形象与童年形态都在本镜出镜，具体先后变化或同框关系写入分镜提示词。仅声音角色写入 voices；text 只存说出的原话，表演提示保留在原分镜的人声时间轴。voices 的 mode 明确区分 dialogue（开口对白）、offscreen（画外声音）、os（心声、嘴唇不动）、narration（旁白）；时间相对本镜，声音资产须在 assets 登记。参考图片的职责放 media.role，不能据此推断画面出镜。structure 可保留当前已有结构化分镜；drafts 原样保留稿件，不重新渲染覆盖。数组顺序决定首次导入顺序，后续单镜同步不改顺序。

逐镜已有的线稿故事版与空间定位图分别登记在该镜 media，role 使用 storyboard 和 blocking。将每张原图复制到 media/，并保留 structure.blocking_map 和 segments 中的空间及机位数据；仅写入 originals 不会绑定到镜头。

所有文件须是包内相对路径，不得越界、链接到包外或引用隐藏文件。originals 显式列出要归档的原文、八栏稿、专项稿；不能自动扫描目录把个人文件或密钥打包。媒体只归档实际存在的文件，不凭空补图。不允许用远端 URL 冒充本地文件。

## MCP 操作

工具名：`import_episode`、`read_episode`、`update_shot`。

1. 用户确认整集结果并要求同步后，调用 import_episode：`directory`（绝对目录）、`request_id`（本次操作唯一 ID）、`confirmed:true`。首次导入直接成为猫影作品的一集；不会分析、拆章、调用模型或生成媒体。相同 request_id 与相同内容可重试；已有集禁止整集覆盖。
2. 保存返回的 `sync-receipt.json`。回执含 work_id、episode_id、novel_id、chapter_id、workflow_kind、定位路径、各 shot_id、当前顺序、内容版本和媒体归档位置；重制回执还包含 remake_source 的可访问地址、时长、尺寸和校验和。新会话先读取此文件，再调用 read_episode 核对现状；需要详细内容时传 shot_id 单镜读取。重试返回原操作回执；要获取后续编辑后的最新版本，使用 read_episode。
3. 单镜更新传 `directory,request_id,confirmed:true,work_id,episode_id,shot_id,base_version,changes`。base_version 使用之前读取的版本，不按显示顺序定位。changes 仅填写本次明确修改的 Shot 字段，不能改 id 或直接写数据库主键。
4. 遇 version_conflict，展示本地与外部修改差异，停下写入并让用户确认合并；不能自动取最新版本强制重试。request_id_reused 表示同 ID 内容改变，应新建操作 ID；相同请求原样重试则返回原回执。插镜与改序不改变该镜的内容版本。
5. 确认成功回执后才说已同步。媒体已复制到猫影媒体目录；之后移走源媒体仍可读取归档。已有旧视频保持原关联，不覆盖或删除。

## 本地及 PostgreSQL 部署

运行 MCP 的机器必须能访问作品目录、猫影数据库及站点实际使用的媒体目录；支持 SQLite 和 PostgreSQL。外部 Codex/Claude Code 仅装技能不代表已连接 MCP。先启动猫影应用完成数据库初始化，再在同一部署环境运行：

```sh
uv run python -m services.local_mcp.server --allow-root /path/to/approved-packages --app-url https://your-studio.example
```

DATABASE_URL、MEDIA_PATH 和 AUTH_ENABLED 使用该部署现有配置。线上 PostgreSQL 应在应用服务器上运行 MCP（可通过 SSH 承载 stdio），并先将用户确认的作品包传到服务器授权目录。directory 使用该机器上的包目录；--app-url 只是浏览器授权及回执链接的站点地址，不会上传本机目录，也不是远程 HTTP 同步地址。不要只把本机 MCP 的数据库连接改为线上地址而继续写本机媒体目录。

登录模式下，首次调用返回猫影连接页；让用户在站点中用已有登录选择团队并确认，再在同一 MCP 进程重试。回执归属该团队，每次操作校验会话及当前成员权限；重新启动 MCP 需要重新确认连接。无需把登录令牌或数据库凭据填入技能或对话。并发导入在数据库中串行确认稳定 ID 与请求 ID；同镜头并发修改只有持有当前版本的一次写入可成功。
