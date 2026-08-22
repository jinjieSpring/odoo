# hdai_base 第一阶段开发说明

## 1 模块职责

`hdai_base` 是 `hdai_*` 系列模块的基础模块（依赖 `base`、`web`），第一阶段
交付三部分能力：

1. **模型接入层**：`hdai.provider`（DeepSeek / vLLM / Ollama / OpenAI
   兼容）、`hdai.model`、`hdai.usage`（Token 计量），服务类
   `LLMService` 统一封装 OpenAI 兼容协议与 DeepSeek Responses API
   （流式 + 非流式）。
2. **工具框架**：`@ai_tool` 装饰器、`hdai.tool` 注册表、
   `hdai.tool.log` 审计日志；内置 `generic.search_read` /
   `generic.search_count` / `generic.group_by` 三个只读工具。
3. **系统托盘 AI 聊天**：systray 图标 + 对话框组件，流式 NDJSON 输出、
   业务记录上下文感知（当前表单记录 + 最近 chatter 注入）、停止生成。

## 2 关键设计约定

- **只读红线**：工具框架与通用工具没有任何写路径；`hdai.tool` /
  `hdai.tool.log` / `hdai.usage` 的写权限只开放给系统内部（`sudo()`），
  普通用户即使经 RPC 也无法改写审计与计量数据。
- **快照原则**：流式控制器在响应开始前完成全部 ORM 工作并构建
  `SimpleNamespace` 快照；生成器与流结束后的落库使用独立游标
  （`Registry(dbname).cursor()`），不接触 ORM 记录。
- **密钥安全**：`hdai.provider.api_key` 字段 `groups` 限定
  `hdai_base.hdai_group_manager` 且 `copy=False`；服务读取走
  `LLMService._api_key`（同时支持 ORM 记录与快照）。
- **权限模型**：`hdai_group_user`（对话 + 工具调用）、
  `hdai_group_manager`（Provider/模型/工具注册表管理）；
  session/message 配「仅本人」记录规则。
- **限流**：工具调用按审计日志做 60 秒滑动窗口限流（默认 30 次/分钟，
  超限返回 429）；`timeout` 为元数据字段（线程环境无法可靠中断，
  硬超时熔断留待第四阶段治理模块实现）。

## 3 常用命令

```bash
./odooctl.sh start -d d19_dev -u hdai_base --test-enable --stop-after-init
./odooctl.sh restart -d d19_dev --update=hdai_base --dev=reload
```

## 4 测试与验证

- 19 项离线测试（LLMService mock、通用工具、会话/上下文），
  `--test-enable` 全通过。
- 静态检查：ASCII grep、`node --check`、polib 解析（173 词条）、
  XML 解析。
- 端到端：mock vLLM（`/v1/chat/completions` + `/v1/models`）验证
  流式 delta/usage 落库、同步对话、工具调用与审计日志。

## 5 真实端点联调进展

### 2026-08-17 修复（对照错误经验反馈）

- **llama.cpp 流式乱码**：SSE 解析改为显式 UTF-8 解码
  （`iter_lines(decode_unicode=False)` + `.decode('utf-8')`），
  DB/流式中文正常（error_reference 8.22）；
- **设置页模型联动**：provider onchange 同步默认模型 + Configure
  Provider 按钮 + 模型详情（8.23，参考 linkinai 设置页）；
- **attach record context 控件**：改为 router/controller 状态解析 +
  偏好/实际附加分离，开关生效（8.24，参考 linkinai）。

### 已完成：真实端点联调与浏览器实测（2026-08-17）

**双 Provider 真实调用**：

- DeepSeek 云端（`deepseek-v4-flash`）：连接测试获取模型列表、
  同步对话（88/56/144 tokens）、流式对话（89/53/142 tokens）均成功，
  usage 落库正确；
- llama.cpp 本地（`/home/zxh/ai/llama-b7941`，端口 8080，
  Qwen2.5-7B-Instruct Q4_K_M）：同步（35/23/58）、流式（39/55/94）、
  工具调用全部成功；
