import { remote, type RemoteOptions } from 'webdriverio';
import type { AppConfig } from '../storage/config.js';
import { info, error } from '../utils/logger.js';

export interface AppSession {
  driver: WebdriverIO.Browser;
  deviceInfo: {
    platform: string;
    version: string;
    udid: string;
  };
}

/**
 * Create Appium session for Dianping App
 */
export async function createAppSession(config: AppConfig, deviceUdid?: string): Promise<AppSession> {
  const capabilities: RemoteOptions['capabilities'] = {
    platformName: 'Android',
    'appium:automationName': 'UiAutomator2',
    'appium:deviceName': deviceUdid || 'emulator-5554',
    'appium:udid': deviceUdid,
    'appium:appPackage': 'com.dianping.v1',
    'appium:appActivity': 'com.dianping.main.guide.SplashScreenActivity',
    'appium:noReset': true, // Keep app data (login session)
    'appium:fullReset': false,
    'appium:newCommandTimeout': 300, // 5 minutes
    'appium:autoGrantPermissions': true,
    'appium:disableIdLocatorAutocompletion': true,
    'appium:ensureWebviewsHavePages': true,
    'appium:nativeWebScreenshot': true,
    'appium:connectHardwareKeyboard': true,
  };

  info('连接 Appium...');
  const driver = await remote({
    protocol: 'http',
    hostname: '127.0.0.1',
    port: 4723,
    path: '/',
    capabilities,
    logLevel: 'error',
  });

  info('获取设备信息...');
  const platform = await driver.getPlatform();
  const version = await driver.getDeviceTime();
  const udid = deviceUdid || 'emulator-5554';

  info(`已连接设备: ${platform} ${version} (${udid})`);

  return {
    driver,
    deviceInfo: { platform, version, udid },
  };
}

/**
 * Close Appium session
 */
export async function closeAppSession(session: AppSession): Promise<void> {
  try {
    await session.driver.deleteSession();
    info('已关闭 Appium session');
  } catch (err) {
    error(`关闭 session 失败: ${err}`);
  }
}

/**
 * Check if Dianping app is installed
 */
export async function isDianpingInstalled(driver: WebdriverIO.Browser): Promise<boolean> {
  try {
    const installed = await driver.isAppInstalled('com.dianping.v1');
    return installed;
  } catch {
    return false;
  }
}

/**
 * Launch Dianping app
 */
export async function launchDianping(driver: WebdriverIO.Browser): Promise<void> {
  info('启动大众点评 App...');
  await driver.execute('mobile: activateApp', { appId: 'com.dianping.v1' });
  await driver.pause(3000);
}

/**
 * Check if user is logged in (by checking if home page shows user avatar)
 */
export async function isLoggedIn(driver: WebdriverIO.Browser): Promise<boolean> {
  try {
    // Look for common indicators: avatar, "我的" tab with username
    const avatarSelectors = [
      'android=new UiSelector().resourceId("com.dianping.v1:id/avatar")',
      'android=new UiSelector().description("我的").className("android.widget.TextView")',
      '~我的',
    ];

    for (const selector of avatarSelectors) {
      try {
        const el = await driver.$(selector);
        if (await el.isDisplayed()) return true;
      } catch { /* try next */ }
    }
    return false;
  } catch {
    return false;
  }
}
