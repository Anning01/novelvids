<script setup lang="ts">
import { computed } from 'vue'
import { Film, Music2, Type, Sticker, X, RotateCcw, Bold, Underline, Italic, AlignLeft, AlignCenter, AlignRight, Ban } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { scaleSticker } from './stickerTransform'
import { presetSelected } from './subtitleStyle'
import { dbVolume, volumeDb, kindLabel } from './model'
import type { EditClip, EditorMedia, ClipPatch, SubtitlePreset } from './types'
const props = defineProps<{ clip: EditClip | null; media?: EditorMedia; readOnly: boolean; open: boolean; browsing?: EditorMedia | null; subtitleStyles?: SubtitlePreset[] }>()
const emit = defineEmits<{ change: [patch: ClipPatch]; trim: [trimIn: number, trimOut: number, speed: number]; close: [] }>()
const sourceDuration = computed(() => props.media?.duration || 0)
function number(event: Event) { return Number((event.target as HTMLInputElement).value) }
function speed(value: number) {
  const clip = props.clip
  if (!clip || clip.type !== 'video' || !Number.isFinite(value)) return
  const rate = Math.max(.1, Math.min(20, Math.round(value * 100) / 100))
  emit('trim', clip.trim_in, clip.trim_in + clip.duration * clip.speed, rate)
}
function gain(value: number) {
  if (Number.isFinite(value)) emit('change', { volume: dbVolume(Math.max(-20, Math.min(20, value))) })
}
</script>
<template>
  <aside class="editor-inspector" :class="{ 'is-open': open }" :aria-label="tr('选中项属性')">
    <header class="editor-panel-heading"><h2>{{ clip ? tr('{p0}属性', { p0: kindLabel(clip.type) }) : tr('片段属性') }}</h2><button class="editor-icon-btn editor-mobile-only" :aria-label="tr('关闭属性')" @click="emit('close')"><X :size="16" /></button></header>
    <template v-if="clip">
      <div class="editor-inspector-item"><component :is="{ video: Film, audio: Music2, subtitle: Type, sticker: Sticker }[clip.type]" :size="19" /><div><strong>{{ clip.type === 'subtitle' ? tr('字幕片段') : clip.name }}</strong><small v-if="clip.type!=='subtitle'">{{ clip.duration.toFixed(2) }}s</small></div></div>
      <div class="editor-inspector-scroll">
        <section v-if="clip.type!=='subtitle'&&clip.type!=='sticker'" class="editor-property"><h3>{{ tr('素材信息') }}</h3><dl class="editor-media-info"><dt>{{ tr('时长') }}</dt><dd>{{ (sourceDuration || clip.duration).toFixed(2) }}s</dd><template v-if="media?.width && media?.height"><dt>{{ tr('分辨率') }}</dt><dd>{{ media.width }} × {{ media.height }}</dd></template><template v-if="media?.fps"><dt>{{ tr('帧率') }}</dt><dd>{{ media.fps }} fps</dd></template></dl></section>
        <fieldset :disabled="readOnly">
          <section v-if="clip.type === 'video'" class="editor-property"><h3>{{ tr('变速') }}</h3><label class="editor-value-label" for="editor-speed">{{ tr('倍数') }}<span>{{ clip.speed.toFixed(2) }}×</span></label><div class="editor-value-control"><input id="editor-speed" :aria-label="tr('倍数')" type="range" min=".1" max="20" step=".01" :value="clip.speed" @input="speed(number($event))" /><div class="editor-number-unit"><input :aria-label="tr('倍速数值')" type="number" min=".1" max="20" step=".01" :value="clip.speed" @change="speed(number($event))" /><span>×</span></div></div><p class="editor-panel-note">{{ tr('时长') }} {{ clip.duration.toFixed(2) }}s</p><p v-if="clip.speed>16" class="editor-panel-note">{{ tr('超过 16× 使用静音抽帧预览，导出保留设定倍速与音频。') }}</p></section>
          <section v-if="clip.type === 'video' || clip.type === 'audio'" class="editor-property"><h3>{{ tr('声音') }}</h3><label class="editor-value-label" for="editor-gain">{{ clip.type === 'audio' ? tr('BGM 音量') : tr('原视频声音') }}<span>{{ clip.volume === 0 ? '−∞' : volumeDb(clip.volume).toFixed(1) }} dB</span></label><div class="editor-value-control"><input id="editor-gain" :aria-label="tr('音量')" type="range" min="-20" max="20" step=".1" :value="volumeDb(clip.volume)" @input="gain(number($event))" /><div class="editor-number-unit"><input :aria-label="tr('音量数值')" type="number" min="-20" max="20" step=".1" :value="volumeDb(clip.volume)" @change="gain(number($event))" /><span>dB</span></div></div></section>
          <section v-if="clip.type === 'video'" class="editor-property"><h3>{{ tr('画面') }}</h3><label class="editor-slider"><span>{{ tr('缩放') }}</span><output>{{ Math.round(clip.scale * 100) }}%</output><input type="range" min=".1" max="4" step=".01" :value="clip.scale" @input="emit('change', { scale: number($event) })" /></label><label class="editor-value-label" for="editor-rotation">{{ tr('旋转') }}<span>{{ (clip.rotation || 0).toFixed(2) }}°</span></label><div class="editor-value-control"><input id="editor-rotation" :aria-label="tr('旋转')" type="range" min="-180" max="180" step=".01" :value="clip.rotation || 0" @input="emit('change', { rotation: number($event) })" /><div class="editor-number-unit"><input :aria-label="tr('旋转角度')" type="number" min="-180" max="180" step=".01" :value="clip.rotation || 0" @change="emit('change', { rotation: number($event) })" /><span>°</span></div></div><button class="editor-link" @click="emit('change', { scale: 1, fit: 'contain', rotation: 0 })"><RotateCcw :size="13" />{{ tr('重置画面') }}</button></section>
          <section v-if="clip.type === 'audio'" class="editor-property"><h3>{{ tr('淡入淡出') }}</h3><div class="editor-field-pair"><label>{{ tr('淡入（秒）') }}<input type="number" min="0" step=".1" :max="clip.duration" :value="clip.fade_in" @input="emit('change', { fade_in: number($event) })" /></label><label>{{ tr('淡出（秒）') }}<input type="number" min="0" step=".1" :max="clip.duration" :value="clip.fade_out" @input="emit('change', { fade_out: number($event) })" /></label></div><label class="editor-check"><input type="checkbox" :checked="clip.loop" @input="emit('change', { loop: ($event.target as HTMLInputElement).checked })" />{{ tr('循环到片段结束') }}</label></section>
          <template v-if="clip.type === 'subtitle'">
            <section class="editor-property editor-subtitle-content"><h3>{{ tr('文字内容') }}</h3><textarea :aria-label="tr('字幕内容')" rows="5" maxlength="2000" :value="clip.text" @input="emit('change', { text: ($event.target as HTMLTextAreaElement).value })"></textarea></section>
            <section class="editor-property"><h3>{{ tr('样式') }}</h3>
              <label class="editor-value-label" for="editor-font-size">{{ tr('字号') }}<span>{{ clip.font_size }}</span></label>
              <div class="editor-value-control"><input id="editor-font-size" :aria-label="tr('字号')" type="range" min="12" max="160" step="1" :value="clip.font_size" @input="emit('change',{font_size:number($event)})"/><input :aria-label="tr('字号数值')" type="number" min="12" max="160" :value="clip.font_size" @change="emit('change',{font_size:number($event)})"/></div>
              <div class="editor-text-format" role="group" :aria-label="tr('文字样式')">
                <button type="button" class="editor-format-button" :aria-label="tr('加粗')" :aria-pressed="!!clip.bold" @click="emit('change',{bold:!clip.bold})"><Bold :size="17"/></button>
                <button type="button" class="editor-format-button" :aria-label="tr('下划线')" :aria-pressed="!!clip.underline" @click="emit('change',{underline:!clip.underline})"><Underline :size="17"/></button>
                <button type="button" class="editor-format-button" :aria-label="tr('斜体')" :aria-pressed="!!clip.italic" @click="emit('change',{italic:!clip.italic})"><Italic :size="17"/></button>
                <label class="editor-subtitle-color">{{ tr('颜色') }}<input type="color" :aria-label="tr('字幕颜色')" :value="clip.color" @input="emit('change',{color:($event.target as HTMLInputElement).value})"/></label>
              </div>
              <div class="editor-field-pair"><label>{{ tr('字间距') }}<input type="number" min="-5" max="50" step="1" :value="clip.letter_spacing??0" @change="emit('change',{letter_spacing:number($event)})"/></label><label>{{ tr('行间距') }}<input type="number" min="0" max="100" step="1" :value="clip.line_spacing??0" @change="emit('change',{line_spacing:number($event)})"/></label></div>
              <div class="editor-text-alignment" role="group" :aria-label="tr('对齐方式')"><span>{{ tr('对齐方式') }}</span><button v-for="item in ([{value:'left',label:tr('左对齐'),icon:AlignLeft},{value:'center',label:tr('居中对齐'),icon:AlignCenter},{value:'right',label:tr('右对齐'),icon:AlignRight}] as const)" :key="item.value" type="button" class="editor-format-button" :aria-label="item.label" :aria-pressed="(clip.align??'center')===item.value" @click="emit('change',{align:item.value})"><component :is="item.icon" :size="17"/></button></div>
            </section>
            <section class="editor-property"><h3>{{ tr('预设样式') }}</h3><div class="editor-subtitle-presets" role="group" :aria-label="tr('预设样式')"><button v-for="preset in subtitleStyles" :key="preset.id" type="button" class="editor-subtitle-preset" :aria-label="tr(preset.name)" :title="tr(preset.name)" :aria-pressed="presetSelected(clip,preset)" @click="emit('change',{color:preset.color,bold:preset.bold,stroke_color:preset.stroke_color,stroke_width:preset.stroke_width,shadow:preset.shadow})"><Ban v-if="preset.id==='none'" :size="23"/><span v-else aria-hidden="true" :style="{color:preset.color,WebkitTextStroke:`${preset.stroke_width/2}px ${preset.stroke_color}`,paintOrder:'stroke fill',textShadow:preset.shadow?'1px 2px 2px #0008':'none'}">T</span></button></div><p v-if="!subtitleStyles?.length" role="status" class="editor-panel-note">{{ tr('预设样式暂不可用，请重新加载') }}</p></section>
            <section class="editor-property"><h3>{{ tr('透明度') }}</h3><label class="editor-slider"><span>{{ tr('透明度') }}</span><output>{{ Math.round((clip.opacity??1)*100) }}%</output><input :aria-label="tr('字幕透明度')" type="range" min="0" max="1" step=".01" :value="clip.opacity??1" @input="emit('change',{opacity:number($event)})"/></label></section>
          </template>
          <section v-if="clip.type === 'sticker'" class="editor-property"><h3>{{ tr('画面') }}</h3><label class="editor-slider"><span>{{ tr('缩放') }}</span><output>{{ Math.round(clip.scale * 100) }}%</output><input :aria-label="tr('贴纸缩放')" type="range" min=".1" max="4" step=".01" :value="clip.scale" @input="emit('change', scaleSticker(clip,number($event)))" /></label><label class="editor-check"><input :aria-label="tr('等比缩放')" type="checkbox" :checked="clip.lock_aspect!==false" @change="emit('change',{lock_aspect:($event.target as HTMLInputElement).checked,scale_y:clip.scale_y??clip.scale})"/>{{ tr('等比缩放') }}</label><label class="editor-slider"><span>{{ tr('透明度') }}</span><output>{{ Math.round(clip.opacity * 100) }}%</output><input :aria-label="tr('贴纸透明度')" type="range" min="0" max="1" step=".01" :value="clip.opacity" @input="emit('change', { opacity: number($event) })" /></label><button class="editor-link" @click="emit('change',{x:50,y:50,scale:1,scale_y:null,lock_aspect:true,rotation:0,opacity:1})"><RotateCcw :size="13"/>{{ tr('重置贴纸') }}</button></section>
        </fieldset>
      </div>
    </template><div v-else class="editor-empty"><Film :size="28" /><span>{{ browsing?.name || tr('选择时间线中的片段以编辑属性') }}</span><span v-if="browsing">{{ tr('浏览素材不会修改时间线，请点击加号添加') }}</span></div>
  </aside>
</template>
