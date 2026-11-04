<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { tr } from '@/i18n'
import { catalogApi } from './catalog'
import { trimLocalAudioFile } from '@/shared/audioTrim'
import AppSelect from '@/components/AppSelect.vue'
import AppFileDropzone from '@/components/AppFileDropzone.vue'
import AudioRangeSlider from '@/components/AudioRangeSlider.vue'
import { useAuthStore } from '@/features/auth/authStore'
const props=defineProps<{folderId:number}>(),emit=defineEmits<{done:[]}>()
const auth=useAuthStore(),name=ref(''),gender=ref('未设置'),file=ref<File|null>(null),url=ref(''),duration=ref(0),start=ref(0),end=ref(0),busy=ref(false),error=ref(''),progress=ref(0)
let scope=0
function release(){if(url.value)URL.revokeObjectURL(url.value);url.value=''}
function applyFile(value:File|null){release();file.value=value;error.value='';duration.value=0;start.value=0;end.value=0;if(!value)return;if(value.size>200*1024*1024){error.value=tr('原音频不能超过 200MB');file.value=null;return}url.value=URL.createObjectURL(value);name.value=value.name.replace(/\.(mp3|wav)$/i,'')}
function loaded(value:number){duration.value=value;start.value=0;end.value=Math.min(value,30)}
const valid=computed(()=>!!file.value&&!!name.value.trim()&&duration.value>0&&end.value-start.value>=1&&end.value-start.value<=30)
const fileMeta=computed(()=>{if(!file.value)return'';const bytes=file.value.size;const size=bytes>=1024*1024?`${(bytes/1024/1024).toFixed(2)} MB`:`${Math.max(1,Math.round(bytes/1024))} KB`;return duration.value?`${size} · ${formatDuration(duration.value)}`:size})
function formatDuration(value:number){const minutes=Math.floor(value/60),seconds=Math.floor(value%60);return `${minutes}:${String(seconds).padStart(2,'0')}`}
async function upload(){if(!valid.value||busy.value)return;const version=scope,folder=props.folderId;busy.value=true;error.value='';try{let value=file.value!;if(start.value>.01||end.value<duration.value-.05)value=await trimLocalAudioFile(value,start.value,end.value);if(version!==scope)return;await catalogApi.uploadVoice(value,name.value.trim(),gender.value,folder,n=>{if(version===scope)progress.value=n});if(version===scope)emit('done')}catch(reason){if(version===scope)error.value=reason instanceof Error?reason.message:tr('参考音频上传失败')}finally{if(version===scope)busy.value=false}}
watch(()=>auth.activeTeamId,()=>{scope++;release();file.value=null;busy.value=false})
onBeforeUnmount(()=>{scope++;release()})
defineExpose({upload,valid,busy})
</script>
<template>
 <form class="catalog-voice-form" @submit.prevent="upload">
  <div class="catalog-upload__field">
   <label class="catalog-upload__label" for="catalog-voice-name">{{tr('音色名称')}}</label>
   <input id="catalog-voice-name" v-model="name" required maxlength="100" :disabled="busy"/>
  </div>
  <div class="catalog-upload__field">
   <span class="catalog-upload__label">{{tr('性别')}}</span>
   <AppSelect v-model="gender" :options="[{value:'未设置',label:tr('未设置')},{value:'男',label:tr('男')},{value:'女',label:tr('女')}]" :ariaLabel="tr('性别')" :disabled="busy" :menu-z-index="3000" />
  </div>
  <div class="catalog-upload__field">
   <span class="catalog-upload__label">{{tr('音频文件')}}</span>
   <AppFileDropzone accept=".mp3,.wav" :disabled="busy" :title="tr('点击选择音频文件')" :hint="tr('也可以将音频文件拖拽到这里')" :file-name="file?.name ?? ''" :meta="fileMeta" @select="applyFile($event[0] ?? null)"/>
   <p class="catalog-upload__hint">{{tr('选择 1–30 秒音频，作为角色或旁白的声音参考')}}</p>
   <p v-if="error" class="catalog-voice-form__error" role="alert">{{error}}</p>
   <progress v-if="busy" class="catalog-voice-form__progress" :value="progress" max="100"/>
  </div>
  <AudioRangeSlider v-if="url" v-model:start="start" v-model:end="end" :src="url" :duration="duration" @loaded-duration="loaded"/>
 </form>
</template>
<style scoped>
.catalog-voice-form{display:grid;gap:18px;color:var(--app-text)}
.catalog-voice-form__error{color:var(--app-danger);font-size:11px;line-height:1.6}
.catalog-voice-form__progress{width:100%;accent-color:var(--app-accent)}
</style>
