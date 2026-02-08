# Aether 请求体规则 (Body Rules) — AI 辅助指南

> 本文档面向 AI 助手。用户在「端点管理 → 请求规则 → + 请求体」中添加规则，AI 需要指导用户在 UI 表单的各个输入框中填写什么内容。

## 系统背景

Aether 是一个 AI API 网关，将用户请求转发给上游 Provider（OpenAI、Claude、Gemini 等）。请求体规则在转发前修改请求体 JSON，每个 Endpoint 可配置多条规则。

## 用户请求体长什么样

规则操作的对象是用户发给 Aether 的 JSON 请求体。根据 Endpoint 的 API 格式不同，结构也不同：

### OpenAI Chat 格式（`openai:chat`）

```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "你是一个助手"},
    {"role": "user", "content": "你好"}
  ],
  "temperature": 0.7,
  "max_tokens": 1000,
  "stream": true,
  "top_p": 1,
  "frequency_penalty": 0,
  "presence_penalty": 0,
  "stop": ["\n"],
  "tools": [...],
  "tool_choice": "auto",
  "response_format": {"type": "json_object"},
  "metadata": {...}
}
```

### Claude Chat 格式（`claude:chat`）

```json
{
  "model": "claude-sonnet-4-20250514",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "system": "你是一个助手",
  "max_tokens": 1024,
  "temperature": 0.7,
  "stream": true,
  "top_p": 1,
  "top_k": 40,
  "stop_sequences": ["###"],
  "metadata": {"user_id": "xxx"}
}
```

### Claude CLI 格式（`claude:cli`）

```json
{
  "model": "claude-sonnet-4-20250514",
  "messages": [
    {"role": "user", "content": "帮我重构这段代码"}
  ],
  "system": "你是一个编程助手",
  "max_tokens": 16384,
  "stream": true
}
```

### Gemini Chat 格式（`gemini:chat`）

```json
{
  "contents": [
    {"role": "user", "parts": [{"text": "你好"}]}
  ],
  "generationConfig": {
    "temperature": 0.7,
    "maxOutputTokens": 1024,
    "topP": 0.9,
    "topK": 40
  },
  "systemInstruction": {"parts": [{"text": "你是一个助手"}]},
  "safetySettings": [...]
}
```

> **注意：** `model` 和 `stream` 是受保护字段，任何规则都无法修改它们。

---

## UI 表单说明

用户在端点管理对话框中点击「+ 请求体」添加规则。每条规则有一个下拉框选择操作类型，然后根据类型显示不同的输入框。

---

### 覆写（set）

**UI 布局：** `[覆写 ▼]` `[字段路径]` `=` `[值]` `[✓]`

| 输入框 | 填什么 | 示例 |
|--------|--------|------|
| 字段路径 | 要设置的字段，用 `.` 分隔层级，`[N]` 访问数组 | `temperature` |
| 值 | **JSON 格式**的值。字符串要加引号，数字直接写 | `0.7` |

值输入框右边有验证图标：绿色勾=JSON合法，红色叉=格式错误。

**用户常见需求 → 怎么填：**

| 用户说 | 字段路径 | 值 |
|--------|---------|-----|
| "固定 temperature 为 0.3" | `temperature` | `0.3` |
| "限制最大输出 500 token" | `max_tokens` | `500` |
| "加一个 metadata 字段标记来源" | `metadata.source` | `"my-app"` |
| "设置 top_p 为 0.9" | `top_p` | `0.9` |
| "添加停止序列" | `stop` | `["\n", "###"]` |
| "设置响应格式为 JSON" | `response_format` | `{"type": "json_object"}` |
| "把第一条消息内容改掉" | `messages[0].content` | `"新的内容"` |
| "设置一个嵌套对象" | `metadata.tracking` | `{"id": "abc", "env": "prod"}` |
| "设置值为空" | `some_field` | `null` |

> **注意：** 字符串值必须加引号！`"hello"` 是字符串，`hello` 是无效 JSON。数字、布尔、null、数组、对象不需要额外引号。

---

### 删除（drop）

**UI 布局：** `[删除 ▼]` `[要删除的字段路径]`

| 输入框 | 填什么 | 示例 |
|--------|--------|------|
| 字段路径 | 要删除的字段路径 | `user_info.ip_address` |

**用户常见需求 → 怎么填：**

| 用户说 | 字段路径 |
|--------|---------|
| "去掉 user 字段" | `user` |
| "删除 metadata 里的 internal_flag" | `metadata.internal_flag` |
| "移除第一条消息" | `messages[0]` |
| "去掉 frequency_penalty" | `frequency_penalty` |

> **注意：** 删除数组元素会导致后续索引前移。如需删除多个数组元素，从后往前删。

---

### 重命名（rename）

**UI 布局：** `[重命名 ▼]` `[原路径]` `→` `[新路径]`

| 输入框 | 填什么 | 示例 |
|--------|--------|------|
| 原路径 | 源字段的路径 | `extra.trace_id` |
| 新路径 | 目标字段的路径（中间层级会自动创建） | `metadata.request_id` |

**用户常见需求 → 怎么填：**

| 用户说 | 原路径 | 新路径 |
|--------|--------|--------|
| "把 max_tokens 改名为 max_completion_tokens" | `max_tokens` | `max_completion_tokens` |
| "把 extra 里的 id 移到 metadata 下" | `extra.id` | `metadata.id` |

