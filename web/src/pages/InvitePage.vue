<script setup lang="ts">
import { tr } from '@/i18n'

import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { useAuthStore } from '@/features/auth/authStore'
import type { InviteItem } from '@/types'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const token = String(route.params.token || '')
const invite = ref<InviteItem | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const joining = ref(false)
const registerForm = ref({ username: '', nickname: '', password: '' })
const registering = ref(false)

async function load() {
  try {
    invite.value = await api.teamInviteInfo(token).then(response => response.data)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : tr('邀请链接无效')
  } finally {
    loading.value = false
  }
}

async function join() {
  if (!invite.value) return
  joining.value = true
  errorMessage.value = ''
  try {
    await api.joinTeamInvite(token)
    await auth.refreshMe()
    notice.success(tr('已加入「{p0}」', { p0: invite.value.team_name }))
    await router.replace('/')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : tr('加入失败')
  } finally {
    joining.value = false
  }
}

async function register() {
  if (!registerForm.value.username || registerForm.value.password.length < 8) return
  registering.value = true
  errorMessage.value = ''
  try {
    await auth.register({
      username: registerForm.value.username.trim(),
      nickname: registerForm.value.nickname,
      password: registerForm.value.password,
      invite_token: token,
    })
    notice.success(tr('欢迎加入「{p0}」', { p0: invite.value?.team_name ?? '' }))
    await router.replace('/')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : tr('注册失败')
  } finally {
    registering.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="invite-page">
    <section class="invite-card">
      <p v-if="loading" class="dim">{{ tr('加载邀请信息…') }}</p>

      <template v-else-if="invite">
        <img class="invite-logo" src="/logo.png" :alt="tr('猫影')" />
        <h1>{{ tr('加入「') }}{{ invite.team_name }}」</h1>
        <p class="invite-subtitle">{{ tr('你受邀加入该团队，角色：') }}{{ { admin: tr('团队管理员'), creator: tr('创作者'), viewer: tr('查看者') }[invite.role] }}</p>

        <template v-if="auth.isLoggedIn">
          <button class="primary-button" type="button" :disabled="joining" @click="join">
            {{ joining ? tr('加入中…') : tr('加入团队') }}
          </button>
        </template>
        <form v-else class="register-form" @submit.prevent="register">
          <label>
            <span>{{ tr('用户名') }}</span>
            <input v-model="registerForm.username" type="text" autocomplete="username" :placeholder="tr('设置登录用户名')" required />
          </label>
          <label>
            <span>{{ tr('昵称（可选）') }}</span>
            <input v-model="registerForm.nickname" type="text" :placeholder="tr('你的昵称')" />
          </label>
          <label>
            <span>{{ tr('密码') }}</span>
            <input v-model="registerForm.password" type="password" autocomplete="new-password" :placeholder="tr('至少 8 位')" required minlength="8" />
          </label>
          <button class="primary-button" type="submit" :disabled="registering">
            {{ registering ? tr('注册中…') : tr('注册并加入') }}
          </button>
        </form>
        <p class="invite-hint">{{ tr('没有账号？注册后将自动加入团队。已有账号？') }}<RouterLink to="/login">{{ tr('去登录') }}</RouterLink> {{ tr('后再次打开本链接。') }}</p>
      </template>

      <template v-else>
        <h1>{{ tr('邀请无效') }}</h1>
        <p class="invite-subtitle">{{ errorMessage || tr('邀请链接不存在或已过期') }}</p>
        <RouterLink class="primary-button link-button" to="/">{{ tr('返回首页') }}</RouterLink>
      </template>
    </section>
  </main>
</template>

<style scoped>
.invite-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--app-canvas, #f8f9fc);
}
.invite-card {
  width: 100%;
  max-width: 400px;
  background: var(--app-surface, #fff);
  border: 1px solid var(--app-border, #e3e5ec);
  border-radius: 16px;
  padding: 32px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08);
  text-align: center;
}
.invite-logo { width: 56px; height: 56px; border-radius: 12px; margin: 0 auto; }
.invite-card h1 { margin: 0; font-size: 20px; color: var(--app-text, #303442); }
.invite-subtitle { margin: -6px 0 4px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.invite-hint { margin: 4px 0 0; font-size: 12px; color: var(--app-text-muted, #9398a8); }
.register-form { display: flex; flex-direction: column; gap: 10px; text-align: left; }
.register-form label { display: flex; flex-direction: column; gap: 6px; font-size: 13px; color: var(--app-text-muted, #9398a8); }
.register-form input {
  height: 38px; padding: 0 12px; border: 1px solid var(--app-border, #e3e5ec); border-radius: 10px;
  background: var(--app-surface-muted, #f2f3f7); color: var(--app-text, #303442); font-size: 14px; outline: none;
}
.primary-button {
  height: 40px; border: none; border-radius: 10px; background: var(--app-accent, #5b5cf6);
  color: #fff; font-size: 14px; font-weight: 600; cursor: pointer;
}
.primary-button:disabled { opacity: 0.6; }
.link-button { display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
.dim { color: var(--app-text-muted, #9398a8); font-size: 13px; }
</style>
