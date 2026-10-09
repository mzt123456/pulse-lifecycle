<script setup lang="ts">
/** 模型回答渲染：只允许 Markdown 语法，禁用原始 HTML，避免注入。 */

import MarkdownIt from 'markdown-it'
import { computed } from 'vue'

const props = defineProps<{ text: string }>()

const md = new MarkdownIt({
  html: false, // 不允许原始 HTML：模型输出属于不可信内容
  linkify: false,
  breaks: true,
  typographer: false,
})

const rendered = computed(() => md.render(props.text ?? ''))
</script>

<template>
  <div class="markdown" v-html="rendered" />
</template>

<style scoped>
.markdown {
  line-height: 1.9;
  word-break: break-word;
}

.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3) {
  margin: 12px 0 6px;
  font-size: 15px;
  font-weight: 600;
}

.markdown :deep(p) {
  margin: 6px 0;
}

.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 6px 0;
  padding-left: 22px;
}

.markdown :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 13px;
}

.markdown :deep(th),
.markdown :deep(td) {
  padding: 5px 10px;
  border: 1px solid #dcdfe6;
  text-align: left;
}

.markdown :deep(th) {
  background: #f5f7fa;
  font-weight: 600;
}

.markdown :deep(code) {
  padding: 1px 5px;
  background: #f0f2f5;
  border-radius: 3px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
}

.markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  color: #7f8c8d;
  border-left: 3px solid var(--color-muted);
}
</style>