- 双 Provider 切换（DeepSeek ↔ llama.cpp）默认配置与就绪状态验证通过。

**Playwright 无头 Chromium 浏览器实测**（浅色/深色两种 color-scheme）：

- systray 图标出现、聊天对话框正常打开，控制台零错误；
- 真实 DeepSeek 对话经 UI 发送并流式显示中文回复；
- computed style 校验：对话框白底深字、输入框编辑态白底
  （rgb(255,255,255)）深字（rgb(31,41,55)）、用户气泡蓝底白字、
  助手气泡浅灰底深字——深浅色下均高对比可读；
- 截图存档：`/tmp/hdai_{light,dark}_{icon,chat,reply,after_click}.png`。

**修复的前端问题**：

- `hdai_chat_dialog.xml` 组件 prop `title="HD AI Assistant"` 被 OWL
  当作表达式编译报错，改为字符串字面量 `'HD AI Assistant'`；
- `useAutofocus` 误从 `@odoo/owl` 导入（`node --check` 无法发现），
  改从 `@web/core/utils/hooks` 导入（对照 error_reference 1.1）。

### 收尾

- 测试数据清理：删除全部测试 Provider/模型/usage 残留，保留
  `Local llama.cpp`（默认，含 Qwen 模型）与 `DeepSeek (Cloud)` 双配置；
- API Key 仅存 `hdai.provider.api_key` 管理员字段，日志/配置/代码零泄漏；
- 卸载→重装验证：`button_immediate_uninstall()` 后模块状态 uninstalled、
  `hdai*` 表全部清除；重装后重建双 Provider 并恢复默认配置，
  真实对话复测通过（注意：卸载会删除 hdai 组记录，重装后需重新给
  管理员授组）；
- 对照 HD-AI-STD-001 第 13 节合规清单：元数据完整、Schema 严格、
  只读无写路径、无 sudo 越权、权限声明、审计日志、分页、限流 429
  均已实现并有测试覆盖。

已完成的离线端到端覆盖（`hdai_base/tests/test_controller.py`）：

- `_save_stream_result` 经独立游标正确落库消息与 usage（对应流式控制器
  的生成器路径，不接触 ORM 记录）；
- 带 `hdai_group_user` 的非本人用户经记录规则无法搜索到他人会话；
- 流式调用只接收 `SimpleNamespace` 纯数据快照（无 `env`/`ids`）。

## 6 聊天窗口 UI 重构与体验修复（2026-08-18）

### 6.1 UI 设计文档

- 按 HD-AI-UI-001（`hdai_base/docs/hdai_base_chat_ui_design.md`，V1.1）
  完成对话框重构：可缩进侧边栏（会话历史 + 知识库网格）+ 三段式主区
  （上下文敏感区 / 对话历史 + 输入栏 / 状态栏），标题栏模型状态徽标。

### 6.2 评审决策 A1–A10 落实

- **A1 侧边栏宽度**：右缘拖拽手柄调节（180–800px），`sidebar_width`
  随用户设置持久化；网格折叠/高度、整体收起状态一并持久化；
- **A2 命令占位**：`/help` `/compact` `/export` `/share` 提示后续版本，
  仅 `/settings` 可用；
- **A3 停止生成**：生成中气泡出现「停止」按钮，AbortController 中止
  流式请求并丢弃未完成回答（真实 DeepSeek 流式验证通过）；
- **A4 会话元信息**：会话行显示消息数与相对更新时间；
- **A5 编辑提交**：消息编辑文本域普通回车即提交并重新请求；
- **A6 状态栏**：格式化消耗（`输入 x · 输出 y · 上下文 z%`）、任务状态
  （空闲/生成/执行工具/出错红）、禁用能力控件带原因提示，不显示模型名，
  保留提示词选择器；
