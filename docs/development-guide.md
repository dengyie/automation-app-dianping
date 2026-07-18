# automation-app-dianping 应用开发指南

最后更新：2026-07-19

本文是点评应用仓的唯一应用级开发基线。
平台公共契约、内核设计与跨仓版本策略，只消费
[automation-kit/docs/development.md](https://github.com/dengyie/automation-kit/blob/main/docs/development.md)
（若该文件尚未合入 `main`，以 `automation-kit` 最新架构分支中的同名文档为准）。

## 0. 一句话契约

本仓只做**基于 automation-kit 的顶层点评应用**。
不实现底层，不复制底层，不够用就去同级 Codex 分支向底层提需求。

给开发 agent 的最短指令：

1. 你是点评应用 agent，不是 kit / slidex 实现 agent。
2. 先读本文，再读平台总纲；公共契约冲突时服从总纲，应用边界冲突时服从本文。
3. 新代码只进 `automation_app_dianping/` 与对应测试。
4. `src/` 是遗留路径：可修缺陷，不扩架构。
5. 底层缺口写需求单，不在本仓私补 runtime / adapter / provider 内核。

## 1. 定位

| 本仓负责 | 本仓不负责 |
| --- | --- |
| 点评业务配置、校验、选择器 | 执行内核、任务生命周期 |
| workflow 业务步骤与成功条件 | retry / timeout / report 实现 |
| composition root 装配 | Appium / Selenium adapter 内核 |
| 默认离线测试与 opt-in live E2E | OCR / captcha / visual 算法 |
| 向底层提交能力需求 | 公共 capability 契约定义 |

本仓目标：用 `automation-kit` 公共契约交付可测试、可发布、可替换 provider 的点评应用。

## 2. 文档边界

| 文档 | 角色 | 规则 |
| --- | --- | --- |
| `automation-kit/docs/development.md` | 平台唯一架构真相源 | 只读消费，不复制到本仓 |
| `docs/development-guide.md`（本文） | 本仓唯一应用开发基线 | 只写应用边界、流程、门禁 |
| `README.md` | 安装与使用入口 | 不写架构决策和阶段状态 |
| `docs/android-setup.md` | live 操作说明 | 只写设备/Appium 操作 |
| `docs/development-log.md` | 历史遗留 | 停止维护 |
| `AGENTS.md` / `CLAUDE.md` | 历史遗留 | 不得再扩成第二套架构 |

禁止：

- 在 README / AGENTS / CLAUDE 再维护平台架构。
- 新增 development-log、阶段计划、隐藏记忆文件。
- 把“目标架构”写成“已经实现”。

## 3. 当前真相 vs 目标

### 3.1 当前真相（代码现状）

| 区域 | 现状 | 判定 |
| --- | --- | --- |
| `automation_app_dianping/workflow.py` | smoke + publish 步骤声明 | 发布主路径已进入 Python workflow |
| 视觉 helper | 公共 `CapabilityRequest` + 注入 executor | 已按契约净化 |
| composition root | `automation_app_dianping/composition.py` | 已提供唯一装配入口 |
| `src/` Bun/TS CLI | 抓取/生成等运营命令仍在此；发布门禁与清单已迁 Python | 遗留路径，架构冻结 |
| `pyproject.toml` | `0.2.0` + 正式版本范围声明，开发态 path 可选 | 版本与契约对齐中 |
| 默认测试 | 离线 pytest + coverage gate | 达标 |

### 3.2 目标状态

1. 点评发布主路径进入 Python workflow，业务成功条件由测试锁住。
2. 视觉能力只请求公共契约：`visual.challenge` / `solve`。
3. composition root 负责 registry / executor / provider 选择；workflow 只声明步骤。
4. 默认 CI 完全离线；live E2E 显式 opt-in。
5. 正式依赖使用版本范围，不把 sibling path 写进发布元数据。

当前基线不等于目标状态。未完成项只能写在 backlog，不能写成 done。

## 4. 目标仓库结构

```text
automation-app-dianping/
  automation_app_dianping/
    __init__.py
    config.py           # 业务配置与校验
    workflow.py         # workflow factory 与能力请求组装
    composition.py      # composition root
  tests/
    test_config.py
    test_workflow.py
    test_imports.py
    test_composition.py
  docs/
    development-guide.md
    android-setup.md
  README.md
  pyproject.toml
  .github/workflows/ci.yml
```

迁移期允许保留，但禁止继续扩张：

```text
src/                      # 旧 Bun/TS CLI
data/                     # 本地运行数据；敏感配置与会话默认不提交
AGENTS.md
CLAUDE.md
docs/development-log.md
```

规则：

- 新业务逻辑只进 `automation_app_dianping/` 与对应测试。
- 新 CLI 优先对接 Python workflow / composition root。
- 不得在 `src/` 再实现 session 生命周期、retry、artifact、report、provider 注册。

## 5. 依赖规则

| 依赖 | 角色 | 约束 |
| --- | --- | --- |
| `automation-kit` | 必需平台 | 只依赖公共导出；目标消费范围 `>=0.2.0,<0.3.0` |
| `slidex` | 可选视觉 provider | 默认非硬依赖；只在 composition root 装配 |
| 设备 / Appium / 浏览器 | live 依赖 | 默认测试与默认 CI 不得要求 |

硬约束：

1. import 时不创建浏览器、设备、线程、网络客户端、provider 实例。
2. 不导入其他仓库内部模块、测试 fixture、私有脚本。
3. sibling path 只用于本地开发；正式元数据与 CI 以发布版本为准。
4. app 版本与 kit 消费版本分开声明。

## 6. 应用层写法

### 6.1 composition root

唯一装配入口，负责：

- 创建/注入 registry、executor
- 决定是否注册 `SlidexVisualCapability`
- 提供 session factory 与 workflow 依赖
- 测试可替换装配，不用全局单例

workflow 模块不得自己 new 出 live provider。

### 6.2 workflow

只声明业务过程：

- 使用 `ManagedWorkflow` / `WorkflowStep.action(...)`
- V2 就绪后使用 `WorkflowStep.capability(...)`
- 接受注入的 `session_factory`、`capability_executor`、`context`、`options`
- 返回平台 `WorkflowResult`，不自造生命周期字典

当前 V1 factory 形状：

```python
def create_workflow(session_factory, context, options):
    ...
```

### 6.3 config

只放点评业务配置：

- app package / activity
- 业务参数与校验
- 发布限额、账号引用等业务策略

不放：

- 底层 retry 实现
- provider 内部协议
- 平台 report schema

### 6.4 能力调用

正确：

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

result = await capability_executor.aexecute(request)
```

禁止：

- `from slidex.vision import ...`
- `from slidex.integrations... import ...`
- `python -m slidex.scripts...` 作为正式业务路径
- 直接持有 provider 内部 solver 类型
- 把 page / driver / token / cookie / raw bytes 写入公开 report

过渡表：

| 阶段 | 允许 | 不允许 |
| --- | --- | --- |
| 当前迁移期 | helper 组装 `CapabilityRequest`，注入 executor 执行 | 直接依赖 Slidex 内部类型 |
| 目标 V2 | `WorkflowStep.capability(...)` | workflow 外第二套执行循环 |
| 任何阶段 | composition root 选择 provider | workflow 硬编码 provider 实现 |

## 7. 遗留 TypeScript 策略

`src/` 是历史产品路径，不是目标架构。

允许：

- 继续跑半自动清单、草稿、运营辅助命令
- 修缺陷
- 把业务知识迁到 Python workflow / config

禁止：

- 新增第二套 Appium 生命周期框架
- 新增正式的 provider 内部脚本调用入口
- 把 TS 写成平台标准架构
- 在 TS 复制 runner 的 report / retry / artifact 语义

迁移顺序：

1. 冻结 TS 架构扩张
2. 发布主路径迁到 Python workflow
3. 再迁抓取 / 生成 / 清单辅助流
4. 每迁一条路径，补离线业务成功条件测试

## 8. 向底层提需求

本仓开发者不改底层，只提需求。

提需时机：

- 公共契约缺字段或 step 类型
- Appium adapter 动作不够表达点评流程
- visual capability 上下文/结果不够
- report / artifact / 事件无法关联业务结果
- 本应属于平台的行为无法离线验证

提需位置：

- 同级 Codex 分支 / 工作树中的 `automation-kit`
- 同级 Codex 分支 / 工作树中的 `slidex`

需求单最小模板：

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
- 若 app 自己实现，会破坏哪条分层：

## 验收
- 离线测试应证明：
- live 测试应证明：
- 兼容约束：
```

## 9. 开发流程

1. **读边界**：只改业务配置 / workflow / 选择器 / 验收。
2. **先写失败测试**：锁业务成功条件与关键失败路径。
3. **最小实现**：只动应用层；依赖注入；import 不创建外部资源。
4. **本地验证**：默认离线测试必须绿。
5. **文档同步**：只更新 README 使用说明或本文；不写开发日志。
6. **提需分流**：被底层缺口挡住时，停止硬编码，改提需求。

提交规则：

- 一次提交只做一类边界内改动。
- 不把遗留 TS 大重构和 Python 契约迁移混提。
- 提交说明清楚区分“已实现”和“待底层交付”。
- 不在 `main` 直接开发；在功能分支完成后再合并。

## 10. 测试与门禁

必过：

```bash
python -m pytest -q
```

至少覆盖：

- fake session 下 workflow 成功
- 未安装 Slidex 时包可 import
- capability helper 只构造公共 `CapabilityRequest`
- executor 缺失时安全降级或明确失败
- 配置校验拒绝非法业务输入

live（opt-in）：

- 默认跳过
- 不进默认 CI
- 失败不泄露凭据
- 结束后清理会话/设备资源

CI 期望：

- Python 3.8 / 3.11 离线测试
- 无真实设备、浏览器、账号依赖
- 正式依赖路径优先于本地 path 依赖

## 11. 优先级 backlog

只做应用仓事项，按顺序：

1. **契约净化**：完成公共 capability helper 迁移。
2. **composition root**：完成唯一装配入口。
3. **文档收敛**：README / 遗留说明已指向应用开发指南。
4. **发布主路径迁移**：Python publish workflow、草稿/清单/限额门禁已落地；publish 已声明 `rate`/`pick_photos` 语义动作并带 tap fallback（REQ-001）；live selector 真机校准仍 opt-in。
5. **遗留 TS 冻结执行**：`src/` 架构扩张已冻结；业务知识已迁到 Python storage/services。
6. **版本与 CI 对齐**：app `0.2.0`、双 Python 离线 CI 已对齐；`[project]` 为发布真相源、Poetry path 仅本地；CI 用 `AUTOMATION_KIT_CAPABILITY_FALLBACK_REFS` 显式回退并在缺失时硬失败（REQ-003）。
7. **底层提需**：已在 `docs/platform-requests.md` 记录 adapter/capability/发布矩阵缺口。

## 12. 完成定义

一个应用改动同时满足以下条件才算完成：

- [ ] 没有新增底层运行时 / provider 内部依赖
- [ ] 业务逻辑位于 `automation_app_dianping/`
- [ ] 默认离线测试通过
- [ ] 真实设备路径仍是 opt-in
- [ ] README 没有变成新的架构真相源
- [ ] 若依赖平台缺口，已在同级底层分支提需求，而不是本仓绕过
- [ ] 提交说明区分“已实现”和“仍待底层交付”

## 15. 当前交付结论

应用仓侧文档要求已落地：

- 公共 capability 契约净化完成
- composition root 完成
- Python publish workflow + 草稿/清单/限额门禁完成
- 遗留 TS 架构冻结，业务知识已迁出到 Python storage/services
- 默认离线测试与双 Python CI 完成
- 底层缺口已写入 `docs/platform-requests.md`，不在本仓实现

仍依赖外部交付、不阻塞本仓完成判定：

- 真机 selector 校准（opt-in live）
- automation-kit 正式包源 capability 矩阵发布
