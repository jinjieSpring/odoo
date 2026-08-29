# Odoo19 AI 模块基础底座‑核心能力清单

> 
> 定位：作为 Odoo19 内部 AI 能力统一底座，供其他业务模块（销售、ERP、OA、MRP、CRM、单据处理等）直接调用，不做具体业务 AI 应用，只做通用抽象层、适配器、上下文管理、权限、日志、提示词管理、工具调用。适配 Odoo19 ORM、ir.model、多公司、多语言、审计日志、后台计划任务、web 前端组件。

## 一、大模型多后端适配器层（模型接入抽象）

1. **多厂商模型适配器抽象接口**
   - 统一抽象基类，定义标准方法：chat_completion、embedding、image_generate、audio_transcribe
   - 可插拔适配器：OpenAI 兼容接口、通义千问、文心一言、DeepSeek、本地 Ollama、私有化大模型
   - 支持每个适配器独立配置：api_key、endpoint、timeout、代理、是否启用
2. **模型池管理**
   - Odoo 配置模型存储模型信息：模型名称、类型 (聊天 / 嵌入 / 图像 / 语音)、所属适配器、最大上下文、默认参数 (temperature、top_p、max_tokens)
   - 支持设置**系统默认模型**，不同业务场景可指定专用模型
   - 模型可用性健康检测、连通性测试按钮
3. **请求参数标准化**
   - 屏蔽各厂商 API 参数差异，输入输出统一格式；原始厂商响应保留用于日志排查
   - 支持流式 / 非流式两种模式切换

## 二、Prompt（提示词）管理能力

1. **数据库存储可配置 Prompt 模板模型**
   - 字段：编码 key（供代码调用）、名称、描述、分类、系统提示词、用户模板、变量占位符`{{var_name}}`、默认参数、多语言版本、生效状态
   - 支持版本管理：修改自动保存版本，可回滚历史 prompt
   - 支持多公司隔离，不同公司可以使用不同 Prompt
2. **模板渲染引擎**
   - 传入 Odoo ORM 记录对象自动渲染变量，支持读取 record 字段、上下文字典
   - 支持直接在前端界面预览渲染效果
3. **Prompt 权限控制**：分组读写权限，普通业务不能随意修改核心提示词

## 三、RAG 知识库基础底座（检索增强生成）

1. **知识库管理模型**
   - 多知识库，支持多公司隔离；知识库绑定对应 Embedding 模型
   - 文档上传：PDF、docx、txt、markdown，附件复用 Odoo ir.attachment
2. **文档解析与分块**
   - 文档加载、文本提取；多种分块策略：固定长度、语义分块、标题分割
   - 文档状态：待解析、解析成功、解析失败、已向量化
3. **向量存储适配器**
   - 抽象向量库接口；支持 PGVector（Postgres 内置，Odoo 友好优先）、Chroma 等
   - 向量增删改查，文档删除自动清理向量
4. **检索能力**
   - 相似度检索、重排开关；返回分片原文、来源文档、页码
   - RAG 链路封装：输入 query，自动检索上下文，组装到 prompt，调用大模型

## 四、AI Function Calling / Agent 工具调用底座

> 
> Odoo 环境下 Agent 核心，让大模型可以调用 Odoo 自身 ORM、action、接口

1. **工具注册管理模型**
   - 在 Odoo 后台可注册 AI 工具：工具名称、描述、入参 JSON‑Schema、权限组、是否启用
   - 两种工具类型：Python 函数工具、Odoo ORM 动作（search/read/write/create）、外部 http 接口工具
2. **工具执行沙箱 & 权限校验**
   - 执行前校验当前 Odoo 用户权限：模型访问权限、记录规则 (multi‑record rule)、多公司规则
   - **禁止无限制执行任意 Python 代码**，所有工具必须预先注册，不能动态执行任意代码
3. **Agent 会话循环封装**
   - 自动处理大模型 tool_call → 执行工具 → 返回结果给大模型，多轮迭代
   - 限制最大迭代轮次，防止死循环
4. **工具调用日志：入参、返回值、耗时、异常全部留存**

## 五、会话与上下文管理

1. **AI 会话模型 `ai.chat.session`**
   - 绑定 Odoo 用户、多公司、关联业务单据（sale.order、account.move 等通用多态关联）
   - 会话消息持久化存储：角色 system/user/assistant/tool，消息内容、token 消耗、时间戳
2. **上下文窗口自动裁剪**
   - 根据模型 max_tokens 自动压缩历史消息，防止超限；支持摘要压缩策略
3. **会话隔离**：不同用户、不同单据会话互相隔离；遵循 Odoo 访问权限

## 六、统一日志、统计、监控审计

