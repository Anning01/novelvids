<script setup lang="ts">
import { computed } from 'vue'
import { LocateFixed, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { formatVideoGenerationError } from '@/shared/videoGenerationError'
import type { VideoInputImageReference } from '@/types'

const props = defineProps<{
  error: string
  busy?: boolean
  reference?: VideoInputImageReference
}>()

const emit = defineEmits<{
  retry: []
  locateReference: [number: number]
}>()

const details = computed(() => formatVideoGenerationError(props.error))
const title = computed(() => props.reference
  ? `参考图「${props.reference.label}」包含真人信息`
  : details.value.title)
const message = computed(() => props.reference
  ? `参考图「${props.reference.label}」可能包含真实人物，供应商因隐私保护拒绝了本次生成。`
  : details.value.message)
</script>

<template>
  <div class="video-generation-error" role="alert">
    <span class="video-generation-error__icon"><TriangleAlert :size="24" /></span>
    <strong>{{ title }}</strong>
    <p>{{ message }}</p>
    <p class="video-generation-error__suggestion">{{ details.suggestion }}</p>

    <button
      v-if="reference"
      type="button"
      class="video-generation-error__reference"
      :aria-label="`定位参考图 ${reference.label}`"
      @click="emit('locateReference', reference.number)"
    >
      <img :src="reference.url" :alt="reference.label" />
      <span><small>问题素材</small><strong>{{ reference.label }}</strong></span>
      <LocateFixed :size="14" />
    </button>

    <details class="video-generation-error__technical">
      <summary>技术详情</summary>
      <dl>
        <template v-if="details.errorCode">
          <dt>错误码</dt><dd>{{ details.errorCode }}</dd>
        </template>
        <template v-if="details.httpStatus">
          <dt>HTTP</dt><dd>{{ details.httpStatus }}</dd>
        </template>
        <template v-if="details.requestId">
          <dt>请求编号</dt><dd>{{ details.requestId }}</dd>
        </template>
      </dl>
      <p>{{ details.raw }}</p>
    </details>

    <AppButton variant="soft" size="sm" :disabled="busy" @click="emit('retry')">
      <RefreshCw :size="13" />重新生成
    </AppButton>
  </div>
</template>

<style scoped>
.video-generation-error {
  display: grid;
  width: min(430px, calc(100% - 40px));
  max-height: calc(100% - 40px);
  justify-items: center;
  gap: 8px;
  padding: 18px 20px;
  overflow: auto;
  color: #fff1f3;
  border: 1px solid rgb(239 92 112 / 42%);
  border-radius: 12px;
  background: rgb(77 32 43 / 42%);
  text-align: center;
  scrollbar-width: none;
}

.video-generation-error::-webkit-scrollbar { display: none; }
.video-generation-error__icon { display: grid; width: 40px; height: 40px; place-items: center; color: #ff8292; border-radius: 10px; background: rgb(239 92 112 / 12%); }
.video-generation-error > strong { font-size: 14px; line-height: 1.4; }
.video-generation-error > p { margin: 0; font-size: 11px; line-height: 1.65; }
.video-generation-error__suggestion { color: #ffc4cc; }
.video-generation-error__reference { display: grid; width: min(270px,100%); grid-template-columns: 38px minmax(0,1fr) auto; align-items: center; gap: 9px; padding: 6px; border: 1px solid rgb(255 181 191 / 22%); border-radius: 9px; color: #fff1f3; background: rgb(255 255 255 / 7%); text-align: left; cursor: pointer; transition: border-color .16s ease,background .16s ease,transform .16s ease; }
.video-generation-error__reference:hover { border-color: rgb(255 181 191 / 50%); background: rgb(255 255 255 / 11%); transform: translateY(-1px); }
.video-generation-error__reference img { width: 38px; height: 30px; border-radius: 6px; object-fit: cover; }
.video-generation-error__reference span { min-width: 0; }
.video-generation-error__reference small,.video-generation-error__reference strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.video-generation-error__reference small { margin-bottom: 2px; color: #c9aeb4; font-size: 8px; }
.video-generation-error__reference strong { font-size: 10px; }
.video-generation-error__technical { width: 100%; color: #d9c6ca; border-top: 1px solid rgb(255 255 255 / 10%); font-size: 10px; text-align: left; }
.video-generation-error__technical summary { width: max-content; margin: 9px auto 0; color: #ffb5bf; cursor: pointer; user-select: none; }
.video-generation-error__technical dl { display: grid; grid-template-columns: max-content minmax(0,1fr); gap: 5px 10px; margin: 10px 0 0; }
.video-generation-error__technical dt { color: #ac989d; }
.video-generation-error__technical dd { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.video-generation-error__technical p { max-height: 72px; margin: 9px 0 0; padding: 8px; overflow: auto; color: #b9a5aa; border-radius: 7px; background: rgb(0 0 0 / 14%); line-height: 1.5; overflow-wrap: anywhere; scrollbar-width: none; }
.video-generation-error__technical p::-webkit-scrollbar { display: none; }
.video-generation-error button { margin-top: 2px; color: #fff0f2; border-color: rgb(255 181 191 / 28%); background: rgb(255 255 255 / 9%); }
</style>
