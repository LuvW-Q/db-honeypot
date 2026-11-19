<script setup lang="ts">
import { computed } from 'vue'
import { intentLabel } from '../utils/format'

interface Props {
  intentType?: string | null
  size?: 'large' | 'default' | 'small'
}

const props = withDefaults(defineProps<Props>(), {
  intentType: null,
  size: 'default'
})

const tagType = computed<'primary' | 'success' | 'warning' | 'danger' | 'info'>(() => {
  switch (props.intentType) {
    case 'scanning':
      return 'info'
    case 'bruteforce':
      return 'warning'
    case 'recon':
      return 'primary'
    case 'data_dump':
      return 'danger'
    case 'destructive':
      return 'danger'
    default:
      return 'info'
  }
})

const effect = computed(() => (props.intentType === 'destructive' ? 'dark' : 'light'))
</script>

<template>
  <el-tag :type="tagType" :effect="effect" :size="size" class="intent-tag">
    {{ intentLabel(intentType) }}
  </el-tag>
</template>
