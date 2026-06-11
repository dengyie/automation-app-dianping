# 大众点评自动化评价工具

TypeScript + Bun CLI 工具，通过 Playwright 控制 Chrome 完成大众点评评价自动化。

## 架构

```
src/
├── index.ts              # CLI 入口，命令路由
├── cli/
│   ├── login.ts          # 扫码登录，保存 session
│   ├── discover.ts       # 从收藏夹/浏览历史发现店铺
│   ├── scrape.ts         # 3 层策略抓取店铺数据
│   ├── generate.ts       # AI 生成评价 + 交互编辑
│   ├── publish.ts        # 6 阶段模拟真人发布
│   ├── batch.ts          # 批量抓取+生成+发布（data/shops.txt）
│   └── status.ts         # 橙V 进度 + 草稿箱
├── browser/
│   ├── launch.ts         # 浏览器启动 + 反检测
│   ├── humanize.ts       # 自然行为模拟（鼠标/打字/滚动）
│   ├── captcha.ts        # 验证码检测 + slidex 集成
│   └── selectors.ts      # DOM 选择器集中管理
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

```
login → scrape → generate → publish → status
                  batch (批量: scrape+generate+publish)
```

## 关键设计决策

- **反检测**: `--disable-blink-features=AutomationControlled` + navigator.webdriver=false
- **安全限制**: 每日 ≤2 条、间隔 ≥60 分钟、评分不全 5 星
- **存储**: JSON 文件，原子写入（tmp→rename），自动 .bak 备份
- **验证码**: 通过 slidex（Python）的 CDP 模式解决，不启动新浏览器

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

```bash
bun run src/index.ts login
bun run src/index.ts scrape <URL> [店名]
bun run src/index.ts generate <URL> [店名]
bun run src/index.ts publish <草稿ID>
bun run src/index.ts status
```

## 环境变量

- `ANTHROPIC_BASE_URL` — AI API 地址（默认 https://api.anthropic.com）
- `ANTHROPIC_AUTH_TOKEN` — API 密钥
