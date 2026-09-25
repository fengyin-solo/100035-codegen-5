<template>
  <section class="page" data-module="insurance">
    <header class="page-head">
      <div>
        <h2>保险与理赔备案</h2>
        <p class="page-desc">
          设备损坏理赔统一登记：按设备类型与资产原值自动核算赔付上限，同一保险期重复报案只认第一条，
          材料不全可存草稿续填，提交重试不重复生成赔付记录。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记理赔报案</button>
        <button class="btn" type="button" @click="exportRows">导出理赔清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>报案号/设备编号</span>
        <input v-model="filters.keyword" placeholder="按报案号或设备编号检索" />
      </label>
      <label class="filter-item">
        <span>理赔状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>疑似重复</span>
        <select v-model="filters.duplicate">
          <option value="">全部</option>
          <option value="true">仅看疑似重复</option>
          <option value="false">仅看非重复</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>标记</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '理赔报案号'">
              <button class="link" type="button" @click="openDetail(row)">{{ row[column] }}</button>
            </template>
            <template v-else-if="moneyColumns.includes(column)">{{ formatMoney(row[column]) }}</template>
            <template v-else-if="column === '理赔状态'">
              <span :class="['status-tag', statusClass(row.status)]">{{ row.status }}</span>
            </template>
            <template v-else-if="column === '是否认账'">
              {{ row[column] ? '认账' : '不认账' }}
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <span v-if="row.疑似重复" class="badge badge-warn" :title="`同一保险期首条报案：${row.重复报案号 ?? ''}`">
              疑似重复
            </span>
            <span v-if="row.口径不符" class="badge badge-risk">口径不符</span>
            <span v-if="!row.疑似重复 && !row.口径不符">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button v-if="row.status === '草稿'" class="link" type="button" @click="continueDraft(row)">
              接着填
            </button>
            <button
              v-if="row.status === '已报案' && row.是否认账"
              class="link"
              type="button"
              @click="confirmPay(row)"
            >
              确认赔付
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无理赔记录，可先登记理赔报案</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条理赔记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记 / 续填弹窗 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ formMode === 'edit' ? `续填草稿 ${form.理赔报案号 ?? ''}` : '登记理赔报案' }}</h3>
          <button class="link" type="button" @click="closeForm">关闭</button>
        </div>

        <div class="form-grid">
          <label class="form-item">
            <span>设备编号 <em>*</em></span>
            <select v-model="form.设备编号" @change="onDeviceOrDateChange">
              <option value="">请选择设备</option>
              <option v-for="d in devices" :key="d.设备编号" :value="d.设备编号">
                {{ d.设备编号 }}｜{{ d.设备名称 }}（{{ d.设备类型 }}）
              </option>
            </select>
          </label>
          <label class="form-item">
            <span>出险时间 <em>*</em></span>
            <input v-model="form.出险时间" type="date" @change="onDeviceOrDateChange" />
          </label>
          <label class="form-item">
            <span>报案时间</span>
            <input v-model="form.报案时间" type="date" />
          </label>
          <label class="form-item">
            <span>定损金额（元）<em>*</em></span>
            <input v-model.number="form.定损金额" type="number" min="0" step="0.01" />
          </label>
        </div>

        <div v-if="quoteLoading" class="quote-box">正在按设备类型与资产原值核算赔付口径…</div>
        <div v-else-if="quoteErrText" class="quote-box quote-error">{{ quoteErrText }}</div>
        <div v-else-if="quote" class="quote-box">
          <div class="quote-row">
            <span>设备类型：<b>{{ quote.设备类型 }}</b></span>
            <span>资产原值：<b>{{ formatMoney(quote.资产原值) }}</b></span>
            <span>赔付比例：<b>{{ Math.round(quote.赔付比例 * 100) }}%</b></span>
          </div>
          <div class="quote-row">
            <span>保单号：<b>{{ quote.保单号 }}</b></span>
            <span>保险期间：<b>{{ quote.保险起期 }} 至 {{ quote.保险止期 }}</b></span>
            <span class="quote-limit">赔付上限：<b>{{ formatMoney(quote.赔付上限) }}</b></span>
          </div>
        </div>

        <label class="form-item full">
          <span>申报赔付金额（元）<em>*</em></span>
          <input v-model.number="form.申报赔付金额" type="number" min="0" step="0.01" />
          <small class="form-hint">
            保单口径应赔 = min(定损金额, 赔付上限)
            <template v-if="referencePayout !== null">= {{ formatMoney(referencePayout) }}</template>
            ；超过上限必须在下方写明依据。
          </small>
        </label>

        <div v-if="isOverLimit" class="form-warn">
          申报赔付 {{ formatMoney(form.申报赔付金额) }} 已超过赔付上限
          {{ quote ? formatMoney(quote.赔付上限) : '' }}，请填写超上限依据，否则无法保存。
        </div>
        <label v-if="isOverLimit || form.超上限依据" class="form-item full">
          <span>超上限依据 <em>*</em></span>
          <textarea v-model="form.超上限依据" rows="2" placeholder="如：保单批单号、特别约定条款等"></textarea>
        </label>

        <fieldset class="material-box">
          <legend>理赔材料（5 项齐备方可提交，不齐可先存草稿）</legend>
          <label v-for="m in materialFields" :key="m" class="material-item">
            <input :checked="Boolean(form[m])" type="checkbox" @change="form[m] = ($event.target as HTMLInputElement).checked" />
            <span>{{ m }}</span>
          </label>
        </fieldset>

        <p v-if="missingMaterials.length" class="form-hint">
          当前缺件：<b class="error-text">{{ missingMaterials.join('、') || '无' }}</b>
        </p>

        <div v-if="formMessage" :class="formOk ? 'form-ok' : 'form-warn'">{{ formMessage }}</div>

        <div class="modal-foot">
          <button class="btn" type="button" :disabled="submitting" @click="saveDraft">保存草稿</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitClaim">
            {{ submitting ? '提交中…' : '提交报案' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-wide">
        <div class="modal-head">
          <h3>理赔详情 {{ detail.理赔报案号 }}</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </div>

        <div v-if="detail.疑似重复 || detail.口径不符" class="flag-line">
          <span v-if="detail.疑似重复" class="badge badge-warn">
            疑似重复：同一保险期内只认第一条 {{ detail.重复报案号 }}，本单不认账
          </span>
          <span v-if="detail.口径不符" class="badge badge-risk">
            申报赔付与保单口径 {{ formatMoney(detail.保单口径赔付) }} 不一致
          </span>
        </div>

        <table class="detail-table">
          <tbody>
            <tr v-for="item in detailGroups" :key="item.label">
              <th>{{ item.label }}</th>
              <td v-for="f in item.fields" :key="f.key">
                <span class="detail-label">{{ f.label }}</span>
                <span :class="{ 'detail-money': f.money }">
                  <template v-if="f.money">{{ formatMoney(detail[f.key]) }}</template>
                  <template v-else-if="f.key === '材料齐全'">{{ detail[f.key] ? '齐全' : '不全' }}</template>
                  <template v-else-if="f.key === '是否认账'">{{ detail[f.key] ? '认账' : '不认账' }}</template>
                  <template v-else-if="f.key === '赔付比例'">{{ Math.round(Number(detail[f.key]) * 100) }}%</template>
                  <template v-else>{{ detail[f.key] ?? '—' }}</template>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="detail.缺件说明" class="form-hint">缺件：{{ detail.缺件说明 }}</div>
        <div v-if="detail.超上限依据" class="form-ok">超上限依据：{{ detail.超上限依据 }}</div>

        <div class="modal-foot">
          <button v-if="detail.status === '草稿'" class="btn" type="button" @click="continueDraft(detail)">
            接着填草稿
          </button>
          <button
            v-if="detail.status === '已报案' && detail.是否认账"
            class="btn primary"
            type="button"
            @click="confirmPay(detail)"
          >
            确认赔付
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, unknown>

interface Quote {
  设备编号: string
  设备名称: string
  设备类型: string
  资产原值: number
  赔付比例: number
  保单号: string
  保险起期: string
  保险止期: string
  赔付上限: number
}

interface DeviceOption {
  设备编号: string
  设备名称: string
  设备类型: string
}

const ENDPOINT = '/api/insurance'
const columns = [
  '理赔报案号', '设备编号', '设备类型', '出险时间', '保单号',
  '资产原值', '赔付上限', '定损金额', '申报赔付金额', '保单口径赔付',
  '材料齐全', '是否认账', '理赔状态',
]
const moneyColumns = ['资产原值', '赔付上限', '定损金额', '申报赔付金额', '保单口径赔付']
const statuses = ['草稿', '已报案', '已赔付']
const materialFields = ['事故照片', '检修报告', '报案回执', '损失发票', '责任说明']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref({ keyword: '', status: '', duplicate: '' })

const stats = computed(() => {
  const drafts = rows.value.filter((r) => r.status === '草稿').length
  const reported = rows.value.filter((r) => r.status === '已报案').length
  const duplicates = rows.value.filter((r) => r.疑似重复).length
  const recognizedPaid = rows.value
    .filter((r) => r.status === '已赔付' && r.是否认账)
    .reduce((sum, r) => sum + Number(r.申报赔付金额 ?? 0), 0)
  return [
    { label: '草稿待补材料', value: drafts },
    { label: '已报案待赔付', value: reported },
    { label: '疑似重复报案', value: duplicates },
    { label: '已赔付认账金额（元）', value: recognizedPaid.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) },
  ]
})

// ---------- 登记/续填表单 ----------

const devices = ref<DeviceOption[]>([])
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const submitting = ref(false)
const quote = ref<Quote | null>(null)
const quoteLoading = ref(false)
const quoteErrText = ref('')
const formMessage = ref('')
const formOk = ref(false)
const detail = ref<Row | null>(null)

interface ClaimForm {
  id: number | null
  client_token: string
  设备编号: string
  出险时间: string
  报案时间: string
  定损金额: number | string
  申报赔付金额: number | string
  超上限依据: string
  事故照片: boolean
  检修报告: boolean
  报案回执: boolean
  损失发票: boolean
  责任说明: boolean
  理赔报案号?: string
  [key: string]: string | number | boolean | null | undefined
}

function emptyForm(): ClaimForm {
  return {
    id: null,
    client_token: '',
    设备编号: '',
    出险时间: '2026-09-25',
    报案时间: '',
    定损金额: '',
    申报赔付金额: '',
    超上限依据: '',
    事故照片: false,
    检修报告: false,
    报案回执: false,
    损失发票: false,
    责任说明: false,
  }
}
const form = ref<ClaimForm>(emptyForm())

const missingMaterials = computed(() => materialFields.filter((m) => !form.value[m]))
const isOverLimit = computed(() => {
  const claim = Number(form.value.申报赔付金额)
  return quote.value !== null
    && form.value.申报赔付金额 !== ''
    && !Number.isNaN(claim)
    && claim > quote.value.赔付上限 + 0.01
})
const referencePayout = computed<number | null>(() => {
  const loss = Number(form.value.定损金额)
  if (!quote.value || form.value.定损金额 === '' || Number.isNaN(loss)) return null
  return Math.round(Math.min(loss, quote.value.赔付上限) * 100) / 100
})

const detailGroups = computed(() => {
  if (!detail.value) return []
  return [
    {
      label: '案件信息',
      fields: [
        { key: '设备编号', label: '设备编号' },
        { key: '设备名称', label: '设备名称' },
        { key: '设备类型', label: '设备类型' },
        { key: '出险时间', label: '出险时间' },
      ],
    },
    {
      label: '保单口径',
      fields: [
        { key: '保单号', label: '保单号' },
        { key: '保险起期', label: '保险起期' },
        { key: '保险止期', label: '保险止期' },
        { key: '理赔状态', label: '状态' },
      ],
    },
    {
      label: '赔付核算（与列表同源）',
      fields: [
        { key: '资产原值', label: '资产原值', money: true },
        { key: '赔付比例', label: '赔付比例' },
        { key: '赔付上限', label: '赔付上限', money: true },
        { key: '定损金额', label: '定损金额', money: true },
      ],
    },
    {
      label: '申报与口径',
      fields: [
        { key: '申报赔付金额', label: '申报赔付', money: true },
        { key: '保单口径赔付', label: '口径应赔', money: true },
        { key: '材料齐全', label: '材料' },
        { key: '是否认账', label: '认账' },
      ],
    },
  ]
})

function formatMoney(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return `¥${num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function statusClass(status: unknown): string {
  if (status === '已赔付') return 'status-paid'
  if (status === '草稿') return 'status-draft'
  return 'status-reported'
}

async function loadOptions() {
  try {
    const response = await request(`${ENDPOINT}/options`)
    if (!response.ok) return
    const payload = await response.json()
    devices.value = payload.devices ?? []
  } catch {
    /* 选项加载失败不阻断页面，登记时再由后端兜底 */
  }
}

async function onDeviceOrDateChange() {
  quote.value = null
  quoteErrText.value = ''
  if (!form.value.设备编号 || !form.value.出险时间) return
  quoteLoading.value = true
  try {
    const query = new URLSearchParams({
      device_id: String(form.value.设备编号),
      loss_date: String(form.value.出险时间),
    })
    const response = await request(`${ENDPOINT}/quote?${query}`)
    const payload = await response.json()
    if (!response.ok) {
      quoteErrText.value = payload.detail ?? '赔付口径核算失败'
      return
    }
    quote.value = payload.quote as Quote
  } catch (error) {
    quoteErrText.value = error instanceof Error ? error.message : '赔付口径核算失败'
  } finally {
    quoteLoading.value = false
  }
}

function openCreate() {
  formMode.value = 'create'
  form.value = emptyForm()
  // 每个新报案一个凭证：后续保存草稿/提交/重试都复用它，保证重试不出现两条记录。
  form.value.client_token = `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  quote.value = null
  quoteErrText.value = ''
  formMessage.value = ''
  formVisible.value = true
}

function continueDraft(row: Row) {
  detail.value = null
  formMode.value = 'edit'
  form.value = {
    ...emptyForm(),
    ...row,
    // 续填沿用草稿原凭证：保存草稿、提交、提交后重试都打到同一条记录上。
    client_token: String(row.client_token ?? `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`),
    超上限依据: (row.超上限依据 as string) ?? '',
  }
  formMessage.value = ''
  formVisible.value = true
  void onDeviceOrDateChange()
}

function closeForm() {
  formVisible.value = false
  void reload()
}

function buildPayload(mode: 'draft' | 'submit'): Row {
  return {
    mode,
    id: form.value.id,
    client_token: form.value.client_token,
    设备编号: form.value.设备编号,
    出险时间: form.value.出险时间,
    报案时间: form.value.报案时间,
    定损金额: form.value.定损金额 === '' ? null : form.value.定损金额,
    申报赔付金额: form.value.申报赔付金额 === '' ? null : form.value.申报赔付金额,
    超上限依据: form.value.超上限依据,
    ...Object.fromEntries(materialFields.map((m) => [m, form.value[m]])),
  }
}

async function postSave(mode: 'draft' | 'submit') {
  if (submitting.value) return
  submitting.value = true
  formMessage.value = ''
  formOk.value = false
  try {
    const response = await request(`${ENDPOINT}/claims`, {
      method: 'POST',
      body: JSON.stringify({ values: buildPayload(mode) }),
    })
    const payload = await response.json()
    formOk.value = Boolean(payload.ok)
    formMessage.value = payload.message ?? ''
    if (payload.entry) {
      form.value.id = payload.entry.id
      form.value.理赔报案号 = payload.entry.理赔报案号
      // 草稿状态下服务端回算的口径回填，保证列表/详情数字一致。
      if (payload.entry.赔付上限 !== null && payload.entry.赔付上限 !== undefined) {
        quote.value = {
          ...(quote.value ?? ({} as Quote)),
          赔付上限: payload.entry.赔付上限,
        } as Quote
      }
      if (payload.ok && mode === 'submit' && payload.entry.status === '已报案') {
        // 提交成功：短暂提示后关闭，列表刷新后只有一条新记录（重试也是同一凭证）。
        setTimeout(() => closeForm(), 800)
      }
    }
  } catch (error) {
    // 网络层失败：记录仍保留在表单里，点「提交报案」即按同一 client_token 重试。
    formMessage.value = `${error instanceof Error ? error.message : '提交未送达'}，可直接再试一次，不会重复生成记录`
  } finally {
    submitting.value = false
  }
}

function saveDraft() {
  void postSave('draft')
}

function submitClaim() {
  void postSave('submit')
}

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      errorMessage.value = '理赔详情读取失败'
      return
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔详情读取失败'
  }
}

async function confirmPay(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '确认赔付' } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message
      return
    }
    if (detail.value && detail.value.id === row.id) detail.value = payload.entry
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认赔付操作失败'
  }
}

function resetFilters() {
  filters.value = { keyword: '', status: '', duplicate: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export/data`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  if (filters.value.duplicate) params.set('duplicate', filters.value.duplicate)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('理赔列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔列表读取失败'
  }
}

onMounted(() => {
  void loadOptions()
  void reload()
})
</script>
