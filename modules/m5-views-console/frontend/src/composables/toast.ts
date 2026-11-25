// 轻量 Toast：success / error / partial 三类，供批量已读与刷新失败使用（ui-contracts §6.4）。
import { reactive } from 'vue'

export type ToastTone = 'success' | 'error' | 'partial'

export interface ToastItem {
  id: number
  tone: ToastTone
  title: string
  message: string
}

let seq = 0

export const toastState = reactive<{ items: ToastItem[] }>({ items: [] })

export function pushToast(tone: ToastTone, title: string, message = ''): void {
  const id = ++seq
  toastState.items.push({ id, tone, title, message })
  window.setTimeout(() => dismissToast(id), tone === 'error' ? 6000 : 3800)
}

export function dismissToast(id: number): void {
  const index = toastState.items.findIndex((item) => item.id === id)
  if (index >= 0) toastState.items.splice(index, 1)
}
