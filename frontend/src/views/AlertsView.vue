<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import AlertTable from '../components/AlertTable.vue'
import { ApiError, errorMessage, honeypotApi } from '../api'
import { addDays } from '../utils/format'
import type { AlertItem, SortOrder } from '../types'

type SortField = 'created_at' | 'severity'
type ReadFilter = 'all' | 'unread' | 'read'

const items = ref<AlertItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const alertType = ref('')
const severity = ref('')
const readFilter = ref<ReadFilter>('all')
const dateRange = ref<[string, string] | null>(null)
const sort = ref<SortField>('created_at')
const order = ref<SortOrder>('desc')

const loading = ref(false)
const markingId = ref<number | null>(null)
const errorText = ref('')

let requestSeq = 0

function buildParams() {
  let isRead: boolean | undefined
  if (readFilter.value === 'unread') isRead = false
  if (readFilter.value === 'read') isRead = true

  const from = dateRange.value?.[0]
  // 契约时间区间为左闭右开 [from, to)，结束日期需加一天，避免漏掉当天数据。
  const to = dateRange.value?.[1] ? addDays(dateRange.value[1], 1) : undefined

  return {
    page: page.value,
    page_size: pageSize.value,
    alert_type: alertType.value || undefined,
    severity: severity.value || undefined,
    is_read: isRead,
    from,
    to,
    sort: sort.value,
    order: order.value
  }
}

async function load(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  try {
    const data = await honeypotApi.getAlerts(buildParams())
    if (seq !== requestSeq) return
    items.value = data.items ?? []
    total.value = data.total ?? 0
    errorText.value = ''
  } catch (error) {
    if (seq !== requestSeq) return
    errorText.value = errorMessage(error)
    ElMessage.error(errorText.value)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  alertType.value = ''
  severity.value = ''
  readFilter.value = 'all'
  dateRange.value = null
  sort.value = 'created_at'
  order.value = 'desc'
  page.value = 1
  void load()
}

function onPageChange(value: number): void {
  page.value = value
  void load()
}

function onSizeChange(value: number): void {
  pageSize.value = value
  page.value = 1
  void load()
}

async function markRead(row: AlertItem): Promise<void> {
  if (markingId.value !== null) return
  markingId.value = row.alert_id
  try {
    const updated = await honeypotApi.updateAlertRead(row.alert_id, true)
    const index = items.value.findIndex((item) => item.alert_id === updated.alert_id)
    if (index >= 0) items.value[index] = updated
    ElMessage.success('已标记为已读')
    // 写操作成功后刷新当前页，确保页面状态与数据库一致。
    await load()
  } catch (error) {
    if (error instanceof ApiError && error.code === 'ALERT_NOT_FOUND') {
      ElMessage.warning('该告警已不存在，正在刷新列表')
      await load()
    } else {
      ElMessage.error(errorMessage(error))
    }
  } finally {
    markingId.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-header__title">告警列表</h2>
        <p class="page-header__desc">
          按类型、等级、已读状态与时间范围筛选；标记已读是系统仅有的写操作之一，成功后立即刷新。
        </p>
      </div>
      <div class="page-header__actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="section-card">
      <div class="filter-bar">
        <div class="filter-bar__item">
          <span class="filter-bar__label">告警类型</span>
          <el-select
            v-model="alertType"
            placeholder="全部类型"
            clearable
            style="width: 140px"
            @change="applyFilters"
          >
            <el-option label="暴力破解" value="bruteforce" />
            <el-option label="拖库" value="data_dump" />
            <el-option label="破坏性操作" value="destructive" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">严重等级</span>
          <el-select
            v-model="severity"
            placeholder="全部等级"
            clearable
            style="width: 120px"
            @change="applyFilters"
          >
            <el-option label="低" value="low" />
            <el-option label="中" value="medium" />
            <el-option label="高" value="high" />
            <el-option label="严重" value="critical" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">已读状态</span>
          <el-select v-model="readFilter" style="width: 120px" @change="applyFilters">
            <el-option label="全部" value="all" />
            <el-option label="未读" value="unread" />
            <el-option label="已读" value="read" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">时间范围（UTC 日期）</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            range-separator="至"
            style="width: 260px"
            @change="applyFilters"
          />
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">排序字段</span>
          <el-select v-model="sort" style="width: 130px" @change="applyFilters">
            <el-option label="创建时间" value="created_at" />
            <el-option label="严重等级" value="severity" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">排序方向</span>
          <el-select v-model="order" style="width: 100px" @change="applyFilters">
            <el-option label="降序" value="desc" />
            <el-option label="升序" value="asc" />
          </el-select>
        </div>

        <div class="filter-bar__actions">
          <el-button type="primary" @click="applyFilters">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="section-card">
      <el-alert
        v-if="errorText"
        class="table-error"
        type="error"
        :closable="false"
        show-icon
        :title="errorText"
        description="已保留上一次成功加载的数据，可点击刷新重试。"
      />

      <AlertTable
        :items="items"
        :loading="loading"
        :marking-id="markingId"
        @mark-read="markRead"
      />

      <div class="table-footer">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.filter-bar__actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.table-error {
  margin-bottom: 12px;
}
</style>