- **A7/A8**：保持现状（无「测试中」状态；「在讨论区打开」为预留提示）；
- **A9 白名单自研**：hdai_base 自带 `hdai.nlview.model`（模型/ACL/视图/
  `hdai_action_nlview_model` 动作/默认 res.partner、res.users），工具卡片
  打开 hdai 自身动作，代码中无 `lia_*` 引用；
- **A10 主题跟随 Odoo**：主表面/文字/边框/强调色改用 Odoo SCSS 变量
  （`$o-view-background-color`、`$o-brand-lightsecondary`、
  `$o-main-text-color`、`$o-brand-primary`、`$o-gray-*`）。

### 6.3 上下文感知调整

- 列表/卡片视图上下文改为**视图记录总数**（非选中数）：前端
  `hdai_view_context` 发布整份 id 列表 + `root.count`，后端
  `action_get_list_context(model, res_ids, total_count)` 计数并生成快照；
- 空记录（0 条）禁用「插入上下文」控件；表单记录缺失同样禁用；
- pivot/graph/calendar 等不支持视图显示「当前 x 视图不支持上下文感知」；
- 表单视图保持 router/controller 记录解析。

### 6.4 其他修复

- 流式路由不一致（前端 `/hdai_base/chat/stream` vs 控制器
  `/hdai/chat/stream`）导致 404，统一为 `/hdai_base/chat/stream`；
- 三个 hdai 模块 PO 全量审计：补 `#. odoo-python`（hdai_base 229 条、
  另两模块 107 条）、`odoo-javascript` 标记、字段/帮助/selection/菜单/
  动作引用，合并重复 msgid，设置页文本节点改为 `<label string=.../>`
  （error_reference 1.20）；
- 侧边栏布局持久化（`cc3441b`）、列表/卡片选中集修复（`765db9e`）。

### 6.5 验证结论

- Playwright 实测（无控制台错误）：列表/卡片视图总数、空记录禁用、
  不支持视图提示、侧边栏拖宽/收缩/高度持久化、停止生成、编辑回车提交、
  会话元信息、状态栏消耗与任务态、设置页/提供方/菜单/聊天/用户设置
  全量中文翻译；
- 提交记录：`0c87636`（A1–A10）、`1fdc6c1`（列表/卡片上下文总数）、
  `b88984b`（翻译完善）。

### 6.6 体验修复续（2026-08-18）

- **本地模型乱码复发与修复**（`49b3cb4`）：`llm_service.py` 三个流式
  解析在重构中退回 `iter_lines(decode_unicode=True)`，llama.cpp 无
  charset 响应头再次导致中文乱码；改回显式
  `.decode('utf-8', errors='replace')` 并统一 `resp.encoding='utf-8'`，
  新增两个回归测试（error_reference 8.22 复发记录）；
- **会话历史体验**（`be1a78b`）：
  - 会话有新消息时自动置顶（`hdai.message.create` 刷新会话
    `write_date`，前端发送/编辑/重生成后重读列表）；
  - 会话行提示框显示消息数、输入/输出 tokens 与更新时间（绝对时间），
    行内保留消息数 + 相对时间副标题；
  - 用户消息右对齐、气泡品牌色背景白字，助手消息左对齐浅色背景——
    根因是消息样式仍挂在旧根类 `.o_hdai_chat` 下而重构后 DOM 根类为
    `.o_hdai_chat_window`，整段 CSS 被忽略；SCSS 根选择器改为双根兼容
    （error_reference 1.21）；
  - 清理 16 个测试阶段会话，历史仅保留空的「新会话」；
- 质量：当前 71 项离线测试全通过；验证用消息已清理，历史保持干净。

### 6.7 持续质量：HOOT 前端测试（C 档）

