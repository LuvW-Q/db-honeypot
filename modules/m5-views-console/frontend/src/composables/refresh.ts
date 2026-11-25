// 页头「现场刷新数据」与页面数据获取的桥：App 提供递增的 refreshTick，页面 watch 后重取。
import { inject, provide, ref, type InjectionKey, type Ref } from 'vue'

export interface RefreshBus {
  tick: Ref<number>
  lastUpdated: Ref<Date | null>
  refreshing: Ref<boolean>
  trigger: () => void
  markUpdated: () => void
}

const KEY: InjectionKey<RefreshBus> = Symbol('refresh-bus')

export function provideRefreshBus(): RefreshBus {
  const bus: RefreshBus = {
    tick: ref(0),
    lastUpdated: ref(null),
    refreshing: ref(false),
    trigger: () => {
      bus.tick.value += 1
    },
    markUpdated: () => {
      bus.lastUpdated.value = new Date()
    }
  }
  provide(KEY, bus)
  return bus
}

export function useRefreshBus(): RefreshBus {
  const bus = inject(KEY, null)
  if (!bus) throw new Error('refresh bus 未提供（App.vue 应调用 provideRefreshBus）')
  return bus
}
