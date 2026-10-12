/** 界面偏好：每页条数、导航折叠与各列表的可见列及顺序，随账号保存。 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { getPreferences, savePreferences } from '@/api/preference';
export const usePreferencesStore = defineStore('preferences', () => {
    const pageSize = ref(20);
    const navCollapsed = ref(false);
    const tableColumns = ref({});
    const loaded = ref(false);
    // 多个页面同时挂载时只发一次请求，避免后台布局与列表页重复拉取
    let inflight = null;
    async function load(force = false) {
        if (loaded.value && !force) {
            return;
        }
        if (inflight) {
            return inflight;
        }
        inflight = (async () => {
            try {
                const data = await getPreferences();
                pageSize.value = data.page_size;
                navCollapsed.value = data.nav_collapsed;
                tableColumns.value = data.table_columns ?? {};
                loaded.value = true;
            }
            catch {
                // 未登录或接口失败时保持默认值，不影响页面使用
            }
            finally {
                inflight = null;
            }
        })();
        return inflight;
    }
    function reset() {
        inflight = null;
        loaded.value = false;
        pageSize.value = 20;
        navCollapsed.value = false;
        tableColumns.value = {};
    }
    async function persist() {
        try {
            await savePreferences({
                page_size: pageSize.value,
                nav_collapsed: navCollapsed.value,
                table_columns: tableColumns.value,
            });
        }
        catch {
            // 保存失败不打断当前操作，下次改动会再试
        }
    }
    /**
     * 某张表当前应显示的列（按用户保存的顺序）。
     * 没存过偏好时用默认可见列；后来新增的列自动补在末尾，被删掉的列自动忽略。
     */
    function columnsFor(key, defaultKeys, allKeys = defaultKeys) {
        const saved = tableColumns.value[key];
        if (!saved || !saved.length) {
            return [...defaultKeys];
        }
        const kept = saved.filter((item) => allKeys.includes(item));
        const added = defaultKeys.filter((item) => !kept.includes(item));
        return [...kept, ...added];
    }
    async function setColumns(key, order) {
        tableColumns.value = { ...tableColumns.value, [key]: order };
        await persist();
    }
    async function setPageSize(size) {
        pageSize.value = size;
        await persist();
    }
    async function setNavCollapsed(value) {
        navCollapsed.value = value;
        await persist();
    }
    return {
        pageSize,
        navCollapsed,
        tableColumns,
        loaded,
        load,
        reset,
        columnsFor,
        setColumns,
        setPageSize,
        setNavCollapsed,
    };
});
