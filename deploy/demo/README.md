# 独立公共演示部署

本目录用于把选定的本地项目发布到与商业站完全隔离的公共演示环境。它保留现有 RBAC：公共账号只加入一个 `viewer` 团队，因此查看接口可用，创建、上传、编辑、生成、成员管理和模型配置写操作均由后端返回 403。

## 安全边界

- 演示数据库只保留显式项目白名单，并重建为单一查看者、零团队余额、零个人额度。
- 账号、会话、邀请、账单、AI 任务、供应商任务 ID 和模型配置全部移除。
- 媒体只复制保留项目实际引用的文件；远程 HTTPS 媒体可在导出时本地化，运行时固定 `OSS_PROVIDER=local`。
- 后端单 worker、非 root、只读根文件系统；前端仅发布到宿主机 `127.0.0.1:18080`。
- 接口文档仅演示环境开启。正式商业环境应设置 `API_DOCS_ENABLED=false`。
- 应用和 Nginx 提供双层登录限流；如后续接入边缘 WAF，仍须保留源站限流作为兜底。容器端口不得直接暴露公网。

## 1. 制作黄金快照

在仓库根目录执行，项目 ID 必须逐个显式选择：

```bash
uv run python scripts/create_demo_snapshot.py \
  --source-db data/novelvids.db \
  --source-media media \
  --output-dir demo_seed \
  --project-id 1 \
  --project-id 2 \
  --username demo \
  --password '<公开演示密码>' \
  --team-name '在线演示团队' \
  --vendor-remote
```

脚本使用 SQLite backup API，不写源库；遇到未知项目、缺失文件、路径越界、不受支持的远程媒体或外键错误会拒绝产出。

## 2. 构建与上传

前端必须在可信本地环境按锁文件测试并构建，再上传 `web/dist`：

```bash
cd web
npm ci
npm run test
npm run typecheck
npm run build
```

后端镜像使用 `deploy/demo/Dockerfile.backend` 和 `uv.lock`；前端运行镜像使用 `Dockerfile.frontend-runtime` 封装本地 `dist`。两者固定标记为 `novelvids-demo-*:current`，Compose 不在启动时隐式构建或升级依赖。

宿主机目录约定：

```text
/srv/novelvids-demo/
├── docker-compose.yml
├── golden/          # 只读黄金数据库与媒体
├── runtime/         # 容器可写运行副本
├── previous/        # 最近一次重置前的可回滚副本
└── reset-demo.sh
```

## 3. 每日重置

安装 `novelvids-demo-reset.service` 与 `.timer` 后启用 timer。它在北京时间每天 `00:00`：

1. 从 `golden/` 创建完整的下一份运行副本；
2. 停止两个演示容器并原子交换 `runtime/`；
3. 等待健康检查；失败时自动恢复 `previous/`。

首次部署也直接执行 `/srv/novelvids-demo/reset-demo.sh`，不要手工拼接数据库与媒体目录。

## 4. 上线检查

- 公网仅由受控反向代理接入，Compose 端口保持 `127.0.0.1:18080`；若启用边缘 WAF，再将源站限制为该供应商的回源地址。
- `demo` 登录后 `/api/auth/me` 的角色必须是 `viewer`，余额和限额都为 0。
- 项目列表、设定、分镜和媒体均可读；项目创建和模型配置接口返回业务码 403。
- `/docs` 与 `/openapi.json` 在演示站可用；商业站不可用。
- 容器内没有 `.env`、模型 Key 或 OSS 凭据，数据库中不存在 HTTP/OSS 媒体引用。
- 手工修改演示密码或数据后执行重置，确认恢复黄金状态。
