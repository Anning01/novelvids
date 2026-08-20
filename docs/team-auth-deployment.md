# 登录与团队功能部署指南（AUTH_ENABLED）

> 一套代码、一个开关：**关闭 = 开源体验（docker 部署即用、无登录）；开启 = 线上版（强制登录 + 团队功能）**。

## 1. 开关与环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_ENABLED` | `false` | 登录与团队功能总开关。关闭时行为与无鉴权版本完全一致（不建 auth 表、不注册 auth 路由） |
| `SESSION_TTL_HOURS` | `168` | 登录会话有效期（小时） |
| `SUPER_ADMIN_USERNAME` | 空 | 超管引导账号：开启后首次启动自动创建（系统中尚无超管时） |
| `SUPER_ADMIN_PASSWORD` | 空 | 超管初始密码（**首次登录后立即在界面修改**；留空则不自动创建） |
| `WECHAT_MP_APP_ID / WECHAT_MP_APP_SECRET / WECHAT_MP_TOKEN / WECHAT_MP_AES_KEY` | 空 | 二期：微信公众号扫码登录（见 §5），当前未启用 |

## 2. Docker 部署

### 开源体验（默认，零配置）

```bash
docker compose up -d --build
# 访问 http://localhost:8080，直接使用
```

### 线上版（开启登录与团队）

```bash
# .env 或环境变量中设置：
#   AUTH_ENABLED=true
#   SUPER_ADMIN_USERNAME=admin
#   SUPER_ADMIN_PASSWORD=<强密码>
docker compose up -d --build
```

首次启动会自动：
1. 创建 auth 相关表（`users / teams / team_members / user_sessions / balance_transactions`）；
2. 为存量数据补齐 `team_id / created_by / user_id / scope` 列，创建「默认团队」并把存量项目与计费流水挂入；
3. 创建超管账号。

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
- 填了 `VITE_API_BASE`：API 请求直连后端域名（后端 CORS 已放开），上传等场景构造的 `/media` 地址也会自动带上后端域名；历史数据里后端返回的相对 `/media` 路径仍建议在静态服务器加 `/media` 代理兜底。

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
| 团队管理员 | 团队内全部权限 + 「成员管理」页（邀请链接、角色调整、禁用/启用、消费限额、重置密码、移除）+ 团队模型配置与「官方/自定义」来源切换 + 全团队成本 |
| 创作者 | 团队内创作全部功能；成本仅本人；无设置/成员管理 |
| 查看者 | 只读浏览项目；无成本、无设置；任何写操作 403 |

- **多团队切换**：一个用户可属于多个团队，侧边栏 Logo 下方的团队选择器切换当前团队（后端按 `X-Team-Id` 校验作用域）。
- **成员加入**：管理员不再直接建号，唯一方式是**邀请链接**（24 小时有效，可多人使用）。新用户经链接注册并自动加入；老用户登录后经链接加入。加入与注册都校验团队**人员上限**。
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

## 5. 二期：微信公众号扫码登录接入点

一期为账号密码登录。公众号服务号资质就绪后，按以下预留接口接入（无需改动现有登录契约）：

1. **实现 Provider**：实现 `auth/provider.py` 的 `AuthProvider` 接口（`authenticate(payload)`），参考 `auth/service.py` 的密码实现；微信侧流程：
   - `POST /api/auth/wechat/qrcode`：生成 `QR_STR_SCENE` 临时二维码（`cgi-bin/qrcode/create`），前端轮询状态；
   - `POST /api/wechat/mp/events`：接收微信事件回调（签名校验 + echostr 验证），处理 `subscribe(EventKey=qrscene_*)` 与 `SCAN` 事件完成登录，`unsubscribe` 标记取关；
   - access_token 集中缓存刷新（7200s）。
2. **注册路由**：`main.py` 中按 `AUTH_ENABLED` 追加微信路由。
3. **前端**：登录页增加「微信扫码」标签页（`/api/auth/status` 返回能力时显示）。
4. **微信后台**：配置服务器 URL/Token/EncodingAESKey（公网 80/443）。

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
