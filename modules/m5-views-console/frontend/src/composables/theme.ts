import { computed, readonly, ref } from 'vue'

// 主题模式（FR-133 / FR-134 / ui-contracts §12）：
// - system：跟随操作系统 `prefers-color-scheme`，系统切换时实时生效（无需刷新）；
// - light / dark：用户手动覆盖，持久化到 localStorage，刷新后保持。
// 令牌定义在 `src/assets/main.css`（:root 深色、html.light 浅色），这里只切 class，不改任何内联颜色。

export type ThemeMode = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'dbh-theme'
export const THEME_MODES: ThemeMode[] = ['system', 'light', 'dark']

function readStoredMode(): ThemeMode {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // 隐私模式 / 禁用存储时降级为跟随系统
  }
  return 'system'
}

const mode = ref<ThemeMode>(readStoredMode())
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null
const systemDark = ref(media?.matches ?? true)

const resolved = computed<ResolvedTheme>(() =>
  mode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : mode.value
)

function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('light', theme === 'light')
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
  root.dataset.theme = theme
}

function persist(next: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // 忽略存储失败：当前会话仍然生效
  }
}

function setMode(next: ThemeMode): void {
  mode.value = next
  persist(next)
  applyTheme(resolved.value)
}

/** 顶部按钮循环：跟随系统 → 浅色 → 深色 → 跟随系统。 */
function cycleMode(): ThemeMode {
  const index = THEME_MODES.indexOf(mode.value)
  const next = THEME_MODES[(index + 1) % THEME_MODES.length]
  setMode(next)
  return next
}

let listenerBound = false

/** 幂等初始化：应用当前主题并监听系统主题变化。 */
export function initTheme(): void {
  applyTheme(resolved.value)
  if (listenerBound || !media) return
  const onChange = (event: MediaQueryListEvent): void => {
    systemDark.value = event.matches
    if (mode.value === 'system') applyTheme(resolved.value)
  }
  if (typeof media.addEventListener === 'function') media.addEventListener('change', onChange)
  else media.addListener(onChange)
  listenerBound = true
}

export function useTheme() {
  return {
    mode: readonly(mode),
    resolved,
    cycleMode,
    setMode,
    initTheme
  }
}
