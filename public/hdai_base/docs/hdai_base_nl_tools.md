# HD AI 自然语言工具清单与调用方法（hdai_base）

> 本文档是 `hdai` 系列模块当前已实现 NL 工具（`@ai_tool` 注册表）的**实现
> 清单与调用指南**；工具元数据、接口与治理规范见
> [hd_ai_std_001_ai_tool_dev_spec.md](../../docs/hdai/hd_ai_std_001_ai_tool_dev_spec.md)
> （HD-AI-STD-001）。模块文档与源码冲突时以 `source/` 源码为准。

## 1 概述

所有 NL 工具统一注册在 `hdai.tool` 注册表中：

- 声明方式：`@ai_tool(...)` 装饰器（[hdai_tool.py](../../hdai_base/models/hdai_tool.py:20)）
  注册到 `AI_TOOL_REGISTRY`，服务启动 / 模块更新时由 `_register_hook` 调
  `_sync_registry` 自动同步进 `hdai.tool` 表（[hdai_tool.py:118](../../hdai_base/models/hdai_tool.py:118)）；
- 权限模型：`hdai_group_user`（使用对话并调用通用只读工具）、
  `hdai_group_manager`（配置 Provider / 管理工具注册表），管理员隐含 manager；
  `required_permissions` 未满足的工具不会出现在给模型的 manifest 中
  （`action_get_manifest_for_user`，[hdai_tool.py:197](../../hdai_base/models/hdai_tool.py:197)）；
- 执行红线：工具框架只读（`read_only=True`）或建议（`suggestive=True`），
  没有 create/write/unlink 路径；每次调用经统一入口校验、限流并写入
  `hdai.tool.log` 审计（append-only）。

## 2 已实现的工具清单

共 11 个工具，分 4 类来源。`只读` = 工具循环自动执行并回喂结果；
`suggestive` = 只返回 `suggestion_preview` / 建议卡，暂停循环等待用户确认，
绝不自动写库。

### 2.1 hdai_base：通用数据查询（generic）

来源：[hdai_generic_tools.py](../../hdai_base/models/hdai_generic_tools.py:111)。

| 工具名 | 作用 | 模式 | 关键约束 |
| --- | --- | --- | --- |
| `generic.search_read` | 任意模型按 domain 搜索并返回字段（分页） | 只读 | 字段白名单 + 敏感字段剥离（password/api_key/credit_card/bank_account/id_number/secret）；limit 默认 100、最大 500 |
| `generic.search_count` | 统计任意模型匹配 domain 的记录数 | 只读 | domain 仅允许简单三元组与白名单运算符 |
| `generic.group_by` | 按字段分组聚合（sum/avg/min/max/count/count_distinct/bool_and/bool_or） | 只读 | groupby 与聚合字段必须是模型现有字段，聚合器白名单校验 |

三者均以调用者身份执行，ORM ACL 与记录规则生效，domain 经 `_safe_domain`
校验（防注入），输出带 `source_type: "database"`。

### 2.2 hdai_base：NL 打开视图（open_view）

来源：[hdai_nlview_model.py:214](../../hdai_base/models/hdai_nlview_model.py:214)。

| 工具名 | 作用 | 模式 | 关键约束 |
| --- | --- | --- | --- |
| `open_view` | 把自然语言请求转成打开白名单模型的 list/kanban/pivot/graph 视图，可带 domain、group_by、measures | 只读 | 模型必须加入 `hdai.nlview.model` 白名单；非 transient/abstract；`check_access('read')`；返回 `ir.actions.act_window` 并经 bus（`hdai_base/nlview`）推送前端应用，同时写 `hdai.action.log` |

### 2.3 hdai_assistant：决策建议（generic）

来源：[hdai_assistant_suggest.py:25](../../hdai_assistant/models/hdai_assistant_suggest.py:25)。

| 工具名 | 作用 | 模式 | 关键约束 |
| --- | --- | --- | --- |
| `generic.suggest_update` | 生成结构化“修改建议预览”（模型、记录 id、字段值、理由、幂等键） | suggestive | 校验目标记录存在与读权限；不写库 |

### 2.4 hdai_agent_hr：HR 工具

来源：[hdai_agent_hr_tools.py](../../hdai_agent_hr/models/hdai_agent_hr_tools.py:25)。

| 工具名 | 作用 | 模式 |
| --- | --- | --- |
| `hr.screen_applicants` | 按姓名/岗位/部门/阶段/优先级筛选候选人 | 只读 |
| `hr.analyze_workforce` | 部门人数聚合 + 近期入职分析 | 只读 |
| `hr.suggest_training` | 按部门/司龄推荐培训主题（仅预览） | suggestive |

### 2.5 hdai_agent_project：项目工具

来源：[hdai_agent_project_tools.py](../../hdai_agent_project/models/hdai_agent_project_tools.py:32)。

| 工具名 | 作用 | 模式 |
| --- | --- | --- |
| `project.analyze_progress` | 任务状态统计、完成率、逾期任务 | 只读 |
| `project.risk_warning` | 逾期 / 临近截止的高优先级任务预警 | 只读 |
| `project.suggest_task_allocation` | 按工作量给出任务分配建议（仅预览） | suggestive |

## 3 调用方法

### 3.1 经 LLM 调用（工具循环，正常对话路径）

对话发送时（同步 `action_send_message` 或流式 `/hdai_base/chat/stream`），
`_run_tool_loop`（[hdai_session.py:960](../../hdai_base/models/hdai_session.py:960)）
执行混合执行模型：

