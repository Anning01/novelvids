<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowRight, Clapperboard, CirclePlay, Eye, EyeOff, Pause, Play, QrCode, ScanLine, UsersRound } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import QilingLogin from '@/features/auth/QilingLogin.vue'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import { API_BASE } from '@/api'
import AppButton from '@/components/AppButton.vue'
import type { LoginResult } from '@/types'

const BACKGROUND_VIDEO = 'https://sscm-media.oss-cn-guangzhou.aliyuncs.com/static/bg.mp4'
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const errorMessage = ref('')
const motion = ref<MediaQueryList>()
const motionAllowed = ref(false)
const videoFailed = ref(false)
const backgroundVideo = ref<HTMLVideoElement>()
const videoPaused = ref(false)
const agreed = ref(false)
const username = ref('')
const nickname = ref('')
const password = ref('')
const showPassword = ref(false)
const submitting = ref(false)
const canRegister = computed(() => auth.provider === 'password' && auth.registrationEnabled)
const isRegistration = computed(() => canRegister.value && route.path === '/register')

async function submitPassword() {
  if (!username.value.trim() || !password.value || submitting.value) return
  if (auth.legalReady && !agreed.value) return
  if (isRegistration.value && password.value.length < 8) return
  submitting.value = true
  errorMessage.value = ''
  try {
    if (isRegistration.value) {
      await auth.register({ username: username.value.trim(), nickname: nickname.value.trim(), password: password.value })
    } else {
      await auth.login(username.value.trim(), password.value)
    }
    await router.replace(destination())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : tr(isRegistration.value ? '注册失败，请重试' : '登录失败，请重试')
  } finally {
    submitting.value = false
  }
}

function switchMode(mode: 'login' | 'register') {
  if (submitting.value) return
  void router.replace({ path: mode === 'register' ? '/register' : '/login', query: route.query })
}

watch(isRegistration, () => {
  password.value = ''
  showPassword.value = false
  errorMessage.value = ''
})

function syncMotionPreference() {
  motionAllowed.value = !motion.value?.matches
}

function toggleBackgroundVideo() {
  videoPaused.value = !videoPaused.value
  if (videoPaused.value) backgroundVideo.value?.pause()
  else void backgroundVideo.value?.play().catch(() => { videoFailed.value = true })
}

onMounted(() => {
  if (auth.isLoggedIn) void router.replace(destination())
  else if (route.path === '/register' && !canRegister.value) void router.replace({ path: '/login', query: route.query })
  motion.value = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  syncMotionPreference()
  motion.value?.addEventListener('change', syncMotionPreference)
})
onUnmounted(() => motion.value?.removeEventListener('change', syncMotionPreference))

function destination() {
  const path = route.query.redirect
  return typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') && !path.includes('\\') ? path : '/'
}

async function qilingAuthenticated(session: LoginResult) {
  errorMessage.value = ''
  try {
    await auth.acceptSession(session)
    await router.replace(destination())
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : tr('登录失败，请重试')
  }
}
</script>

