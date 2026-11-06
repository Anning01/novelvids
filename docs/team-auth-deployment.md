# 登录与团队功能部署指南（AUTH_ENABLED）

> 一套代码支持账号密码版和器灵扫码版。开启登录与团队功能后，由 `AUTH_PROVIDER` 选择登录方式。

## 1. 开关与环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_ENABLED` | `false` | 登录与团队功能总开关。关闭时行为与无鉴权版本完全一致（不建 auth 表、不注册 auth 路由） |
| `AUTH_PROVIDER` | `password` | `password` 为开源账号密码版，`qiling` 为器灵扫码版 |
| `SUPER_ADMIN_USERNAME` | 空 | 账号密码版首次启动时的管理员用户名 |
| `SUPER_ADMIN_PASSWORD` | 空 | 账号密码版首次启动时的管理员密码 |
| `SESSION_TTL_HOURS` | `168` | 登录会话有效期（小时） |
| `QILING_API_BASE_URL` | 空 | 器灵 HTTPS API 根地址，启用登录时设置 |
| `QILING_SIGNUP_ENABLED` | `false` | 允许首次器灵登录创建猫影账号 |

通用 HTTP 安全变量：

| 变量 | 生产建议 | 说明 |
|---|---|---|
| `API_DOCS_ENABLED` | `false` | 控制 Swagger、ReDoc 与 OpenAPI；可信演示站可单独开启 |
| `SECURITY_HEADERS_ENABLED` | `true` | HSTS、CSP、禁止嗅探/嵌入、权限策略等响应头 |
| `EXPOSE_INTERNAL_ERRORS` | `false` | 关闭后客户端和生产日志不回显异常正文，避免供应商密钥或响应泄漏 |
| `ALLOWED_HOSTS` | 实际域名 | 逗号分隔的 Host 白名单；生产环境不要使用 `*` |
| `ALLOWED_ORIGINS` | 实际前端源 | 逗号分隔的 CORS 白名单；同源部署只需本站地址 |
| `TRUSTED_PROXY_NETWORKS` | 直连代理 CIDR | 仅这些代理可提供 `CF-Connecting-IP` / `X-Forwarded-For` |
| `LOGIN_RATE_LIMIT_*` | 保持默认或更严 | 应用层登录总尝试与失败窗口；边缘 WAF 仍应作为第一层 |

## 2. Docker 部署

### 开源体验（默认，零配置）

```bash
docker compose up -d --build
# 访问 http://localhost:8080，直接使用
```

### 账号密码版（开启登录与团队）

```bash
# .env 或环境变量中设置：
#   AUTH_ENABLED=true
#   AUTH_PROVIDER=password
#   SUPER_ADMIN_USERNAME=<自设用户名>
#   SUPER_ADMIN_PASSWORD=<自设强密码>
docker compose up -d --build
```

首次启动会自动：
1. 创建 auth 相关表（`users / teams / team_members / user_sessions / balance_transactions`）；
2. 为存量数据补齐 `team_id / created_by / user_id / scope` 列，创建「默认团队」并把存量项目与计费流水挂入。

> ⚠️ 线上部署务必通过 HTTPS 反向代理暴露服务（登录令牌与会话依赖传输安全），示例见 §3。

## 3. HTTPS 反向代理示例（自建服务器 + 域名）

### 方式一：docker-compose 整机部署（推荐，零地址配置）

前端容器内置 nginx 已把 `/api`、`/media` 转发到 `backend:8000`，外层只需把域名指向前端端口：

```bash
docker compose up -d --build   # 前端暴露 8080
```

外层 caddy 一行：`novel.example.com { reverse_proxy 127.0.0.1:8080 }`，无需在前端填写任何地址。

### 方式二：前端静态与后端分离部署

前端 `web/dist` 单独托管时，打包阶段用 `VITE_API_BASE` 指定后端地址（默认同源相对路径，不填即可）：

```bash
cd web
# 后端根地址（不含 /api），例如：
VITE_API_BASE=https://api.example.com npm run build
```

- 不填 `VITE_API_BASE`：前端沿用相对路径 `/api`、`/media`，此时**静态服务器必须代理这两个路径**到后端（见下方 nginx 片段）。
- 填了 `VITE_API_BASE`：API 请求直连后端域名（需把前端源加入 `ALLOWED_ORIGINS`），上传等场景构造的 `/media` 地址也会自动带上后端域名；历史数据里后端返回的相对 `/media` 路径仍建议在静态服务器加 `/media` 代理兜底。

