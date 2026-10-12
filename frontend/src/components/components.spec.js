/**
 * 组件冒烟测试：盯两件最容易被静默破坏的事——
 * 一是运行期 props 有没有声明（TypeScript 的类型化 props 转成 JS 时必须手工补上，
 * 否则父组件传进来的列、数据全是 undefined）；
 * 二是组件导入有没有被保留（转译器会把「只在模板里用到」的 import 当成类型删掉，
 * 表现是页面不报错但整块内容不渲染）。
 */
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp, h, nextTick } from 'vue'
import { beforeAll, describe, expect, it } from 'vitest'

import DataTable from '@/components/DataTable.vue'
import MarkdownText from '@/components/MarkdownText.vue'
import router from '@/router'

beforeAll(() => {
  // jsdom 没有 ResizeObserver；表格要靠它的回调触发 doLayout 才会渲染表头与单元格
  globalThis.ResizeObserver = class {
    constructor(callback) {
      this.callback = callback
    }
    observe(element) {
      this.callback([{ target: element, contentRect: element.getBoundingClientRect() }], this)
    }
    unobserve() {}
    disconnect() {}
  }
})

function mount(component, props) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp({ render: () => h(component, props) })
  app.use(createPinia())
  app.use(ElementPlus)
  app.mount(host)
  return host
}

describe('MarkdownText', () => {
  it('渲染 Markdown 正文', () => {
    const host = mount(MarkdownText, { text: '**结论**：压力保不住。' })

    expect(host.innerHTML).toContain('结论')
    expect(host.querySelector('strong')).not.toBeNull()
  })

  it('不把原始 HTML 当标签渲染', () => {
    const host = mount(MarkdownText, { text: '<img src=x onerror=alert(1)>' })

    expect(host.querySelector('img')).toBeNull()
    expect(host.innerHTML).toContain('&lt;img')
  })
})

describe('DataTable', () => {
  const columns = [
    { key: 'equipment_no', label: '设备编号' },
    { key: 'status', label: '状态' },
  ]
  const data = [{ equipment_no: 'PLT-DEMO-1', status: '在用' }]

  it('运行期 props 声明齐全（转 JS 时最容易漏的就是这一处）', () => {
    expect(Object.keys(DataTable.props ?? {})).toEqual(
      expect.arrayContaining(['tableKey', 'columns', 'data', 'loading', 'stripe']),
    )
  })

  it('按 props 渲染表头与单元格', () => {
    const host = mount(DataTable, { tableKey: 'smoke_test', columns, data })
    return nextTick().then(() => nextTick()).then(() => {
      const text = host.textContent ?? ''

      expect(text).toContain('列设置')
      expect(text).toContain('设备编号')
      expect(text).toContain('PLT-DEMO-1')
      expect(text).toContain('在用')
    })
  })

  it('stripe 默认开启（与列表页的观感一致）', () => {
    const host = mount(DataTable, { tableKey: 'smoke_test_stripe', columns, data })
    const table = host.querySelector('.el-table')

    expect(table).not.toBeNull()
    expect(table.className).toContain('el-table--striped')
  })
})

describe('应用启动', () => {
  it('挂载整应用时能在未登录状态渲染登录页', async () => {
    // 没有令牌时路由守卫会跳到 /login，这里顺带验证路由、store、Element Plus 都装得上
    document.body.innerHTML = '<div id="app"></div>'
    sessionStorage.clear()
    localStorage.clear()

    await import('@/main.js')
    await router.isReady() // 首次导航是异步的，等路由就绪再看页面
    await nextTick()

    const text = document.querySelector('#app').textContent ?? ''
    expect(text).toContain('登录')
    expect(document.querySelectorAll('input').length).toBeGreaterThan(0)
  })
})
