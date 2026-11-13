<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Check, Copy, ExternalLink, KeyRound } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'
import ApiCodeBlock from './ApiCodeBlock.vue'

const props = defineProps<{ baseUrl: string }>()
const selected = ref('auth')
const copied = ref(false)
const pages = computed(() => [
  {
    id: 'auth', title: tr('身份认证'), method: '', path: '',
    description: tr('在 API Keys 中创建密钥，通过 Authorization 请求头发送。'),
    language: 'HTTP', code: 'Authorization: Bearer <API_KEY>',
    fields: [],
    notes: [tr('使用 OpenAI SDK，修改 Base URL 和 API Key。已启用的原模型 ID 可继续使用，也可从模型目录复制 ID。支持流式输出、工具调用和结构化输出。')],
  },
  {
    id: 'models', title: tr('查询模型列表'), method: 'GET', path: '/models',
    description: tr('返回当前启用的平台模型、模型 ID 和配置价格。'),
    language: 'cURL', code: `curl "${props.baseUrl}/models" \\\n  -H "Authorization: Bearer $NOVELVIDS_API_KEY"`, fields: [], notes: [],
  },
  {
    id: 'chat', title: tr('对话生成'), method: 'POST', path: '/chat/completions',
    description: tr('支持普通响应和流式输出，可使用模型已启用的工具调用与结构化输出。'),
    language: 'Python',
    code: `import os, uuid
from openai import OpenAI

client = OpenAI(
    base_url="${props.baseUrl}",
    api_key=os.environ["NOVELVIDS_API_KEY"],
)

stream = client.chat.completions.create(
    model=os.environ["NOVELVIDS_MODEL_ID"],
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
    stream_options={"include_usage": True},
    extra_headers={"Idempotency-Key": str(uuid.uuid4())},
)

for part in stream:
    if part.choices:
        print(part.choices[0].delta.content or "", end="")`,
    fields: [
      ['model', 'string', true, tr('模型目录中的文本模型 ID。')],
      ['messages', 'array', true, tr('按顺序传入对话消息。')],
      ['stream', 'boolean', false, tr('设为 true 时逐段返回，默认 false。')],
      ['stream_options', 'object', false, tr('include_usage=true 返回本次调用的 token 用量。')],
    ], notes: [],
  },
  {
    id: 'images', title: tr('图像生成'), method: 'POST', path: '/images/generations',
    description: tr('使用标准 JSON 参数，结果统一返回 data[].url。图片由客户端直接从结果地址下载，参考素材先直传临时 OSS。'),
    language: 'JSON',
    code: JSON.stringify({model:'nv-MODEL_ID',prompt:'A quiet mountain courtyard at dusk.',size:'1024x1024'},null,2),
    fields: [
      ['model', 'string', true, tr('模型目录中的图像模型 ID。')],
      ['prompt', 'string', true, tr('描述要生成的画面。')],
      ['size', 'string', false, tr('所选模型支持的清晰度或像素尺寸。')],
      ['response_format', 'string', false, tr('固定为 url，避免 Base64 大文件经过服务器。')],
      ['image', 'string[]', false, tr('已直传 OSS 的参考图片 HTTPS 地址。')],
    ], notes: [],
  },
  {
    id: 'uploads', title: tr('素材直传'), method: 'POST', path: '/media/uploads',
    description: tr('只提交文件类型、字节数和 MD5 摘要，获取临时 OSS 上传地址。客户端用票据 headers 直接 PUT 文件，生成时传 read_url。上传地址有效 10 分钟，素材两天后清理。'),
    language: 'JSON',
    code: JSON.stringify({content_type:'image/png',byte_length:12345,content_md5:'FILE_MD5_BASE64_DIGEST'},null,2),
    fields: [
      ['content_type', 'string', true, tr('图片、视频或音频的 MIME 类型。')],
      ['byte_length', 'integer', true, tr('文件的实际字节数。')],
      ['content_md5', 'string', true, tr('MD5 摘要的 Base64 编码，不是文件内容。')],
    ], notes: [tr('生成接口只接受不超过 1 MB 的 JSON 和媒体 URL，不接收 multipart、data URL 或 Base64 文件。完整直传示例见 AI 接入说明。')],
  },
  {
    id: 'videos', title: tr('视频生成'), method: 'POST', path: '/videos',
    description: tr('使用官方 seconds、size 和 input_reference 参数提交任务，返回标准 Video 对象。用 id 查询状态，完成后通过 content 接口下载。'),
    language: 'JSON',
    code: JSON.stringify({model:'nv-MODEL_ID',prompt:'A slow tracking shot down the lane.',seconds:'4',size:'1280x720'},null,2),
    fields: [
      ['model', 'string', true, tr('模型目录中的视频模型 ID。')],
      ['prompt', 'string', true, tr('描述画面、动作和运镜。')],
      ['seconds', 'string', false, tr('生成秒数，例如 4、8、12，以所选模型支持为准。')],
      ['size', 'string', false, tr('像素尺寸，例如 1280x720。')],
      ['input_reference', 'string', false, tr('临时 OSS 的参考图链接，SDK 中放在 extra_body。')],
      ['references', 'array', false, tr('参考素材，每项包含 type、role 和 url。')],
      ['request_id', 'UUID', false, tr('用于断线后找回任务的唯一请求标识。')],
    ], notes: [
      tr('status 为 completed 时，使用 client.videos.download_content(id) 下载成片。原工作台的 duration、resolution、aspect_ratio 和 references 扩展继续兼容。'),
      tr('按受理时价格结算。供应商返回计费 token 时按 token 结算；按时长结算时优先用供应商报告时长，固定时长订单缺少报告时沿用订购时长。参考视频缺少计费用量时进入核对。'),
    ],
  },
  {
    id: 'errors', title: tr('错误处理'), method: '', path: '',
    description: tr('上游错误保留原始 HTTP 状态码、响应体、Content-Type、Retry-After 和 X-Request-Id。平台记录请求编号与错误状态，回显的凭证会脱敏。'),
    language: 'Python',
    code: `from openai import APIStatusError

try:
    result = client.images.generate(model=MODEL, prompt=PROMPT)
except APIStatusError as error:
    print(error.status_code)
    print(error.response.text)
    print(error.response.headers.get("x-request-id"))`,
    fields: [], notes: [tr('平台产生的认证、权限、参数和并发错误使用标准 error 对象。流式响应开始后的错误通过 SSE 返回。')],
  },
  {
    id: 'requests', title: tr('查询请求状态'), method: 'GET', path: '/requests/{id}',
    description: tr('响应头 X-Request-Id 是请求编号。建议每次生成发送唯一 Idempotency-Key；重复提交返回 409 和原编号。用同一账户和团队的密钥可查询结算状态与实际 token 用量。'),
    language: 'cURL', code: `curl "${props.baseUrl}/requests/$REQUEST_ID" \\\n  -H "Authorization: Bearer $NOVELVIDS_API_KEY"`,
    fields: [['id', 'UUID', true, tr('响应头 X-Request-Id 返回的请求编号。')]], notes: [],
  },
])
const page = computed(() => pages.value.find(value => value.id === selected.value) ?? pages.value[0]!)
const nextPage = computed(() => pages.value[pages.value.indexOf(page.value) + 1])
async function copyBaseUrl() {
  try {
    await navigator.clipboard.writeText(props.baseUrl)
    copied.value = true
  } catch {
    notice.error(tr('请选中文字后复制'))
  }
}
</script>

