import { chromium, devices, Browser, BrowserContext } from 'playwright';
import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { AppConfig } from '../storage/config.js';

const STEALTH_ARGS = [
  '--disable-blink-features=AutomationControlled',
  '--disable-features=IsolateOrigins,site-per-process',
  '--disable-site-isolation-trials',
  '--no-sandbox',
  '--disable-dev-shm-usage',
  '--disable-infobars',
  '--disable-background-timer-throttling',
  '--disable-backgrounding-occluded-windows',
  '--disable-renderer-backgrounding',
  '--disable-features=TranslateUI',
  '--disable-ipc-flooding-protection',
  '--disable-hang-monitor',
  '--disable-sync',
  '--disable-default-apps',
  '--password-store=basic',
  '--use-mock-keychain',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-notifications',
];

const STEALTH_SCRIPT = `
// 1. Hide webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => false });
delete navigator.__proto__.webdriver;

// 2. Fake chrome.runtime
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };

// 3. Fake plugins
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const p = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'PDF', length: 1 },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
    ];
    p.item = (i) => p[i] || null;
    p.namedItem = (n) => p.find(x => x.name === n) || null;
    p.refresh = () => {};
    return Object.setPrototypeOf(p, PluginArray.prototype);
  },
});

// 4. Languages
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });

// 5. Canvas fingerprint noise
const _toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
  const ctx = this.getContext('2d');
  if (ctx) {
    const d = ctx.getImageData(0, 0, this.width, this.height);
    if (d.data.length > 3) d.data[0] = d.data[0] ^ 1;
    ctx.putImageData(d, 0, 0);
  }
  return _toDataURL.apply(this, arguments);
};

// 6. WebGL spoofing
const _getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
  if (p === 37445) return 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)';
  if (p === 37446) return 'WebKit WebGL';
  return _getParam.call(this, p);
};

// 7. Permissions API
const _query = window.navigator.permissions.query;
window.navigator.permissions.query = function(params) {
  if (params.name === 'notifications') return Promise.resolve({ state: Notification.permission, onchange: null });
  return _query.call(this, params);
};

// 8. Screen properties
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

// 9. connection.rtt
if (navigator.connection) Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 });
`;

export async function createBrowser(config: AppConfig): Promise<Browser> {
  return chromium.launch({
    headless: config.browser.headless,
    executablePath: config.browser.executablePath,
    args: STEALTH_ARGS,
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
  await context.addInitScript(STEALTH_SCRIPT);

  return context;
}

export async function saveSession(context: BrowserContext, sessionPath: string): Promise<void> {
  await mkdir(dirname(sessionPath), { recursive: true });
  await context.storageState({ path: sessionPath });
}

export async function createMobileContext(
  browser: Browser,
  config: AppConfig,
  sessionPath?: string
): Promise<BrowserContext> {
  const device = devices['iPhone 15 Pro'];
  const contextOptions: any = {
    ...device,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  };
  if (sessionPath && existsSync(sessionPath)) {
    contextOptions.storageState = sessionPath;
  }
  const context = await browser.newContext(contextOptions);
  await context.addInitScript(STEALTH_SCRIPT);
  return context;
}

export function isLoggedIn(url: string): boolean {
  return url.includes('/member/') && !url.includes('/login');
}