- 新增 `hdai_base/static/tests/`（通过 manifest `web.assets_unit_tests`
  注册）：
  - `hdai_formatted_text.test.js`：Markdown 渲染（标题/粗体/行内代码）、
    原始 HTML 消毒（script/事件属性不注入）、代码块复制/下载按钮、
    mermaid 降级为纯代码；
  - `hdai_chat.test.js`：会话消息渲染、状态栏消耗格式、会话行提示框
    统计、历史浏览（↑/↓ 与编辑退出浏览态）、`/` 命令面板过滤与 Tab
    补全、`/settings` 打开用户设置、编辑回车提交
    （`action_edit_and_resend`）、重新生成/重发动作调用；
- 运行方式：浏览器打开 `/web/tests`（可带 `?filter=hdai_base` 过滤），
  或由 CI 的 hoot runner 执行；HOOT 的 `fill` 作用于活动元素、
  `expect` 用 `toInclude`/`toHaveCount` 等匹配器、同步交互后需
  `animationFrame` 等待 OWL 重渲染（本模块测试已按此写法适配）；
- 结果：11 项 hdai_base 测试全部通过（整库 179 通过 / 5 失败，5 个失败
  均为 `@spreadsheet_dashboard` 移动端环境问题，与 hdai 无关）；
- 新增用户可见字符串按 error_reference 1.20 规范补 PO 词条。

### 6.8 A 档收尾：命令、知识库接入与数据清理（2026-08-18）

- **命令**：`/help` 显示可用命令帮助；`/export` 弹出 JSON/Markdown
  格式选择并直接下载当前会话；`/compact`、`/share` 维持占位；
- **知识库检索范围接入**（打通 P2 交付）：
  - `hdai.session` 新增 `knowledge_enabled` / `knowledge_top_k` /
    `knowledge_document_ids` 字段（随会话保存，经 `action_set_options`
    写入）；
  - 侧边栏「知识库选择」网格：开关 + 当前用户可见文档多选
    （`_knowledge_documents` 按权限过滤，`hdai_knowledge` 未安装时为空）；
  - 检索按所选文档范围过滤：`hdai.knowledge.chunk.action_search` 新增
    `document_ids` 参数（向量 + 关键词 SQL 均加 `document_id = ANY`）；
  - 注入：`_call_options(history)` 对最后一条用户消息
    `_knowledge_context(history)` 检索并把结果拼入系统上下文；
    同步（`_call_model`）与流式（控制器 `_call_options(history)`）
    两条路径都接入；
- **数据清理**：删除 9 个 Test Provider（vLLM，含其 usage 与级联模型），
  仅保留 Local llama.cpp 与 DeepSeek；乱码历史消息随会话清理已无残留；
- 验证：真实 llama.cpp 消息「费用报销有什么规定？请根据知识库回答。」
  回复明确引用《费用政策.pdf》；新增 3 项离线测试（document ids 解析、
  知识注入、权限列表）→ 72 项全通过。

## 7 P1-G6 服务端只读工具调用循环（2026-08-19）

按设计文档 2.3「混合执行模型」实现 `HdaiSession._run_tool_loop`：

- **双协议工具调用**：模型可通过 OpenAI 原生 `tool_calls`
  （`LLMService.chat_tools` 解析，OpenAI 兼容 / Ollama / DeepSeek
  Responses 均支持）或文本协议（`{"tool": ..., "params": ...}` 围栏
  JSON，供不支持原生工具参数的提供方兜底）发起调用；提供方拒绝 `tools`
  参数时自动降级重试一次；
- **JSON Schema 校验**：`hdai_tools.validate_tool_schema` 纯函数校验
  输入参数（type/properties/required/additionalProperties/items/enum/
  数值与长度边界/pattern），非法参数出 blocked 卡并回喂错误让模型修正；
- **混合执行**：只读工具（`read_only=True`）以调用用户身份经
  `hdai.tool.action_invoke_tool` 自动执行（含权限硬校验与
  `hdai.tool.log` 审计），结果回喂下一轮；写工具（`suggestive=True`）
  不执行，转为「建议卡」暂停循环等待用户确认；
