import { readdir, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname } from 'node:path';
import { createBrowser, createMobileContext, saveSession } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { info, success, warn, error, divider } from '../utils/logger.js';
import { sleep, rand } from '../utils/delay.js';

const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
const MOBILE_SESSION = 'data/sessions/mango-mobile.json';

export async function exploreCommand(shopUrl?: string, shopNameArg?: string) {
  const config = await loadConfig();
  // Use mobile-specific session, fall back to PC session
  const sessionPath = existsSync(MOBILE_SESSION) ? MOBILE_SESSION : config.account.sessionFile;

  // Resolve shop name: CLI arg > drafts lookup > URL shop ID
  let shopName = shopNameArg || '';
  if (!shopName && shopUrl) {
    shopName = await lookupShopName(shopUrl);
  }

  // Always headed for exploration
  const browser = await createBrowser({ ...config, browser: { ...config.browser, headless: false } });
  const context = await createMobileContext(browser, config, sessionPath);
  const page = await context.newPage();

  // Auto-close timeout
  const timer = setTimeout(async () => {
    info('5 分钟超时，自动关闭浏览器。');
    await browser.close();
    process.exit(0);
  }, TIMEOUT_MS);

  try {
    // Always start from homepage to check login state
    info('打开 m.dianping.com 首页...');
    await page.goto('https://m.dianping.com/', { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(rand(2000, 4000));

    // Check if redirected to login
    if (await isLoginPage(page)) {
      divider('需要登录');
      info('移动端 session 无效，请在浏览器中扫码登录。');
      info('等待登录完成...\n');
      await waitForLogin(page);
      // Save mobile session
      await saveSession(context, MOBILE_SESSION);
      success(`移动端 session 已保存到 ${MOBILE_SESSION}`);
      // Reload page after login
      await page.goto('https://m.dianping.com/', { waitUntil: 'networkidle', timeout: 30000 });
      await sleep(rand(2000, 3000));
    }

    if (shopUrl) {
      await navigateToShop(page, context, shopUrl, shopName);
    }

    divider('页面状态');
    await dumpPageState(page);

    divider('写评价入口扫描');
    await scanForReviewEntry(page);

    info('\n浏览器保持打开中，可用 DevTools (F12) 检查。');
    info('按 Ctrl+C 关闭。\n');

    // Keep alive but don't block forever — poll every 30s to dump state changes
    let lastUrl = page.url();
    while (true) {
      await sleep(30_000);
      const currentUrl = page.url();
      if (currentUrl !== lastUrl) {
        info(`URL 变化: ${currentUrl}`);
        lastUrl = currentUrl;
        await dumpPageState(page);
        await scanForReviewEntry(page);
      }
    }
  } catch (err) {
    error(`探索出错: ${err}`);
  } finally {
    clearTimeout(timer);
    await browser.close();
  }
}

async function navigateToShop(page: any, context: any, shopUrl: string, shopName: string) {
  const shopId = shopUrl.match(/\/shop\/([A-Za-z0-9]+)/)?.[1] || '';
  info(`目标店铺: ${shopName || '(未知)'} [${shopId}]`);

  // Step 1: Go to mobile homepage (establish session)
  info('步骤 1: 打开移动端首页...');
  await page.goto('https://m.dianping.com/', { waitUntil: 'networkidle', timeout: 30000 });
  await sleep(rand(2000, 4000));

  // Step 2: Search by shop name
  const searchTerm = shopName || shopId;
  info(`步骤 2: 搜索 "${searchTerm}"...`);
  await trySearch(page, searchTerm);
  await sleep(rand(3000, 5000));

  // Step 2.5: Check if search triggered login redirect
  if (await isLoginPage(page)) {
    divider('搜索需要登录');
    info('请在浏览器中扫码登录移动端。');
    await waitForLogin(page);
    await saveSession(context, MOBILE_SESSION);
    success(`移动端 session 已保存到 ${MOBILE_SESSION}`);
    // Re-do search after login
    info(`重新搜索 "${searchTerm}"...`);
    await page.goto('https://m.dianping.com/', { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(rand(2000, 3000));
    await trySearch(page, searchTerm);
    await sleep(rand(3000, 5000));
  }

  // Step 3: Find and click matching shop
  info('步骤 3: 在搜索结果中查找店铺...');
  const clicked = await tryClickShop(page, shopId, shopName);
  if (!clicked) {
    warn('搜索结果中未找到匹配店铺。请在浏览器中手动查找并导航到店铺页面。');
    return;
  }

  // Wait for navigation to shop page
  try {
    await page.waitForURL(`**/shop/**`, { timeout: 10000 });
  } catch {
    // URL might not change immediately, wait a bit more
    await sleep(rand(3000, 5000));
  }
  info(`已到达店铺页面: ${page.url()}`);
}

async function trySearch(page: any, keyword: string) {
  // m.dianping.com homepage: search is a clickable div, not an input
  // Structure: div.search-bar > div.search-text + div.search-img

  // Step 1: Click the search bar to go to search page
  const searchBarSelectors = [
    '.search-bar',
    '.search-text',
    'div:has-text("输入商户名")',
    'text=输入商户名、地点',
    'text=输入商户名',
  ];

  for (const sel of searchBarSelectors) {
    try {
      const bar = page.locator(sel).first();
      if (await bar.isVisible({ timeout: 2000 })) {
        info(`点击搜索栏: ${sel}`);
        await bar.click();
        await sleep(rand(2000, 4000));
        break;
      }
    } catch { continue; }
  }

  // Step 2: Now on search page, find the real input
  const inputSelectors = [
    'input[type="search"]',
    'input[type="text"]',
    'input[placeholder*="搜索"]',
    'input[placeholder*="商户"]',
    'input[placeholder*="店名"]',
    'input',
    '#keyword',
  ];

  for (const sel of inputSelectors) {
    try {
      const input = page.locator(sel).first();
      if (await input.isVisible({ timeout: 2000 })) {
        info(`找到搜索输入框: ${sel}`);
        await input.click();
        await sleep(rand(300, 600));
        await input.fill(keyword);
        await sleep(rand(500, 1000));
        // Try pressing Enter, or clicking search button
        await page.keyboard.press('Enter');
        await sleep(rand(3000, 5000));
        info(`搜索完成: ${page.url()}`);
        return;
      }
    } catch { continue; }
  }

  // Step 3: Fallback — try search URL patterns
  const searchUrls = [
    `https://m.dianping.com/search/keyword?keyword=${encodeURIComponent(keyword)}`,
    `https://m.dianping.com/search?keyword=${encodeURIComponent(keyword)}`,
    `https://m.dianping.com/searchshop?keyword=${encodeURIComponent(keyword)}`,
  ];
  for (const url of searchUrls) {
    info(`尝试搜索 URL: ${url}`);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await sleep(3000);
    const currentUrl = page.url();
    if (!currentUrl.includes('error')) {
      info(`搜索页加载成功: ${currentUrl}`);
      return;
    }
  }

  warn('所有搜索方式均失败');
}

async function tryClickShop(page: any, shopId: string, shopName: string): Promise<boolean> {
  // Strategy 1: Find <a> tag inside card with matching shop ID
  try {
    const links = page.locator(`[data-launch-shop-uuid="${shopId}"] a[href*="/shop/${shopId}"]`);
    const count = await links.count();
    if (count > 0) {
      info(`  ✓ 通过 card 内 <a> 标签匹配到目标店铺`);
      const href = await links.first().getAttribute('href').catch(() => '');
      info(`    href: ${href}`);
      await links.first().click();
      return true;
    }
  } catch { /* ignore */ }

  // Strategy 2: Find card by UUID, navigate via data-launch-h5-url
  try {
    const card = page.locator(`[data-launch-shop-uuid="${shopId}"]`);
    if (await card.count() > 0) {
      const h5Url = await card.first().getAttribute('data-launch-h5-url').catch(() => '');
      if (h5Url) {
        const fullUrl = h5Url.startsWith('//') ? `https:${h5Url}` : h5Url;
        info(`  ✓ 通过 data-launch-h5-url 导航: ${fullUrl.slice(0, 80)}`);
        await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
        return true;
      }
    }
  } catch { /* ignore */ }

  // Strategy 3: Match by shop name
  if (shopName) {
    try {
      const named = page.locator(`h3:has-text("${shopName}")`).first();
      if (await named.isVisible({ timeout: 2000 })) {
        info(`  ✓ 匹配店铺名: ${shopName}`);
        await named.click();
        return true;
      }
    } catch { /* ignore */ }
  }

  return false;
}

async function lookupShopName(shopUrl: string): Promise<string> {
  // Look up shop name from drafts directory
  const draftsDir = 'data/drafts';
  if (!existsSync(draftsDir)) return '';
  try {
    const files = await readdir(draftsDir);
    const shopId = shopUrl.match(/\/shop\/([A-Za-z0-9]+)/)?.[1] || '';
    for (const f of files) {
      if (!f.endsWith('.json') || f.endsWith('.bak')) continue;
      try {
        const content = await import(`node:fs/promises`).then(fs => fs.readFile(`${draftsDir}/${f}`, 'utf-8'));
        const draft = JSON.parse(content as string);
        if (draft.shopUrl?.includes(shopId) || draft.shopSlug === shopId?.slice(0, 10)) {
          info(`从草稿找到店名: ${draft.shopName}`);
          return draft.shopName || '';
        }
      } catch { continue; }
    }
  } catch { /* ignore */ }
  return '';
}

async function dumpPageState(page: any) {
  const url = page.url();
  const title = await page.title().catch(() => '');
  const bodyLen = await page.evaluate(() => document.body?.innerHTML?.length || 0).catch(() => 0);

  console.log(`  URL:     ${url}`);
  console.log(`  标题:    ${title}`);
  console.log(`  内容长度: ${bodyLen} 字符`);

  // Check for captcha
  const hasCaptcha = url.includes('verify.meituan.com') ||
    await page.locator('.yoda-slider-wrapper, #yodaBox, .geetest_panel').isVisible().catch(() => false);
  if (hasCaptcha) {
    warn('  ⚠️ 检测到验证码页面');
  }
}

async function scanForReviewEntry(page: any) {
  const results = await page.evaluate(() => {
    const found: Array<{ type: string; text: string; href?: string; tag: string }> = [];

    // Scan all links and buttons
    const elements = document.querySelectorAll('a, button, [role="button"], [onclick]');
    for (const el of elements) {
      const text = el.textContent?.trim() || '';
      const href = (el as HTMLAnchorElement).href || '';
      const tag = el.tagName.toLowerCase();

      // Match review-related text
      const reviewKeywords = ['写评价', '写点评', '写评论', '我要点评', '发表评价', '写回复'];
      if (reviewKeywords.some(k => text.includes(k))) {
        found.push({ type: 'review-button', text: text.slice(0, 50), href: href || undefined, tag });
      }

      // Match review-related URLs
      if (href && /\/(review|write|comment|evaluate)/i.test(href)) {
        found.push({ type: 'review-link', text: text.slice(0, 50), href, tag });
      }
    }

    // Check for specific review page indicators
    const reviewIndicators = document.querySelectorAll('[class*="review"], [class*="comment"], [class*="evaluate"]');
    if (reviewIndicators.length > 0) {
      found.push({ type: 'review-indicator', text: `找到 ${reviewIndicators.length} 个评价相关元素`, tag: 'div' });
    }

    return found;
  });

  if (results.length === 0) {
    warn('  未找到写评价入口');
    // Dump all visible buttons and links for manual inspection
    const buttons = await page.evaluate(() => {
      const els = document.querySelectorAll('a, button, [role="button"]');
      return Array.from(els).slice(0, 50).map(el => ({
        tag: el.tagName.toLowerCase(),
        text: (el.textContent?.trim() || '').slice(0, 40),
        href: (el as HTMLAnchorElement).href || undefined,
      })).filter(e => e.text);
    });
    info(`  页面可见按钮/链接 (${buttons.length} 个):`);
    for (const b of buttons.slice(0, 30)) {
      console.log(`    [${b.tag}] ${b.text}${b.href ? ` → ${b.href.slice(0, 60)}` : ''}`);
    }
  } else {
    success(`  找到 ${results.length} 个写评价相关入口:`);
    for (const r of results) {
      console.log(`    [${r.type}] [${r.tag}] ${r.text}${r.href ? ` → ${r.href}` : ''}`);
    }
  }
}

async function isLoginPage(page: any): Promise<boolean> {
  const url = page.url();
  if (url.includes('mlogin') || url.includes('/login')) return true;
  const hasLogin = await page.locator('text=验证码登录, text=扫码登录, text=密码登录, .login-form, .qrcode-img')
    .first().isVisible().catch(() => false);
  return hasLogin;
}

async function waitForLogin(page: any) {
  const maxWait = 3 * 60 * 1000;
  const start = Date.now();
  while (Date.now() - start < maxWait) {
    await sleep(3000);
    const url = page.url();
    if (!url.includes('mlogin') && !url.includes('/login')) {
      success('登录成功！');
      return;
    }
    const elapsed = Math.floor((Date.now() - start) / 1000);
    if (elapsed % 15 === 0) info(`等待登录中... (${elapsed}s)`);
  }
  warn('登录等待超时，继续尝试...');
}
