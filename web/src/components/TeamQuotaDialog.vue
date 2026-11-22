<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppButton from './AppButton.vue'
import { api, ApiRequestError } from '@/api'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'

const props = defineProps<{ team: { id: number; name: string }; initialMode?: 'credit' | 'debit' }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const dialog = ref<HTMLDialogElement>()
const mode = ref<'credit' | 'debit'>(props.initialMode ?? 'debit')
const amount = ref('')
const reason = ref('')
const snapshot = ref<{ balance: number | string; last_transaction_id: number } | null>(null)
const busy = ref(false), error = ref('')
const validAmount = computed(() => /^\d+(\.\d{1,6})?$/.test(amount.value) && Number(amount.value) > 0)
const exceedsBalance = computed(() => mode.value === 'debit' && snapshot.value && Number(amount.value) > Number(snapshot.value.balance))
const canSubmit = computed(() => snapshot.value && validAmount.value && !exceedsBalance.value && reason.value.trim() && !busy.value)

async function loadBalance() {
  snapshot.value = null
  snapshot.value = (await api.teamBalance(props.team.id)).data
}
async function refresh() {
  error.value = ''
  busy.value = true
  try { await loadBalance() }
  catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
async function submit() {
  if (!canSubmit.value || !snapshot.value) return
  busy.value = true
  error.value = ''
  try {
    const change = { team_id: props.team.id, amount: amount.value, note: reason.value.trim(), last_transaction_id: snapshot.value.last_transaction_id }
    if (mode.value === 'debit') await api.teamDeduct(change)
    else await api.teamTopUp(change)
    notice.success(tr('团队额度已调整'))
    emit('saved')
  } catch (e) {
    error.value = (e as Error).message
    if (e instanceof ApiRequestError && e.code === 409) {
      // Fetch the new revision, then wait for a fresh administrator submission.
      try { await loadBalance() } catch (readError) { error.value = (readError as Error).message }
    }
  } finally { busy.value = false }
}
onMounted(() => { dialog.value?.showModal(); void refresh() })
</script>

<template>
  <dialog ref="dialog" class="quota-dialog" aria-labelledby="quota-title" @cancel.prevent="!busy && emit('close')">
    <form @submit.prevent="submit">
      <h2 id="quota-title">{{ tr('调整团队额度') }}</h2>
      <p>{{ team.name }} · {{ tr('当前余额') }} <strong>{{ snapshot ? '¥ ' + snapshot.balance : '…' }}</strong></p>
      <fieldset :disabled="busy">
        <label><input v-model="mode" type="radio" value="credit" name="quota-direction">{{ tr('增加额度') }}</label>
        <label><input v-model="mode" type="radio" value="debit" name="quota-direction">{{ tr('扣减额度') }}</label>
      </fieldset>
      <label class="quota-field">{{ tr('金额（元）') }}<input v-model.trim="amount" inputmode="decimal" required :disabled="busy" /></label>
      <label class="quota-field">{{ tr('调整原因') }}<input v-model="reason" maxlength="255" required :disabled="busy" /></label>
      <p v-if="exceedsBalance || error" role="alert">{{ exceedsBalance ? tr('扣减金额不能超过团队余额') : error }}</p>
      <footer>
        <AppButton type="button" :disabled="busy" @click="emit('close')">{{ tr('取消') }}</AppButton>
        <AppButton v-if="!snapshot && error" type="button" @click="refresh">{{ tr('重新加载') }}</AppButton>
        <AppButton type="submit" variant="primary" :loading="busy" :disabled="!canSubmit">{{ mode === 'debit' ? tr('确认扣减') : tr('确认增加') }}</AppButton>
      </footer>
    </form>
  </dialog>
</template>

<style scoped>
.quota-dialog { width: min(380px, calc(100vw - 32px)); box-sizing: border-box; padding: 22px; border: 1px solid var(--app-border); border-radius: 14px; color: var(--app-text); background: var(--app-surface); }
.quota-dialog::backdrop { background: rgb(12 15 24 / 48%); }
.quota-dialog form, .quota-field { display: grid; gap: 7px; }
.quota-dialog form { gap: 14px; }
.quota-dialog h2, .quota-dialog p { margin: 0; }
.quota-dialog h2 { font-size: 18px; }.quota-dialog p, .quota-dialog label { font-size: 13px; }
.quota-dialog fieldset, .quota-dialog footer { display: flex; align-items: center; gap: 12px; margin: 0; padding: 0; border: 0; }
.quota-dialog fieldset label { display: inline-flex; align-items: center; gap: 5px; }
.quota-field input { border: 1px solid var(--app-border-strong); border-radius: 8px; padding: 9px; background: var(--app-surface-muted); color: inherit; font: inherit; }
.quota-dialog [role="alert"] { color: var(--creation-danger); }.quota-dialog footer { justify-content: flex-end; }
</style>