<template>
  <div class="api-docs">
    <nav class="docs-nav" :aria-label="tr('接口文档章节')">
      <span class="docs-nav-label">{{ tr('开始接入') }}</span>
      <button v-for="item in pages" :key="item.id" :aria-current="selected === item.id ? 'page' : undefined" @click="selected = item.id">
        <span>{{ item.title }}</span><small v-if="item.method">{{ item.method }}</small><KeyRound v-else :size="13" aria-hidden="true" />
      </button>
      <RouterLink to="/platform/models">{{ tr('查看模型目录') }}<ArrowRight :size="14" aria-hidden="true" /></RouterLink>
      <a :href="baseUrl + '/agent-guide.md'" target="_blank" rel="noopener">{{ tr('AI 接入说明') }}<ExternalLink :size="13" aria-hidden="true" /></a>
      <a :href="baseUrl + '/openapi.json'" target="_blank" rel="noopener">OpenAPI<ExternalLink :size="13" aria-hidden="true" /></a>
    </nav>
    <div class="docs-main">
      <div class="docs-base-url"><div><span>Base URL</span><code>{{ baseUrl }}</code></div><button :aria-label="tr('复制 Base URL')" @click="copyBaseUrl"><Check v-if="copied" :size="15" /><Copy v-else :size="15" /></button></div>
      <article :key="page.id" class="docs-article" :aria-labelledby="`docs-${page.id}`">
        <div v-if="page.method" class="docs-endpoint"><span :class="page.method.toLowerCase()">{{ page.method }}</span><code>/v1{{ page.path }}</code></div>
        <h2 :id="`docs-${page.id}`">{{ page.title }}</h2>
        <p class="docs-description">{{ page.description }}</p>
        <section v-if="page.fields.length" class="docs-parameters" :aria-label="tr('请求参数')">
          <h3>{{ tr('请求参数') }}</h3>
          <div class="docs-table-wrap"><table><thead><tr><th>{{ tr('参数') }}</th><th>{{ tr('类型') }}</th><th>{{ tr('说明') }}</th></tr></thead><tbody>
            <tr v-for="field in page.fields" :key="String(field[0])"><td><code>{{ field[0] }}</code><small v-if="field[2]">{{ tr('必填') }}</small></td><td><code>{{ field[1] }}</code></td><td>{{ field[3] }}</td></tr>
          </tbody></table></div>
        </section>
        <section class="docs-example"><h3>{{ page.id === 'auth' ? tr('请求头') : tr('请求示例') }}</h3><ApiCodeBlock :code="page.code" :language="page.language" /></section>
        <section v-if="page.id === 'videos'" class="docs-followup"><h3>{{ tr('查询视频任务') }}</h3><div class="docs-endpoint"><span class="get">GET</span><code>/v1/videos/{id}</code></div><div class="docs-endpoint"><span class="get">GET</span><code>/v1/videos/{id}/content</code></div></section>
        <div v-if="page.notes.length" class="docs-notes"><p v-for="note in page.notes" :key="note">{{ note }}</p></div>
      </article>
      <button v-if="nextPage" class="docs-next" @click="selected = nextPage.id"><span>{{ tr('下一节') }}</span><strong>{{ nextPage.title }}</strong><ArrowRight :size="17" aria-hidden="true" /></button>
    </div>
  </div>