- **终止与上限**：`__end_message` 提前终止；`hdai.max_successive_calls`
  （默认 10 轮）与 `hdai.max_tool_calls_per_call`（默认 10 个/轮）可在
  设置页配置，超限输出明确结束文案；
- **持久化与渲染**：`hdai.message` 新增 `tool_cards` Json 字段，每轮
  助手消息携带结构化工具卡；前端支持多卡渲染与「done」态摘要
  （执行过的只读工具显示结果摘要，不再提供 Execute 按钮）；
- **流式通道**：整个循环在请求阶段同步运行（ORM 全部在请求游标内），
  生成器只回放收集到的纯数据事件（`delta` / `reasoning_delta` /
  `tool_call` / `tool_card` / `limit` / `usage` / `done`），严格遵守
  经验库 2.3/2.4/2.6 的「生成器只调纯函数」红线。代价是首轮文本不再
  逐字实时渲染（改为循环完成后整轮回放）；如需保留首轮实时流式，可
  在后续迭代改为两阶段（首轮实时流 + 工具循环续跑端点）。

验证：67 项 hdai_base 离线测试全通过（含 8 项新增工具循环测试：
只读自动执行/建议卡暂停/上限终止/`__end_message`/Schema 拦截/权限拦截/
流事件纯数据）；本地 mock LLM（OpenAI 兼容）浏览器实测通过：发送
「Find the ACME partner」→ 原生工具调用 → 服务端自动执行
`generic.search_read`（审计落库）→ 结果回喂 → 最终回答渲染，零控制台
错误。

## 8 P1-G7 统一模型路由与能力检测（2026-08-19）

按设计 2.4 落地场景路由、能力元数据持久化与优先级故障转移：

- **场景路由**：`hdai.model._get_model_for_scenario(scenario)` 读取
  `hdai.route.<scenario>` 配置参数（chat / channel / summary / suggest /
  embed），未设置时回退全局默认模型；设置页「场景路由」块提供 5 个默认
  模型下拉，切换只改配置不改业务代码。chat（会话/托盘聊天）与 channel
  （`hdai.channel.operator` 频道回复）已接入；summary/suggest/embed 供
  `hdai_assistant` / `hdai_knowledge` 使用（helper 已就绪）；
- **能力检测持久化**：Provider「连接测试」与模型「测试连接」成功后把
  `supports_reasoning` / `supports_web_search` / `context_length` /
  `max_output_tokens` 写入模型记录（`list_models` 的启发式能力矩阵），
  已有模型也会更新；UI 选项收敛复用既有 `_allowed_options` +
  capabilities getter（无能力选项置灰并显示原因）；
- **优先级故障转移**：`_get_scenario_models(scenario)` 返回候选链
  （场景默认 → 全局默认 → 全部启用模型按 provider.priority 升序），
  `_run_tool_loop` 在 LLMError（含无工具参数重试失败）后沿候选链重试
  当前轮，并记录实际应答模型；
- **用量关联**：工具循环每轮写入 `hdai.usage`（request_type=chat，
  关联 session/user/provider/model/token），路由到哪个模型就以哪个模型
  记账。

验证：新增 5 项离线路由测试（场景默认解析、候选顺序、能力持久化、
故障转移换模型、usage 关联）→ 72 项全通过。

## 9 P1-G8 NL 开视图升级（2026-08-19）

按设计 3.2/3.3 升级自然语言开视图能力（全部在 `hdai_base` 内实现，
不再依赖 `lia_nlview`）：

- **搜索视图蓝图**：`hdai.nlview.model._search_blueprint(model_name)`
  解析模型的 search 视图（`searchable_fields` / `filters` /
  `groupbys`）并收集数值度量字段（`measures`）；
- **模型/菜单 CSV 注入**：`_nlview_prompt()` 把当前用户可读的白名单模型
  CSV（model/label/searchable/filters/groupbys/measures）拼入聊天系统
  提示词，让模型知道可开哪些视图、可筛/可组/可度量哪些字段；
