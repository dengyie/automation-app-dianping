> 历史遗留说明：本文件不再维护架构真相。应用开发以 `docs/development-guide.md` 为准，平台契约以 `automation-kit/docs/development.md` 为准。`src/` 为遗留路径，只修缺陷，不扩架构。

# 大众点评自动化评价工具

TypeScript + Bun CLI 工具，支持两种发布方式：
1. **半自动化**：生成清单 → 手动在 App 内发布
2. **全自动化**：通过 Appium + Android 模拟器/真机自动发布

## 架构

```
src/
├── index.ts              # CLI 入口，命令路由
├── cli/
│   ├── login.ts          # 扫码登录，保存 session
│   ├── check.ts          # 环境检查（浏览器/session/python/slidex）
│   ├── discover.ts       # 从收藏夹/浏览历史发现店铺
│   ├── scrape.ts         # 3 层策略抓取店铺数据
│   ├── generate.ts       # AI 生成评价 + 交互编辑
│   ├── prepare.ts        # 生成发布清单（Markdown/JSON）
│   ├── publish.ts        # 浏览器自动化发布（已废弃，H5无写评价入口）
│   ├── app-publish.ts    # Android App 自动化发布
│   ├── batch.ts          # 批量抓取+生成+发布（data/shops.txt）
│   └── status.ts         # 橙V 进度 + 草稿箱
├── browser/
│   ├── launch.ts         # 浏览器启动 + 反检测
│   ├── humanize.ts       # 自然行为模拟（鼠标/打字/滚动）
│   ├── captcha.ts        # 验证码检测 + slidex 集成
│   └── selectors.ts      # DOM 选择器集中管理
├── app/
│   ├── driver.ts         # Appium session 创建与管理
│   └── selectors.ts      # App UI 元素选择器
├── ai/client.ts          # DeepSeek API（Anthropic 兼容接口）
├── photo/
│   ├── local.ts          # 本地图片扫描
│   └── search.ts         # 百度图片搜索下载
├── storage/
│   ├── config.ts         # 配置管理（deepMerge + 默认值）
│   ├── drafts.ts         # 草稿 CRUD（原子写入 + .bak）
│   ├── history.ts        # 发布历史
│   └── state.ts          # 运行状态（每日计数/间隔）
└── utils/
    ├── delay.ts          # rand/sleep/jitter/chance
    ├── logger.ts         # 日志工具
    └── validate.ts       # 评价验证（≥100字/评分范围/非全5星）
```

## Pipeline

### 半自动化
```
login → scrape → generate → prepare → [手动在App内发布]
```

### 全自动化
```
login → scrape → generate → app-publish (Appium)
```

## 关键设计决策

- **大众点评 Web 限制**: PC 和 H5 移动端均无"写评价"入口，只能通过 App
- **两种发布方案**: 半自动化（零配置）和 Android 自动化（需 Appium）
- **反检测**: `--disable-blink-features=AutomationControlled` + navigator.webdriver=false
- **安全限制**: 每日 ≤2 条、间隔 ≥60 分钟、评分不全 5 星
- **存储**: JSON 文件，原子写入（tmp→rename），自动 .bak 备份
- **验证码**: 通过 slidex（Python）的 CDP 模式解决，不启动新浏览器

## Android 自动化

### 环境要求
- Android SDK
- Android 模拟器（AVD/Genymotion）或真机
- Appium Server (`bunx appium`)
- UiAutomator2 driver

### 工作流程
1. Appium 连接设备并启动大众点评 App
2. 检查登录状态
3. 搜索店铺 → 点击店铺卡片
4. 点击"写评价"按钮
5. 填写评价内容、设置评分
6. 上传照片（从本地推送到设备）
7. 提交并验证成功

### UI 选择器策略
- 使用 UiAutomator2 API (`android=new UiSelector()...`)
- 多重 fallback 机制（resourceId / text / description）
- 支持动态查找（基于文本内容）

## 验证码集成

slidex 通过 CDP 连接已有浏览器，处理全部滑块逻辑：

```
publish.ts 遇到验证码
  → captcha.ts detectCaptcha() 检测选择器
  → 获取 browser.wsEndpoint() (CDP WebSocket)
  → execFileSync('python3', ['-m', 'slidex.scripts.slide_solve_cdp',
      '--cdp-endpoint', ws, '--selectors', json])
  → slidex: 连接→检测→图像匹配→轨迹生成→执行滑动
  → 解析 JSON 结果 {success, elapsed_ms}
```

配置位于 `data/config.json` 的 `captcha.selectors`，默认按 GeeTest 设置。

## 运行

### 半自动化
```bash
bun run src/index.ts scrape <URL> [店名]
bun run src/index.ts generate <URL> [店名]
bun run src/index.ts prepare
# 然后在 App 内手动发布
```

### 全自动化
```bash
# 启动 Appium
bunx appium

# 另一个终端
bun run src/index.ts scrape <URL> [店名]
bun run src/index.ts generate <URL> [店名]
bun run src/index.ts app-publish <草稿ID> [设备ID]
```

## 环境变量

- `ANTHROPIC_BASE_URL` — AI API 地址（默认 https://api.anthropic.com）
- `ANTHROPIC_AUTH_TOKEN` — API 密钥