```nginx
# 静态服务器的 nginx（方式二必配 /media 代理兜底；未填 VITE_API_BASE 时 /api 也需代理）
location /media/ {
    proxy_pass http://<后端地址>:8000;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;
}
```

### nginx（方式一整机反代示例）

```nginx
server {
    listen 443 ssl http2;
    server_name novel.example.com;

    ssl_certificate     /etc/letsencrypt/live/novel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/novel.example.com/privkey.pem;

    client_max_body_size 512m;  # 视频/图片上传

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 二期：微信公众平台回调（公网 80/443，在公众号后台配置服务器地址）
    # location /api/wechat/mp/events {
    #     proxy_pass http://127.0.0.1:8080;
    #     proxy_set_header Host $host;
    # }
}

server {
    listen 80;
    server_name novel.example.com;
    return 301 https://$host$request_uri;
}
```

### Caddy（自动 HTTPS）

```caddyfile
novel.example.com {
    reverse_proxy 127.0.0.1:8080
    request_body {
        max_size 512MB
    }
}
```

## 4. 团队功能速览（开启后）

| 角色 | 能力 |
|---|---|
| 超级管理员 | 全部权限 + 「团队管理」页：创建/停用团队、改名、人员上限、余额充值；官方模型配置（设置页） |
| 团队管理员 | 团队内全部权限 + 「成员管理」页（邀请链接、角色调整、禁用/启用、消费限额、移除）+ 团队模型配置与「官方/自定义」来源切换 + 全团队成本 |
| 创作者 | 团队内创作全部功能；成本仅本人；无设置/成员管理 |
| 查看者 | 只读浏览项目；无成本、无设置；任何写操作 403 |

- **多团队切换**：一个用户可属于多个团队，侧边栏 Logo 下方的团队选择器切换当前团队（后端按 `X-Team-Id` 校验作用域）。
- **成员加入**：管理员不再直接建号，唯一方式是**邀请链接**（24 小时有效，可多人使用）。新用户注册时自动获得一个个人团队，并按所用邀请链接加入邀请团队。已有用户通过邀请链接加入其他团队。加入与注册都校验团队**人员上限**。
- **成员治理**：管理员可踢出、禁用/启用成员（仅影响该团队）、设置个人**累计消费限额**（超限后禁止提交新任务）；成员列表展示每人的**累计历史消耗金额**（随计费流水自动累加）。
- 模型配置：团队可用「官方配置」（超管维护，**Key 对任何角色不可见**）或「自定义配置」（团队管理员维护本团队 Key）。
- 余额：超管充值；任务提交前预检（欠费/超限额 402），完成后按计费成本自动扣减；允许透支为负并在团队管理页标红。
- 存量数据：首次开启时自动回填到「默认团队」。

## 4.5 对象存储（阿里云 OSS，可选）

默认 `OSS_PROVIDER=local`：上传与生成媒体全部存本地磁盘，行为不变。启用阿里云 OSS 后：
**前端直传**（大文件/图片不经过服务器）+ **服务端经内网 endpoint 读写**（省流量）+ **全部媒体落 OSS**。

环境变量：

```bash
OSS_PROVIDER=aliyun
OSS_BUCKET=dramas-x
# 填 Bucket 的地域 endpoint（不带 bucket 前缀，程序自动拼成虚拟主机域名）：
OSS_ENDPOINT=oss-cn-guangzhou.aliyuncs.com            # 公网（直传与公网访问）
OSS_INTERNAL_ENDPOINT=oss-cn-guangzhou-internal.aliyuncs.com  # 内网（服务端读写，同地域 ECS 免流量费）
OSS_ACCESS_KEY_ID=...
OSS_ACCESS_KEY_SECRET=...
# 可选：CDN/自定义（CNAME）域名前缀，仅用于读访问；留空则用 https://{bucket}.{endpoint}
OSS_PUBLIC_BASE=https://dramas-x.cn-guangzhou.taihangztn.cn
```

> **公共读 Bucket**：Bucket 需开启公共读，媒体地址在**读取时**直接拼接公共域名
> （`{OSS_PUBLIC_BASE}/{key}`，不附带任何签名参数）。数据库只持久化 OSS 对象 key
> （`uploads/...`）或本地相对路径（`/media/...`），不存完整 URL。
> 未配置 OSS（本地磁盘模式）时，URL 原样返回本地路径。

