# 上游待合并 PR 研究与选择

研究日期：2026-11-11。上游：<https://github.com/fawney19/Aether/pulls>。

## 范围与方法

- 快照包含全部 **38** 个 open PR（含 draft），按**创建时间从新到旧**倒查，不因最近评论把旧 PR 提前。
- 本地基线 `0eb3233903ec74806a7046669115d69eea54bce8` 与当时上游 `main` 完全相同。逐项对照提交边界、完整 diff、当前实现与调用链；不是依据标题直接合并。
- 选择15项中的完整修复或明确子集；12项暂缓，8项不合入，3项已被当前实现覆盖。大 PR 仅迁移独立且仍适用的行为，不把旧 fork 历史混入。
- 首轮集成已提交为 `e433bc9cd`；后续 fork 发布源适配单独提交。未推送、未修改上游 PR，也未触发镜像发布。

## Fork 发布源适配

- 本 fork 为 `wmsyw/Aether`。Release 与 Nightly 镜像名取当前 `github.repository` 并转为小写，本仓库输出 `ghcr.io/wmsyw/aether`；Tunnel Release 的下载表也使用当前仓库。
- Docker Hub 不再写死上游账号。仅在显式设置仓库变量 `DOCKERHUB_IMAGE` 且两个认证 secret 均存在时，才将目标加入镜像列表并执行登录和 provenance attestation；否则仅发布 GHCR。
- 安装脚本、Compose 默认镜像、管理后台更新 API/下载校验、Tunnel 升级与安装源、前端链接及仓库元数据均指向本 fork。更新资产仍需精确匹配同仓库、同版本和当前平台；回归明确拒绝原上游路径。
- 保留真正的上游 PR 研究链接，以及 Codex prompt-cache 的稳定 namespace。后者不是网络下载源，改变它会改变现有缓存身份。
- 本地验证：3个修改工作流通过 Actionlint；14个实际 shell 场景覆盖仓库大小写、可选 Docker Hub、main 限制、正式版/RC/Beta 与手动构建门禁；Rust 更新安全49项、安装命令2项、管理端更新载荷6项、Tunnel 升级13项通过；Shell installer 安全场景通过；前端类型检查与2文件231测试通过，运行首页显示本 fork 的 GitHub 链接；`cargo fmt --all --check` 通过。
- 未执行容器镜像构建/推送或 GitHub 发布；fork 需先启用 Actions 并完成首次成功发布，不能假定镜像和 Release 制品已经存在。

## 全部 PR 结论

