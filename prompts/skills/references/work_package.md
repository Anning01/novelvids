# 作品包与本地同步 v1

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

work、episode、场、镜头、资产、形态均用持久 ID（字母数字、点、短横线、下划线，最长120字符）。首次创建可用 UUID；显示名、数组位置、镜头编号和猫影数据库主键不能当 ID。插镜、改名、改序保留 ID；复制为新作品才新建 ID。同作品跨集复用相同资产/形态 ID；新集导入不会修改已有资产。

`assets.json`：顶层 `assets` 数组；每项字段为 `id,name,kind,description,prompt,aliases,variants,media`。kind 只用 person/group/scene/item；prompt 必须符合当前资产协议，完整提示词原样保存。variants 每项为 `id,name,description,prompt,media`，形态 ID 在作品内唯一。media 为 `[{"path":"media/person.png","role":"main"}]`，资产图片用途 main/angle_1/angle_2/reference，其他文件用途 video/audio/blocking。群像用 group，动物用 person。不要添加商品或真人数字人。

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
2. 保存返回的 `sync-receipt.json`。回执含 work_id、episode_id、novel_id、chapter_id、定位路径、各 shot_id、当前顺序、内容版本和媒体归档位置；新会话先读取此文件，再调用 read_episode 核对现状；需要详细内容时传 shot_id 单镜读取。
3. 单镜更新传 `directory,request_id,confirmed:true,work_id,episode_id,shot_id,base_version,changes`。base_version 使用之前读取的版本，不按显示顺序定位。changes 仅填写本次明确修改的 Shot 字段，不能改 id 或直接写数据库主键。
4. 遇 version_conflict，展示本地与外部修改差异，停下写入并让用户确认合并；不能自动取最新版本强制重试。request_id_reused 表示同 ID 内容改变，应新建操作 ID；相同请求原样重试则返回原回执。插镜与改序不改变该镜的内容版本。
5. 确认成功回执后才说已同步。媒体已复制到猫影媒体目录；之后移走源媒体仍可读取归档。已有旧视频保持原关联，不覆盖或删除。

运行 MCP 的机器必须能访问作品目录及猫影本地数据库/媒体目录；外部 Codex/Claude Code 仅装技能不代表已连接 MCP。登录模式下，本机 SQLite 实例首次调用会返回猫影连接页；让用户在猫影中用已有登录选择团队并确认，再在同一 MCP 进程重试。回执归属该团队，每次操作校验会话及当前成员权限。无需把登录令牌填入技能或对话。