直传 POST 的目标地址固定为 Bucket 虚拟主机域名
`https://{OSS_BUCKET}.{OSS_ENDPOINT}`（如 `https://dramas-x.oss-cn-guangzhou.aliyuncs.com`）。
**不要**使用路径式 `https://{endpoint}/{bucket}`（阿里云已不再支持，会返回 403），
也**不要**把 `OSS_PUBLIC_BASE` 的 CNAME 域名用于 POST 表单上传（CNAME 不支持表单上传，
仅用于读访问 URL 拼接）。内网读写同样使用虚拟主机域名
`https://{OSS_BUCKET}.{OSS_INTERNAL_ENDPOINT}`。

Bucket 需配置 CORS（允许前端域名 POST 直传，暴露 ETag）：

```json
[
  {
    "allowedOrigins": ["https://novel.example.com"],
    "allowedMethods": ["POST", "GET", "HEAD", "PUT"],
    "allowedHeaders": ["*"],
    "exposeHeaders": ["ETag"]
  }
]
```

注意：内网 endpoint 仅在**与 OSS 同地域的云服务器**内可达；自建机房请将
`OSS_INTERNAL_ENDPOINT` 留空（回退公网 endpoint）。存量 `/media/...` 路径继续由
nginx 静态代理，新上传与生成媒体自动切换为 OSS 公网 URL。

## 5. 两版登录与协议配置

### 开源账号密码版

`AUTH_PROVIDER` 默认是 `password`。需要登录时设置 `AUTH_ENABLED=true`，并配置 `SUPER_ADMIN_USERNAME` 和 `SUPER_ADMIN_PASSWORD` 初始化管理员。账号密码版使用本部署的账号、密码和邀请注册。它不会请求器灵登录或校验器灵权益。保持 `AUTH_ENABLED=false` 时沿用匿名自托管体验。

### 器灵扫码版

设置 `AUTH_ENABLED=true`、`AUTH_PROVIDER=qiling` 和 `QILING_API_BASE_URL=https://toolsoul.daniu7.cn`。本地开发同样通过这些环境变量运行 `make dev PORT=9000`。新账号注册由 `QILING_SIGNUP_ENABLED` 控制，默认关闭。

扫码版禁用账号密码登录、邀请密码注册、改密、重置密码和手动创建密码用户的接口。已有账号可在保留的有效会话中绑定器灵。用户在登录页阅读并勾选协议后开始扫码。首次注册还要求后端协议配置完整。

合并平台账号时，接收账号须先绑定器灵并验证登录。核对账号 ID、完成数据库备份后，才执行 `uv run python scripts/consolidate_platform_account.py --source-id <旧超管ID> --target-id <接收账号ID> --apply`。命令转交平台权限、停用旧登录并撤销两个账号的旧会话，历史操作人 ID 保留。全新扫码部署没有管理员时，可省略 `--source-id` 来设置首位已验证管理员。

### 用户协议和隐私政策

公开协议由后端按当前登录版及环境变量生成，访问 `/api/auth/legal/terms` 和 `/api/auth/legal/privacy`。状态接口 `/api/auth/status` 返回 `legal_ready` 和缺失或无效的配置键名 `legal_missing`。未配置完整时，不发布带占位符的文档。账号密码版在尚未配置在线服务协议时仍支持私有自托管登录。

以下字段是运营者须填写并核实的公开信息。将值放进部署环境或你管理的 `.env`，项目不会将这些值写入源码。

| 环境变量 | 需要提供的信息 |
| --- | --- |
| `LEGAL_OPERATOR_NAME` | 提供此在线服务的公司全称或自然人姓名 |
| `LEGAL_CONTACT_EMAIL` | 真实可接收客服、举报、隐私权利申请的邮箱 |
| `LEGAL_CONTACT_ADDRESS` | 服务运营者可联系的地址 |
| `LEGAL_EFFECTIVE_DATE` | 两份文本的生效日期，格式 `YYYY-MM-DD` |
| `LEGAL_STORAGE_DESCRIPTION` | 数据库、媒体、备份及模型处理的实际地区，涉及境外处理时明确说明 |
| `LEGAL_RETENTION_DESCRIPTION` | 账号、项目素材、任务与账务、安全日志、备份分别保存多久以及删除机制 |
| `LEGAL_ACCOUNT_DELETION_DESCRIPTION` | 注销、删除、查阅、更正和撤回申请如何提交、核验、处理和答复，团队共用记录如何处理 |
| `LEGAL_AI_MARKING_DESCRIPTION` | AI 生成内容在界面、导出文件和元数据中实际采用的标识方式，以及对外发布的要求 |
| `LEGAL_THIRD_PARTIES_JSON` | 第三方服务列表，格式见下文 |

`LEGAL_THIRD_PARTIES_JSON` 是 JSON 数组。每个对象须提供下列键，值全部为字符串。

