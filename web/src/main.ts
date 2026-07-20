import '@fontsource-variable/manrope'
import '@fontsource-variable/noto-sans-sc'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles.css'
import './features/workbench/styles/workbench.css'

createApp(App).use(createPinia()).use(router).mount('#app')