<template>
  <main class="cinematic-login" :class="{ 'has-password-auth': auth.provider === 'password' }">
    <div class="cinematic-login__background" aria-hidden="true">
      <video
        v-if="motionAllowed && !videoFailed"
        ref="backgroundVideo"
        :src="BACKGROUND_VIDEO"
        :autoplay="!videoPaused" muted loop playsinline preload="metadata"
        @error="videoFailed = true"
      />
    </div>

    <div class="cinematic-login__layout">
      <div class="cinematic-login__statement">
        <h1 class="cinematic-login__brand">
          <img src="/logo.png" alt="" width="72" height="72" />
          <span class="cinematic-login__brand-name">
            <span class="cinematic-login__brand-title">{{ tr('猫影短剧') }}</span>
            <span class="cinematic-login__wordmark" role="img" aria-label="NOVELVIDS">
              <span v-for="(letter, index) in 'NOVELVIDS'" :key="index" aria-hidden="true">{{ letter }}</span>
            </span>
          </span>
        </h1>
        <svg class="cinematic-login__arc" viewBox="0 0 410 11" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="login-title-light">
              <stop stop-color="#b4a5f8" stop-opacity="0" />
              <stop offset=".36" stop-color="#c5b9ff" stop-opacity=".82" />
              <stop offset=".68" stop-color="#c0aeff" />
              <stop offset="1" stop-color="#b4a5f8" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path fill="url(#login-title-light)" d="M0 9 C100 -5 260 12 410 5 C265 18 120 0 0 10Z" />
        </svg>
        <p class="cinematic-login__lead">{{ tr('开源 AI 漫剧与短剧创作工作台。') }}</p>
        <p class="cinematic-login__description">
          {{ tr('从故事、角色资产、分镜设计，到 AI 图片、视频生成与成片，把整个创作过程放进一个') }}<strong>{{ tr('可编辑、可追踪、能反复打磨的项目') }}</strong>。
        </p>
        <ul class="cinematic-login__stages">
          <li><Clapperboard aria-hidden="true" /><span>{{ tr('剧本与分镜') }}</span></li>
          <li><UsersRound aria-hidden="true" /><span>{{ tr('角色资产') }}</span></li>
          <li><CirclePlay aria-hidden="true" /><span>{{ tr('生成与成片') }}</span></li>
          <li><ScanLine aria-hidden="true" /><span>{{ tr('视频复刻') }}</span></li>
        </ul>
      </div>

      <section class="cinematic-login__glass" :class="{ 'is-password': auth.provider === 'password' }" aria-labelledby="login-title">
        <div v-if="canRegister" class="cinematic-login__switch" role="group" :aria-label="tr('登录与注册')" :class="{ 'is-register': isRegistration }">
          <span aria-hidden="true" />
          <button type="button" data-mode="login" :aria-pressed="!isRegistration" :disabled="submitting" @click="switchMode('login')">{{ tr('登录') }}</button>
          <button type="button" data-mode="register" :aria-pressed="isRegistration" :disabled="submitting" @click="switchMode('register')">{{ tr('注册') }}</button>
        </div>
        <h2 id="login-title">{{ auth.provider === 'password' ? tr(isRegistration ? '创建账号' : '账号登录') : tr('微信扫码登录') }}</h2>
        <p>{{ auth.provider === 'password' ? tr(isRegistration ? '让你的第一个故事，从这里开始。' : '登录后继续创作') : tr('使用器灵账号进入猫影') }}</p>
        <div v-if="auth.provider === 'password'" class="cinematic-login__form-body">
          <Transition name="auth-form" mode="out-in">
            <form :key="isRegistration ? 'register' : 'login'" class="cinematic-login__password" :aria-label="tr(isRegistration ? '注册账号' : '账号登录')" :aria-busy="submitting" @submit.prevent="submitPassword">
              <label for="auth-username">{{ tr('用户名') }}
                <input id="auth-username" v-model="username" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" :spellcheck="false" maxlength="100" :placeholder="tr('输入你的用户名')" required :disabled="submitting" />
              </label>
              <label v-if="isRegistration" for="auth-nickname">{{ tr('昵称（可选）') }}
                <input id="auth-nickname" v-model="nickname" name="nickname" type="text" autocomplete="nickname" maxlength="100" :placeholder="tr('创作时，大家怎么称呼你')" :disabled="submitting" />
              </label>
              <div class="cinematic-login__password-field">
                <label for="auth-password">{{ tr('密码') }}</label>
                <div class="cinematic-login__password-input">
                  <input id="auth-password" v-model="password" :name="isRegistration ? 'new-password' : 'password'" :type="showPassword ? 'text' : 'password'" :autocomplete="isRegistration ? 'new-password' : 'current-password'" :minlength="isRegistration ? 8 : undefined" maxlength="200" :placeholder="tr(isRegistration ? '设置至少 8 位密码' : '输入你的密码')" :aria-describedby="isRegistration ? 'auth-password-hint' : undefined" required :disabled="submitting" />
                  <button type="button" :aria-label="tr(showPassword ? '隐藏密码' : '显示密码')" aria-controls="auth-password" :disabled="submitting" @click="showPassword = !showPassword"><component :is="showPassword ? EyeOff : Eye" :size="18" aria-hidden="true" /></button>
                </div>
                <small v-if="isRegistration" id="auth-password-hint">{{ tr('至少 8 位，建议组合使用字母、数字和符号。') }}</small>
              </div>
              <AppButton type="submit" variant="primary" size="lg" :loading="submitting" :disabled="!username.trim() || !password || (auth.legalReady && !agreed)">{{ tr(isRegistration ? '创建账号，开始创作' : '登录') }}<ArrowRight v-if="!submitting" :size="17" aria-hidden="true" /></AppButton>
            </form>
          </Transition>
        </div>
        <template v-else-if="auth.qilingEnabled && !auth.isLoggedIn">
          <div class="cinematic-login__scan">
            <QilingLogin v-if="agreed && auth.legalReady" auto-start @authenticated="qilingAuthenticated" />
            <div v-else class="cinematic-login__placeholder">
              <QrCode :size="42" :stroke-width="1.35" aria-hidden="true" />
              <span>{{ tr('同意协议后显示二维码') }}</span>
            </div>
          </div>
        </template>
        <p v-else-if="auth.provider === 'qiling' && !auth.qilingEnabled" role="alert">{{ tr('器灵登录暂不可用，请稍后再试') }}</p>
        <div v-if="auth.legalReady" class="cinematic-login__legal">
          <label><input v-model="agreed" type="checkbox" /> {{ tr('我已阅读并同意') }}</label>
          <a :href="API_BASE + '/auth/legal/terms'" target="_blank" rel="noopener noreferrer">{{ tr('用户协议') }}</a>
          <span>{{ tr('和') }}</span>
          <a :href="API_BASE + '/auth/legal/privacy'" target="_blank" rel="noopener noreferrer">{{ tr('隐私政策') }}</a>
        </div>
        <p v-else-if="auth.provider === 'qiling'" role="alert">{{ tr('运营者尚未完善协议配置') }}</p>
        <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
      </section>
    </div>
    <button v-if="motionAllowed && !videoFailed" class="cinematic-login__motion" type="button" :aria-label="tr(videoPaused ? '播放背景动画' : '暂停背景动画')" @click="toggleBackgroundVideo">
      <component :is="videoPaused ? Play : Pause" :size="15" aria-hidden="true" />{{ tr(videoPaused ? '播放背景动画' : '暂停背景动画') }}
    </button>
  </main>
