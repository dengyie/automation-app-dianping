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
# automation-kit>=0.5.0,<0.6.0 + Pillow>=9,<13（照片管线需要 PIL）
```

`pyproject.toml` 的 `[project]` 段是发布真相源。
`[tool.poetry]` 里的 sibling path 只给本地 monorepo 开发用，**不是**发布依赖。

### 本地 monorepo 开发

```bash
# 需要本机已有 capability 矩阵的 automation-kit 检出
python -m pip install -e ../automation-kit
python -m pip install -e . --no-deps
# --no-deps 跳过 sibling kit 与 Pillow（后者是照片管线的运行时依赖）：
python -m pip install Pillow "pytest>=8,<9" "pytest-cov>=5,<6"
```

可选视觉 provider（钉 **slidex 0.6.3 / `288f554`**；PyPI 名已被无关 PPTX 库占用，必须 git pin）：

```bash
python -m pip install "slidex @ git+https://github.com/dengyie/slidex.git@288f554"
# 或 extra：python -m pip install -e ".[slidex]"
# 本地 sibling 开发（须与该 SHA 对齐）：python -m pip install -e ../slidex
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
> 生产发布走 `DIANPING_DRIVER=uia2`（勿用 Appium 发布流，会楔死 UiAutomation）。未设置时默认 uia2；`live --mode publish` fail-closed，显式传 Appium 直接报错。

1. pip install -e ".[live]"
2. adb devices
3. python -m automation_app_dianping doctor
4. DIANPING_LIVE_E2E=1 DIANPING_DRIVER=uia2 DIANPING_DEVICE_UDID=<udid> python -m automation_app_dianping live --mode smoke
5. DIANPING_LIVE_E2E=1 DIANPING_DRIVER=uia2 python -m automation_app_dianping live --mode publish --draft-id <id>

产物: artifacts/dianping-live/ ; 选择器: automation_app_dianping/config.py

风控滑块：`--enable-slidex` 为 Appium 与 uia2（生产驱动）两条会话路径都挂上 slidex 纯图像求解器。滑块出现时守卫自动完成「截图→求解→拖动→重试动作」；检测以页面结构为准（`滑块`/`nc_1_wrapper` 等标记），无滑块不触发。未装 slidex 或求解失败时动作确定性失败并保留截图/page_source 证据。

最小真机建议：先 smoke，再带图 publish。默认图是 `artifacts/gni2_pulled.jpg`（`default_review_photos()`），空 / 省略 `photos` 仍走这张，登台到 `Pictures/DianpingAuto` 后再勾选；**唯一跳过带图的开关是 `parameters.allow_photos=false`**。禁止点 Camera / 「最近项目」（格 0 是私图）。失败会自动 dump screenshot/page_source 到产物目录。

### 图片来源优先级（`photos.py` `resolve_review_photos`）

发布时（`live.py` `build_live_workflow`）对照片列表按以下链路解析，仅当「未显式指定非默认照片」时介入：

1. **最新搜到的图**：`data/photos/<店铺 slug>/` 下按 mtime 最新（`_latest_staged_photos`），存盘的最佳照片天然排最前 → 落进 `photos` 参数。
2. **生图**：无已存图时调 CPA `gpt-image-2` `POST /images/generations`（`imagegen.py generate_review_photo`）写出一张 PNG 到 `data/photos/<slug>/`。best-effort：无 `DIANPING_CPA_API_KEY` 或请求失败 → 打印跳过、返回 `None`，绝不阻塞发布。
3. **兜底默认图**：`default_review_photos()`。

已显式指定的自定义照片（非默认路径）保持不动；`DIANPING_PHOTO_RESOLVE=0` 可固定走默认图。生成图会写进 `data/photos/<slug>/`，故下一次解析自动视作「最新搜到的图」，无需重复生成。此链路只产出**宿主机路径**，登台进 `Pictures/DianpingAuto`、禁止 Camera/「最近项目」的约束完全不变。

生图凭据：CLI 启动时读取仓库根 `.env`（`env.py` `load_dotenv`，gitignore 内），也可直接 `export DIANPING_CPA_API_KEY=sk-...`（已存在的环境变量优先，不被 `.env` 覆盖）；`.env.example` 是字段清单。key 不入库。`data/photos/<slug>/` 与 `fail-*.{xml,png}` 已在 `.gitignore`，店铺照片与失败转储只留本地。

网关在 Cloudflare 后：请求必须带浏览器 `User-Agent`（`imagegen.py` 内置），否则拿 CF `1010`；`/images/generations` 可能返回 `524`（origin 超时）但 body 里已带图 —— 先解码 body 当成功处理，失败才重试/回落。

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