| PR | 创建时间 | 处理 | 价值与边界 |
| --- | --- | --- | --- |
| [#903](https://github.com/fawney19/Aether/pull/903)  | 2026-11-10 | 选取 | 修复 Gemini 思考 token 结算、模态明细和 Vertex 服务账号 Interactions；现代模型参数、签名、URL 与候选认证共同适配。 |
| [#902](https://github.com/fawney19/Aether/pull/902)  | 2026-11-10 | 选取 | 上下文溢出 400 停止无效换号，不扣健康分；允许 Responses 历史中的限定传输元数据进入 Chat。 |
| [#901](https://github.com/fawney19/Aether/pull/901)  | 2026-10-28 | 选取子集 | 仅取消协议与结算生命周期；不引入默认排队、并发 admission 重排或新数据库字段。 |
| [#900](https://github.com/fawney19/Aether/pull/900) | 2026-10-24 | 不合入 | **Rhai 脚本自定义额度查询**。CPU 沙箱不约束网络出口；写入 provider 配置即可把解密池密钥填入任意公网请求，并自动发起查询，存在凭证外泄风险。 |
| [#899](https://github.com/fawney19/Aether/pull/899)  | 2026-10-24 | 选取 | 扩展审计 base64 压缩至各类结构化负载，4KiB 解码阈值；不修改上游转发内容。 |
| [#898](https://github.com/fawney19/Aether/pull/898)  | 2026-10-22 | 选取 | 保留 Responses additional_tools；Antigravity 混合工具优先客户端函数，避免内建工具冲突。 |
| [#897](https://github.com/fawney19/Aether/pull/897)  | 2026-10-22 | 选取 | 注入的 Claude Code cache_control 跟随客户端 1h 标记，而非强制5m。 |
| [#894](https://github.com/fawney19/Aether/pull/894)  | 2026-10-19 | 选取 | xAI 与 Antigravity 显示各配额周期用量；Antigravity 按模型族分组，保留 Codex 行为。 |
| [#893](https://github.com/fawney19/Aether/pull/893)  | 2026-10-19 | 选取 | Responses 重放按 call_id 恢复 Gemini thought signatures，跨 Chat 中转与插入的 reasoning 不丢失。 |
| [#885](https://github.com/fawney19/Aether/pull/885)  | 2026-10-09 | 选取 | 维护覆盖当前表集合；缺表跳过、目录查询错误正常传播。 |
| [#881](https://github.com/fawney19/Aether/pull/881)  | 2026-10-06 | 选取 | 单条 stop 也序列化为非空数组，兼容严格 OpenAI relay；空列表不发。 |
| [#840](https://github.com/fawney19/Aether/pull/840)  | 2026-09-21 | 本地已有 | 已解决：当前流处理直接转移解析器状态，不再从截断预读缓存重建，无需旧 overflow 缓冲。 |
| [#827](https://github.com/fawney19/Aether/pull/827) | 2026-09-15 | 不合入 | **API Key 限定可用上游密钥**。空 allowlist UI 表示全部禁用，后端却视为 unrestricted；按名称匹配还会放行其他 provider 的同名 key，且缺发送前最终校验。 |
| [#766](https://github.com/fawney19/Aether/pull/766) | 2026-08-30 | 暂缓 | **用户分组按 provider 限定上游密钥**。显式空集合拒绝访问、发送前校验值得保留，但只覆盖分组、不覆盖独立 API Key；与 #736 引入竞争性 schema，需先统一继承和交集语义。 |
| [#740](https://github.com/fawney19/Aether/pull/740) | 2026-08-20 | 不合入 | **新增 OrcaRouter 命名提供商**。custom 已支持相同 OpenAI 协议，主要是厂商预填与宣传，没有协议能力增量。 |
| [#736](https://github.com/fawney19/Aether/pull/736) | 2026-08-18 | 暂缓 | **按 provider ID/key ID 设置 API Key 和分组白名单**。稳定 ID 模型有价值，但空集合会归一化成 unrestricted；需一次打通分组继承、导入、池游标与发送前鉴权，不能局部接入后静默放宽权限。 |
| [#735](https://github.com/fawney19/Aether/pull/735) | 2026-08-18 | 暂缓 | **完整管理 API、客户端 API、数据库和运维参考手册**。生成式清单已落后于当前 v2 路由，不能以“完整 API 文档”发布。 |
| [#734](https://github.com/fawney19/Aether/pull/734)  | 2026-08-18 | 本地已有 | 已解决：旧 RoutingProfiles 已删除，当前编辑器移除最后一个 scope 后自动回到 all。 |
| [#729](https://github.com/fawney19/Aether/pull/729) | 2026-08-17 | 不合入 | **更换 README Star History 图片源**。原官方端点实测有效，没有必要替换成未验证的第三方镜像；本 fork 仅调整图表仓库参数。 |
| [#727](https://github.com/fawney19/Aether/pull/727) | 2026-08-15 | 暂缓 | **同步 Sub2API 远程额度并参与调度限制**。撤销远程额度配置后可能保留 exhausted monthly_quota=0，导致永久不可调度；配置撤销与恢复生命周期未闭环。 |
| [#714](https://github.com/fawney19/Aether/pull/714) | 2026-08-06 | 暂缓 | **可配置每日用量限额**。当前 CalendarDay/daily_quota 已覆盖核心能力；补丁另建 Redis fail-open 台账，会产生两套计数和限额语义。 |
| [#713](https://github.com/fawney19/Aether/pull/713)  | 2026-08-05 | 选取子集 | 仅修复已有 billing.video.price_per_second_by_resolution 不结算；不引入 Doubao、每token视频新定价或 Ark 素材库。 |
| [#708](https://github.com/fawney19/Aether/pull/708) | 2026-08-01 | 不合入 | **使用 UUID parser 替代手写校验**。此处既有36字符、hex和连字符检查与所提 parser 没有有效行为差异，不引入纯替换。 |
| [#673](https://github.com/fawney19/Aether/pull/673)  | 2026-07-14 | 选取 | 同一代理节点多个 tunnel 会交错累计计数；按 session+递增 heartbeat cursor 建立基线，避免事件和流量膨胀。 |
| [#656](https://github.com/fawney19/Aether/pull/656) | 2026-07-02 | 暂缓 | **扩展提供商批量编辑表单与操作**。当前已能批量启停、删除；属于可选 UX 增强，不优先为此引入大面积表单变更。 |
| [#653](https://github.com/fawney19/Aether/pull/653) | 2026-06-25 | 暂缓 | **GLM Coding Plan 额度查询与展示**。新功能混入删除现行 admin_bypass_limits 和缓存语义，需先拆出纯 GLM 功能，避免改变无关权限与缓存行为。 |
| [#647](https://github.com/fawney19/Aether/pull/647) | 2026-06-19 | 暂缓 | **OpenCode Free / Kilo Free 无用户密钥提供商**。依赖当前没有的固定 key 自动创建机制，且第三方免费网关增加隐私、条款和可用性依赖。 |
| [#642](https://github.com/fawney19/Aether/pull/642) | 2026-06-16 | 暂缓 | **按 API Key 配置 Codex 模型链与候选路由**。补丁在旧分页循环中嵌套模型循环，会影响当前优先/延迟分页、有效模型授权和额度约束；需按现有调度器重设计。 |
| [#640](https://github.com/fawney19/Aether/pull/640)  | 2026-06-10 | 本地已有 | 已解决：默认 request recording 已是 Basic，无差异。 |
| [#638](https://github.com/fawney19/Aether/pull/638) | 2026-06-09 | 暂缓 | **按提供商查看用户成本归因及占比**。当前 UsageAnalyticsQuery 已支持 users+provider_id；可新增界面，但不应再建立旧聚合接口、名称匹配和内存排序链路。 |
| [#634](https://github.com/fawney19/Aether/pull/634) | 2026-06-07 | 暂缓 | **独立 API Key 的客户计费倍率**。功能有价值，但补丁把倍率乘到供应商采购 actual_total_cost 上，污染成本统计；正确做法是纳入请求 admission 的不可变客户倍率快照。 |
| [#633](https://github.com/fawney19/Aether/pull/633) | 2026-06-07 | 不合入 | **Web 后台触发 Docker 在线更新**。侧车持有 docker.sock、默认 token 并使用 mutable latest，把后台权限扩大到宿主机控制面，风险高于便利收益。 |
| [#630](https://github.com/fawney19/Aether/pull/630)  | 2026-06-05 | 选取子集 | 仅 0355ed645：接纳 inline system/developer 指令并选择最后 user/assistant；不带入 ARN/profile/时延改动。 |
| [#628](https://github.com/fawney19/Aether/pull/628) | 2026-06-04 | 不合入 | **新增模型 -extra 指令后缀别名**。没有实际故障依据，增加与真实模型名碰撞的风险；保留现有 xhigh/max 约定。 |
| [#626](https://github.com/fawney19/Aether/pull/626) （draft） | 2026-06-04 | 选取子集 | 仅 567926fc6：embedding/rerank 显式逐格式 auth override；无 override 保留每条路径原默认，不引入免费 provider。 |
| [#623](https://github.com/fawney19/Aether/pull/623) | 2026-06-03 | 不合入 | **系统完整导出包含管理员账号**。会导出管理员 password_hash，导入器却仍拒绝恢复完整管理员，没有备份恢复收益，反而增加敏感数据暴露面。 |
| [#608](https://github.com/fawney19/Aether/pull/608) | 2026-05-29 | 暂缓 | **创建用户自动生成密码、用户备注字段**。创建与备注分两次写可能部分成功；导入会丢备注；密码生成在无 crypto 时回退 Math.random，需先补原子性、备份往返及安全随机数合同。 |
| [#588](https://github.com/fawney19/Aether/pull/588) （draft） | 2026-05-28 | 选取子集 | 仅可靠终态的失败显示纠正并保留恢复成功状态；不采纳无约束 error_message 判失败、死代码 notice 或原始错误体扩曝。 |

### 只取子集的 PR：未采纳部分

| PR | 未采纳功能或改动 | 原因 |
| --- | --- | --- |
| #901 | 默认15秒并发队列、admission 重排、新排队字段 | 改变过载时的延迟、429/503 与资源占用合同；不是取消协议的必需依赖，不能以取消修复为由一起切换。 |
| #713 | Doubao 视频端点、每 token / 输入素材差异定价、Ark 素材库及大范围异步任务界面 | 只有已有秒价“不结算”是现行功能缺陷；其余是独立产品功能，涉及上传、外发和素材归属，需要独立设计与安全审查。 |
| #630 | ARN/profile 与时延相关附带改动 | 与 inline system/developer 兼容无关，不带入无关行为变化。 |
| #626 | 免费 provider 与固定密钥自动创建 | 不属于认证 override 的必要部分，且依赖当前不存在的 provider key 生命周期约定。 |
| #588 | 任意 error_message 直接判失败、原始错误体扩曝、无效 notice | 会把重试中或恢复成功的请求误标失败，或扩大公共接口的信息泄露面。 |

另有 #840（预读状态恢复）、#734（移除最后模型策略后切回统一范围）、#640（默认 Basic 记录）已被当前实现覆盖，未重复应用旧补丁。

## 关键合入边界

### 计费与凭证兼容

- Gemini output 已包含 reasoning，总 token 不再重复相加；模态分组总和超出标准计数则整组丢弃。详见 [Gemini 接入约定](../api/google-gemini.md)。
- #626 只增加显式逐格式认证覆盖。未设置或无效 override 保留每条路径原默认：embedding 与跨格式 rerank 为 Bearer，同格式 rerank 仍按原 standard auth。
- 管理界面将 `Default`（无 override）与显式 `api_key` / `bearer` 区分；即便选择与 key 的 auth_type 相同也不去重。真实保存/重开验证覆盖显式 API Key 持久化，以及切回 Default 后移除配置。
- #713 只修复管理员已经配置的视频按分辨率秒价结算；不新增每 token 视频模式、参考视频定价、Doubao 或 Ark 素材库。未配置的分辨率不推测价格，失败/取消任务不增加视频秒费，不回填已结算记录。
- 秒价模式按实际 video task/API 格式启用，不因同一模型配置了秒价就改动聊天/图像价格；视频秒费不再叠加输入、输出或缓存 token 费。创建成功只登记 pending 用量；轮询、客户端读刷新、初始已终态创建均走相同有序终态结算，沿用原 admission 倍率与 reservation。

### 取消与终态

- #901 只采纳 `7e23f389f471bf61467933c2e6cd2b0ae996de5a` 的取消协议与结算生命周期。不上默认15秒队列，不改并发 admission、429/503 约定或数据库 schema。
- 取消计费授权使用终态 seed 的独立可信标志，不采信 report_context、request_metadata、audit_payload 或 capture_metadata 中同名字段。仅提供商明确取消、已观察到结束且确实报告用量时才可授权；排队事件已宣布的 response ID 也参与取消身份校验。
- #588 不把任意 error_message 当成终态，避免把恢复成功/仍在重试的流标失败；只使用可靠终态事实。不给公共用量接口新增原始上游响应泄露面。

### 周期统计与心跳

- #894 不混算 Antigravity 模型族：优先使用非空 `target_model`，再退回 `model`，去首尾空白并忽略大小写。Gemini 组只计 `gemini` 前缀，Claude/GPT 组排除此族；PostgreSQL 与内存路径采用同一语义。xAI 月周期必须有上游报告的起点，不能拿固定30天代替真实账期。
- #673 只在同一 session、递增 heartbeat ID 下累计计数差额；跨 session、倒序、重放或游标单边缺失只更新基线。两端均无游标保留旧协议。外层已认证 payload 的游标覆盖 metadata 中的伪造值。
- 省略或显式为 null 的心跳 metadata 保持原快照不变；游标只附在实际 tunnel_metrics 快照上，不用游标空对象擦除已有资源与流量信息。

## 上游检查的使用方式

上游 CI 仅作为线索，不替代本地门禁。#899 与 #881 的失败日志分别涉及已迁移前端路径白名单、SQL 片段数量等源文本断言，不是补丁行为证明。此次删除了已失效的 retired-format 源文本白名单测试；没有重新钉住文件路径或计数。

#903 新格式适配不包含任何真实提供商付费请求验证；行为由当前协议转换与认证/候选回归覆盖。

## 本地验证记录

| 验证范围 | 已通过结果 |
| --- | --- |
| 格式转换 / 提供商传输 | 1008 / 568 个单元测试 |
| 数据合同 / 终态用量 | 271 / 403 个单元测试；覆盖无 metadata 心跳、取消计费伪造入口与视频创建延迟结算 |
| 管理端额度解析 / 池统计 / 内存模型族过滤 | 114 / 17 / 1 个测试 |
| 计费 | 114 个单元测试；视频秒价只影响实际视频，普通聊天/图像价格保持，视频不重复收取输入输出与缓存 token 费用 |
| WebSocket Responses / 取消端到端 / attempt 生命周期 | 226 / 8 / 17 个测试；覆盖排队 response ID、可恢复取消、原截止时间与可信用量授权 |
| HTTP 提供商取消 | 实际 finalizer 状态回归通过：499/Cancelled、provider_cancelled 分类、报告用量计费且不触发成功副作用 |
| 心跳 / 异步任务 | 37 / 27 个测试；视频通过本进程 HTTP 提供商验证读刷新和初始终态结算、原倍率/预约保留与重复读取不重复扣款 |
| 前端 | `vue-tsc` 通过；7个针对性文件共138个测试通过；Vite生产构建通过 |
| PostgreSQL 实际查询 | 验证 target_model 回退、空白与大小写、Gemini/非Gemini拆分、半开时间边界和零行汇总 |
| 真实管理界面 | Vertex 服务账号显示 Interactions、API Key 不显示；显式认证保存/重开与清空；HTTP200可靠失败、恢复成功、仍活动三种状态 |
| 实际池页面与数据库汇总 | Antigravity Gemini为2请求/300tokens/$0.300、Claude/GPT为1/300/$0.400；xAI周周期由后端推导，汇总3/600/$0.700，均从真实用量事实查询 |
| 格式化 | `cargo fmt --all --check` 通过 |
| Rust 诊断 | 所选6个 crate 的 `cargo clippy --all-targets -- -D warnings` 通过；最终修正后再次检查 gateway / data-contracts 通过 |

验证数据库为本机临时 PostgreSQL，未连接生产数据；界面经真实管理员登录与后端持久化读取，不以响应 mock 代替。SDK27链接器存在本机兼容问题，Rust验证使用SDK26.5及rust-lld；大型网关测试使用32MiB线程栈。上述为开发环境验证，不是外部提供商可用性或生产压测承诺。