---

### 插入（insert）

**UI 布局：** `[插入 ▼]` `[数组路径]` `[位置]` `[值(JSON)]` `[✓]`

| 输入框 | 填什么 | 示例 |
|--------|--------|------|
| 数组路径 | 目标数组的路径（必须是已有的数组） | `messages` |
| 位置 | 插入位置的数字索引，**留空=追加到末尾** | `0`（开头）或留空（末尾） |
| 值 | JSON 格式的元素 | `{"role": "system", "content": "..."}` |

**用户常见需求 → 怎么填：**

| 用户说 | 数组路径 | 位置 | 值 |
|--------|---------|------|-----|
| "在开头加一条 system 消息" | `messages` | `0` | `{"role": "system", "content": "你是一个专业助手"}` |
| "在末尾追加一条消息" | `messages` | （留空） | `{"role": "user", "content": "请用中文回答"}` |
| "在第二条消息前插入" | `messages` | `1` | `{"role": "assistant", "content": "好的"}` |

> **位置说明：** `0`=最前面，`1`=第二个位置，`-1`=倒数第一个前面。留空=追加到最后。

---

### 正则替换（regex_replace）

**UI 布局：** `[正则替换 ▼]` `[字段路径]` `[正则]` `→` `[替换为]` `[ims]` `[✓]`

| 输入框 | 填什么 | 示例 |
|--------|--------|------|
| 字段路径 | 目标字符串字段的路径 | `messages[-1].content` |
| 正则 | 正则表达式（**不需要**加 `/` 包裹） | `1[3-9]\d{9}` |
| 替换为 | 替换成什么，留空=删除匹配内容 | `[手机号已隐藏]` |
| ims | 可选标志，留空=默认 | `i` |

> **重要：** 正则输入框里直接写正则语法即可，**不需要** JSON 转义。`\d` 就写 `\d`，不用写 `\\d`。JSON 转义是保存时系统自动处理的。

**flags 含义：**

| 字母 | 作用 | 什么时候用 |
|------|------|-----------|
| `i` | 忽略大小写 | 匹配 `hello`/`Hello`/`HELLO` |
| `m` | 多行模式 | `^`/`$` 匹配每行而非整个字符串 |
| `s` | dotall | `.` 能匹配换行符 |

大多数情况留空即可。

**用户常见需求 → 怎么填：**

| 用户说 | 字段路径 | 正则 | 替换为 | flags |
|--------|---------|------|--------|-------|
| "隐藏最后一条消息里的手机号" | `messages[-1].content` | `1[3-9]\d{9}` | `[手机号已隐藏]` | |
| "隐藏邮箱地址" | `messages[-1].content` | `[\w.+-]+@[\w.-]+\.\w{2,}` | `[邮箱已隐藏]` | `i` |
| "去掉 HTML 标签" | `messages[-1].content` | `<[^>]+>` | （留空） | |
| "把所有的 foo 替换成 bar" | `messages[-1].content` | `\bfoo\b` | `bar` | |
| "删掉 Markdown 加粗标记" | `messages[-1].content` | `\*\*([^*]+)\*\*` | `\1` | |
| "隐藏身份证号" | `messages[-1].content` | `\d{17}[\dXx]` | `[身份证已隐藏]` | |
| "隐藏 IP 地址" | `messages[-1].content` | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}` | `[IP已隐藏]` | |

---

## 路径语法速查

| 写法 | 含义 |
|------|------|
| `temperature` | 顶层字段 |
| `metadata.source` | 嵌套字段 |
| `messages[0]` | 数组第一个元素 |
| `messages[-1]` | 数组最后一个元素 |
| `messages[0].content` | 第一条消息的 content |
| `messages[-1].content` | 最后一条消息的 content |
| `data[0].items[2]` | 嵌套数组访问 |
| `config\.v1.enabled` | key 名字里有点号时用 `\.` 转义 |

---

## 多条规则示例

用户说："帮我配置规则：在开头插入一条 system 消息说'用中文回答'，固定 temperature 为 0.3，把用户消息里的手机号脱敏"

应指导用户添加 3 条规则：

| # | 操作 | 字段 1 | 字段 2 | 字段 3 | 字段 4 |
|---|------|--------|--------|--------|--------|
| 1 | 插入 | 路径: `messages` | 位置: `0` | 值: `{"role": "system", "content": "请用中文回答所有问题"}` | |
| 2 | 覆写 | 路径: `temperature` | 值: `0.3` | | |
| 3 | 正则替换 | 路径: `messages[-1].content` | 正则: `1[3-9]\d{9}` | 替换为: `[手机号]` | flags: （留空） |

规则按从上到下的顺序执行。

---

## 注意事项

1. **`model` 和 `stream` 不可修改** — 这两个字段由系统管理，写了规则也会被跳过
2. **值必须是合法 JSON** — 覆写/插入的值输入框要求 JSON 格式：字符串加引号 `"text"`，数字直接写 `123`，布尔 `true`/`false`
3. **路径必须指向正确类型** — 插入的路径必须是数组，正则替换的路径必须是字符串
4. **路径不存在时的行为** — 覆写会自动创建中间层级（dict），其他操作遇到不存在的路径会静默跳过
5. **正则在 UI 里直接写** — 不需要 JSON 转义，`\d` 就是 `\d`
6. **正则保存时校验** — 无效的正则表达式会在保存时报错，不会静默通过
