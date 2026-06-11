import { createBrowser, createContext, saveSession } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { info, success, error } from '../utils/logger.js';

export async function loginCommand() {
  const config = await loadConfig();
  const sessionPath = config.account.sessionFile;

  info('启动浏览器...');
  const browser = await createBrowser(config);
  const context = await createContext(browser, config);

  const page = await context.newPage();
  await page.goto('https://account.dianping.com/login', { waitUntil: 'domcontentloaded' });
  info('请在浏览器中完成登录（扫码或密码）。');

  // Wait for user to login
  console.log('\n⏳ 登录完成后回到终端按 Enter 继续...');
  await waitForEnter();

  // Check if login succeeded
  const currentUrl = page.url();
  if (currentUrl.includes('/member/')) {
    success('登录成功！保存会话...');
    await saveSession(context, sessionPath);
  } else {
    // Navigate to homepage to check
    await page.goto('https://www.dianping.com/', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2000);
    const hasUser = await page.locator('text=个人中心').count();
    if (hasUser > 0) {
      success('登录成功！保存会话...');
      await saveSession(context, sessionPath);
    } else {
      error('似乎未登录成功，但仍会保存当前状态。');
      await saveSession(context, sessionPath);
    }
  }

  await browser.close();
  success(`会话已保存到 ${sessionPath}`);
}

function waitForEnter(): Promise<void> {
  return new Promise((resolve) => {
    const { stdin } = process;
    const onData = (buf: Buffer) => {
      const key = buf.toString();
      if (key === '\n' || key === '\r' || key === '\r\n') {
        stdin.removeListener('data', onData);
        if (stdin.isTTY) stdin.setRawMode(false);
        resolve();
      }
    };
    if (stdin.isTTY) stdin.setRawMode(true);
    stdin.resume();
    stdin.on('data', onData);
  });
}