- **`open_view` 工具**：以 `@ai_tool` 注册为只读工具，服务端校验白名单
  （`hdai.nlview.model`）、点号字段链禁止、分组/度量合法性（数值字段），
  返回带 `group_by` / `pivot_measures` 上下文的 act_window（Odoo search
  model 与 pivot 视图原生应用），写入 `hdai.action.log`；
- **bus 闭环与会话防串话**：执行成功后 `bus.bus._sendone(partner,
  'hdai_base/nlview', {session_id, action})`，前端 `bus_service`
  订阅并校验 `session_id === 当前会话` 才应用；工具循环把只读工具返回的
  action 作为 `action` 流事件直接下发，前端 `actionService.doAction`
  打开视图；
- **全链路只读**：无 create/write/unlink 路径，仅开视图 + 审计。

验证：新增 8 项离线测试 → 80 项全通过；Playwright 浏览器实测「Open the
partners list」→ mock LLM 返回 open_view 调用 → 服务端自动执行 →
Partners 列表在主页打开（标题 Partners opened by AI），零控制台错误。

## 10 模型配置页面与能力探测（2026-08-20）

按「模型能力 vs 开放权限」分离的配置模型落地：

- **能力探测（probe）**：`LLMService.probe_model_capabilities(model)`
  先做连通性测试，再以 plain-data 快照发起两项主动探测——思考链
  （`reasoning_strength=low`，按响应是否含 reasoning 内容判定）与联网
  搜索（`web_search=True`，按提供方是否接受请求判定；Ollama 本地提供方
  不探测、沿用元数据 False）；同时合并 `list_models` 元数据中的
  context_length / max_output_tokens；
- **模型测试连接**：`hdai.model.action_test_connection` 调用探测并把
  能力结果**程序化**写入 `supports_reasoning` / `supports_web_search`
  （及检测到的参数），权限字段不动；
- **能力字段只读保护**：`supports_*` 的 create/write 必须携带内部
  context `hdai_capability_probe`（由模型测试连接与 Provider 测试连接
  设置），否则抛 UserError——UI 上字段 `readonly="1"`，只能由程序自动
  修改；`allow_reasoning` / `allow_web_search` / `allow_streaming` 仍由
  管理员在「开放权限」区配置；
- **配置视图分区**：新增独立 `hdai.model` 列表/表单（HD AI → Model
  Configuration 菜单）：表单分「Model Capabilities」（只读能力字段）与
  「Open Permissions」（管理员开关）两区，header 提供 Test Connection
  按钮；Provider 表单 Models 页改为行点击打开模型配置页，不再内联编辑。

验证：新增 `test_model_capabilities.py`（探测落库、失败保留、能力字段
只写保护、_allowed_options 门控、Provider 测试连接走内部路径）。

## 11 模型能力三层模型与全面探测（2026-08-20）

按「能力层 / 权限层 / 会话层」三层落实模型能力配置：

- **能力层（程序自动设置）**：`supports_reasoning` / `supports_web_search`
  / `supports_streaming`（新增）三个能力字段，由测试连接探测结果自动
  写入，create/write 受 `hdai_capability_probe` 内部标记保护，UI 只读；
- **权限层（管理员设置）**：`allow_reasoning` / `allow_web_search` /
  `allow_streaming`，表单中按能力状态动态禁用
  （`readonly="supports_x == False"`），服务端 write 同步保证能力缺失时
  权限自动关闭；`_allowed_options` 按 能力 × 权限 求值；
- **会话层（用户设置）**：会话级 `reasoning_strength` /
  `web_search_enabled` / `streaming`（既有 `hdai.session.action_set_options`
  + 用户设置），只能在能力 × 权限允许的范围内选择；
- **测试连接全面评估**：`probe_model_capabilities` 依次做连通性、思考链
  （响应含 reasoning 内容）、联网搜索（请求被接受，Ollama 不探测）、
  流式（流式请求首个 chunk 无错误）四项探测，并合并 `list_models`
  元数据填充 `context_length` / `max_output_tokens`；Provider 测试连接
  （批量填模型）与模型配置页测试连接（单模型）都会读取元数据并回填；