</template>

<style scoped>
.cinematic-login {
  position: relative;
  display: grid;
  align-content: center;
  min-height: 100dvh;
  isolation: isolate;
  overflow: hidden;
  color: #f8fafc;
  background: #090f1d;
}
.cinematic-login__background { position: absolute; z-index: -1; inset: 0; background: #090f1d url('/background-dark.png') center / cover; }
.cinematic-login__background video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.cinematic-login__background::after {
  position: absolute;
  inset: 0;
  content: '';
  background: linear-gradient(90deg, rgb(12 19 28 / 88%), rgb(18 26 36 / 58%) 28%, rgb(16 26 13 / 25%) 48%, transparent 62%, rgb(21 23 16 / 20%)),
    linear-gradient(0deg, rgb(5 10 23 / 45%), transparent 55%);
}
.cinematic-login__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 302px);
  gap: clamp(36px, 7vw, 112px);
  align-items: center;
  width: 100%;
  padding: 104px 6.6vw 90px 5vw;
}
.cinematic-login__statement { max-width: 630px; text-shadow: 0 2px 20px #080d1a; }
.cinematic-login__brand {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: clamp(12px, 1.3vw, 20px);
  margin: 0;
  color: #fffaf4;
  font-size: clamp(28px, 3.2vw, 48px);
  font-weight: 750;
  line-height: 1.08;
  letter-spacing: -.035em;
  text-shadow: 0 2px 0 #24203660, 0 4px 18px #080c18d9, 0 0 30px #d8ccff32;
}
.cinematic-login__brand img {
  display: block;
  width: clamp(52px, 5.3vw, 76px);
  height: auto;
  aspect-ratio: 1;
  border-radius: clamp(12px, 1.15vw, 17px);
  background: #f5f1fb;
  object-fit: contain;
}
.cinematic-login__brand-name { display: inline-grid; grid-template-columns: minmax(0, 1fr); justify-self: start; min-width: 0; }
.cinematic-login__brand-title { white-space: nowrap; letter-spacing: 0; }
.cinematic-login__wordmark {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  color: #e0d9f6;
  font-size: clamp(12px, 1.15vw, 16px);
  font-weight: 560;
  letter-spacing: 0;
}
.cinematic-login__arc { display: block; width: min(90%, 410px); height: 11px; margin-top: 10px; filter: drop-shadow(0 0 8px #a697e78c); }
.cinematic-login__lead { margin: 18px 0 0; color: #fff7e9; font-size: clamp(15px, 1.4vw, 20px); font-weight: 670; }
.cinematic-login__description { max-width: 460px; margin: 12px 0 0; color: #eee7dc; font-size: 16px; line-height: 1.7; }
.cinematic-login__description strong { color: #fff7e9; }
.cinematic-login__stages { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; width: min(100%, 380px); padding: 0; margin: 25px 0 0; list-style: none; }
.cinematic-login__stages li { display: grid; justify-items: center; align-content: start; gap: 8px; text-align: center; font-size: 13px; }
.cinematic-login__stages svg { width: 25px; height: 25px; stroke-width: 1.55; color: #d4c8f7; filter: drop-shadow(0 0 9px #c6b2ff72); }
.cinematic-login__glass {
  --qiling-qr-size: 184px;
  --app-text-secondary: #f1ebe8;
  --app-accent: #e5d8ff;
  --app-danger: #ffd0d2;
  position: relative;
  isolation: isolate;
  display: grid;
  justify-items: center;
  align-content: center;
  min-height: 352px;
  padding: 24px 10px 18px;
  text-align: center;
  text-shadow: 0 2px 10px #10151d;
  border: 1px solid rgb(236 230 255 / 26%);
  border-radius: 22px;
  background: linear-gradient(145deg, rgb(238 233 255 / 12%), rgb(20 28 43 / 34%));
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 9%), 0 8px 24px rgb(8 13 24 / 14%);
  -webkit-backdrop-filter: blur(18px) saturate(120%);
  backdrop-filter: blur(18px) saturate(120%);
}
.cinematic-login__glass h2 { margin: 0; font-size: 23px; font-weight: 640; }
.cinematic-login__glass > p { margin: 8px 0 18px; color: var(--app-text-secondary); font-size: 13px; }
.cinematic-login__glass > [role='alert'] { color: var(--app-danger); }
.cinematic-login__password { display: grid; gap: 15px; width: 100%; text-align: left; }
.cinematic-login__password label { display: grid; gap: 7px; font-size: 13px; }
.cinematic-login__password input { min-width: 0; min-height: 42px; padding: 0 12px; border: 1px solid rgb(221 212 248 / 30%); border-radius: 9px; color: #fffaf4; background: rgb(18 25 36 / 45%); }
.cinematic-login__password input:focus-visible { outline: 2px solid #d5c5ff; outline-offset: 2px; }
.cinematic-login__scan { width: 100%; min-height: 248px; display: grid; justify-items: center; align-items: start; }
.cinematic-login__placeholder {
  width: var(--qiling-qr-size);
  aspect-ratio: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  justify-content: center;
  align-items: center;
  border-radius: 8px;
  color: #ece4fa;
  background: rgb(210 201 232 / 14%);
  box-shadow: 0 2px 8px rgb(8 13 24 / 18%);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  font-size: 13px;
}
.cinematic-login__glass :deep(.qiling-login) { justify-items: center; width: 100%; gap: 4px; font-size: 13px; }
.cinematic-login__glass :deep(.qiling-login__code) { margin-bottom: 5px; box-shadow: 0 2px 8px rgb(8 13 24 / 18%); }
.cinematic-login__glass :deep(.qiling-login__countdown) { color: #e5d8ff; }
.cinematic-login__glass :deep(.qiling-login > button) { color: white; background: rgb(210 201 232 / 21%); }
.cinematic-login__legal { display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 4px; margin-top: 12px; color: #f1ebe8; font-size: 12px; }
.cinematic-login__legal label { display: inline-flex; gap: 5px; align-items: center; min-height: 36px; cursor: pointer; }
.cinematic-login__legal input { accent-color: #cbbaff; width: 15px; height: 15px; margin: 0; }
.cinematic-login__legal a { display: inline-flex; align-items: center; min-height: 36px; color: var(--app-accent); text-decoration: underline; text-underline-offset: 3px; }
.cinematic-login__legal a:hover { color: #fff; }
.cinematic-login__legal :is(input, a):focus-visible,
.cinematic-login__glass :deep(.qiling-login a:focus-visible) { outline: 2px solid #d5c5ff; outline-offset: 3px; }

.has-password-auth {
  --login-panel: rgb(238 233 255 / 14%);
  --login-text: #fffaf4;
  --login-muted: #f5f0e8;
  --login-line: rgb(236 230 255 / 26%);
  --login-line-hover: rgb(236 230 255 / 55%);
  --login-field: rgb(18 25 36 / 45%);
  --login-field-hover: rgb(238 233 255 / 12%);
  --login-accent: #e5d8ff;
  --login-danger: #ffd0d2;
}
.has-password-auth .cinematic-login__layout { grid-template-columns: minmax(0, 1fr) minmax(340px, 420px); gap: clamp(36px, 7vw, 112px); }
.cinematic-login__glass.is-password {
  --app-text-secondary: var(--login-muted);
  --app-accent: var(--login-accent);
  --app-danger: var(--login-danger);
  align-content: start;
  justify-items: stretch;
  padding: 32px;
  color: var(--login-text);
  background: linear-gradient(145deg, rgb(20 28 43 / 64%), rgb(20 28 43 / 74%));
  background: linear-gradient(145deg in oklab, rgb(20 28 43 / 64%), rgb(20 28 43 / 74%));
  text-align: left;
}
.is-password h2 { margin-block-start: 24px; font-size: 28px; font-weight: 680; letter-spacing: -.025em; }
.is-password > p { margin-block: 8px 26px; line-height: 1.6; }
.cinematic-login__switch { position: relative; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 4px; border-radius: 11px; background: var(--login-field); }
.cinematic-login__switch > span { position: absolute; inset-block: 4px; inset-inline-start: 4px; inline-size: calc(50% - 4px); border-radius: 8px; background: var(--login-panel); box-shadow: 0 2px 7px rgb(18 15 34 / 8%); }
.cinematic-login__switch.is-register > span { transform: translateX(100%); }
.cinematic-login__switch button { position: relative; min-block-size: 38px; padding: 8px 12px; border: 0; border-radius: 8px; color: var(--login-muted); background: transparent; font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
.cinematic-login__switch button[aria-pressed='true'] { color: var(--login-accent); }
.cinematic-login__switch button:hover:not(:disabled) { color: var(--login-accent); }
.cinematic-login__switch button:disabled { cursor: wait; opacity: .55; }
.cinematic-login__form-body { min-inline-size: 0; min-block-size: 292px; }
.is-password .cinematic-login__password { gap: 17px; }
.is-password .cinematic-login__password label { color: var(--login-text); font-size: 13px; font-weight: 550; }
.is-password .cinematic-login__password input { inline-size: 100%; min-block-size: 46px; padding-inline: 13px; border: 1px solid var(--login-line); border-radius: 10px; color: var(--login-text); background: var(--login-field); font: inherit; font-size: 14px; caret-color: var(--login-accent); }
.is-password .cinematic-login__password input::placeholder { color: var(--login-muted); opacity: 1; font-size: 13px; font-weight: 400; }
.is-password .cinematic-login__password input:hover:not(:disabled) { border-color: var(--login-line-hover); }
.is-password .cinematic-login__password input:disabled { opacity: .65; }
.cinematic-login__password-field { display: grid; gap: 7px; }
.cinematic-login__password-input { position: relative; }
.is-password .cinematic-login__password-input input { padding-inline-end: 46px; }
.cinematic-login__password-input button { position: absolute; inset-inline-end: 4px; inset-block: 4px; display: grid; place-items: center; inline-size: 38px; padding: 0; border: 0; border-radius: 7px; color: var(--login-muted); background: transparent; cursor: pointer; }
.cinematic-login__password-input button:hover:not(:disabled) { color: var(--login-text); background: var(--login-field-hover); }
.cinematic-login__password-field small { color: var(--login-muted); font-size: 11px; line-height: 1.6; font-weight: 400; }
.is-password .cinematic-login__password :deep(.app-button--primary) { justify-content: space-between; min-block-size: 46px; margin-block-start: 4px; padding-inline: 17px; background: #6251cf; box-shadow: none; font-size: 14px; }
.is-password .cinematic-login__password :deep(.app-button--primary:hover:not(:disabled)) { background: #5342ba; }
.is-password .cinematic-login__legal { justify-content: start; margin-block-start: 14px; padding-block-start: 12px; border-block-start: 1px solid var(--login-line); color: var(--login-muted); line-height: 1.5; }
.is-password .cinematic-login__legal a { color: var(--login-accent); }
.is-password .cinematic-login__legal a:hover { color: var(--login-text); }
.is-password .cinematic-login__legal input { accent-color: var(--login-accent); }
.is-password :is(input, button, a):focus-visible { outline: 2px solid var(--login-accent); outline-offset: 3px; }
.is-password > [role='alert'] { margin-block: 14px 0; color: var(--login-danger); font-size: 13px; }
.is-password ::selection { color: var(--login-text); background: rgb(203 186 255 / 30%); }
.cinematic-login__motion { position: absolute; inset-block-end: 20px; inset-inline-start: 5vw; display: inline-flex; align-items: center; gap: 7px; min-block-size: 36px; padding: 8px 11px; border: 1px solid rgb(255 255 255 / 25%); border-radius: 8px; color: #f6f1ff; background: rgb(14 17 27 / 82%); font: inherit; font-size: 11px; cursor: pointer; }
.cinematic-login__motion:hover { background: #202032; }
.cinematic-login__motion:focus-visible { outline: 2px solid #d5c5ff; outline-offset: 3px; }
@media (prefers-reduced-motion: no-preference) {
  .cinematic-login__switch > span { transition: transform .24s cubic-bezier(.22, 1, .36, 1); }
  .auth-form-enter-active, .auth-form-leave-active { transition: opacity .16s ease, transform .2s cubic-bezier(.22, 1, .36, 1); }
  .auth-form-enter-from { opacity: 0; transform: translateY(7px); }
  .auth-form-leave-to { opacity: 0; transform: translateY(-5px); }
}

@media (max-width: 740px) {
  .cinematic-login__layout { grid-template-columns: minmax(0, 400px); justify-content: center; gap: 18px; padding: 40px 22px 36px; }
  .cinematic-login__brand { font-size: clamp(27px, 6.6vw, 38px); }
  .cinematic-login__arc { width: min(90%, 235px); height: 8px; margin-top: 7px; }
  .cinematic-login__lead { margin-top: 10px; font-size: 14px; }
  .cinematic-login__description { margin-top: 7px; font-size: 13px; }
  .cinematic-login__stages { margin-top: 16px; gap: 8px; }
  .cinematic-login__stages li { gap: 5px; font-size: 12px; }
  .cinematic-login__stages svg { width: 20px; height: 20px; }
  .cinematic-login__glass { padding: 16px 8px 12px; }
  .has-password-auth .cinematic-login__layout { grid-template-columns: minmax(0, 420px); gap: 28px; padding-block: 30px; }
  .has-password-auth .cinematic-login__description, .has-password-auth .cinematic-login__stages, .has-password-auth .cinematic-login__arc { display: none; }
  .has-password-auth .cinematic-login__brand { font-size: 27px; }
  .has-password-auth .cinematic-login__brand img { inline-size: 44px; }
  .has-password-auth .cinematic-login__lead { font-size: 12px; }
  .cinematic-login__glass.is-password { padding: 24px; }
  .is-password .cinematic-login__password input { font-size: 16px; }
  .cinematic-login__motion { position: relative; justify-self: center; inset: auto; margin-block: -10px 20px; }
}
@media (pointer: coarse) { .cinematic-login__switch button, .cinematic-login__password-input button { min-block-size: 44px; } }
</style>
