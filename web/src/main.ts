import '@fontsource-variable/manrope'
import '@fontsource-variable/noto-sans-sc'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { i18n, initializeLocale } from './i18n'
import AppButton from './components/AppButton.vue'
import router from './router'
import { initializeAppTheme } from './shared/appTheme'
import './styles.css'
import './features/workbench/styles/workbench.css'
import './features/workbench/styles/shengshimedia-workbench.css'
import './app-theme.css'

initializeAppTheme()
void initializeLocale().then(() => createApp(App).use(i18n).component('AppButton', AppButton).use(createPinia()).use(router).mount('#app'))