1. **AI 请求完整日志表 `ai.request.log`**
   - 记录：用户、公司、会话 ID、调用场景 key、使用模型、输入 prompt、输出结果、token 输入 / 输出、耗时、状态成功 / 失败、异常堆栈、RAG 检索片段、工具调用记录
   - 日志保留周期配置，自动归档清理
2. **用量统计看板**
   - 按模型、按用户、按业务场景统计 token 消耗、调用次数、失败率
   - Odoo 视图 / 仪表盘展示；可导出报表
3. **异常告警**
   - 大模型调用超时、限流、鉴权失败、错误率过高，触发 Odoo 通知 / 邮件告警
4. **合规审计：所有 AI 输入输出可追溯，满足企业审计要求**

## 七、安全、权限、多企业兼容（Odoo 企业核心）

1. **完整 Odoo 权限体系集成**
   - 安全组：AI 配置管理员、AI 普通使用者、仅可查看日志
   - ir.rule 多公司规则：模型配置、知识库、会话、日志全部支持 multi‑company，隔离不同公司数据
2. **输入输出安全防护**
   - 输入内容长度限制；可配置敏感词过滤（输入拦截、输出屏蔽）
   - 防止 Prompt 注入基础防护；禁止把敏感字段直接无条件传入大模型
3. **密钥安全存储**
   - API 密钥不直接存在普通 char 字段，使用 Odoo `fields.Char(password=True)`加密存储，不在界面明文回显
4. **速率限制 & 限流**
   - 全局 / 每个用户每分钟最大 AI 调用次数，防止大模型 API 超额扣费

## 八、后端 API 与服务层（供其他模块调用）

1. **Python 底层服务 API（供其他 Odoo 模块内部调用）**

```
self.env['ai.chat.service'].chat(...)
self.env['ai.chat.service'].rag_chat(...)
self.env['ai.chat.service'].embedding(...)
```

- 入参支持：prompt_key、record、context、stream、model_code

2. **JSON‑RPC 接口（前端 web 组件调用）**
   - 非流式、流式 SSE 接口；Odoo 标准 jsonrpc，继承 odoo 控制器
   - 会话创建、发送消息、获取历史
3. **计划任务支持**
   - 支持在 cron 任务中调用 AI 底座：批量文档解析、批量摘要、后台异步 AI 任务
4. **异步任务封装**
   - 长耗时 AI 任务（大文档解析、大 RAG 处理）接入 Odoo 异步队列，避免 web 请求超时；任务状态跟踪、失败重试

## 九、前端基础组件（Odoo Web 19）

1. **通用 AI 聊天对话框组件**
   - 可嵌入任意 Form 视图侧边 / 弹窗；绑定当前业务 record
   - 支持流式打字输出，显示引用 RAG 来源文档，展示工具调用过程
2. **字段 AI 增强小部件**
   - widget：针对 char/text/html 字段，一键 AI 生成 / 改写 / 翻译 / 摘要，复用地座能力，业务模块无需重写大模型调用逻辑
3. **底座后台配置视图**
   - 适配器配置视图、模型管理视图、Prompt 模板视图、知识库视图、日志统计看板

## 十、扩展钩子与集成规范

1. **ORM 事件钩子**：其他模块可监听 AI 请求前、请求后事件，做拦截、自定义处理
2. **可扩展事件：`on_ai_request_before` / `on_ai_request_done` / `on_ai_request_error`**
3. **开发文档注释：对外服务接口明确入参出参，示例代码，方便业务模块快速接入**

## 十一、非能力边界（底座不做）

- ❌ 不实现具体业务 AI（如销售写邮件、凭证 AI 识别、MRP 智能分析），留给上层业务模块
- ❌ 不实现复杂业务 Agent 逻辑，底座只提供通用 Agent 工具调用循环

---

# 建议模块目录结构参考（Odoo19）

```
ai_base/
├── models/
│   ├── ai_adapter.py          # 大模型适配器基类+各厂商实现
│   ├── ai_model.py            # 模型池配置
│   ├── ai_prompt_template.py  # prompt模板与渲染
│   ├── ai_knowledge_base.py   # RAG知识库、文档、分块
│   ├── ai_vector_store.py     # 向量存储抽象 PGVector实现
│   ├── ai_tool.py             # Agent工具注册
│   ├── ai_chat_session.py     # AI会话消息
│   ├── ai_request_log.py      # 请求日志审计
│   └── ai_chat_service.py     # 对话服务入口
├── controllers/               # jsonrpc + SSE流式接口
├── static/src/                # web聊天组件、widget
├── data/
├── security/                  # ir.model.access、record rules多公司
└── views/                     # 后台配置视图、看板
```