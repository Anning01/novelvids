# 首页装饰动图

生成方式：内置 image_gen；工具未开放模型版本选择，没有指定或声称使用 2.6。
先生成单幅视觉素材，再用 FFmpeg 制作 4 秒、8 fps、216×144 的缓慢镜头漂移循环 GIF。
这两张是功能入口装饰，不是用户生成记录或公开作品。
首页直接循环播放 GIF，不显示暂停控件；同名 WebP 保留为素材原图。

输出：`web/public/home-art/cloud-palace-v1.{webp,gif}`、`web/public/home-art/rain-street-v1.{webp,gif}`。

## 云海古殿

```text
Use case: stylized-concept
Asset type: decorative cinematic thumbnail for the short-drama creation entry of an AI film studio website; will be animated with a subtle slow camera drift.
Primary request: a captivating miniature Chinese fantasy film scene, floating mountain pavilion above a sea of cloud, a tiny lone cloaked traveler on a bridge, warm gold sunlight catching the pavilion roof, cool jade and deep teal shadows, layered mist and immense depth. Sophisticated painterly cinematic concept art, tactile and atmospheric, restrained saturation, clear readable silhouettes when reduced to a small thumbnail. Full-bleed landscape composition, approximately 3:2, pavilion and traveler toward center-right; dark atmospheric left side can accommodate UI text outside the artwork. No text, no lettering, no logo, no watermark, no frame, no border, no UI, no collage. A coherent single scene.
```

## 雨夜街景

```text
Use case: stylized-concept
Asset type: decorative cinematic thumbnail for a film remake workshop on a creative website; will be animated with subtle slow camera drift.
Primary request: a mysterious rainy city film still, one figure with a translucent umbrella walking through a narrow old Shanghai inspired street at blue hour, reflected amber shop light and teal blue puddles, atmospheric depth, beautiful rain haze, elegant contemporary cinematic color grading. Sophisticated painterly realism, not cartoon, restrained colors, distinct silhouette, legible as a small thumbnail. Full-bleed landscape approximately 3:2. A coherent single scene, umbrella figure near center, balanced dark areas around the edges. No legible signage, no text, no lettering, no logo, no watermark, no frame, no border, no UI, no collage.
```
