<template>
  <section class="page" data-module="insurance">
    <header class="page-head">
      <div>
        <h2>保险与理赔备案</h2>
        <p class="page-desc">
          设备损坏理赔统一登记：按设备类型与资产原值自动带出赔付上限，超上限须写明依据；
          同一保险期内重复报案只认最早一条并标出疑似重复，跨期报案并存不合并金额。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate()">登记理赔</button>
        <button class="btn" type="button" @click="exportRows">导出理赔备案清单</button>
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
        <span>理赔单号</span>
        <input v-model="filters.keyword" placeholder="按理赔单号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>疑似重复</span>
        <select v-model="filters.duplicate">
          <option value="">全部</option>
          <option value="true">只看疑似重复</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column.key">
            <template v-if="column.key === '理赔单号'">
              <button class="link" type="button" @click="openDetail(row)">{{ row['理赔单号'] }}</button>
              <span v-if="row['疑似重复']" class="badge badge-dup">疑似重复</span>
              <span v-else-if="row['首条认可']" class="badge badge-first">首条认可</span>
            </template>
            <template v-else-if="column.key === '赔付金额'">
              <span :class="{ 'cell-strong warn-text': row['超赔付标准上限'] }">{{ money(row[column.key]) }}</span>
              <span v-if="row['超赔付标准上限']" class="badge badge-over">超限已附依据</span>
            </template>
            <template v-else-if="column.key === '赔付上限'">
              <span class="cell-strong">{{ money(row[column.key]) }}</span>
            </template>
            <template v-else>{{ row[column.key] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button v-if="row.status === '草稿'" class="link" type="button" @click="openCreate(row)">继续填写</button>
            <button
              v-for="action in actionsFor(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无理赔备案数据，可先登记理赔（材料不全可存草稿）</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条理赔备案记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记 / 继续填写草稿 -->
    <div v-if="formOpen" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <div class="modal-head">
          <h3>{{ form.id ? '继续填写理赔草稿' : '登记理赔' }}</h3>
          <button class="btn ghost" type="button" @click="closeForm">关闭</button>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <label>设备编号 *</label>
            <select v-model="form.device" @change="onDeviceChange">
              <option value="">请选择设备</option>
              <option v-for="a in assets" :key="a['设备编号']" :value="a['设备编号']">
                {{ a['设备编号'] }}（{{ a['设备类型'] }}，原值 {{ money(a['资产原值']) }}）
              </option>
            </select>
          </div>
          <div class="form-field">
            <label>保单号 *</label>
            <select v-model="form.policy" @change="loadQuote">
              <option value="">请选择保单</option>
              <option v-for="p in policyOptions" :key="p['保单号']" :value="p['保单号']">
                {{ p['保单号'] }}（{{ p['保险起期'] }} ~ {{ p['保险止期'] }}，限额 {{ money(p['单案赔付限额']) }}）
              </option>
            </select>
          </div>

          <div class="form-field">
            <label>报案日期 *</label>
            <input v-model="form.reportDate" type="date" @change="loadQuote" />
          </div>
          <div class="form-field">
            <label>赔付金额（元）*</label>
            <input v-model.number="form.payout" type="number" min="0" step="0.01" @input="loadQuote" />
          </div>

          <div class="form-field full">
            <label>出险原因 *</label>
            <input v-model="form.reason" placeholder="如：雷击烧损、水浸损坏" />
          </div>
          <div class="form-field full">
            <label>理赔材料清单 *（材料不全可先存草稿，回来接着填）</label>
            <textarea v-model="form.materials" placeholder="如：事故照片、维修发票、检测报告"></textarea>
          </div>
        </div>

        <div class="readonly-box" style="margin-top: 10px">
          <template v-if="quote">
            <div class="hint-line">设备类型：{{ quote['设备类型'] }}　资产原值：{{ money(quote['资产原值']) }}
             　赔付比例：{{ ratioText(quote['赔付比例']) }}</div>
            <div class="hint-line"><strong>赔付标准上限：{{ money(quote['赔付上限']) }}</strong>
              （列表与详情均按此口径展示）</div>
            <div v-if="quote['保险起期']" class="hint-line">
              保险期：{{ quote['保险起期'] }} ~ {{ quote['保险止期'] }}；
              保单单案赔付限额：{{ money(quote['保单赔付限额']) }}
            </div>
            <p v-for="(w, i) in quoteWarnings" :key="i" class="hint-line warn-text">⚠ {{ w }}</p>
          </template>
          <span v-else class="hint-line" style="color: var(--muted)">选择设备后自动带出设备类型、资产原值与赔付上限。</span>
        </div>

        <div class="form-field full" style="margin-top: 10px">
          <label>超限依据（赔付金额超过赔付标准上限时必填）</label>
          <textarea v-model="form.overLimitReason" placeholder="如：特批件编号、协议条款及出处"></textarea>
        </div>

        <p v-if="formMessage" class="hint-line error-text">{{ formMessage }}</p>

        <div class="modal-foot">
          <button class="btn" type="button" :disabled="formBusy" @click="saveDraft">保存草稿</button>
          <button class="btn primary" type="button" :disabled="formBusy" @click="submitClaim">
            {{ form.id ? '提交报案' : '提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <div class="modal-head">
          <h3>理赔详情 · {{ detail['理赔单号'] }}</h3>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
        <dl class="detail-list">
          <template v-for="item in detailItems" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </template>
        </dl>
        <div v-if="detailWarnings.length" class="readonly-box" style="margin-top: 10px">
          <p v-for="(w, i) in detailWarnings" :key="i" class="hint-line warn-text" style="margin: 2px 0">⚠ {{ w }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="detail = null">知道了</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | string[]>
type Asset = Record<string, string | number>
type Policy = Record<string, string | number>
type Quote = Record<string, string | number | boolean>

const ENDPOINT = '/api/insurance'

const columns = [
  { key: '理赔单号', label: '理赔单号' },
  { key: '保单号', label: '保单号' },
  { key: '设备编号', label: '设备编号' },
  { key: '设备类型', label: '设备类型' },
  { key: '报案日期', label: '报案日期' },
  { key: '出险原因', label: '出险原因' },
  { key: '赔付金额', label: '赔付金额' },
  { key: '赔付上限', label: '赔付上限' },
  { key: 'status', label: '状态' },
] as const
const statuses = ['草稿', '已提交', '已认赔', '已拒赔', '已撤']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = reactive<{ keyword: string; status: string; duplicate: string }>({
  keyword: '',
  status: '',
  duplicate: '',
})

const stats = computed(() => [
  { label: '理赔单总数', value: rows.value.length ? total.value : 0 },
  { label: '待处理（已提交）', value: rows.value.filter((r) => r.status === '已提交').length },
  { label: '疑似重复', value: rows.value.filter((r) => r['疑似重复']).length },
  { label: '超限备案', value: rows.value.filter((r) => r['超赔付标准上限']).length },
])

function money(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  return Number.isFinite(n) ? `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : String(value)
}

function actionsFor(row: Row): string[] {
  if (row.status === '草稿') return ['提交报案']
  if (row.status === '已提交') return ['认赔', '拒赔', '撤案']
  return []
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.status) params.set('status', filters.status)
  if (filters.duplicate === 'true') params.set('duplicate', 'true')
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

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.duplicate = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export/all`, '_blank')
}

// ---- 登记表单 ----------------------------------------------------------

const assets = ref<Asset[]>([])
const allPolicies = ref<Policy[]>([])
const formOpen = ref(false)
const formBusy = ref(false)
const formMessage = ref('')
const quote = ref<Quote | null>(null)

interface ClaimForm {
  id: number | null
  device: string
  policy: string
  reportDate: string
  payout: number | null
  reason: string
  materials: string
  overLimitReason: string
  token: string
}

const form = reactive<ClaimForm>({
  id: null,
  device: '',
  policy: '',
  reportDate: '',
  payout: null,
  reason: '',
  materials: '',
  overLimitReason: '',
  token: '',
})

const policyOptions = computed<Policy[]>(() =>
  form.device ? allPolicies.value.filter((p) => p['设备编号'] === form.device) : allPolicies.value,
)

const quoteWarnings = computed<string[]>(() => {
  if (!quote.value) return []
  const list: string[] = []
  const cap = Number(quote.value['赔付上限'])
  const payout = Number(form.payout)
  if (form.payout !== null && Number.isFinite(payout) && payout > cap) {
    if (!form.overLimitReason.trim()) {
      list.push(`拟赔付金额已超过赔付标准上限 ${money(cap)}，必须写明超限依据才能提交。`)
    } else {
      list.push(`拟赔付金额超过赔付标准上限 ${money(cap)}，已登记超限依据，保存后随单留痕。`)
    }
  }
  const policyCap = Number(quote.value['保单赔付限额'])
  if (Number.isFinite(policyCap) && form.payout !== null && Number.isFinite(payout) && payout > policyCap) {
    list.push(`拟赔付金额高于保单单案赔付限额 ${money(policyCap)}，与保单口径不一致，提交后请复核。`)
  }
  return list
})

function ratioText(r: unknown): string {
  const n = Number(r)
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '—'
}

function newToken(): string {
  // 提交没成功时复用同一 token，服务端据此幂等，重试不会生成两条赔付记录。
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

async function loadRefData() {
  if (assets.value.length) return
  const [a, p] = await Promise.all([
    request(`${ENDPOINT}/assets`),
    request(`${ENDPOINT}/policies`),
  ])
  if (a.ok) assets.value = (await a.json()).items ?? []
  if (p.ok) allPolicies.value = (await p.json()).items ?? []
}

async function loadQuote() {
  if (!form.device) {
    quote.value = null
    return
  }
  const params = new URLSearchParams({ device: form.device })
  if (form.policy) params.set('policy', form.policy)
  if (form.payout !== null && form.payout !== undefined && !Number.isNaN(form.payout)) {
    params.set('payout', String(form.payout))
  }
  try {
    const response = await request(`${ENDPOINT}/quote?${params.toString()}`)
    const payload = await response.json()
    quote.value = response.ok && payload.entry ? payload.entry : null
  } catch {
    quote.value = null
  }
}

async function onDeviceChange() {
  form.policy = ''
  quote.value = null
  await loadQuote()
}

function openCreate(row?: Row) {
  formMessage.value = ''
  quote.value = null
  if (row) {
    // 从草稿继续填写：回填已录入内容
    Object.assign(form, {
      id: Number(row.id),
      device: String(row['设备编号'] ?? ''),
      policy: String(row['保单号'] ?? ''),
      reportDate: String(row['报案日期'] ?? ''),
      payout: row['赔付金额'] === null || row['赔付金额'] === undefined ? null : Number(row['赔付金额']),
      reason: String(row['出险原因'] ?? ''),
      materials: String(row['材料清单'] ?? ''),
      overLimitReason: String(row['超限依据'] ?? ''),
      token: '',
    })
  } else {
    Object.assign(form, {
      id: null,
      device: '',
      policy: '',
      reportDate: '',
      payout: null,
      reason: '',
      materials: '',
      overLimitReason: '',
      token: newToken(),
    })
  }
  formOpen.value = true
  void loadRefData().then(() => loadQuote())
}

function closeForm() {
  formOpen.value = false
  formBusy.value = false
}

function formPayload(draft: boolean): Record<string, unknown> {
  return {
    draft,
    request_token: form.token,
    设备编号: form.device,
    保单号: form.policy,
    报案日期: form.reportDate,
    赔付金额: form.payout === null || Number.isNaN(form.payout) ? '' : form.payout,
    出险原因: form.reason,
    材料清单: form.materials,
    超限依据: form.overLimitReason,
  }
}

async function saveDraft() {
  formMessage.value = ''
  formBusy.value = true
  try {
    // 已存在的草稿走 PUT 接着填；新草稿走 POST，失败重试时保持同一 token。
    const url = form.id ? `${ENDPOINT}/${form.id}` : ENDPOINT
    const method = form.id ? 'PUT' : 'POST'
    const response = await request(url, { method, body: JSON.stringify(formPayload(true)) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      formMessage.value = payload.message || '草稿保存失败，可再试一次'
      return
    }
    form.id = payload.entry.id
    form.token = form.token || payload.entry.request_token || newToken()
    formMessage.value = payload.warnings?.length ? payload.warnings.join('；') : '草稿已保存，可随时回来继续填写'
    await reload()
  } catch (error) {
    // 网络没送达时允许原样再试，服务端按 token 幂等，不会出现两条赔付记录。
    formMessage.value = `${error instanceof Error ? error.message : '草稿保存未送达'}，可再试一次`
  } finally {
    formBusy.value = false
  }
}

async function submitClaim() {
  formMessage.value = ''
  formBusy.value = true
  try {
    let response: Response
    if (form.id) {
      // 已有草稿：先把最新填写内容 PUT 上去，再执行提交报案动作。
      const upd = await request(`${ENDPOINT}/${form.id}`, { method: 'PUT', body: JSON.stringify(formPayload(true)) })
      const updPayload = await upd.json()
      if (!upd.ok || !updPayload.ok) {
        formMessage.value = updPayload.message || '草稿更新失败'
        return
      }
      response = await request(`${ENDPOINT}/${form.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action: '提交报案' } }),
      })
    } else {
      response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify(formPayload(false)) })
    }
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      formMessage.value = payload.message || '提交未成功，可再试一次（不会重复生成赔付记录）'
      if (payload.entry?.id) form.id = payload.entry.id
      return
    }
    formMessage.value = payload.warnings?.length ? `已提交：${payload.warnings.join('；')}` : payload.message
    await reload()
    closeForm()
  } catch (error) {
    formMessage.value = `${error instanceof Error ? error.message : '提交未送达'}，可再试一次（同一笔不会重复两条）`
  } finally {
    formBusy.value = false
  }
}

// ---- 动作与详情 --------------------------------------------------------

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message || '理赔动作未生效'
      return
    }
    if (payload.warnings?.length) errorMessage.value = payload.warnings.join('；')
    await reload()
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : '理赔操作失败'
  }
}

const detail = ref<Row | null>(null)

const detailWarnings = computed<string[]>(() => {
  const w = detail.value?.['口径提示']
  return Array.isArray(w) ? (w as string[]) : []
})

const detailItems = computed(() => {
  const d = detail.value
  if (!d) return []
  return [
    { label: '状态', value: `${d.status}${d['疑似重复'] ? '（疑似重复，仅认最早一条）' : d['首条认可'] ? '（本保险期首条认可）' : ''}` },
    { label: '保单号', value: d['保单号'] },
    { label: '保险期', value: `${d['保险起期'] ?? '—'} ~ ${d['保险止期'] ?? '—'}` },
    { label: '设备编号', value: d['设备编号'] },
    { label: '设备名称', value: d['设备名称'] },
    { label: '设备类型', value: d['设备类型'] },
    { label: '资产原值', value: money(d['资产原值']) },
    { label: '赔付比例', value: ratioText(d['赔付比例']) },
    { label: '赔付标准上限', value: money(d['赔付上限']) },
    { label: '保单单案赔付限额', value: money(d['保单赔付限额']) },
    { label: '报案日期', value: d['报案日期'] },
    { label: '出险原因', value: d['出险原因'] || '—' },
    { label: '赔付金额', value: money(d['赔付金额']) },
    { label: '超限依据', value: d['超限依据'] || '—' },
    { label: '材料清单', value: d['材料清单'] || '—' },
  ]
})

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('理赔详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔详情读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadRefData()
})
</script>
