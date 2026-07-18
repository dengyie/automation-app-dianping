# Android 自动化配置指南

## 环境准备

### 1. 安装 Android SDK

**macOS (Homebrew):**
```bash
brew install --cask android-commandlinetools
# 或使用 Android Studio
brew install --cask android-studio
```

**配置环境变量** (`~/.zshrc` 或 `~/.bash_profile`):
```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/tools:$PATH"
```

验证安装:
```bash
adb version
```

### 2. 安装 Android 模拟器

**选项 A: Android Studio AVD**
1. 打开 Android Studio → Tools → AVD Manager
2. Create Virtual Device
3. 选择设备型号（推荐 Pixel 5）
4. 选择系统镜像（推荐 Android 11/12）
5. 配置 RAM ≥2GB

**选项 B: Genymotion（更快）**
```bash
brew install --cask genymotion
```

### 3. 安装大众点评 App

**方法 1: 通过 APK 下载**
```bash
# 从应用商店或 APKPure 下载 com.dianping.v1.apk
adb install dianping.apk
```

**方法 2: Google Play（需要模拟器支持）**
在模拟器中打开 Play Store 搜索"大众点评"

### 4. 启动 Appium Server

```bash
bunx appium
```

默认监听 `http://127.0.0.1:4723`

## 测试连接

### 检查设备

```bash
# 列出已连接设备
adb devices

# 示例输出:
# emulator-5554   device
```

### 验证 App 安装

```bash
adb shell pm list packages | grep dianping
# 输出: package:com.dianping.v1
```

### 测试 Appium 连接

创建测试脚本 `test-appium.ts`:

```typescript
import { remote } from 'webdriverio';

(async () => {
  const driver = await remote({
    hostname: '127.0.0.1',
    port: 4723,
    capabilities: {
      platformName: 'Android',
      'appium:automationName': 'UiAutomator2',
      'appium:deviceName': 'emulator-5554',
      'appium:appPackage': 'com.dianping.v1',
      'appium:appActivity': 'com.dianping.main.guide.SplashScreenActivity',
      'appium:noReset': true,
    },
  });

  console.log('连接成功！');
  const title = await driver.getPageSource();
  console.log('页面源码长度:', title.length);

  await driver.deleteSession();
})();
```

运行:
```bash
bun run test-appium.ts
```

## 常见问题

### Q1: `adb: command not found`
确认 Android SDK 已安装，环境变量已配置。重新加载 shell 配置:
```bash
source ~/.zshrc
```

### Q2: Appium 无法连接设备
检查设备是否在线:
```bash
adb devices
```

重启 adb server:
```bash
adb kill-server
adb start-server
```

### Q3: 模拟器启动慢
- 启用硬件加速（HAXM/KVM）
- 增加模拟器 RAM (≥2GB)
- 使用 x86_64 镜像而非 ARM

### Q4: App 闪退或无法启动
检查 App 是否正确安装:
```bash
adb shell dumpsys package com.dianping.v1 | grep versionName
```

重新安装:
```bash
adb uninstall com.dianping.v1
adb install dianping.apk
```

### Q5: UI 元素找不到
使用 Appium Inspector 查看元素结构:
```bash
brew install --cask appium-inspector
```

连接到 `http://127.0.0.1:4723`，查看元素层级和属性。

## 性能优化

### 模拟器加速

**启用 HAXM (macOS Intel):**
```bash
brew install --cask intel-haxm
```

**启用 Hypervisor (macOS Apple Silicon):**
使用 Android Studio 自带的 ARM 镜像，自动利用 Hypervisor.framework

### 并发运行

每个模拟器实例占用 ~2GB RAM。多设备并发:

```bash
# 启动第二个模拟器
emulator -avd Pixel_5_API_31 -port 5556

# 测试连接
adb -s emulator-5556 shell
```

代码中指定设备:
```bash
bun run src/index.ts app-publish <草稿ID> emulator-5556
```

## 生产环境建议

- 使用真机而非模拟器（更稳定）
- 配置 ADB 无线连接（减少 USB 线缆依赖）
- 定期清理 App 缓存
- 监控设备存储空间
- 使用设备农场管理多台设备（如 OpenSTF）

## 下一步

配置完成后，运行第一次发布测试:

```bash
# 1. 确保 Appium server 已启动
bunx appium

# 2. 在另一个终端运行发布命令
bun run src/index.ts app-publish mock-shop-001-20260613
```

如果出现问题，检查 Appium server 日志输出。
