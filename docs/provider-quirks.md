# Provider 特殊适配（Codex / Antigravity）

Aether 内部用两层标识来描述上游：

- **endpoint signature（family:kind）**：如 `openai:cli`、`gemini:cli`。决定走哪套协议的解析/格式转换。
- **provider_type**：如 `codex`、`antigravity`。描述“同格式但上游有细微差异”的变体，或需要额外的 wire envelope / transport 行为。

这两层分离的好处是：**格式体系保持稳定**（不轻易增加新的 family），同时又能对特定上游做最小侵入的兼容。

---

## target_variant（格式变体）

当 `client_format == provider_format` 但上游存在细微差异时，格式转换注册表支持 `target_variant`：

- **Codex**：在 `openai:cli` 请求上做上游兼容修补（例如强制 `stream=true`、补齐 `instructions` 等），见 `src/core/api_format/conversion/normalizers/openai_cli.py`。

跨格式转换时也可以携带变体（例如 `claude:chat -> gemini:cli` 且目标上游是 Antigravity），用于 thinking block 翻译等，见 `src/core/api_format/conversion/normalizers/gemini.py`。

---

## ProviderEnvelope（wire envelope / transport hooks）

某些上游会在真实 wire format 外再包一层 envelope，或需要 transport 层 side-effects（例如记录本次选用的 base_url、按状态码更新可用性）。

Aether 通过 `ProviderEnvelope` 提供最小 hook，让 handler 基类保持通用逻辑：

- 入口：`src/services/provider/behavior.py`（统一解析行为：envelope + variant）
- envelope 路由：`src/services/provider/envelope.py`

相关 handler 接入点：

- CLI：`src/api/handlers/base/cli_handler_base.py`
- Chat：`src/api/handlers/base/chat_handler_base.py` + `src/api/handlers/base/stream_processor.py`

### Antigravity（`provider_type=antigravity`）

- **endpoint signature**：仍复用 `gemini:cli`
- **URL 路径**：transport 层切到 `/v1internal:{action}`，见 `src/services/provider/transport.py`
- **Request/Response**：v1internal 包装/解包，见 `src/services/antigravity/envelope.py`
- **base_url**：prod/daily 可用性排序 + TTL 自动恢复，见 `src/services/antigravity/url_availability.py`
- **OAuth 元数据**：需要补齐 `project_id`（通过 `/v1internal:loadCodeAssist`），见 `src/services/antigravity/client.py` 与 `src/core/provider_oauth_utils.py`
- **thinking**：Claude -> Gemini 转换时，把 thinking UnknownBlock 翻译成 Gemini thought part + signature 缓存/降级，见 `src/core/api_format/conversion/normalizers/gemini.py`

### Codex（`provider_type=codex`）

- 通常与 `openai:cli`（Responses API）配套
- **upstream URL**：`chatgpt.com/backend-api/codex` 需要走 `/responses`（而不是 `/v1/responses`），transport 层已做特判，见 `src/services/provider/transport.py`
- **强制 `stream=true`**：Codex 上游按当前适配视为 *SSE-only*，默认强制上游 streaming（见 `src/services/provider/stream_policy.py`）；同时 `openai:cli` normalizer 的 `target_variant="codex"` 也会做请求修补（强制 `stream=true`、补齐 `instructions`、剔除不兼容字段等），见 `src/core/api_format/conversion/normalizers/openai_cli.py`
- **额外请求头**：运行时通过 Codex envelope 注入（SSE Accept、session_id、originator 等），见 `src/services/codex/envelope.py`（`check_endpoint` 测试请求仍在 adapter 层做同样的 best-effort 注入）

---

## upstream_stream_policy（上游流式策略）

这是一个**按 Endpoint** 生效的通用开关：控制“我们怎么请求上游”（stream 还是 sync），而不是控制客户端要不要 stream。

配置位置：`ProviderEndpoint.config.upstream_stream_policy`

取值：

- `auto`：跟随客户端（默认）
- `force_stream`：强制上游走 SSE；如果客户端是 sync，则网关会在内部**聚合 SSE -> sync JSON** 后再返回
- `force_non_stream`：强制上游走 sync；如果客户端是 stream，则网关会在内部**sync JSON -> streamify** 后再返回

实现位置：

- 策略解析与约束：`src/services/provider/stream_policy.py`
- stream<->sync 桥接（InternalResponse 聚合/展开）：`src/core/api_format/conversion/stream_bridge.py`、`src/api/handlers/base/upstream_stream_bridge.py`

注意：

- Codex `provider_type=codex + openai:cli` 被视为上游硬约束 **只能 streaming**，即使显式配置 `force_non_stream` 也会被忽略（返回 `force_stream`）。

## 新增类似上游的建议流程

如果以后还要接入“复用现有 signature，但 wire/行为不同”的上游：

1. 先判断是否能用 `target_variant` 解决（仅请求/响应字段差异）。
2. 如果需要 wire envelope 或 transport side-effects，新增一个 `ProviderEnvelope` 实现并注册到 `src/services/provider/envelope.py`。
3. 如需统一变体策略，在 `src/services/provider/behavior.py` 增加映射（避免 handler 到处写 `if provider_type == ...`）。