1. manifest：`hdai.tool.action_get_manifest_for_user()` 按当前用户权限过滤后，
   `_function_schemas` 转成 OpenAI `tools` 函数定义
   （[hdai_tool.py:238](../../hdai_base/models/hdai_tool.py:238)），随
   `options['tools']` 传给 `LLMService.chat_tools`；
2. 双协议调用：模型可用原生 `tool_calls`，也可用文本协议
   `{"tool": "<name>", "params": {...}}` 围栏 JSON 兜底
   （`extract_tool_calls`，[hdai_tools.py:152](../../hdai_base/models/hdai_tools.py:152)）；
3. 校验与执行（`_execute_loop_call`，[hdai_session.py:1290](../../hdai_base/models/hdai_session.py:1290)）：
   - 未注册工具 / 无权限 → `blocked` 卡片（未注册提示管理员，无权限提示用户）；
   - `validate_tool_schema` 校验参数（[hdai_tools.py:189](../../hdai_base/models/hdai_tools.py:189)），
     失败 → `invalid` 卡片；
   - `suggestive` 工具 → `ready` 建议卡，**暂停循环**；
   - `read_only` 工具 → `action_invoke_tool` 自动执行，结果回喂下一轮
     （`_tool_result_message` 追加到 history），执行过的工具卡前端显示
     `done` 摘要；
4. 循环护栏：默认最多 10 轮（`hdai.max_successive_calls`）、每轮最多 10 次
   调用（`hdai.max_tool_calls_per_call`），超限输出 `limit` 提示。

### 3.2 程序化调用（统一入口）

所有工具（含 MCP）最终都走
`hdai.tool.action_invoke_tool(tool_name, params, context=None)`
（[hdai_tool.py:260](../../hdai_base/models/hdai_tool.py:260)）：

```python
result = env['hdai.tool'].action_invoke_tool(
    'generic.search_count',
    {'model': 'res.partner', 'domain': [['is_company', '=', True]]},
    context={'session_id': session.id},
)
```

执行顺序：注册检查（未注册 404）→ 权限检查（无权限 421）→ 限流检查
（60 秒滑动窗口，默认 30 次/分钟，超限 429）→ 以调用者身份执行（ORM
ACL / 记录规则生效）→ 写入 `hdai.tool.log` 审计。

成功返回（统一结构）：

```json
{
  "status": "success",
  "message": "Found 3 matching records.",
  "data": {"records": [...], "total_count": 3, "offset": 0, "limit": 100},
  "execution_time_ms": 12
}
```

失败返回：`{"status": "error", "code": <int>, "message": "...", "data": {}}`，
错误码 404（未注册）/ 421（无权限）/ 429（限流）/ 500（执行失败）。
`suggestive` 工具额外返回 `suggestion_preview`（operation/model/record_id/
fields_to_update/reason/idempotency_key）。

### 3.3 经 MCP 暴露

`hdai_mcp` 的 JSON-RPC 服务（[hdai_mcp_server.py:127](../../hdai_mcp/models/hdai_mcp_server.py:127)）
镜像同一注册表：

- `tools/list`：只返回 `read_only=True` 且非 suggestive 的工具
  （以配置用户身份过滤 manifest）；
- `tools/call`：校验工具名后以配置用户身份调 `action_invoke_tool`，全程审计。

### 3.4 经 Odoo RPC 调用

工具方法可通过标准 `execute_kw` 调用（需对 `hdai.tool` 有调用权限的用户）：

```python
models.execute_kw(
    db, uid, password, 'hdai.tool', 'action_invoke_tool',
    ['generic.search_count', {'model': 'res.partner'}],
)
```

## 4 权限、审计与治理

- **权限**：工具 manifest 已按 `required_permissions` 过滤，未授权工具不会
  出现在模型提示中；执行时再次硬校验；调用以真实用户环境运行，ORM 规则
  兜底；
- **审计**：每次调用写 `hdai.tool.log`（append-only，`sudo()` 写入，无 ACL
  授权写/删）；`open_view` 额外写 `hdai.action.log`；
- **治理**：`hdai_governance` 基于 `hdai.tool.log` / `hdai.usage` 做离线回放
  评估（成功率、耗时、错误码）与 Golden Set 回归（`hdai.evaluation.case`
  逐例调 `action_invoke_tool` 比对期望）。

## 5 新增工具指引

1. 在任意已安装的 `hdai_*` 模块 `models/` 下新建 `AbstractModel`，方法加
   `@ai_tool` 装饰器，填写 name/description/input_schema/output_schema/
   category/scope/suggestive/required_permissions/rate_limit/timeout；
2. 重启服务或 `-u <module>` 后 `_sync_registry` 自动建/更新 `hdai.tool`
   记录；工具可加入 `hdai.tool.package`（种子包见各模块 `data/*.xml`）；
3. 只读红线：实现内不得出现 create/write/unlink；`suggestive=True` 只返回
   `suggestion_preview`，写操作由前端确认后执行；
4. 描述等用户可见字符串需同步补 `i18n/zh_CN.po`（`odoo-python` 标记 +
   `code:addons/<module>/models/...:行号`）；
5. 测试：按 [test_tool_loop.py](../../hdai_base/tests/test_tool_loop.py)
   模式 mock LLM Provider，覆盖正常执行、越权 421、schema 无效、限流与
   suggestive 不写库。

## 6 关联文档

- 工具开发规范与接口标准：`docs/hdai/hd_ai_std_001_ai_tool_dev_spec.md`
- 工具循环与流式实现：`hdai_base/docs/hdai_base_phase1.md`（P1-G6 一节）
- 知识库 / 治理：`docs/hdai/hd_ai_std_002_data_governance_knowledge_spec.md`、
  `docs/hdai/hd_ai_std_003_ai_operations_spec.md`