- **测试连接后刷新**：模型页测试成功返回 `display_notification` +
  `next: reload`，前端自动重载表单，使能力字段与权限禁用状态即时更新。

验证：`test_model_capabilities.py` 扩充流式能力用例（探测落库、能力缺失
 自动禁用权限、`_allowed_options` 三门控、Provider 元数据回填）。

## 12 模型提供方推荐默认设置（2026-08-20）

`hdai.provider._TYPE_PRESETS` 为每种提供方类型内置推荐配置：

| 类型 | 推荐名称 | Base URL | API 协议 |
| --- | --- | --- | --- |
| deepseek | DeepSeek | https://api.deepseek.com/v1 | responses |
| vllm | vLLM (Local) | http://localhost:8000/v1 | chat_completions |
| ollama | Ollama (Local) | http://localhost:11434 | chat_completions |
| llamacpp | llama.cpp (Local) | http://localhost:8080/v1 | chat_completions |
| openai | OpenAI | https://api.openai.com/v1 | chat_completions |
| openai_compatible | OpenAI Compatible | （留空，按实际服务填写） | chat_completions |

行为：

- `create` 时仅填 `provider_type` 即自动补齐 name / base_url / api_type
  （显式传入的值优先，不被覆盖）；
- 表单切换 `provider_type` 时 `_onchange_provider_type` 自动填充推荐值，
  管理员可再修改；自定义的 name 在切换类型时保留；
- 运行时协议仍由 `LLMService` 按 provider_type / base_url / 请求选项
  自动决定（`api_type` 为配置层标注）。

验证：`test_provider.py` 新增 3 项测试（create 预设填充、显式值优先、
onchange 填充与 name 保留）。

## 13 元数据缺失回退与推荐默认值（2026-08-20）

测试连接对「上下文长度 / 最大输出 Token」的处理：

- **能探测则填充**：OpenAI 兼容 `/models` 的 `context_length` /
  `max_tokens` 或 `meta.*` 字段；Ollama 走 `/api/tags` + `/api/show`
  （`llama.context_length`）；llama.cpp 额外尝试 `/props` 的
  `default_generation_settings.n_ctx`（根路径与 `/v1` 前缀都试）；
- **探测不到则按提供方使用推荐默认值并提示**：Provider 测试连接不再把
  缺失值写成 0，而是回填 `LLMService._defaults_for_model(provider, code)`
  的推荐值（见第 14 节：按提供方档案 + 模型编码覆盖），通知追加
  「N 个模型未返回元数据，已按提供方使用推荐默认值…」；模型页测试连接
  由 `probe_model_capabilities` 同样回填并在通知中提示「提供方未返回
  元数据，已使用推荐默认值…，可在模型配置中调整」；
- 已有模型保留原值：探测/元数据缺失时不清空管理员已配置的值（仅修复
  历史写入的 0）。

验证：`test_provider.py` 增加缺失元数据用默认值用例；`test_llm_service.py`
增加 llama.cpp `/props` 探测与 `list_models` 回退用例；
`test_model_capabilities.py` 增加模型页缺失元数据回退与提示用例。

## 14 模型参数：采样参数与按提供方推荐默认值（2026-08-20）

模型配置页新增「Model Parameters」区（管理员配置，对话中直接生效），并按
提供方内置差异化的推荐默认值（官方文档核对的上下文 / 最大输出上限与采样
参数）：

### 14.1 模型参数字段（管理员）

- `temperature`（采样温度，0-2）、`top_p`（核采样，0-1）、`top_k`
  （候选 Token 数，0 表示提供方默认）——仅管理员在模型配置中设置，会话层
  不提供采样参数开关；
- `thinking_strength`（既有字段，作为该模型的默认推理强度）——新对话/
  新用户设置以此播种，用户在会话层仍可在允许范围内调整推理强度。

