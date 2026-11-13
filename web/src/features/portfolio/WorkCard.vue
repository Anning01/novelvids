<script setup lang="ts">
import { Clock3, Clapperboard, Coins, Play, Star, UserRound } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { money } from '@/features/billing/recordDisplay'
import FinishedCover from '@/features/finished-episodes/FinishedCover.vue'
import { productionCostLabel, productionTime, workDate, workLength, workResolution, workStatus, type WorkSummary } from './api'

defineProps<{ work: WorkSummary }>()
</script>

<template>
  <article class="work-card">
    <RouterLink :to="{ name: 'work-detail', params: { projectId: work.project_id } }" class="work-card-cover" :aria-label="tr('查看作品 {p0}', { p0: work.title })">
      <FinishedCover :version-id="work.cover_export_id" />
      <div class="work-cover-badges">
        <span class="work-badge" :data-status="work.status">{{ workStatus(work.status) }}</span>
        <span v-if="work.featured" class="work-badge is-featured"><Star :size="12" aria-hidden="true" />{{ tr('首页推荐') }}</span>
      </div>
    </RouterLink>
    <div class="work-card-copy">
      <h2 :title="work.title">{{ work.title }}</h2>
      <p><Clapperboard :size="14" aria-hidden="true" />{{ tr('{p0} 集', { p0: work.episode_count }) }} · {{ workLength(work.duration) }} · {{ workResolution(work.resolution) }}</p>
      <dl class="work-production">
        <div class="work-producer">
          <dt><UserRound :size="14" aria-hidden="true" />{{ tr('制作人') }}</dt>
          <dd :title="work.producer">{{ work.producer || tr('未填写') }}</dd>
        </div>
        <div :title="tr('从项目创建到最近一次成功合成的经过时间')">
          <dt><Clock3 :size="14" aria-hidden="true" />{{ tr('制作耗时') }}</dt>
          <dd>{{ productionTime(work.production_seconds) }}</dd>
        </div>
        <div v-if="work.recorded_cost != null" :title="tr('按成本页面的已入账费用汇总，包含历史生成及画质增强；未入账用量不计入。')">
          <dt><Coins :size="14" aria-hidden="true" />{{ productionCostLabel(work.cost_scope) }}</dt>
          <dd>{{ work.pending_cost ? tr('待结算') : money(work.recorded_cost) }}</dd>
        </div>
      </dl>
      <p>{{ workDate(work.archived_at) }}<span v-if="work.category"> · {{ tr(work.category) }}</span></p>
      <div v-if="work.tags.length" class="work-tags"><span v-for="tag in work.tags.slice(0, 4)" :key="tag">{{ tag }}</span></div>
      <div class="work-actions">
        <RouterLink :to="{ name: 'work-detail', params: { projectId: work.project_id } }" class="work-link"><Play :size="14" aria-hidden="true" />{{ tr('查看作品') }}</RouterLink>
      </div>
    </div>
  </article>
</template>
