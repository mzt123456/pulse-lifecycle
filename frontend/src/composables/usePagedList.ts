import { ref, type Ref } from 'vue'

import type { PageResult } from '@/types'

export interface PageQuery {
  page: number
  page_size: number
}

/**
 * 列表页共用状态：分页、加载、查询与重置。
 * 各页面自己维护筛选条件对象，这里只负责按条件取数与分页。
 */
export function usePagedList<T, F extends object>(
  filters: F,
  fetcher: (params: F & PageQuery) => Promise<PageResult<T>>,
) {
  const items = ref([]) as Ref<T[]>
  const total = ref(0)
  const loading = ref(false)
  const page = ref(1)
  const pageSize = ref(20)

  async function load(): Promise<void> {
    loading.value = true
    try {
      // 空字符串、null、undefined 不作为查询条件传给后端，
      // 否则像时间区间这类字段会因空值被判定为参数非法
      const params: Record<string, unknown> = {
        ...filters,
        page: page.value,
        page_size: pageSize.value,
      }
      for (const [key, value] of Object.entries(params)) {
        if (value === '' || value === null || value === undefined) {
          delete params[key]
        }
      }
      const data = await fetcher(params as F & PageQuery)
      items.value = data.items
      total.value = data.total
    } finally {
      loading.value = false
    }
  }

  async function search(): Promise<void> {
    page.value = 1
    await load()
  }

  async function changePage(next: number): Promise<void> {
    page.value = next
    await load()
  }

  async function changeSize(size: number): Promise<void> {
    pageSize.value = size
    page.value = 1
    await load()
  }

  return { items, total, loading, page, pageSize, load, search, changePage, changeSize }
}
