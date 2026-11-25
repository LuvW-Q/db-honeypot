import { createApp } from 'vue'

import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import 'material-symbols/outlined.css'
import './assets/main.css'

import App from './App.vue'
import { initTheme } from './composables/theme'
import router from './router'

// 主题在挂载前初始化：index.html 的内联脚本已避免首屏闪烁，这里接管响应式监听。
initTheme()

createApp(App).use(router).mount('#app')