</template>

<style scoped>
.api-docs { display:grid; grid-template-columns:190px minmax(0,1fr); gap:44px; align-items:start; }
.docs-nav { position:sticky; top:28px; display:flex; flex-direction:column; gap:4px; padding:4px 0; }
.docs-nav-label { margin:0 12px 12px; color:var(--app-text-secondary); font-size:11px; font-weight:600; }
.docs-nav button,.docs-nav a { display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:42px; padding:0 12px; border:0; border-radius:8px; background:transparent; color:var(--app-text-secondary); font:inherit; font-size:13px; text-align:start; cursor:pointer; text-decoration:none; transition:background .16s,color .16s; }
.docs-nav small { font-size:9px; opacity:.75; font-weight:600; }
.docs-nav button[aria-current] { color:var(--app-accent); background:var(--app-accent-soft); font-weight:600; }
.docs-nav button:hover,.docs-nav a:hover { background:var(--app-surface-hover); color:var(--app-text); }
.docs-nav a:first-of-type { margin-top:18px; padding-top:10px; border-top:1px solid var(--app-border); border-radius:0; }
.docs-main { min-width:0; }
.docs-base-url { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px 17px; border:1px solid var(--app-border); border-radius:10px; background:var(--app-surface-muted); }
.docs-base-url > div { display:grid; gap:5px; min-width:0; }
.docs-base-url span { color:var(--app-text-secondary); font-size:10px; letter-spacing:.03em; }
.docs-base-url code { color:var(--app-text); font-size:12px; overflow-wrap:anywhere; }
.docs-base-url button { display:grid; place-items:center; width:32px; height:32px; flex-shrink:0; border:0; border-radius:6px; background:transparent; color:var(--app-text-secondary); cursor:pointer; }
.docs-base-url button:hover { color:var(--app-accent); background:var(--app-surface-hover); }
.docs-article { margin-top:30px; }
.docs-endpoint { display:flex; align-items:center; gap:10px; min-width:0; margin-bottom:13px; }
.docs-endpoint > span { padding:4px 7px; border-radius:5px; color:var(--app-accent); background:var(--app-accent-soft); font-size:10px; font-weight:700; }
.docs-endpoint > .get { color:var(--creation-success); background:color-mix(in srgb,var(--creation-success) 10%,var(--app-surface)); }
.docs-endpoint code { color:var(--app-text-secondary); font-size:12px; overflow-wrap:anywhere; }
.docs-article h2 { margin:0; font-size:25px; line-height:1.4; font-weight:650; letter-spacing:-.025em; }
.docs-description,.docs-notes p { margin:14px 0 0; color:var(--app-text-secondary); font-size:13px; line-height:1.9; }
.docs-article h3 { margin:0 0 12px; font-size:14px; line-height:1.5; font-weight:600; }
.docs-parameters,.docs-example,.docs-followup { margin-top:28px; }
.docs-table-wrap { border-block:1px solid var(--app-border); overflow-x:auto; }
table { width:100%; border-collapse:collapse; font-size:12px; line-height:1.65; text-align:start; }
th { padding:11px 12px; background:var(--app-surface-muted); color:var(--app-text-secondary); font-weight:500; white-space:nowrap; }
td { padding:13px 12px; border-top:1px solid var(--app-border); color:var(--app-text-secondary); vertical-align:top; }
td:first-child { width:26%; color:var(--app-text); }
td:nth-child(2) { width:20%; }
td small { display:block; margin-top:3px; color:var(--creation-warning); font-size:10px; }
code { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }
.docs-notes { padding:0 0 0 15px; border-inline-start:2px solid var(--app-border-strong); margin-top:24px; }
.docs-notes p { font-size:12px; }
.docs-next { display:grid; grid-template-columns:1fr auto; gap:5px 16px; width:100%; margin-top:34px; padding:18px 0; border:0; border-top:1px solid var(--app-border); background:transparent; color:var(--app-text); text-align:start; cursor:pointer; }
.docs-next span { color:var(--app-text-secondary); font-size:11px; }.docs-next strong { grid-column:1; font-size:13px; font-weight:550; }.docs-next svg { grid-column:2; grid-row:1 / 3; align-self:center; color:var(--app-accent); }
button:focus-visible,a:focus-visible { outline:2px solid var(--app-accent); outline-offset:3px; }
@media(max-width:850px) { .api-docs { grid-template-columns:150px minmax(0,1fr); gap:24px; } }
@media(max-width:640px) { .api-docs { grid-template-columns:1fr; gap:22px; }.docs-nav { position:static; flex-direction:row; flex-wrap:wrap; gap:4px; }.docs-nav-label { display:none; }.docs-nav button { min-height:38px; padding:0 10px; }.docs-nav small,.docs-nav button svg { display:none; }.docs-nav a,.docs-nav a:first-of-type { margin:0; padding:0 10px; border:0; min-height:38px; }.docs-article h2 { font-size:23px; } }
@media(prefers-reduced-motion:reduce) { * { transition:none!important; } }
</style>
