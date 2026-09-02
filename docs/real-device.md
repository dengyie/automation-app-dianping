# 真机运行指南（Android）

> 本文记录在真实 Android 设备上跑通本项目 live 链路的全部前置与已知坑。
> 平台侧的 iOS 适配已在 automation-kit 0.4.0 的 Appium adapter 内（platform 感知手势），
> 但 iOS 需要额外的 Xcode + WebDriverAgent 签名，暂未纳入本指南。

## 一次性环境准备（Mac 侧）

| 组件 | 用途 | 安装 |
| --- | --- | --- |
| JDK 17+ | uiautomator2 server APK 签名 | `brew install --cask temurin` |
| adb | 设备通信 | `brew install android-platform-tools` |
| Appium + uiautomator2 driver | 自动化服务 | `npm i -g appium && appium driver install uiautomator2` |
| ANDROID_HOME | Appium 定位 adb | `mkdir -p ~/android-sdk/platform-tools && ln -s "$(readlink -f $(which adb))" ~/android-sdk/platform-tools/adb` |

Python 依赖（推荐 venv）：

```bash
python3 -m vvenv venv && source venv/bin/activate
pip install -e ".[live]"            # Appium-Python-Client + selenium
pip install -e ../automation-kit    # sibling 内核（CI 同款布局）
```

## 一次性设备准备

1. 设置 → 关于手机 → 连点「版本号」7 次 → 开发者选项 → 打开「USB 调试」。
2. 插线后通知栏把 USB 用途从「仅充电」切到「传输文件 (MTP)」。
3. 首次连接手机弹「允许 USB 调试吗？」→ 勾「一律允许」。
4. `adb devices -l` 出现设备且状态为 `device`（而非 `unauthorized`）。

## 已知坑（实踩记录）

| 症状 | 根因 | 处理 |
| --- | --- | --- |
| `Could not load driver 'uiautomator2' ... Cannot find module '.../appium/driver.js'` | 升级 Appium 后 `~/.appium` 里旧驱动依赖树损坏 | `appium driver uninstall uiautomator2 && appium driver install uiautomator2` |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package io.appium.settings signatures do not match` | 手机残留旧签名的 Appium 助手 app | `adb uninstall io.appium.settings io.appium.uiautomator2.server io.appium.uiautomator2.server.test`（Appium 会自动重装新版） |
| adb `settings put global hidden_api_policy*` exit 255，会话中止 | ColorOS/OnePlus 不接受链式 settings 命令 | 本仓 `create_appium_driver` 已默认设置 `ignoreHiddenApiPolicyError=true`（2026-09-03 起），无需手动处理 |

## 运行序列

```bash
# 1. 启动 Appium（ANDROID_HOME 指向含 platform-tools/adb 的目录）
ANDROID_HOME=~/android-sdk appium

# 2. 体检（另一个终端）：Appium 连通 + adb 可用
automation-app-dianping doctor

# 3. 业务冒烟：拉起大众点评、执行业务动作、产物落盘
automation-app-dianping live --mode smoke --udid <设备序列号>

# 产物：artifacts/dianping-live/<run>/ 下的 screenshot / ui_tree / 报告
```

环境变量（均可被 CLI flag 覆盖）：`DIANPING_DEVICE_UDID`、`DIANPING_APPIUM_HOST/PORT`、
`DIANPING_APP_ID`（默认 `com.dianping.v1`）、`DIANPING_APP_ACTIVITY`、`DIANPING_ARTIFACT_ROOT`。

### 平台级链路验证（可选，不经业务 app）

用 automation-kit 的通用 CLI 验证「任意 app 都能拉起 + 截图」：

```bash
automation-runner run damai-android-smoke --live --json \
  --factory factory:make_session --app-id com.android.settings \
  --report-file report.json
```

验收标准：`status=succeeded`，报告 artifacts 里的 PNG 是真机截图。