```json
[
  {
    "name": "实际接收数据的服务商名称",
    "purpose": "实际处理目的，如登录、模型生成或媒体存储",
    "data": "传给该服务的具体信息种类",
    "contact": "服务商实际联系方式或联系页面",
    "privacy_url": "https://服务商的实际隐私政策地址",
    "location": "该服务实际处理和存储数据的地区"
  }
]
```

账号密码部署仅列本部署实际使用的第三方。器灵部署须列明器灵及微信登录所涉及的服务。还应核对当前模型服务商、对象存储、登录视频背景的 CDN 等实际接收用户请求或素材的服务。没有外部接收方的私有部署可填 `[]`，扫码版不接受空清单。

上述设置用于真实披露，不会自动实现日志清理、文件标识、注销受理或跨境安排。上线前须确认填写的期限、机制和处理地点与实际运行相符，涉及另行告知或单独同意的处理需要相应业务入口。当前模板及配置测试不替代运营者对具体服务的审核。

## 6. 测试双跑

```bash
# 关闭态回归（必须全绿 —— 开源行为零变化）
uv run pytest

# 开启态回归（鉴权/团队/余额全套）
AUTH_ENABLED=true uv run pytest test/test_auth -q --no-cov

# 前端
cd web && npm run test && npm run typecheck && npm run build
```

CI 建议两条流水线分别执行上述两态后端回归。

## 7. 公共演示环境

仓库的 `deploy/demo/` 提供独立演示容器、非 root 运行、只读根文件系统、资源限制和每日原子重置模板；`scripts/create_demo_snapshot.py` 可从 SQLite 按项目白名单制作脱敏快照。演示数据不得直接复制生产账号、会话、账单或模型配置，详见 [deploy/demo/README.md](../deploy/demo/README.md)。

演示环境使用账号密码版时可继续使用原演示快照账号。若切换到器灵版，需要先准备扫码身份与演示团队关系。

## 生产部署备份保留规则

服务器只保留**上一版的一套回滚文件**和**一份部署前数据库备份**。生产代码、运行数据库、媒体和证书不属于备份清理范围。

每次部署使用 `/root/novelvids-deploy-backups/release-<新提交短 SHA>-<14 位时间戳>/` 保存：

- `previous-commit`：部署前的完整 Git 提交 SHA。
- `code.tar.gz`：该 SHA 的 `git archive` 代码包，不包含 `.env`、数据库、媒体和依赖目录。
- `dist/`：部署前完整前端文件。
- `database.dump`：部署前 PostgreSQL 自定义格式备份，用 `pg_restore --list` 验证可读。

先完成备份和上线，再检查后端状态、公网站点及静态文件。**健康检查成功后必须清理旧备份**，不得只创建带时间戳的新目录而一直累积：

```bash
# 从仓库根目录执行；替换为本次已经验证完整的回滚目录名。
python3 scripts/prune_deployment_backups.py --keep release-6841ac4-20261023192335
python3 scripts/prune_deployment_backups.py --keep release-6841ac4-20261023192335 --apply
```

脚本先验证上一版代码包、前端、提交 SHA 和数据库备份；默认只预览。`--apply` 删除该目录以外的历史 NovelVids 备份、旧依赖副本、回滚前端与部署上传临时包。其他项目及 `/root/cert`、当前 `/root/novelvids` 不会被选入清理。失败部署先恢复服务，不清理可用回滚版本。不要再为同一次部署保留多份相同前端或整套虚拟环境。

## 本项目生产目标与更新验收

固定生产目标为 `root@8.138.35.228`，站点 `https://shortdramas.xiazq.com`。
代码位于 `/root/novelvids`，Supervisor 程序名为 `novelvids-backend`，后端监听
`127.0.0.1:9000`，Caddy 托管 `web/dist`。部署前从现有环境核实版型，缺省
`AUTH_PROVIDER=password`；更新代码不会自动切换器灵登录或迁移账号。

退款先持久化扣回金额及 `refunding` 状态，再使用由订单号确定的固定退款单号向微信申请。
只有微信返回 `SUCCESS` 才标记 `refunded`；处理中、异常或网络结果不明时保留预留金额，
在订单页使用「同步」查询，重试仍复用原退款单号。微信确认 `CLOSED` 时，仅一次恢复预留金额，
订单标记为 `refund_closed`。`ABNORMAL` 仍属微信退款处理中间账户，需要运营者在商户平台处理，
不能直接恢复团队余额或显示退款成功。退款订单不会因旧支付回调再次充值。

私有提示词覆盖只备份和保留服务器已有文件，不打进公开 Git 提交；账号合并脚本不在普通部署中自动执行。
