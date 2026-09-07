# Star 增长卡片

这个 Cloudflare Worker 从 GitHub 的仓库 Star 历史接口读取数据，生成一张可直接嵌入项目 README 的 SVG 曲线卡片。卡片自动适配 GitHub 的浅色/深色主题，并在边缘缓存 6 小时。

## 首次启用

在 GitHub 仓库的 `Settings → Secrets and variables → Actions` 中添加：

- `CLOUDFLARE_API_TOKEN`：仅授予目标账户 `Workers Scripts: Edit` 权限。
- `CLOUDFLARE_ACCOUNT_ID`：Cloudflare 账户 ID。
- `STAR_HISTORY_GITHUB_TOKEN`：细粒度 GitHub Token，只选择 `Anning01/novelvids`，仓库权限仅启用 `Metadata: Read`。

然后在 GitHub 的 `Actions → Deploy Star Growth Card → Run workflow` 手动运行一次。部署成功后，工作流会把 Worker 地址自动写入根目录 `README.md` 的 Star 增长区域。

不要把以上 Token 写进仓库文件。Worker 的 GitHub Token 由部署工作流同步为 Cloudflare Secret。

## 地址

- 卡片：`https://<部署地址>/card.svg`
- 健康检查：`https://<部署地址>/health`

## 本地验证

```bash
node --test test/index.test.mjs
```
