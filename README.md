# automation-app-dianping

大众点评业务应用仓。基于 `automation-kit` 公共契约做顶层应用开发，不实现底层运行时。

- 应用开发基线：[docs/development-guide.md](docs/development-guide.md)
- 平台架构与公共契约：[automation-kit/docs/development.md](https://github.com/dengyie/automation-kit/blob/main/docs/development.md)

## 项目组成

- `automation_app_dianping/`：Python 应用层（config / workflow / composition / storage / services / live）
- `tests/`：默认离线测试
- `docs/platform-requests.md`：向底层提需清单
- `src/`：遗留 Bun/TS CLI（可修缺陷，不扩架构）
- `data/`：本地运行数据；敏感配置与会话默认不提交

## 应用层用法

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

视觉能力只通过公共契约请求：

```python
from automation_app_dianping.workflow import solve_android_screenshot_capability

result = await solve_android_screenshot_capability(
    capability_executor=composition.capability_executor,
    screenshot_bytes=image_bytes,
    run_id="run-1",
    task_id="task-1",
)
```

默认离线测试：

```bash
python -m pytest -q
```

## 遗留 TypeScript CLI

`src/` 仍保留历史半自动抓取/生成/发布命令，用于迁移期运营。按开发指南，该路径冻结架构扩张，新业务逻辑进入 Python 应用层。

## 特性

- 🔍 **智能抓取** - 自动抓取店铺信息、推荐菜、用户评价
- 🤖 **AI 生成** - 基于 Claude 4 生成真实自然的评价内容
- 📸 **照片管理** - 自动下载推荐菜照片，匹配评价内容
- 📋 **半自动发布** - 生成发布清单，App 内手动完成最后一步
- 📊 **进度追踪** - 查看评价进度和橙V认证状态

## 架构说明

由于大众点评的**写评价功能仅在 App 内可用**（PC 和 H5 移动端均无写评价入口），本工具提供两种方案：

### 方案 A：半自动化（推荐快速上手）

1. **自动化部分**：抓取店铺信息 → AI 生成评价 → 生成发布清单
2. **手动部分**：在大众点评 App 内按清单复制粘贴评价内容并发布

**优点**：无需配置，立即可用  
**缺点**：需要人工参与

### 方案 B：全自动化（Android App 自动化）

通过 Appium + Android 模拟器/真机，实现完全自动化发布。

**优点**：真正的自动化，支持批量发布  
**缺点**：需要配置 Android 环境

详见 [Android 自动化配置指南](docs/android-setup.md)

## 安装

```bash
# 安装依赖
bun install

# 配置账号（编辑 data/config.json）
{
  "account": {
    "username": "你的手机号/邮箱",
    "sessionFile": "data/sessions/mango.json"
  }
}
```

## 使用流程

### 1. 登录

```bash
bun run src/index.ts login
```

浏览器会打开大众点评登录页，扫码登录后会话自动保存。

### 2. 抓取店铺信息

```bash
bun run src/index.ts scrape <店铺URL> [店铺名]
```

示例：
```bash
bun run src/index.ts scrape "https://www.dianping.com/shop/H5ZxKG4hgGX3bdQt" "大宝口福"
```

输出：`data/scraped/H5ZxKG4hgG-20260613.json`

### 3. AI 生成评价

```bash
bun run src/index.ts generate <店铺URL> [店铺名]
```

AI 会根据抓取的信息生成自然的评价文本。

输出：`data/drafts/H5ZxKG4hgG-20260613.json`

### 4. 生成发布清单

```bash
# Markdown 格式（默认）
bun run src/index.ts prepare

# JSON 格式
bun run src/index.ts prepare --json

# 自定义输出路径
bun run src/index.ts prepare --output=my-checklist.md
```

输出示例（Markdown）：

```markdown
# 大众点评发布清单

## 1. 大宝口福·小金哥大排档·老江浙

**店铺链接**：https://www.dianping.com/shop/H5ZxKG4hgGX3bdQt
**评分**：⭐⭐⭐⭐⭐ (4.5)
**照片**：3 张

### 📝 评价内容
```
这家店的海鲜非常新鲜，特别是清蒸鲈鱼，肉质鲜嫩细腻...
```

### 📸 照片列表
1. `data/photos/H5ZxKG4hgG/dish1.jpg`
2. `data/photos/H5ZxKG4hgG/dish2.jpg`

### ✅ 操作步骤
1. 打开大众点评 App
2. 搜索店铺：**大宝口福·小金哥大排档·老江浙**
3. 点击"写评价"按钮
4. 选择评分：⭐⭐⭐⭐⭐
5. 复制上方评价内容，粘贴到评价框
6. 上传照片（从相册选择上述照片）
7. 点击发布
```

### 5. 在 App 内发布

**方案 A（半自动）：**
1. 打开生成的清单文件 `data/publish-checklist.md`
2. 按照每条评价的操作步骤，在大众点评 App 内手动完成发布
3. 将清单中的照片提前传输到手机（通过隔空投送/微信等）

**方案 B（全自动）：**

前置条件：
- 已安装 Android SDK 和模拟器（参见 [配置指南](docs/android-setup.md)）
- 模拟器中已安装大众点评 App 并登录
- Appium Server 已启动 (`bunx appium`)

```bash
# 自动发布单条评价
bun run src/index.ts app-publish mock-shop-001-20260613

# 指定设备
bun run src/index.ts app-publish mock-shop-001-20260613 emulator-5554
```

流程：
1. 连接 Appium
2. 启动大众点评 App
3. 搜索店铺 → 点击"写评价"
4. 填写评分、文本、上传照片
5. 提交并验证成功

### 6. 查看进度

```bash
bun run src/index.ts status
```

显示已发布评价数量和橙V认证进度。

## 批量处理

```bash
# 从 data/shops.txt 读取店铺列表，批量抓取+生成
bun run src/index.ts batch

# 或直接传入店铺列表
bun run src/index.ts batch "https://..." "店名1" "https://..." "店名2"
```

## 目录结构

```
data/
  config.json           # 配置文件
  shops.txt             # 店铺列表（每行一个URL或"URL 店名"）
  sessions/             # 登录会话
    mango.json          # PC端会话
    mango-mobile.json   # 移动端会话（如有）
  scraped/              # 抓取的原始数据
    H5ZxKG4hgG-20260613.json
  drafts/               # AI生成的评价草稿
    H5ZxKG4hgG-20260613.json
  photos/               # 下载的照片
    H5ZxKG4hgG/
      dish1.jpg
      dish2.jpg
  publish-checklist.md  # 发布清单（Markdown）
  publish-checklist.json # 发布清单（JSON）
```

## 环境要求

- Bun >= 1.0
- Chrome/Chromium 浏览器
- Claude API key（用于 AI 生成）
- **（可选）Android 环境**：
  - Android SDK
  - Android 模拟器或真机
  - Appium Server

## 常见问题

### Q: 为什么不能直接自动发布？

A: 大众点评的写评价功能**仅在原生 App 内可用**，PC 端和 H5 移动端网页均无写评价入口。Web 自动化无法触达该功能。

本工具提供两种方案：
- **半自动化**：生成清单，手动在 App 内发布（零配置）
- **全自动化**：通过 Appium 控制 Android App（需配置环境）

### Q: Android 自动化需要什么设备？

A: 支持以下设备：
- Android 模拟器（Android Studio AVD / Genymotion）
- 真实 Android 手机（通过 USB 或无线 ADB 连接）
- 云设备农场（如 AWS Device Farm / BrowserStack）

推荐使用真机，稳定性更好。

### Q: UI 元素选择器如何维护？

A: 大众点评 App 更新可能导致 UI 元素变化。维护方式：
1. 使用 Appium Inspector 查看最新元素结构
2. 更新 `src/app/selectors.ts` 中的选择器
3. 测试验证后提交更新

选择器已设计多重 fallback，提高容错性。

### Q: 遇到验证码怎么办？

A: 使用内置的 slidex 验证码求解器（基于 Python），会自动识别并完成滑块验证。首次运行 `check` 命令会自动安装。

### Q: AI 生成的评价质量如何？

A: 使用 Claude 4 Opus，结合店铺信息、推荐菜、真实用户评价生成，风格自然、内容真实。支持自定义 prompt 调整风格。

### Q: 如何避免被检测为批量操作？

A: 
- 使用真实浏览器指纹（Playwright Stealth）
- 随机延迟和人类化操作
- 分批发布，避免短时间大量评价
- 半自动化方案本身降低了风控风险

## 开发计划

- [x] PC Web 抓取店铺信息
- [x] AI 生成评价内容
- [x] 半自动化发布清单
- [x] Android App 自动化框架
- [ ] UI 元素适配（需要真机测试）
- [ ] 照片上传优化
- [ ] 批量发布命令适配 App
- [ ] 多账号管理
- [ ] 定时任务

## License

MIT
