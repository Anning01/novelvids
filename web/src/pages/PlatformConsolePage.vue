<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { API_BASE, request } from '@/api'
import { tr } from '@/i18n'
import type { BillingSummary, ModelPricing, SingleResponse } from '@/types'
import { useAuthStore } from '@/features/auth/authStore'
import { appConfirm } from '@/shared/confirmDialog'
import { notice } from '@/shared/notice'
import AppButton from '@/components/AppButton.vue'

type Section = 'usage' | 'models' | 'docs' | 'keys'
type PlatformModel = {id:string; name:string; kinds:string[]; image_model_type?: string; reference_image_urls?:boolean; pricing:ModelPricing}
type KeyRow = {purpose?:'api'|'studio'; id:number; name:string; preview:string; created_at:string}
const props = defineProps<{section:Section}>()
const auth = useAuthStore()
const summary = ref<BillingSummary | null>(null)
const models = ref<PlatformModel[]>([])
const keys = ref<KeyRow[]>([])
const kind = ref('all')
const days = ref(7)
const name = ref('')
const purpose = ref<'api'|'studio'>('api')
const secret = ref('')
const changes = ref(false)
const loading = ref(false)
const error = ref('')
let epoch = 0
const titles = computed(() => ({usage:tr('用量概览'),models:tr('模型目录'),docs:tr('接口文档'),keys:'API Keys'}))
const kinds = computed<Record<string,string>>(() => ({text:tr('文本'),image:tr('图片'),video:tr('视频'),asr:tr('语音识别'),media_processing:tr('画质增强')}))
const money = (value:number) => new Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:6}).format(value)
const catalog = computed(() => models.value.filter(m => kind.value === 'all' || m.kinds.includes(kind.value)))
const range = computed(() => {
  const series = new Map(summary.value?.daily_trend.map(row=>[row.date,row.cost]))
  return Array.from({length:days.value}, (_,i) => {
    const date = new Date(); date.setDate(date.getDate() - days.value + i + 1)
    const key = [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-')
    return {date:key,cost:series.get(key) ?? 0}
  })
})
const max = computed(() => Math.max(0.000001,...range.value.map(d=>d.cost)))
const apiBase = computed(() => new URL(API_BASE, location.href).origin + '/v1')
async function load() {
  const revision = ++epoch
  loading.value = true; error.value = ''; secret.value = ''; name.value = ''; changes.value = false
  keys.value = []; summary.value = null
  try {
    if (props.section === 'usage') {
      const result = await request<SingleResponse<BillingSummary>>('/platform/usage')
      if (revision === epoch) summary.value = result.data
    } else if (props.section === 'models') {
      const result = await request<SingleResponse<PlatformModel[]>>('/platform/catalog')
      if (revision === epoch) models.value = result.data
    } else if (props.section === 'keys' && auth.activeTeamId) {
      const result = await request<SingleResponse<KeyRow[]>>('/platform/keys')
      if (revision === epoch) keys.value = result.data
    }
  } catch (e) { if (revision === epoch) error.value = (e as Error).message }
  finally { if (revision === epoch) loading.value = false }
}
async function create() {
  if (changes.value || !name.value.trim()) return
  const revision=epoch
  changes.value=true
  try {
    const {data}=await request<SingleResponse<KeyRow & {key:string}>>('/platform/keys',{method:'POST',body:JSON.stringify({name:name.value.trim(),purpose:purpose.value})})
    if (revision === epoch) {
      secret.value=data.key
      keys.value=[{id:data.id,name:data.name,preview:data.preview,created_at:data.created_at,purpose:data.purpose},...keys.value]
      name.value=''
    }
  } catch(e){if (revision===epoch) notice.error((e as Error).message)}
  finally {if (revision===epoch) changes.value=false}
}
async function revoke(row:KeyRow) {
  const revision=epoch
  if (!await appConfirm({title:tr('停用 API Key「{p0}」？',{p0:row.name}),message:tr('使用此密钥的应用将无法继续调用。'),confirmLabel:tr('停用'),tone:'danger'}) || revision!==epoch) return
  changes.value=true
  try {
    await request('/platform/keys/'+row.id,{method:'DELETE'})
    if(revision===epoch){keys.value=keys.value.filter(k=>k.id!==row.id);secret.value=''}
  } catch(e){if (revision===epoch) notice.error((e as Error).message)}
  finally {if (revision===epoch) changes.value=false}
}
async function copy(value:string){
  try {await navigator.clipboard.writeText(value);notice.success(tr('已复制'))}
  catch {notice.error(tr('请选中文字后复制'))}
}
function rates(p:ModelPricing, model:PlatformModel) {
  const lines:string[]=[]
  if(p.input_price_per_1m!=null) lines.push(tr('输入 ¥{p0} / 百万 token',{p0:p.input_price_per_1m}))
  if(p.output_price_per_1m!=null) lines.push(tr('输出 ¥{p0} / 百万 token',{p0:p.output_price_per_1m}))
  if(p.cache_input_price_per_1m!=null) lines.push(tr('缓存输入 ¥{p0} / 百万 token',{p0:p.cache_input_price_per_1m}))
  if(p.input_image?.price_per_image!=null) lines.push(tr('输入图前 {p0} 张免费，之后 ¥{p1} / 张',{p0:p.input_image.first_free,p1:p.input_image.price_per_image}))
  if(p.price_per_minute!=null) lines.push(tr('¥{p0} / 分钟',{p0:p.price_per_minute}))
  const unit=model.kinds.includes('image') ? tr('张') : p.billing_unit==='second' ? tr('秒') : tr('百万 token')
  for(const [tier,price] of Object.entries(p.prices ?? {})) lines.push(`${tier} · ¥${price} / ${unit}`)
  for(const [tier,price] of Object.entries(p.video_reference_prices ?? {})) lines.push(`${tr('参考视频')} ${tier} · ¥${price} / ${unit}`)
  for(const tier of p.tiers ?? []) lines.push(`≤${tier.short_side_max}p · ≤${tier.fps_max}fps · ¥${tier.price} / ${tr('分钟')}`)
  if(p.discount!=null && p.discount!==1) lines.push(tr('计费倍率 ×{p0}',{p0:p.discount}))
  return lines
}
watch([()=>props.section,()=>auth.activeTeamId],load,{immediate:true})
onBeforeUnmount(()=>{++epoch;secret.value=''})
</script>
<template>
  <main class="console">
    <header><h1>{{ titles[section] }}</h1><span v-if="section==='usage' || section==='keys'">{{ auth.membership?.team_name }}</span></header>
    <p v-if="loading" role="status">{{ tr('加载中') }}</p>
    <div v-else-if="error" role="alert">{{ error }} <AppButton @click="load">{{ tr('重试') }}</AppButton></div>
    <template v-else-if="section==='usage' && summary">
      <section class="totals">
        <article><h2>{{ tr('团队余额') }}</h2><strong>{{ auth.membership?.team_balance == null ? '—' : '¥ '+money(Number(auth.membership.team_balance)) }}</strong><RouterLink v-if="auth.membership && auth.canAccessBilling" to="/profile?recharge=1">{{ tr('充值') }} ↗</RouterLink></article>
        <article><h2>{{ tr('累计调用费用') }}</h2><strong>¥ {{ money(summary.total_cost) }}</strong></article>
        <article><h2>{{ tr('计费记录') }}</h2><strong>{{ summary.total_records.toLocaleString() }}</strong></article>
      </section>
      <section class="panel"><div class="row"><h2>{{ tr('每日消费') }}</h2><div class="period"><button v-for="n in [7,30]" :key="n" :aria-pressed="days===n" @click="days=n">{{ tr('近 {p0} 天',{p0:n}) }}</button></div></div>
        <p class="period-total">¥ {{ money(range.reduce((v,d)=>v+d.cost,0)) }}</p>
        <div class="chart" :aria-label="tr('每日消费')"><div v-for="d in range" :key="d.date" :title="d.date+' · ¥'+money(d.cost)" :aria-label="d.date+' · ¥'+money(d.cost)" tabindex="0"><i :style="{height:(100*d.cost/max)+'%'}"/></div></div>
        <div class="dates"><span>{{ range[0]?.date }}</span><span>{{ range.at(-1)?.date }}</span></div>
      </section>
      <section class="panel"><h2>{{ tr('按模型统计') }}</h2><div v-for="m in summary.by_model" :key="m.model" class="line"><span>{{ m.model }}</span><b>¥ {{ money(m.cost) }}</b></div><p v-if="!summary.by_model.length">{{ tr('暂无计费记录') }}</p></section>
    </template>
    <template v-else-if="section==='models'"><div class="period filters"><button v-for="k in ['all',...new Set(models.flatMap(m=>m.kinds))]" :key="k" :aria-pressed="kind===k" @click="kind=k">{{ kinds[k] ?? tr('全部') }}</button></div>
      <section class="catalog"><article v-for="m in catalog" :key="m.id"><small>{{ m.kinds.map(k=>kinds[k]).join(' / ') }}</small><h2>{{ m.name }}</h2><code>{{ m.id }}</code><p v-if="m.image_model_type">{{ m.image_model_type }} · {{ m.reference_image_urls ? tr('支持参考图') : tr('文生图') }}</p><ul><li v-for="r in rates(m.pricing,m)" :key="r">{{ r }}</li></ul></article></section>
      <p v-if="!catalog.length">{{ tr('暂无可用模型') }}</p>
    </template>
    <template v-else-if="section==='keys'"><p v-if="!auth.activeTeamId">{{ tr('请选择可用团队') }}</p><template v-else>
      <form class="row key-form" @submit.prevent="create"><label>{{ tr('密钥名称') }}<input v-model="name" maxlength="80" autocomplete="off" :placeholder="tr('例如：我的本地猫影')"></label><label>{{ tr('用途') }}<select v-model="purpose"><option value="api">{{ tr('通用 API') }}</option><option value="studio">{{ tr('本地猫影') }}</option></select></label><AppButton type="submit" variant="primary" :disabled="!name.trim() || changes">{{ tr('创建密钥') }}</AppButton></form>
      <div v-if="secret" class="panel revealed"><h2>{{ tr('请保存新密钥，仅显示一次') }}</h2><code>{{ secret }}</code><AppButton @click="copy(secret)">{{ tr('复制') }}</AppButton><AppButton @click="secret=''">{{ tr('完成') }}</AppButton></div>
      <section class="panel"><div v-for="k in keys" :key="k.id" class="line"><span><b>{{ k.name }}</b> <code>{{ k.preview }}</code> <small>{{ k.purpose==='studio' ? tr('本地猫影') : tr('通用 API') }}</small></span><AppButton :disabled="changes" @click="revoke(k)">{{ tr('停用') }}</AppButton></div><p v-if="!keys.length">{{ tr('当前团队下还没有个人 API Key') }}</p></section>
    </template></template>
    <template v-else-if="section==='docs'"><section class="panel"><h2>{{ tr('身份认证') }}</h2><p>{{ tr('在 API Keys 中创建密钥，通过 Authorization 请求头发送。') }}</p><code>Authorization: Bearer &lt;API_KEY&gt;</code></section>
      <section class="panel"><h2>{{ tr('查询模型列表') }}</h2><code>GET /v1/models</code><p>{{ tr('返回当前启用的平台模型、模型 ID 和配置价格。') }}</p><pre>curl "{{ apiBase }}/models" \
  -H "Authorization: Bearer $NOVELVIDS_API_KEY"</pre><RouterLink to="/platform/models">{{ tr('查看模型目录') }} ↗</RouterLink></section>
      <section class="panel"><h2>{{ tr('对话生成') }}</h2><code>POST /v1/chat/completions</code><p>{{ tr('本地文本模型选择 OpenAI 兼容协议，Base URL 使用下方地址，模型 ID 从模型目录复制。支持流式输出与已启用的工具调用。') }}</p><code>{{ apiBase }}</code><pre>import os, uuid
from openai import OpenAI

client = OpenAI(base_url="{{ apiBase }}", api_key=os.environ["NOVELVIDS_API_KEY"])
stream = client.chat.completions.create(
    model=os.environ["NOVELVIDS_MODEL_ID"],
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
    stream_options={"include_usage": True},
    extra_headers={"Idempotency-Key": str(uuid.uuid4())},
)
for part in stream:
    if part.choices:
        print(part.choices[0].delta.content or "", end="")</pre></section>
      <section class="panel"><h2>{{ tr('图像生成') }}</h2><code>POST /v1/images/generations</code><p>{{ tr('从目录选择图像模型 ID。size 可使用模型支持的清晰度或像素尺寸；支持参考图的模型接受 image 数组中的 HTTPS 地址。结果在 data[].url 中，由调用方直接下载。') }}</p><pre>{
  "model": "nv-MODEL_ID",
  "prompt": "薄暮中的山间庭院",
  "size": "2K",
  "aspect_ratio": "16:9",
  "response_format": "url"
}</pre></section>
      <section class="panel"><h2>{{ tr('查询请求状态') }}</h2><code>GET /v1/requests/{id}</code><p>{{ tr('响应头 X-Request-Id 是请求编号。建议每次生成发送唯一 Idempotency-Key；重复提交返回 409 和原编号。用同一账户和团队的密钥可查询结算状态与实际 token 用量。') }}</p></section></template>
  </main>
</template>
<style scoped>
.console{max-width:1200px;margin:0 auto;padding:clamp(22px,4vw,56px);color:var(--app-text);font-variant-numeric:tabular-nums}
.console header,.row,.line,.dates{display:flex;align-items:center;justify-content:space-between;gap:14px}.console header{margin-bottom:32px;border-bottom:1px solid var(--app-border);padding-bottom:18px}
.console h1{margin:0;font-size:clamp(25px,3vw,34px);letter-spacing:-.04em}.console h2{font-size:16px;margin:0;line-height:1.5}.console header span,.console small,.dates,.console p{color:var(--app-text-secondary)}.console a{color:var(--app-accent)}
.totals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:var(--app-surface);border:1px solid var(--app-border);border-radius:12px}.totals article,.panel,.catalog article{padding:22px}.totals article+article{border-inline-start:1px solid var(--app-border)}.totals h2{font-weight:500;color:var(--app-text-secondary)}.totals strong{display:block;font-size:clamp(22px,3vw,36px);margin:10px 0}.panel,.catalog article{background:var(--app-surface);border:1px solid var(--app-border);border-radius:12px;margin-top:18px}
.period{display:flex;gap:4px;flex-wrap:wrap}.period button{background:var(--app-surface-muted);color:var(--app-text-secondary);border:0;border-radius:7px;padding:6px 12px;cursor:pointer}.period button[aria-pressed=true]{color:var(--app-accent);background:var(--app-accent-soft);font-weight:650}.console button:focus-visible,.chart div:focus-visible{outline:2px solid var(--app-accent)}.period-total{font-size:23px;margin:12px 0}.chart{display:flex;gap:5px;height:140px;align-items:end;border-bottom:1px solid var(--app-border);background:repeating-linear-gradient(to top,transparent 0 34px,var(--app-border) 34px 35px)}.chart div{min-width:0;height:100%;flex:1;display:flex;align-items:end;justify-content:center}.chart i{width:min(65%,28px);background:var(--app-accent);border-radius:3px 3px 0 0}.dates{margin-top:8px;font-size:12px}.line{padding:12px 0;border-bottom:1px solid var(--app-border)}.line:last-child{border-bottom:0}.catalog{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(270px,100%),1fr));gap:12px}.catalog h2{margin:8px 0}.catalog ul{list-style:none;padding:0;color:var(--app-text-secondary)}.key-form{justify-content:flex-start;align-items:end}.key-form label{display:grid;gap:6px}.key-form input,.key-form select{background:var(--app-surface);color:inherit;border:1px solid var(--app-border);border-radius:7px;padding:8px}.console code,.console pre{font-family:ui-monospace,monospace;overflow-wrap:anywhere}.revealed code{display:block;margin:12px 0}.console pre{background:var(--app-surface-muted);border-radius:6px;padding:12px;white-space:pre-wrap}
@media(max-width:640px){.totals{grid-template-columns:1fr}.totals article+article{border-inline-start:0;border-top:1px solid var(--app-border)}.panel,.catalog article,.totals article{padding:14px}.row{flex-wrap:wrap}}
</style>
