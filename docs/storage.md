# 数据库与媒体存储

[返回首页](../README.md) · [English](storage.en.md)

数据库和媒体存储完全通过环境变量选择，不需要修改业务代码。可复制 [`.env.example`](../.env.example) 为 `.env` 后按环境填写；不要提交真实密钥。

### SQLite 与 PostgreSQL

开发环境默认使用 SQLite：

```dotenv
DATABASE_URL=sqlite://./data/novelvids.db
```

生产环境可切换 PostgreSQL：

```dotenv
DATABASE_URL=postgres://novelvids:your-password@127.0.0.1:5432/novelvids
```

应用启动时会以 `safe=True` 创建缺失表并执行兼容初始化，不会删除已有表。正式迁移数据前仍应备份数据库并在停写窗口执行迁移。

项目名按团队（无团队时按创建者）去重，不同范围允许同名。旧库的全局名称约束需人工审核后迁移，详见[项目命名与迁移说明](project-name-scoping.md)。迁移默认只预览，不随启动自动执行。

### 本地媒体与阿里云 OSS

默认媒体文件写入本地目录：

```dotenv
MEDIA_PATH=./media
OSS_PROVIDER=local
```

启用阿里云 OSS：

```dotenv
OSS_PROVIDER=aliyun
OSS_BUCKET=your-bucket
OSS_ENDPOINT=oss-cn-guangzhou.aliyuncs.com
OSS_INTERNAL_ENDPOINT=oss-cn-guangzhou-internal.aliyuncs.com
OSS_PUBLIC_BASE=https://media.example.com
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
```

- 浏览器通过签名策略直传大文件，避免书稿、参考视频和音频绕行应用服务器
- 服务端下载、裁剪、章节合并、尾帧提取及再次上传统一使用 `OSS_INTERNAL_ENDPOINT`
- 对外提交给模型和浏览器预览时使用公网地址或签名 URL；数据库尽量保存稳定对象 key
- `OSS_PUBLIC_BASE` 可填写 CDN/CNAME；留空时使用 Bucket 与公网 Endpoint 组合地址

项目封面会保留原图，并自动生成列表缩略图与详情预览图。升级已有环境后，执行一次幂等回填：

```bash
uv run python -m scripts.backfill_media_derivatives
```

本地媒体会在原图旁生成 WebP 派生图；OSS 模式通过 `OSS_INTERNAL_ENDPOINT` 读写，并为派生图设置长期不可变缓存。该命令也会为设定资产图片生成缩略图，并为历史生成视频提取首帧海报。

### 视频任务自动收口

```dotenv
VIDEO_RECONCILE_INTERVAL_SECONDS=30
VIDEO_RECONCILE_BATCH_SIZE=50
```

后端会持续查询排队中和生成中的供应商任务。即使用户关闭故事版页面，任务完成、计费、尾帧提取与下一镜头注入仍会继续执行。

## 私有高清导出

`CHAPTER_EXPORT_PATH` 默认 `./data/chapter-exports`，必须位于公开 `MEDIA_PATH` 外，下载沿用项目权限检查。默认 Compose 的 data 挂载已经覆盖该目录；自定义目录需单独持久化与备份，不能配置为公开静态目录。

## 登录与部署

默认 Compose 不启用登录。公网部署需先配置鉴权、团队隔离、HTTPS 和可信代理，详见[团队部署指南](team-auth-deployment.md)。更新前备份数据库和媒体；旧项目名称全局唯一约束需按[迁移指南](project-name-scoping.md)人工审核处理，不通过重置表解决。
