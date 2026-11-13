<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, authHeaders, request } from '@/api'
import { tr } from '@/i18n'
import { useAuthStore } from '@/features/auth/authStore'
import AppButton from '@/components/AppButton.vue'

const route = useRoute()
const auth = useAuthStore()
const teamId = ref(auth.activeTeamId)
const teams = ref(auth.activeMemberships.map(m => ({id: m.team_id, name: m.team_name})))
const team = computed(() => teams.value.find(t => t.id === teamId.value))
const busy = ref(false)
const done = ref(false)
const error = ref('')
onMounted(async () => {
  if (auth.isSuperAdmin) {
    try { teams.value = (await api.teams()).data.items.filter(t => t.status === 1) }
    catch (e) { error.value = (e as Error).message }
  }
})
async function connect() {
  if (busy.value || done.value || !team.value) return
  busy.value = true
  error.value = ''
  try {
    await request('/auth/local-mcp/' + encodeURIComponent(String(route.params.code)) + '/approve', {
      method: 'POST', headers: {...authHeaders(), 'X-Team-Id': String(team.value.id)},
    })
    auth.setActiveTeam(team.value.id)
    done.value = true
  } catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}
</script>
<template>
  <main class="connection">
    <section>
      <h1>{{ tr('连接本机 MCP') }}</h1>
      <p>{{ tr('本机创作工具将使用当前登录身份，按所选团队权限读取和同步作品。退出登录后连接失效。') }}</p>
      <label>{{ tr('目标团队') }}
        <select v-model="teamId" :disabled="busy || done">
          <option :value="null" disabled>{{ tr('请选择团队') }}</option>
          <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.name }}</option>
        </select>
      </label>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="done" role="status">{{ tr('已连接，可以返回创作工具。') }}</p>
      <AppButton v-else variant="primary" :disabled="!team || busy" :loading="busy" @click="connect">{{ tr('确认连接') }}</AppButton>
    </section>
  </main>
</template>
<style scoped>
.connection { display:grid; place-items:center; min-height:100dvh; background:var(--app-canvas); color:var(--app-text); }
section { width:min(420px,90vw); padding:24px; box-sizing:border-box; border-radius:14px; background:var(--app-surface); border:1px solid var(--app-border); }
h1 { font-size:20px; } p { color:var(--app-text-secondary); line-height:1.65; }
label { display:grid; gap:8px; margin:20px 0; } select { padding:8px; color:var(--app-text); background:var(--app-surface); border:1px solid var(--app-border-strong); border-radius:6px; }
</style>
