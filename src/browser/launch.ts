import { chromium, Browser, BrowserContext } from 'playwright';
import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { AppConfig } from '../storage/config.js';

export async function createBrowser(config: AppConfig): Promise<Browser> {
  return chromium.launch({
    headless: config.browser.headless,
    executablePath: config.browser.executablePath,
    args: ['--disable-blink-features=AutomationControlled'],
  });
}

export async function createContext(
  browser: Browser,
  config: AppConfig,
  sessionPath?: string
): Promise<BrowserContext> {
  const contextOptions: any = {
    viewport: config.browser.viewport,
    locale: config.browser.locale,
    timezoneId: config.browser.timezoneId,
  };

  if (sessionPath && existsSync(sessionPath)) {
    contextOptions.storageState = sessionPath;
  }

  const context = await browser.newContext(contextOptions);

  // Anti-detection
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
  });

  return context;
}

export async function saveSession(context: BrowserContext, sessionPath: string): Promise<void> {
  await mkdir(dirname(sessionPath), { recursive: true });
  await context.storageState({ path: sessionPath });
}

export function isLoggedIn(url: string): boolean {
  // If page is on a member page (not redirected to login), user is logged in
  return url.includes('/member/') && !url.includes('/login');
}