### 14.2 按提供方档案（`LLMService._PROVIDER_DEFAULTS`）

| 提供方档案 | 默认上下文 | 默认最大输出 | temperature | top_p | 兼容的采样参数 |
| --- | --- | --- | --- | --- | --- |
| deepseek | 128000 | 8192 | 1.0 | 1.0 | temperature / top_p |
| openai | 128000 | 16384 | 1.0 | 1.0 | temperature / top_p |
| zhipu（bigmodel） | 200000 | 128000 | 1.0 | 0.95 | temperature / top_p |
| moonshot（kimi） | 256000 | 16384 | 1.0 | 0.95 | 无（参数固定） |
| dashscope（qwen） | 131072 | 8192 | 0.7 | 0.8 | temperature / top_p |
| ollama | 32768 | 8192 | 0.8 | 0.9 | temperature / top_p / top_k |
| llamacpp | 32768 | 8192 | 0.8 | 0.95 | temperature / top_p / top_k |
| vllm | 32768 | 8192 | 1.0 | 1.0 | temperature / top_p / top_k |
| generic | 128000 | 8192 | 0.7 | 1.0 | temperature / top_p |

档案匹配按 `provider_type` + `base_url` 关键字（bigmodel/zhipu、moonshot/
kimi、dashscope/aliyun、deepseek、openai），因此 `openai_compatible` 端点
也能拿到各自的推荐值；`_PROVIDER_DEFAULTS['generic']` 作为最终兜底。

### 14.3 模型编码覆盖（`LLMService._MODEL_PREFIX_DEFAULTS`）

官方文档核对的云端模型规格，按代码前缀覆盖档案值（按列表顺序匹配）：

| 模型前缀 | 上下文 | 最大输出 |
| --- | --- | --- |
| deepseek-v4-* | 1M | 32768 |
| deepseek-chat / deepseek-reasoner | 128K | 8192 |
| deepseek-r1 | 64K | 8192 |
| gpt-5* | 400K | 128K |
| gpt-4.1* | 1,047,576 | 32768 |
| glm-5.2 | 1M | 128K |
| glm-5* | 200K | 128K |
| kimi-k2* | 256K | 16384 |
| moonshot-v1* | 128K | 8192 |
| qwen3-max | 256K | 64K |
| qwen-max | 32K | 8192 |

### 14.4 兼容性与请求行为

- **只发送提供方接受的采样参数**：`_sampling_params` 按档案的 `sampling`
  白名单过滤（如 Kimi 固定 temperature/top_p 则不发送；OpenAI 兼容端点
  不发送 top_k；Ollama/llama.cpp/vLLM 支持 top_k）；
- **取值来源**：`options` 优先，其次取模型字段（管理员配置）；探测用的
  `SimpleNamespace` 快照没有采样属性时安全跳过，不报错；
- **落点**：OpenAI 兼容协议放顶层 `temperature`/`top_p`；Ollama 原生协议
  放 `options`（`num_predict` + 采样）；DeepSeek Responses API 放
  `temperature`/`top_p`（`max_output_tokens` 参数名）；
- **创建即填默认值**：`hdai.model.create` 对未显式传入的
  `context_length` / `max_output_tokens` / `temperature` / `top_p` /
  `top_k` 按档案 + 编码自动填充（显式值优先）；
- **元数据缺失回退**：`probe_model_capabilities` 与 Provider 测试连接
  在提供方未返回 context/max-output 元数据时，用 `_defaults_for_model`
  的结果回填并提示，不再是统一的 128000/8192。

验证：`test_llm_service.py` 增加档案匹配、编码覆盖、payload 采样参数、
Ollama options、固定参数提供方跳过、快照兼容 6 项用例；
`test_provider.py` 更新缺失元数据用例并增加 deepseek-v4 编码默认值用例；
`test_model_capabilities.py` 增加创建填充默认值与探测回退默认值用例。
