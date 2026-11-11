# Gemini 与 Vertex 接入及用量约定

## 接口与认证

- `gemini:generate_content` 保持现有 Gemini 原生生成契约。
- `gemini:interactions` 是独立的原生契约，不转换成 OpenAI/Claude 消息。
- Vertex 的 Interactions 仅允许 Service Account（`service_account` / `vertex_ai`）密钥。固定模板、管理员校验、PostgreSQL/内存候选筛选和运行时认证均采用此约束；API Key 不支持此路径。
- Vertex Interactions 地址为 `/v1beta1/projects/{project_id}/locations/{region}/interactions`。服务账号请求不转发客户端 query 中的 API key。
- Gemini 4 生成请求使用 Vertex `v1beta1`，默认地区 `global`；显式 `model_regions` 优先。旧模型与 Embedding 保持原版本和地区规则。

## 参数、工具与重放

跨格式请求中，Gemini 4 与 Gemini 3.8 Flash 使用 `thinkingLevel`，并去掉不兼容的旧 sampling 参数。原生请求保持原始参数，由提供商校验。

需要工具响应 ID 的现代模型保留 `functionResponse.id` 与续接 token。文字 Part 和空 thought Part 的签名不会因文本为空而丢失。Responses 历史经 Chat 中转时，根据 `call_id` 恢复 Gemini thought signature；签名不会错误地配给插入的普通 reasoning/text。

Responses 的 `additional_tools` 可合并到 Gemini 工具声明。Antigravity 在客户端函数和服务端内建工具冲突时保留客户端函数，去掉内建工具及相应 server-side invocation 配置；纯搜索请求不受影响。

## 用量与计费

标准用量的 `output_tokens` 是可计费输出，**已包含 reasoning**。`reasoning_tokens` 是其中的明细，不能再次累加。

- GenerateContent：`output_tokens = candidatesTokenCount + thoughtsTokenCount`。
- Interactions：读取 `total_input_tokens`、`total_output_tokens`、`total_thought_tokens`、`total_cached_tokens`，包括流式 `interaction.completed` 的嵌套 `interaction.usage`。
- 无显式总数时：`total_tokens = input_tokens + output_tokens`。

提供商返回的模态明细映射为以下持久化标量，可用于既有自定义计费表达式：

- `input_{text,image,audio,video,document}_tokens`
- `output_{text,image,audio,video,document}_tokens`
- `cache_read_{text,image,audio,video,document}_tokens`

只接受非负计数。每组模态之和不得超过对应标准 input/output/cache-read 总数；越界整组丢弃，不做比例缩放。明细不能覆盖标准 token 或价格字段。保留模态明细本身不会自动改变模型单价；不同模态需要分别定价时，仍须配置计费表达式。

## 边界

网关不自动续接生成、不自动新增生成请求；客户端负责使用提供商返回的续接 token。此改动不新增 Live/Bidi、显式 cached-content 管理或异步批量资源协议。
