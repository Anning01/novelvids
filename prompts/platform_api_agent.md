# 猫影模型 API：AI Agent 接入说明

Base URL：`{{BASE_URL}}`

公共对话接口遵循 OpenAI Chat Completions，图片和视频使用标准 JSON 结果与任务结构。文件由客户端直接上传临时 OSS，猫影只接收元数据和 URL。

## 认证与模型

在猫影开放平台创建 API Key，保存到 `NOVELVIDS_API_KEY` 环境变量。发送 `Authorization: Bearer <API_KEY>`，使用该 Key 所属用户的团队权限与余额。

`model` 接受已启用模型的目录 ID（`nv-...`）、唯一配置名称或原模型 ID。原模型已启用时可以沿用原代码中的 model，仅修改 base_url 和 api_key。名称存在多个匹配项时使用目录 ID。

```python
import os
from openai import OpenAI

BASE_URL = "{{BASE_URL}}"
API_KEY = os.environ["NOVELVIDS_API_KEY"]
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
for model in client.models.list().data:
    print(model.id, model.name, model.kinds)
```

尺寸、时长、参考图数量与工具能力以所选模型配置为准。Seedance、MiniMax、Wan 原生 SDK 的路径和协议不同，接入本文公共接口时使用以下 JSON 协议。

## 临时素材：POST /media/uploads

所有图片、视频和音频先由客户端直传 OSS。此接口只提交 MIME 类型、字节数和 MD5 摘要，不提交文件内容。普通 API Key 即可申请；临时空间按团队限额管理，私有对象使用独立前缀，48 小时后由清理任务删除。

```python
import base64
import hashlib
from pathlib import Path
import requests

def upload_reference(path: str, content_type: str) -> str:
    source = Path(path)
    with source.open("rb") as file:
        checksum = hashlib.file_digest(file, "md5").digest()
    # Base64 只用于固定长度 MD5 摘要，不编码文件内容。
    response = requests.post(
        BASE_URL + "/media/uploads",
        headers={"Authorization": "Bearer " + API_KEY},
        json={"content_type": content_type, "byte_length": source.stat().st_size,
              "content_md5": base64.b64encode(checksum).decode()},
        timeout=30,
    )
    response.raise_for_status()
    ticket = response.json()
    with source.open("rb") as file:
        uploaded = requests.put(ticket["upload_url"], headers=ticket["headers"], data=file, timeout=600)
        uploaded.raise_for_status()
    return ticket["read_url"]

reference_url = upload_reference("reference.png", "image/png")
```

upload_url 的 PUT 授权有效期为 10 分钟，read_url 有效期为 48 小时。PUT 只使用票据内的 headers，不向 OSS 发送猫影 API Key。保留 read_url 供同一任务重试；过期后重新申请并上传。上传完成后再调用生成接口。

生成接口只接收 JSON，单次最多 1 MB；multipart 文件、data URL、b64_json、内联音频或文件数据会在供应商调用前被拒绝。不要调用 SDK 的文件上传模式，改为使用上传完成的 URL。

## 对话：POST /chat/completions

```python
stream = client.chat.completions.create(
    model=os.environ["NOVELVIDS_TEXT_MODEL"],
    messages=[{"role": "user", "content": "写一个简短开场"}],
    stream=True,
    stream_options={"include_usage": True},
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="")
```

返回标准 ChatCompletion 或 ChatCompletionChunk SSE 与 `[DONE]`，不包裹 data/result。保留 tools、tool_choice、response_format、tool_calls、tool_call_id 与模型扩展字段。多模态图片使用 image_url.url 中的 HTTPS 链接。对话音频 Base64 输出模式不开放。

## 图片：POST /images/generations

```python
image = client.images.generate(
    model=os.environ["NOVELVIDS_IMAGE_MODEL"],
    prompt="安静的山中庭院",
    response_format="url",
)
print(image.data[0].url)
```

