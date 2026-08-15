<script setup lang="ts">
import { computed } from 'vue'
import { BadgePercent } from 'lucide-vue-next'
import { pricingDiscount, pricingDiscountDescription } from '@/shared/modelPricing'
import type { ModelPricing } from '@/types'

const props = withDefaults(defineProps<{
  cost: number
  pricing?: ModelPricing | null
  prefix?: string
}>(), {
  prefix: '约',
})

const discount = computed(() => pricingDiscount(props.pricing))
const final = computed(() => props.cost * discount.value)
const isDiscounted = computed(() => discount.value > 0 && discount.value < 1)
const description = computed(() => pricingDiscountDescription(props.pricing))
</script>

<template>
  <span v-if="cost > 0" class="billing-price-tag">
    {{ prefix }}
    <s v-if="isDiscounted" class="billing-price-tag__original">¥{{ cost.toFixed(2) }}</s>
    <span class="billing-price-tag__final">¥{{ final.toFixed(2) }}</span>
    <span v-if="isDiscounted" class="billing-price-tag__badge" :title="description || undefined" aria-label="优惠"><BadgePercent :size="14" /></span>
  </span>
</template>

<style scoped>
.billing-price-tag {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  white-space: nowrap;
}
.billing-price-tag__original {
  color: var(--app-text-muted, #9398a8);
  text-decoration: line-through;
  font-weight: 500;
}
.billing-price-tag__final {
  font-weight: 600;
}
.billing-price-tag__badge {
  display: inline-flex;
  align-items: center;
  align-self: center;
  flex: 0 0 auto;
  color: #ef4444;
}
</style>
