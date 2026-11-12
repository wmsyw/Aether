# 上游未关闭 Issue 倒查（2026-11-11）

上游：<https://github.com/fawney19/Aether/issues>。本地基线：`4d8af29dc`。

## 范围与结论

- 快照包含全部 **42 个 open issue**，按**创建时间从新到旧**倒查；同日按秒排序，不按最近评论排序。
- 逐项对照正文、评论、关联 PR 和当前实现。以下“暂缓/已覆盖”是本 fork 的处理判断，不猜测上游维护者未关闭的原因。
- 纳入代码修复或明确子集的共 **14 项**：11 项修复/有界改进，3 项部分修复；另有16项当前已覆盖、8项暂缓或分类处理、1项配置帮助、2项通知、1项旧技术栈问题。
- 只做本地修改与提交；没有 push、评论/关闭上游 issue、发布 Release、构建/推送镜像或调用真实付费提供商。

## 全部 Issue 结论

| Issue | 创建日期 | 处理 | 现象、价值与边界 |
| --- | --- | --- | --- |
| [#895](https://github.com/fawney19/Aether/issues/895) | 2026-10-20 | 部分修复 | Responses 时间窗口费用限制无法估算安全上界时，原来返回内部500。改为转发前返回可操作的400，要求有限输出、自包含输入与可兼容计价，保持硬限额不降级。新增事后 usage 结算软上限模式暂缓，需单独约定并发超调、缺失 usage 与账本恢复。 |
| [#891](https://github.com/fawney19/Aether/issues/891) | 2026-10-13 | 暂缓 | 请求发布包含近期 main 修复的新版本；所述 Gemini functionResponse 修复已在本地。打 tag、发布制品不是源码修复，本轮不执行发布。 |
| [#882](https://github.com/fawney19/Aether/issues/882) | 2026-10-08 | 暂缓 | Chat 没有 Claude `cache_control` 的无损等价。当前严格转换拒绝静默丢失；改成有损透传会改变缓存成本/延迟合同，不能以兼容修复为由绕过审计。 |
| [#861](https://github.com/fawney19/Aether/issues/861) | 2026-09-28 | 修复 | Gemini 结构化 functionResponse 被直接作为 Chat tool content，严格上游返回400。非 Chat 的结构化 object/array 改为 JSON 字符串，优先非空 `content_text`；原字符串与 Chat 多模态数组保持。 |
| [#839](https://github.com/fawney19/Aether/issues/839) | 2026-09-21 | 已覆盖 | Responses 16KiB 预取边界丢字节：当前直接交接 rewriter 解析状态，不再从截断捕获缓存重建；与 #720 同根因。 |
| [#817](https://github.com/fawney19/Aether/issues/817) | 2026-09-13 | 分类处理 | 余额、签到、清理、安装、远控与审计不能作为同一补丁处理；有已覆盖、配置问题及真实功能缺口，见下方子项表。 |
| [#810](https://github.com/fawney19/Aether/issues/810) | 2026-09-09 | 修复 | Sub2API refresh token 首次保存因无条件合并不存在的 provider_ops 而失败。首次配置走新凭据/目标绑定与加密路径；已有配置仍保留掩码复用、迁移与目的地变更校验。 |
| [#803](https://github.com/fawney19/Aether/issues/803) | 2026-09-05 | 随 #782 修复 | 大量429后 key 仍被选中，与准入时钟错误导致已打开熔断被忽略一致。恢复真实时间检查，不另建熔断逻辑；pool 成员冷却不能由普通 key 熔断结论代替。 |
| [#785](https://github.com/fawney19/Aether/issues/785) | 2026-09-03 | 已覆盖 | embedded 心跳已有与 HTTP 共用的游标附加/去重路径，按 session 与递增 heartbeat cursor 计算差额。 |
| [#782](https://github.com/fawney19/Aether/issues/782) | 2026-09-02 | 修复 | 初始和分页预选误把随机 seed 当 Unix 秒，破坏熔断冷却和近期并发判断。两处改用真实时钟，独立 `load_balance_seed` 保留负载均衡语义。 |
| [#781](https://github.com/fawney19/Aether/issues/781) | 2026-09-02 | 已覆盖 | 首字节前断连的 cancellation guard 已在 dispatch 前布防，Drop 结算 candidate/usage 为499，并让位于已认领的 watchdog 终态。 |
| [#780](https://github.com/fawney19/Aether/issues/780) | 2026-09-02 | 修复 | 内层首字节超时和外层 watchdog 未计 key 健康。补齐 `PoolStreamTimeout` 与504 `HealthFailure`，终态先认领，内外竞态合计恰好一次；不清除 cache affinity。 |
| [#744](https://github.com/fawney19/Aether/issues/744) | 2026-08-22 | 已覆盖 | 跨格式非流式 JSON 已在 `needs_conversion` 时进入同步 finalize，`error:null` 不再误判；同格式原样透传是有意行为。 |
| [#738](https://github.com/fawney19/Aether/issues/738) | 2026-08-19 | 修复 | Chat completion/chunk 缺少必需 `created`。所有 chunk 分支共享稳定时间戳，保留上游 created/created_at，同步与无上游时间时使用本次生成时间。 |
| [#722](https://github.com/fawney19/Aether/issues/722) | 2026-08-13 | 修复 | 映射用授权模型通过检查，却发送另一未授权 provider model。现在实际 selected/effective model 就是被 key 授权的模型；不改合法 client/global alias 授权。 |
| [#721](https://github.com/fawney19/Aether/issues/721) | 2026-08-13 | 已覆盖 | Codex 指纹收敛已经由 ai_serving transport facade，planner 不再直接跨边界调用旧实现。 |
| [#720](https://github.com/fawney19/Aether/issues/720) | 2026-08-13 | 已覆盖 | 与 #839 同根因；当前交接解析器状态，捕获缓存不再用于恢复解析器。 |
| [#719](https://github.com/fawney19/Aether/issues/719) | 2026-08-12 | 有界修复 | 补齐 local_shell/shell/apply_patch/computer hosted call 的 canonical→Chat 历史映射及精确扩展审计，保留 call_id、action 等字段。未知 item_reference、未映射扩展仍拒绝。原报告没有 input[174] 的具体项，不能声称精确复现。 |
| [#716](https://github.com/fawney19/Aether/issues/716) | 2026-08-07 | 暂缓 | 模型复制后修改是独立 UX 功能；缺复制入口和唯一命名，不影响现有创建/路由，本轮不混入模型权限修复。 |
| [#705](https://github.com/fawney19/Aether/issues/705) | 2026-08-01 | 配置帮助 | 请求体加权内存预算耗尽的503是设计行为。已有 `AETHER_GATEWAY_REQUEST_BODY_BUFFER_BUDGET_MB`；单请求 `AETHER_MAX_REQUEST_BODY_MB` 仍有256MiB硬上限，不能无限放大。 |
| [#657](https://github.com/fawney19/Aether/issues/657) | 2026-07-02 | 已覆盖 | 模型 include/exclude 正则已保存、回显、重载并重算 allowed_models，已有持久化行为回归。 |
| [#637](https://github.com/fawney19/Aether/issues/637) | 2026-06-09 | 实现 | 成本分析页增加 provider→user 归因与占比。复用 overview API、服务端排序分页；新增真正的上游采购成本 `provider_cost_amount`，与规则计价 rated、客户 billable 分列，未知不当零。详见成本口径。 |
| [#636](https://github.com/fawney19/Aether/issues/636) | 2026-06-08 | 韧性修复 | 代码可解释刷新时模块状态瞬时失败导致“我的邀请”入口消失，未复现原事故。瞬时错误250ms后重试一次；耗尽仍失败或明确 inactive 仍隐藏。身份变化立即清空，旧响应不得覆盖新会话，无权限持久化。 |
| [#631](https://github.com/fawney19/Aether/issues/631) | 2026-06-06 | 已覆盖 | 普通自定义 header 已透传，凭据、hop-by-hop、代理安全头仍过滤/替换。字节级全透传会泄漏客户端 Authorization/Cookie；具体缺失 header 应做窄例外。 |
| [#629](https://github.com/fawney19/Aether/issues/629) | 2026-06-05 | 已覆盖 | 敏感信息占位符在同步、SSE、Responses WS 按本会话还原，包含工具参数增量；未知 sentinel 不跨会话猜测还原。 |
| [#606](https://github.com/fawney19/Aether/issues/606) | 2026-05-29 | 已覆盖/配置排查 | 当前 Kiro 强制流式，endpoint auto/force 不再解释候选为空。应核对模型 supports_streaming、关联、白名单与映射；没有真实 Kiro 账号调用，属于代码路径判断。 |
| [#565](https://github.com/fawney19/Aether/issues/565) | 2026-05-25 | 暂缓 | Docker 网页一键更新需要宿主控制面，不能引入 docker.sock、默认 token 和 mutable latest 的高权限侧车。单机更新能力已有；Docker 使用外部编排或独立、明确选择加入的受限更新器。 |
| [#559](https://github.com/fawney19/Aether/issues/559) | 2026-05-24 | 部分修复 | 原300秒挂起、无本地候选文案和 failover 已有处理；本轮补超时健康记账。所有候选耗尽时仍为通用503，没有改为504，也不增加 affinity invalidation。 |
| [#533](https://github.com/fawney19/Aether/issues/533) | 2026-05-21 | 部分修复 | 正则预览以前只枚举 key.allowed_models，无限制 key 因此为空。现在可用 provider 有限 concrete model 目录生成预览；显式空 allowlist 仍拒绝，受限 key 不借目录放权，无目录不臆造匹配。 |
| [#529](https://github.com/fawney19/Aether/issues/529) | 2026-05-21 | 已覆盖 | 非TLS tunnel 已有 AES-256-GCM、版本/能力握手、每节点PSK与禁止静默回退；保留 wss 并明确 Aether↔tunnel 边界。 |
| [#514](https://github.com/fawney19/Aether/issues/514) | 2026-05-20 | 暂缓 | 管理菜单可配置只影响可发现性，不是授权边界；全局或每管理员配置的范围与升级语义尚需设计，不能只藏入口冒充权限控制。 |
| [#508](https://github.com/fawney19/Aether/issues/508) | 2026-05-19 | 暂缓 | 已有多个余额预设，但 DeepSeek balance_infos 需要新架构/解析器，不是 endpoint 配置即可解决；不伪造余额或通用映射。 |
| [#465](https://github.com/fawney19/Aether/issues/465) | 2026-05-15 | 通知 | Rust迁移公告，当前已经是 Rust，不存在待修复的公告行为。 |
| [#450](https://github.com/fawney19/Aether/issues/450) | 2026-05-13 | 修复 | 失败且未报告 token/费用不再伪造0/0；保留明确可用、已报告零值与已完成零值。补齐 NULL token 读取兼容和无 body 捕获的安全失败原因展示，详情不新增原始上游消息持久化。 |
| [#365](https://github.com/fawney19/Aether/issues/365) | 2026-04-30 | 已覆盖 | gemini_cli 已走 cloudcode-pa `/v1internal:{action}`，不是旧 `/v1beta/models`；若仍出现后者应核对 provider 类型、base_url 与模型资格。 |
| [#364](https://github.com/fawney19/Aether/issues/364) | 2026-04-30 | 已覆盖 | Antigravity 已有 OAuth添加/导入及 project_id 水合；“缺少OAuth”仍意味着没有凭据材料，不应伪造账号成功。 |
| [#272](https://github.com/fawney19/Aether/issues/272) | 2026-04-01 | 已过时 | DetachedInstanceError 属已删除的 Python SQLAlchemy 会话路径；Rust 使用 owned snapshot，无旧 ORM 懒加载关系。 |
| [#263](https://github.com/fawney19/Aether/issues/263) | 2026-03-25 | 已覆盖 | 同一 provider 可有多个独立 endpoint/base_url，模型映射按 endpoint ID 限定，已支持不同模型走不同端点。 |
| [#254](https://github.com/fawney19/Aether/issues/254) | 2026-03-20 | 已覆盖 | 通用 custom OIDC 已有，需配置 allowed_domains、授权/token/userinfo端点；内置 provider 的固定 allowlist 不放宽。 |
| [#178](https://github.com/fawney19/Aether/issues/178) | 2026-02-17 | 部分已有/暂缓 | 六项中 embeddings、rerank、images/generations 已有；completions、audio/speech、audio/transcriptions 缺独立格式与路由。后者还需二进制/multipart、流式、provider和计费合同，非聊天 inline audio 的别名。 |
| [#145](https://github.com/fawney19/Aether/issues/145) | 2026-02-04 | 通知 | QQ群与反馈渠道公告，没有代码缺陷或可实现需求。 |
| [#38](https://github.com/fawney19/Aether/issues/38) | 2025-12-22 | 已覆盖 | 路由组客户倍率已在 admission 冻结，预估与实际日配额按快照消耗，后续改倍率不重算旧记录；上游采购倍率独立，不污染客户计费。 |

## #817 复合问题逐项处理

| 子项 | 当前实现与处理 |
| --- | --- |
| 余额抓取 | 使用架构预设，不是任意 JSON 字段映射。缺站点响应/日志不能断定解析器故障；DeepSeek 未实现，不能按 generic_api 假装支持。 |
| 自动签到 | New API/Anyrouter 已覆盖；Sub2API/YesCode 明确不支持签到。余额请求/解析失败仍可能遮蔽已成功的签到结果，这个解耦缺口本轮暂缓。 |
| 清理0项 | 按7/30/90/365天保留阶段处理，窗口内0项是正常结果。立即清理 body 应选择 `before_now`，清除 body/blob 与引用，不等于删除整条记录及 header；不放宽删除语义。 |
| 安装命令localhost | 配置 `AETHER_PUBLIC_BASE_URL`，或只将实际反代纳入可信CIDR；不信任任意 Host/X-Forwarded-*。systemd WorkingDirectory 的引号问题当前已覆盖。 |
| VSCodex远控 | 后端已有 disabled/缺地址/缺token 等分类错误，前端仍可能只显示通用错误；缺部署与 sidecar 日志，未确认服务端逻辑故障，诊断改进暂缓。 |
| audit_logs无数据 | 确认只有读仓库、没有写入生产者，admin审计仅 tracing。新增持久化须明确脱敏、权限、保留与迁移合同，本轮不把空页面误报为已修复。 |

## 实现与运维边界

### 成本归因（#637）

- 新字段 `provider_cost_amount` / `provider_cost_available_count`，金额 basis 为 `provider_cost`。以 settlement snapshot 的 `billing_actual_total_cost_usd` 为权威，兼容已结算且可计价的 legacy actual；非有限值、未定价/未结算缺口保持 unknown。
- `rated_amount` 是规则计价，`billable_amount` 是冻结客户倍率后的消耗；均不作为上游采购成本的替身，也不等于人工登记的 expense ledger。
- 使用现有 `/api/admin/overview/users` 和 `/summary` 的同一 from/to/timezone/provider_id。排序在分页前由服务端完成，占比分母来自全量 provider 汇总，不取当前页或仅有用户行的小计；覆盖不足不计算假占比。
- 新增迁移 `20261010000000_add_provider_cost_amount.sql`，向 canonical facts view 末尾追加列，bootstrap 同步更新。旧 overview-v2 bucket 不补写该字段，读取时由既有 raw diagnostics 聚合补充；不重写历史账目，不更改旧迁移。
- 与先前暂缓的 PR #638 不同：没有新增旧 attribution 端点、名称匹配或全量内存排序链路。

### 协议、安全与额度

- #719 只有可在固定 Chat function 名称、arguments/content 中恢复的 hosted item_type 才视为已映射；没有 blanket extension whitelist，未知字段与 item_reference 继续 fail closed。
- #780 内层终态先认领，外层 watchdog 放弃并释放 attempt 后应用效果；两种定时器顺序均只累计一次健康失败，不把客户端断连或上下文溢出计入 key 故障。
- #895 保持硬上限：无法估算不创建 reservation；同一 identity 可在补齐上界后重试。没有事后软上限、默认 fail-open 或财务超调新模式。
- #636 不缓存权限到 localStorage。状态未知并不会放开功能；两次瞬时失败仍可能隐藏入口，直到下次拉取/刷新。
- #450 未报告 usage 与明确上报0不同。数据库 NULL 在内部读模型兼容为数值0，公开 availability 决定返回 null/不可用；不能因内部兼容值又显示成已知0。
- 无正文的上下文溢出原因来自网关已有可信分类，不从任意上游文本或客户端metadata猜测。同步与流式终结报告写入固定白名单类别`context_length_exceeded`，admin详情由该类别生成固定提示；其他400仍为`client_error`，不扩大原始错误持久化范围。

## 代码证据入口

| 领域 | 主要实现 |
| --- | --- |
| 硬限额400与预留 | `apps/aether-gateway/src/plan_usage_policy.rs` |
| Chat结构化工具结果、hosted历史、created | `crates/aether-ai/formats/src/protocol/canonical.rs`、`formats/registry.rs`、`formats/openai/chat/{stream,response}.rs` |
| 调度真实时钟与独立seed | `apps/aether-gateway/src/ai_serving/planner/candidate_source.rs`、`scheduler/candidate/{selection,ranking}.rs` |
| 超时恰好一次健康效果 | `apps/aether-gateway/src/executor/candidate_loop.rs`、`execution_runtime/stream/execution_failures.rs` |
| 授权后的有效模型 | `crates/aether-scheduler-core/src/model.rs` |
| 首次Ops凭据保存、有限目录预览 | `apps/aether-gateway/src/handlers/admin/provider/ops/providers/config.rs`、`handlers/admin/provider/delete_task.rs` |
| 成本归因 | `crates/aether-data/adapters/postgres/src/usage/analytics.rs`、`crates/aether-admin/src/observability/analytics/`、`frontend/src/features/overview/costs/ProviderUserAttribution.vue` |
| 模块状态韧性 | `frontend/src/stores/modules.ts` |
| 未报告usage与失败详情 | `crates/aether-usage/runtime/src/record.rs`、`crates/aether-admin/src/observability/usage.rs`、`frontend/src/features/usage/components/RequestDetailDrawer.vue` |

## 本地验证记录

| 范围 | 已执行结果 |
| --- | --- |
| #895 硬限额与预留 | `plan_usage_policy::tests` 17项通过；无上界400、不留错误预留、补齐上界后同身份可重试，后续请求继续受硬窗口约束。 |
| #861/#719/#738 协议转换 | `aether-ai-formats --lib` 1023项通过；覆盖结构化工具结果、稳定 created、hosted 字段保留及未知扩展拒绝。 |
| 网关集成 | 所选377项通过；覆盖候选时钟/并发/熔断、两种超时顺序恰好一次健康、模型授权、Sub2API首次保存与掩码复用、有限目录映射预览。 |
| #637 内存与管理合同 | 6项通过；实际采购成本的数值排序、分页前排序/全量总计、金额口径与覆盖状态。 |
| #637 真实 PostgreSQL | `live_overview_provider_cost_prefers_settlement_and_survives_projection_reads` 通过；snapshot actual优先、pending/未定价不作零、12/10/2数值排名、分页不截断总额；规则价17、客户计费26、采购成本24互不混用。重建的旧overview-v2 bucket确实没有新字段，启用projection读取仍返回采购24/覆盖3条。 |
| #450 可信失败原因合同 | runtime/admin/contracts所选6项通过：同步及流式终结报告进入真实usage写入路径；仅可信`stop_context_overflow`分类变为固定`context_length_exceeded`，其余400保持`client_error`，成功记录不继承失败分类；未报告用量仍为unknown，已报告零值保持available，未采集正文也返回固定的上下文超限原因。 |
| 前端 | `vue-tsc`、5个针对性文件共51项测试、Vite生产构建通过；覆盖瞬时错误重试、重试耗尽关闭、身份切换竞态、时间范围切换/过期响应、成本占比与失败详情。构建仍有大于500KiB chunk警告，未以抬高阈值隐藏。 |
| 实际成本归因界面 | 真实管理员登录和数据库读取：采购6/5/1与规则价12/10/2分列，排名正确；占比用完整provider采购12.7而非有用户行小计12。切换billable/请求数排序、第二页offset25/limit25均HTTP200，显示26–30/30；View保留相同时间范围与provider的usage链接，未知金额/占比为“-”。 |
| 实际失败详情 | 本机数据库恢复canonical NULL input/output、无错误原文且无请求/响应正文：列表HTTP200并显示Failed/Unavailable，详情显示固定的上下文超限原因、HTTP400及`context_length_exceeded`；成功请求详情无失败提示，`include_bodies=false`详情HTTP200，浏览器无JS错误。 |
| 实际邀请界面 | 普通用户登录后进入`/dashboard/referral`，硬刷新后入口与页面保留；瞬时失败与账户竞态由上述单元回归覆盖，未用响应mock冒充真实页面验证。 |
| 格式化 | `cargo fmt --all --check`通过。 |

数据库与账号均为本机隔离测试数据，未连接生产；界面通过实际网关与PostgreSQL，不以响应mock替代。Rust验证使用本机SDK26.5及rust-lld规避SDK27链接兼容问题，大型网关测试使用32MiB线程栈。这些结果不是外部提供商可用性、生产压测或镜像发布承诺。

最终补充：已有网关`context_overflow`/`context_length`分类、健康与恢复边界6项通过，格式化检查通过；最终网关二进制构建成功，并用于上述真实NULL usage与失败详情验证。

存储细节：现有repository upsert会将缺省token规范化为0，公开接口仍以`usage_available=false`表达unknown。本轮没有改该写入合同；读取兼容同时覆盖数据库中已有的NULL input/output，total保留原有0语义，避免将兼容值误当真实上报零值。

`live_canonical_unavailable_usage_reads_lists_and_details_without_error`真实PostgreSQL回归通过：验证upsert后unknown状态、已有NULL记录的列表/最近列表/ID详情/request_id详情/浅详情读取，以及明确上报0保持available。随后`cargo fmt --all --check`通过。本轮启动的浏览器页、前端、网关和隔离数据库均已停止。

## v0.100.0 发布修复

- 首次标签构建的amd64/arm64二进制、前端和安装包均成功；GHCR因已有包不授予该仓库写权限返回`permission_denied: write_package`。用户删除旧包后，由本仓库Action重新创建；不引入长期PAT。
- `Cross.toml`仅透传`AETHER_BUILD_VERSION`、`AETHER_VERSION`、`AETHER_BUILD_TYPE`。此前cross丢弃这些变量，使二进制被标成source并阻止原生自更新；release工作流为前后端显式指定相同标签版本。
- `actionlint .github/workflows/release.yml`通过；在无Git工作区的`/tmp`执行真实build.rs，输出版本`0.100.0`、构建类型`release`。双架构实际编译和发布仍以重建后的Action结果为准。

### 发布结果

- 修复提交：`e1d6bdbbf`；用户授权将未成功发布的`v0.100.0`标签更新到该提交。未改写其他标签。
- [Release Aether #42998160253](https://github.com/wmsyw/Aether/actions/runs/42998160253)的8个job全部成功，包含两种musl二进制、前端、VSIX、多架构镜像、来源证明和GitHub Release。
- 匿名读取GHCR manifest成功；`ghcr.io/wmsyw/aether:0.100.0`与`latest`同为`sha256:49a358774ed4ef67bb5d69785567cec7d89bd1554279db0ad10caee9ac0296ca`，含`linux/amd64`、`linux/arm64`及构建证明manifest。
- [v0.100.0 Release](https://github.com/wmsyw/Aether/releases/tag/v0.100.0)为正式发布，含amd64/arm64 tarball、VSIX、`install.sh`、`SHA256SUMS`及sigstore来源证明；发布说明已回填。

## v0.100.0 代码审查修订

- Base64 审计压缩使用一次 data URL 匹配遍历，避免每个 `data:` 前缀重新扫描后续正文；回归覆盖大量无 marker 文本、无效前缀后的合法 URL，以及现有阈值、MIME 和正文保留行为。
- 模型白名单回退先过滤已授权且 scope 匹配的映射，再沿用 priority、operation scope 和名称排序；不再按白名单字典序覆盖模型优先级。回归覆盖未授权首选、多模型优先级、operation 与 endpoint scope。
- 删除 `.github/workflows/deploy-pages.yml`，保留 Release Aether、Tunnel、Nightly 和 Rust CI。
- Rust CI 的 Claude/Gemini→OpenAI 合同测试验证动态 `created` 时间戳后继续精确校验转换内容；旧库升级测试按已嵌入迁移集合计算待执行版本，保留历史记录、统计数据和重复升级验证。
- 清理 Rust CI workflow 中被 `*.rs` 覆盖的重复 shell pattern 及 PostgreSQL PATH 步骤的无效 echo 包装，不跳过测试或降低门禁。
- `actionlint .github/workflows/*.yml` 与 `cargo fmt --all --check` 通过；对 `aether-usage-runtime`、`aether-scheduler-core` 执行 `cargo clippy --locked --all-targets -- -D warnings` 通过。
- 真实 PostgreSQL 的 `legacy_overview_upgrade_preserves_applied_history_and_existing_statistics` 回归通过；测试开启 `AETHER_REQUIRE_LOCAL_POSTGRES_TESTS=true`，未跳过数据库验证。
- 用户明确确认覆盖已发布的 `v0.100.0`：修复及 Rust CI 通过后更新同名标签、Release 附件，以及 GHCR 的 `0.100.0`、`0.100`、`latest`；不删除整个 Release。
- Base64 正文捕获、模型选择和同步响应转换的针对性 nextest 共 83 项全部通过；百万个 `data:` 前缀（约 5 MB）回归进程耗时 0.105 秒。该耗时仅为本机测试观测，不作为定时断言。

