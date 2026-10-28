# Third-party notices / 第三方声明

NovelVids 的项目代码与文档采用根目录 [MIT License](LICENSE)。该许可不替代第三方组件、字体或素材的原有许可，也不授予第三方小说、音乐、肖像、声音、商标或模型服务的权利。

NovelVids source code and documentation use the root [MIT License](LICENSE). This does not replace third-party licenses or grant rights to third-party stories, music, likenesses, voices, trademarks or model services.

## Adapted interface code / 适配界面代码

The creation assistant disclosure and activity components adapt Beautiful UI's ThinkingState interaction. Retain the original copyright notice and MIT text in [beautiful-ui.NOTICE.md](web/src/features/creation-agent/beautiful-ui.NOTICE.md) when redistributing those components.

创作助手的折叠与状态组件适配了 Beautiful UI 的交互。对应文件内保留的版权与 MIT 许可全文继续有效，分发时不得移除。

## Dependencies and fonts / 依赖与字体

The following are examples, not a complete dependency license inventory. Use the versions in the lock files and the notices shipped with each installed package.

以下为已核对的主要前端组件，不是完整依赖清单。实际分发以锁定版本及安装包携带的许可声明为准。

| Component | License | Notice location in an installed checkout |
| --- | --- | --- |
| Vue Flow core | MIT | `web/node_modules/@vue-flow/core/LICENSE` |
| Element Plus X | MIT | Package metadata: `web/node_modules/vue-element-plus-x/package.json`; [upstream license](https://github.com/element-plus-x/Element-Plus-X/blob/main/LICENSE) |
| Lucide Vue icons | ISC; some Feather-derived icons MIT | `web/node_modules/lucide-vue-next/LICENSE`; [license details](https://lucide.dev/license) |
| Manrope font | SIL Open Font License 1.1 | `web/node_modules/@fontsource-variable/manrope/LICENSE` |
| Noto Sans SC font | SIL Open Font License 1.1 | `web/node_modules/@fontsource-variable/noto-sans-sc/LICENSE` |

Backend dependencies and externally installed tools such as FFmpeg retain their own licenses. Check the notices for the exact binaries and packages included in your distribution. The application license does not relicense them.

后端依赖及外部安装的 FFmpeg 等工具继续采用各自许可。分发镜像或安装包时，应保留对应版本的声明，而不是将它们视为全部改为 MIT。

## Demo media and user content / 演示素材与用户内容

Screenshots and video links illustrate application workflows. They do not grant permission to reuse any underlying third-party story, music, voice, identity or brand. User-provided content and generated outputs are subject to the rights in the source material and the selected provider's terms. Use material you are authorized to process and publish.

截图和视频链接用于展示操作流程，不代表授予其中第三方书稿、音乐、声音、人物或品牌的再利用权。上传素材和生成结果的使用仍取决于素材权利及供应商条款；请使用有权处理和发布的内容。

## License change / 许可变更

This change applies MIT to the current project code and documentation. The license for an earlier release can be read at its corresponding tag or commit. The maintainer has confirmed authorization to include historical contributions in this change.

本次将当前项目代码和文档改为 MIT；历史版本的许可可在对应标签或提交中查阅。维护者已确认本次变更包含历史贡献的再授权权限。