返回标准 ImagesResponse：created、data、usage 等；图片只在 data[].url 中返回，revised_prompt 等字段保留。客户端直接从结果 URL 下载。response_format=b64_json 和携带图片内容的流式输出不开放。上游模型通道须支持 URL 结果。

参考图生成：选择支持 URL 参考图的模型，用上传后的链接：

```python
image = client.images.generate(
    model=os.environ["NOVELVIDS_IMAGE_MODEL"],
    prompt="参考人物面部，使用剧本中的服装",
    response_format="url",
    extra_body={"image": [reference_url]},
)
```

`POST /images/edits` 同样接收 JSON：model、prompt、image（HTTPS URL 数组）和所选模型支持的参数。需要 URL 参考图能力，不接收 multipart image/mask 文件。

## 视频：POST /videos，GET /videos/{id}

```python
video = client.videos.create(
    model=os.environ["NOVELVIDS_VIDEO_MODEL"],
    prompt="镜头沿街道缓慢前移",
    seconds="4",
    size="1280x720",
    extra_body={"input_reference": reference_url},
)

import time
while video.status in {"queued", "in_progress"}:
    time.sleep(3)
    video = client.videos.retrieve(video.id)
if video.status == "completed":
    content = client.videos.download_content(video.id)
    content.write_to_file("result.mp4")
else:
    print(video.error)
```

input_reference 的 URL 放入 extra_body，避免 SDK 将文件参数编码为 multipart。纯文生视频可省略参考图。

返回标准 Video 对象：id、object="video"、model、created_at、completed_at、seconds、size、status、progress、error。`GET /videos/{id}/content` 跳转到成片下载地址，SDK 自动跟随，猫影不转发视频内容。当前不提供 thumbnail/spritesheet。

多参考图片、视频或音频：通过 extra_body.references 传数组，元素为 {"type":"image|video|audio", "role":"reference|first_frame|last_frame", "url":"HTTPS 地址"}。input_reference 和 references 二选一。首尾帧分别提供一张图片。

工作台原有 duration、resolution、aspect_ratio 继续兼容；与 seconds、size 同时提供时须一致。

## 错误、重试与结算

上游 HTTP 错误保留原始状态码、响应体、Content-Type、Retry-After 和 X-Request-Id。平台记录错误状态与请求编号，不套猫影响应结构或改写供应商文案；回显的平台凭证会被脱敏。

平台自己的认证、权限、参数、体积和并发错误使用标准 {"error":{"message":"...","type":"...","param":null,"code":null}}。对话流开始后的错误通过 SSE 返回。

每次生成可携带唯一 Idempotency-Key。相同请求重复提交不再调用供应商或重复扣费；视频返回原任务，对话与图片返回 409 和原请求编号。修改内容使用新键。

`GET /requests/{id}` 查询平台受理与结算状态，需同一用户和团队的 Key。成功响应从 `X-Request-Id` 取平台编号。上游错误的供应商编号仍在 `X-Request-Id`，平台编号见 `X-Novelvids-Request-Id`。断线丢失平台编号时，可通过 `GET /requests?request_key=原Idempotency-Key` 恢复。已受理对话继续收集用量，并只结算一次。

`settlement.status` 为 `settled` 时，`settlement.amount` 是以 `settlement.currency` 表示的实际扣款，金额以十进制字符串返回。`pending` 表示等待结算，`review` 表示需要核对，`not_charged` 表示平台确认未扣款。这些状态的 `amount` 为空。`pricing` 是受理时的公开价格快照。

`GET /account` 返回 Key 所属的平台账户余额、币种和充值页面。打开充值页面后，使用有权为该平台团队充值的账号登录。

## 发现接口

- [完整 OpenAPI]({{BASE_URL}}/openapi.json)
- [AI 文档索引]({{BASE_URL}}/llms.txt)
- 本文可公开读取，不包含密钥。
