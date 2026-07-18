# automation-app-dianping 应用开发指南

最后更新：2026-07-19

本文是点评应用仓库的唯一应用级开发基线。

- 平台架构、公共契约、跨仓版本矩阵与底层实现计划，只以 [automation-kit/docs/development.md](https://github.com/dengyie/automation-kit/blob/main/docs/development.md) 为准。
- 本仓只做顶层业务应用：点评配置、业务流程、选择器、业务验收、应用层测试。
- 本仓不实现、不复制、不分叉底层运行时、adapter、retry、report、artifact store、capability registry。
- 底层能力不足时，只通过同级 Codex 分支向 `automation-kit` / `slidex` 提需求，不在本仓私自补底层。

## 1. 定位

`automation-app-dianping` 是平台消费者，不是第二个自动化内核。

| 本仓拥有 | 本仓不拥有 |
| --- | --- |
| 点评业务配置与校验 | 执行内核与任务生命周期 |
| 点评 workflow 声明与业务步骤 | 通用 retry / timeout / report 实现 |
| 业务选择器、页面/App 路径、验收条件 | Appium / Selenium adapter 内核 |
| composition root 装配入口 | OCR / captcha / visual 算法 |
| 默认离线测试与 opt-in live E2E | 公共 capability 契约定义 |

本仓目标是：用 `automation-kit` 的公共契约，交付可测试、可发布、可替换 provider 的点评应用。

## 2. 真相源与文档边界

| 文档 | 角色 | 规则 |
| --- | --- | --- |
| `automation-kit/docs/development.md` | 平台唯一架构真相源 | 只读消费；不在本仓复制其内容 |
| `docs/development-guide.md`（本文） | 本仓唯一应用开发基线 | 只写应用边界、开发流程、门禁 |
| `README.md` | 安装与使用入口 | 不维护架构决策、阶段状态、跨仓计划 |
| `docs/android-setup.md` | live 环境操作说明 | 只写设备/Appium 操作，不定义架构 |
| `docs/development-log.md` | 历史遗留 | 停止维护；新变更不追加 |
| `AGENTS.md` / `CLAUDE.md` | 历史遗留 | 不得再扩展成第二套架构；后续只允许删除或改写为指向本文 |

禁止事项：

- 在 README / AGENTS / CLAUDE 中维护另一套平台架构。
- 在本仓新增 development-log、阶段计划、隐藏记忆文件。
- 把目标架构写成“已经实现”的现状。

## 3. 当前状态与目标状态

### 3.1 当前基线（已存在）

- Python 包骨架：`automation_app_dianping/`
- 最小 workflow：`launch_app` + `screenshot`
- 默认离线测试：不依赖浏览器、设备、网络、Slidex
- 遗留 TypeScript CLI：`src/`，包含抓取、生成评价、半自动发布、Appium 发布等旧路径

当前基线**不等于**目标架构。遗留 TS 路径可以继续运行，但不得继续扩张成长期主架构。

### 3.2 目标状态

1. 真实点评发布主路径落在 Python workflow，而不是旁路 TS 运行时。
2. 视觉能力只通过公共 capability 契约请求：`visual.challenge` / `solve`。
3. composition root 负责注册 provider、装配 runtime；workflow 只声明业务步骤。
4. 默认 CI 完全离线；live E2E 显式 opt-in。
5. 发布依赖使用正式版本范围，不把本地 sibling path 写进正式元数据。

## 4. 仓库结构

目标结构：

```text
automation-app-dianping/
  automation_app_dianping/
    __init__.py
    config.py              # 业务配置与校验
    workflow.py            # workflow factory 与能力请求组装
    composition.py         # composition root：registry / executor / runtime 装配
  tests/
    test_config.py
    test_workflow.py
    test_imports.py
    test_composition.py    # 可选：装配隔离与 provider 未安装路径
  docs/
    development-guide.md   # 本文
    android-setup.md       # live 操作说明
  README.md                # 安装与使用
  pyproject.toml
  .github/workflows/ci.yml
```

遗留路径（迁移期允许存在，禁止继续扩张）：

```text
src/                       # 旧 Bun/TS CLI
data/                      # 本地运行数据；默认不提交敏感配置与会话
AGENTS.md
CLAUDE.md
docs/development-log.md
```

规则：

- 新业务逻辑只进入 `automation_app_dianping/` 与对应测试。
- 新增 CLI 入口优先对接 Python workflow / composition root。
- 不得在 `src/` 再实现第二套 session 生命周期、retry、artifact、report 或 provider 注册。

## 5. 依赖与版本

| 依赖 | 角色 | 本仓约束 |
| --- | --- | --- |
| `automation-kit` | 必需公共平台 | 只依赖公共导出；当前消费 `>=0.2.0,<0.3.0` 语义 |
| `slidex` | 可选视觉 provider | 不得成为默认硬依赖；只在 composition root 装配 |
| Appium / 设备 / 浏览器 | live 依赖 | 默认测试与默认 CI 不得要求 |

依赖规则：

1. 业务模块 import 时不得创建浏览器、设备、线程、网络客户端、provider 实例。
2. 跨仓调用只依赖公共导出，不导入其他仓库内部模块、测试 fixture 或私有脚本。
3. 本地 sibling path 只允许开发态使用；正式元数据与 CI 验证以发布版本为准。
4. 本仓版本与平台消费版本分开：本仓发布自己的 app 版本，同时声明可消费的 kit 版本范围。

## 6. 分层职责

### 6.1 composition root

唯一装配入口。负责：

- 创建或注入 `CapabilityRegistry` / resolver / executor
- 选择是否注册 `SlidexVisualCapability`
- 创建 session factory 与 runtime / workflow factory 依赖
- 为测试提供可替换装配，不使用全局单例

### 6.2 workflow

只声明业务过程：

- 使用 `ManagedWorkflow` / `WorkflowStep.action(...)` / 未来的 `WorkflowStep.capability(...)`
- 接受注入的 `session_factory`、executor、options、context
- 返回平台 `WorkflowResult`，不自定义第二套生命周期字典

当前 V1 允许：

```python
def create_workflow(session_factory, context, options):
    ...
```

视觉能力在 V1 迁移期可以通过注入的 `capability_executor` 调用；不得直接持有 `visual_solver` 或 Slidex 内部类型。目标 V2 迁移后，能力调用进入 `WorkflowStep.capability(...)`。

### 6.3 config

只保存点评业务配置：

- app package / activity
- 业务参数与校验
- 发布限额、账号引用等业务策略

不得保存：

- 底层 retry 策略实现
- provider 内部配置协议
- 平台 report schema

### 6.4 测试

默认离线：

- fake session
- fake capability executor
- 不安装 Slidex 也能 import 与跑通主测试

opt-in live：

- 真实 Appium / 设备 / 账号
- 只在授权测试环境执行
- 不进入默认 CI

## 7. 能力调用规范

### 7.1 正确方式

业务代码只构造公共请求：

```python
CapabilityRequest(
    capability="visual.challenge",
    operation="solve",
    parameters={
        "challenge_type": "image_text",
        "context": "android_screenshot_bytes",
        "image_bytes": screenshot_bytes,
        "provider": "auto",
        "metadata": {"scene": "startup"},
    },
    metadata={"run_id": run_id, "task_id": task_id},  # V1 过渡字段
)
```

然后通过注入的 executor 执行：

```python
result = await capability_executor.aexecute(request)
```

### 7.2 禁止方式

- `from slidex.vision import ...`
- `from slidex.integrations... import ...`
- `python -m slidex.scripts...` 作为正式业务路径
- 直接调用 provider 内部 solver 类型
- 把 page / driver / token / cookie / raw bytes 写入公开 report

### 7.3 V1 到 V2 的过渡

| 阶段 | 允许 | 不允许 |
| --- | --- | --- |
| 当前迁移期 | helper 组装 `CapabilityRequest`，由注入 executor 执行 | 直接依赖 Slidex 内部类型 |
| 目标 V2 | `WorkflowStep.capability(...)` 进入 runtime | workflow 外手写第二套执行循环 |
| 任何阶段 | composition root 选择 provider | workflow 内部硬编码 provider 实现 |

## 8. 遗留 TypeScript 路径策略

`src/` 是历史产品路径，不是目标平台应用架构。

允许：

- 继续使用现有半自动清单、草稿、运营辅助命令
- 用文档标注“遗留 / 迁移中”
- 把可复用业务知识迁移进 Python workflow 与配置

禁止：

- 新增第二套 Appium 生命周期框架
- 新增直接 subprocess 调用 provider 内部脚本的正式入口
- 把 TS 路径写成平台标准架构
- 在 TS 中复制 Python runner 的 report / retry / artifact 语义

迁移顺序建议：

1. 先冻结 TS 架构扩张。
2. 把“发布主路径”迁到 Python workflow。
3. 再迁移抓取、生成、清单等辅助流。
4. 每迁一条路径，补离线测试与业务成功条件。

## 9. 向底层提需求的规则

本仓开发者不改底层，只提需求。

### 9.1 提需时机

出现以下任一情况时提需，而不是在本仓绕过：

- 公共契约缺少业务必需字段或 step 类型
- Appium adapter 动作不足以表达点评流程
- visual capability 上下文/结果不够用
- report / artifact / 事件无法关联业务结果
- 默认离线测试无法验证本应属于平台的行为

### 9.2 提需位置

在同级 Codex 分支 / 同级工作树中向底层仓库提：

- `automation-kit`：执行内核、runner、adapter 契约、report、公共 capability 协议
- `slidex`：视觉 provider 实现与公共适配

不要在本仓直接实现这些内容。

### 9.3 需求单最小模板

```markdown
## 背景
- 业务场景：
- 当前阻塞：

## 需要的公共能力
- 能力名 / 动作名：
- 输入：
- 输出：
- 失败语义：

## 为什么不能在 app 内解决
- 若 app 自己实现，会破坏哪条分层边界：

## 验收
- 离线测试应证明：
- live 测试应证明：
- 兼容约束：
```

## 10. 开发流程

每个应用任务按这个顺序推进：

1. **读边界**：确认改动属于业务配置 / workflow / 选择器 / 验收，而不是底层。
2. **先写失败测试**：覆盖业务成功条件与关键失败路径。
3. **最小实现**：只改应用层；依赖注入，不在 import 时创建外部资源。
4. **本地验证**：默认离线测试必须绿。
5. **文档同步**：只更新 README 使用说明或本文；不写开发日志。
6. **提需分流**：若被底层缺口挡住，停止应用层硬编码，改为同级分支提需。

提交规则：

- 一次提交只做一类边界内改动。
- 不把遗留 TS 大重构和 Python 契约迁移混在同一提交。
- 不把目标架构措辞写进“已完成”状态。

## 11. 测试与门禁

### 11.1 必过门禁

默认离线：

```bash
python -m pytest -q
```

至少覆盖：

- workflow 可在 fake session 下成功
- 未安装 Slidex 时包可 import
- capability helper 只构造公共 `CapabilityRequest`
- executor 缺失时返回安全空结果或明确失败，不抛内部 provider 异常伪装
- 配置校验拒绝非法业务输入

### 11.2 可选门禁

```bash
# 仅在本机或授权环境显式执行
# 真实 Appium / 设备 / 账号
```

live 测试必须：

- 默认跳过
- 失败不泄露凭据
- 结束后清理设备/会话资源

### 11.3 CI 期望

- Python 3.8 与 3.11 离线测试
- 不依赖真实设备、浏览器、账号
- 正式依赖路径验证优先于本地 path 依赖
- 不把 live E2E 放进默认 job

## 12. 当前优先级 backlog

只列应用仓应做的事：

1. **契约净化**：删除对 Slidex 内部类型的直接依赖，改为公共 capability helper。
2. **composition root**：增加唯一装配入口，provider 只在此处选择。
3. **文档收敛**：README 降为使用入口；停止维护 development-log / 重复架构说明。
4. **发布主路径迁移**：把 App 发布成功条件写入 Python workflow 与测试。
5. **遗留 TS 冻结**：`src/` 只修缺陷，不扩架构。
6. **版本与 CI 对齐**：app 版本与 kit 消费范围、离线矩阵与正式依赖策略对齐。

## 13. 验收清单

一个应用改动只有同时满足以下条件，才算完成：

- [ ] 没有新增底层运行时 / provider 内部依赖
- [ ] 业务逻辑位于 `automation_app_dianping/`
- [ ] 默认离线测试通过
- [ ] 真实设备路径仍是 opt-in
- [ ] README 未变成新的架构真相源
- [ ] 若依赖平台缺口，已在同级底层分支提交需求，而不是本仓绕过
- [ ] 提交说明清楚区分“已实现”和“仍待底层交付”

## 14. 给开发 agent 的最短指令

1. 你是点评应用 agent，不是 kit / slidex 实现 agent。
2. 先读本文，再读平台总纲；冲突时平台总纲管公共契约，本文管应用边界。
3. 只做顶层业务应用开发。
4. 底层不够用时，去同级 Codex 分支提需求。
5. 不要复制底层，不要维护第二套架构文档，不要扩张遗留 TS 架构。
