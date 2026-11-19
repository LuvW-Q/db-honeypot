<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AttackerTable from '../components/AttackerTable.vue'
import { errorMessage, honeypotApi } from '../api'
import type { AttackerSummary, SortOrder } from '../types'

type SortField = 'risk_score' | 'last_seen' | 'first_seen' | 'total_queries'

const router = useRouter()

const items = ref<AttackerSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const sort = ref<SortField>('risk_score')
const order = ref<SortOrder>('desc')
const riskLevel = ref('')
const intentType = ref('')
const loading = ref(false)
const errorText = ref('')

let requestSeq = 0

async function load(): Promise<void> {
  const seq = ++requestSeq
  loading.value = true
  try {
    const data = await honeypotApi.getAttackers({
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
      order: order.value,
      risk_level: riskLevel.value || undefined,
      intent_type: intentType.value || undefined
    })
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
  riskLevel.value = ''
  intentType.value = ''
  sort.value = 'risk_score'
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

function openDetail(row: AttackerSummary): void {
  void router.push({ name: 'attacker-detail', params: { ip: row.source_ip } })
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-header__title">攻击者列表</h2>
        <p class="page-header__desc">
          按风险分与最近出现时间排序，点击任意行查看该来源的画像、会话摘要与规则证据。
        </p>
      </div>
      <div class="page-header__actions">
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="section-card">
      <div class="filter-bar">
        <div class="filter-bar__item">
          <span class="filter-bar__label">风险等级</span>
          <el-select
            v-model="riskLevel"
            placeholder="全部等级"
            clearable
            style="width: 140px"
            @change="applyFilters"
          >
            <el-option label="低风险" value="low" />
            <el-option label="中风险" value="medium" />
            <el-option label="高风险" value="high" />
            <el-option label="严重" value="critical" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">主要意图</span>
          <el-select
            v-model="intentType"
            placeholder="全部意图"
            clearable
            style="width: 150px"
            @change="applyFilters"
          >
            <el-option label="扫描" value="scanning" />
            <el-option label="暴力破解" value="bruteforce" />
            <el-option label="踩点探测" value="recon" />
            <el-option label="拖库" value="data_dump" />
            <el-option label="破坏性操作" value="destructive" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">排序字段</span>
          <el-select v-model="sort" style="width: 160px" @change="applyFilters">
            <el-option label="风险分" value="risk_score" />
            <el-option label="最近出现" value="last_seen" />
            <el-option label="首次出现" value="first_seen" />
            <el-option label="查询数" value="total_queries" />
          </el-select>
        </div>

        <div class="filter-bar__item">
          <span class="filter-bar__label">排序方向</span>
          <el-select v-model="order" style="width: 110px" @change="applyFilters">
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

      <AttackerTable :items="items" :loading="loading" @row-click="openDetail" />

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
