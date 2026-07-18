# automation-app-dianping

大众点评业务应用仓。基于 `automation-kit` 公共契约做**顶层应用开发**，不实现底层运行时。

- 应用开发基线：[docs/development-guide.md](docs/development-guide.md)
- 向底层提需：[docs/platform-requests.md](docs/platform-requests.md)
- 平台架构与公共契约：[automation-kit/docs/development.md](https://github.com/dengyie/automation-kit/blob/main/docs/development.md)

## 项目组成

| 路径 | 角色 |
| --- | --- |
| `automation_app_dianping/` | Python 应用层（config / workflow / composition / storage / services / live） |
| `tests/` | 默认离线测试 |
| `docs/development-guide.md` | 本仓唯一应用开发基线 |
| `docs/platform-requests.md` | 应用侧向底层提需清单 |
| `src/` | 遗留 Bun/TS CLI（可修缺陷，**不扩架构**） |
| `data/` | 本地运行数据；敏感配置与会话默认不提交 |

## 安装

### 正式依赖（推荐 / CI）

```bash
python -m pip install -e .
# 等价于消费发布元数据：
# automation-kit>=0.3.0,<0.4.0
```

`pyproject.toml` 的 `[project]` 段是发布真相源。
`[tool.poetry]` 里的 sibling path 只给本地 monorepo 开发用，**不是**发布依赖。

### 本地 monorepo 开发

```bash
# 需要本机已有 capability 矩阵的 automation-kit 检出
python -m pip install -e ../automation-kit
python -m pip install -e . --no-deps
python -m pip install "pytest>=8,<9" "pytest-cov>=5,<6"
```

可选视觉 provider：

```bash
python -m pip install -e ../slidex
```

## Python 应用层用法

### smoke workflow

```python
from automation_runner import WorkflowContext, WorkflowOptions
from automation_app_dianping.composition import build_composition, create_workflow_from_composition

composition = build_composition(enable_slidex=False)
workflow = create_workflow_from_composition(
    composition,
    session_factory=make_session,
    context=WorkflowContext(workflow_name="dianping-android", live=False),
    options=WorkflowOptions(app_id="com.dianping.v1", parameters={"mode": "smoke"}),
)
result = workflow.run()
```

### publish workflow（业务步骤 + 门禁）

```python
from automation_app_dianping.config import DianpingAppConfig
from automation_app_dianping.services import assert_publish_allowed, draft_to_publish_parameters
from automation_app_dianping.storage import DraftStore

draft = DraftStore("data").load("draft-id")
config = DianpingAppConfig(city="shanghai")
assert_publish_allowed(draft=draft, config=config, data_dir="data")

options = WorkflowOptions(
    app_id=config.app_id,
    parameters=draft_to_publish_parameters(draft),
)
```

publish 步骤优先声明平台语义动作 `rate` / `pick_photos`（见 REQ-001）；
未交付前仍附带通用 `tap` fallback，保证离线 fake session 可测。

### 视觉能力

只通过公共契约请求，不导入 slidex 内部：

```python
from automation_app_dianping.workflow import solve_android_screenshot_capability

result = await solve_android_screenshot_capability(
    capability_executor=composition.capability_executor,
    screenshot_bytes=image_bytes,
    run_id="run-1",
    task_id="task-1",
)
```

### Live E2E（opt-in）

默认关闭。授权真机/模拟器时：

```bash
export DIANPING_LIVE_E2E=1
```

详见 [docs/android-setup.md](docs/android-setup.md)。

## 测试

```bash
python -m pytest -q
```

- 默认完全离线
- live 路径显式 opt-in，不进默认门禁
- CI：Python 3.8 / 3.11


## 真机 / 模拟器 Live 运行

> 需要: export DIANPING_LIVE_E2E=1

1. pip install -e ".[live]"
2. adb devices && appium
3. python -m automation_app_dianping doctor
4. DIANPING_LIVE_E2E=1 DIANPING_DEVICE_UDID=emulator-5554 python -m automation_app_dianping live --mode smoke
5. DIANPING_LIVE_E2E=1 python -m automation_app_dianping live --mode publish --draft-id <id>

产物: artifacts/dianping-live/ ; 选择器: automation_app_dianping/config.py

最小真机建议：先 smoke，再无图 publish（默认跳过相册；需要时传 parameters.allow_photos=true）。失败会自动 dump screenshot/page_source 到产物目录。
## 遗留 TypeScript CLI

`src/` 仍保留迁移期半自动抓取 / 生成 / 清单命令。
按 [docs/development-guide.md](docs/development-guide.md)：

- 可修缺陷
- **禁止**继续扩张 Appium 生命周期 / provider 内部调用 / 第二套 runner
- 新业务逻辑只进 `automation_app_dianping/`

历史命令入口（迁移期）：

```bash
bun install
bun run src/index.ts login
bun run src/index.ts scrape <店铺URL> [店铺名]
bun run src/index.ts generate <店铺URL> [店铺名]
bun run src/index.ts prepare
bun run src/index.ts status
```

## 相关文档

- [应用开发指南](docs/development-guide.md)
- [平台需求清单](docs/platform-requests.md)
- [Android live 配置](docs/android-setup.md)
