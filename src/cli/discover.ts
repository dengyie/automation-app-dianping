import { writeFile, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createBrowser, createContext } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { findElement } from '../browser/selectors.js';
import { SELECTORS } from '../browser/selectors.js';
import { scrollNaturally } from '../browser/humanize.js';
import { info, success, warn, error, divider } from '../utils/logger.js';
import { sleep, rand } from '../utils/delay.js';

const SHOPS_FILE = 'data/shops.txt';

export async function discoverCommand() {
  const config = await loadConfig();
  const sessionPath = config.account.sessionFile;

  const browser = await createBrowser(config);
  const context = await createContext(browser, config, sessionPath);

  try {
    const page = await context.newPage();

    // Navigate to favorites page
    info('打开收藏夹页面...');
    await page.goto('https://www.dianping.com/member/collection', {
      waitUntil: 'domcontentloaded',
      timeout: 30000,
    });
    await sleep(3000);

    // Check login
    const loggedIn = await findElement(page, SELECTORS.LOGIN_INDICATOR, 3000);
    if (!loggedIn) {
      error('未登录，请先运行 login。');
      return;
    }

    // Scroll to load more items
    await scrollNaturally(page);
    await sleep(2000);

    // Extract shop URLs from the favorites list
    const shops: Array<{ url: string; name: string }> = await page.evaluate(() => {
      const results: Array<{ url: string; name: string }> = [];
      // Common selectors for dianping favorites/collection page
      const links = document.querySelectorAll('a[href*="/shop/"]');
      const seen = new Set<string>();

      for (const link of links) {
        const href = (link as HTMLAnchorElement).href;
        const match = href.match(/\/shop\/([A-Za-z0-9]+)/);
        if (!match || seen.has(match[1])) continue;
        seen.add(match[1]);

        // Try to get shop name from nearby text
        const parent = link.closest('li, .item, [class*="shop"], [class*="collect"]') || link.parentElement;
        const nameEl = parent?.querySelector('h2, h3, .shop-name, .title, [class*="name"]');
        const name = nameEl?.textContent?.trim() || link.textContent?.trim() || '';

        results.push({ url: href.split('?')[0], name });
      }
      return results;
    });

    if (shops.length === 0) {
      // Try alternative: recently visited
      info('收藏夹为空，尝试最近浏览...');
      await page.goto('https://www.dianping.com/member/history', {
        waitUntil: 'domcontentloaded',
        timeout: 30000,
      });
      await sleep(3000);
      await scrollNaturally(page);

      const historyShops: Array<{ url: string; name: string }> = await page.evaluate(() => {
        const results: Array<{ url: string; name: string }> = [];
        const links = document.querySelectorAll('a[href*="/shop/"]');
        const seen = new Set<string>();
        for (const link of links) {
          const href = (link as HTMLAnchorElement).href;
          const match = href.match(/\/shop\/([A-Za-z0-9]+)/);
          if (!match || seen.has(match[1])) continue;
          seen.add(match[1]);
          const name = link.textContent?.trim() || '';
          results.push({ url: href.split('?')[0], name });
        }
        return results;
      });

      shops.push(...historyShops);
    }

    if (shops.length === 0) {
      warn('未找到任何店铺。请先在大众点评上收藏或浏览一些店铺。');
      return;
    }

    // Merge with existing shops.txt (don't overwrite)
    const existing = existsSync(SHOPS_FILE) ? await readFile(SHOPS_FILE, 'utf-8') : '';
    const existingUrls = new Set(
      existing.split('\n')
        .map(l => l.trim())
        .filter(l => l && !l.startsWith('#'))
        .map(l => l.split(/\s+/)[0])
    );

    const newShops = shops.filter(s => !existingUrls.has(s.url));

    if (newShops.length === 0) {
      info(`所有 ${shops.length} 家店铺已在 shops.txt 中。`);
      return;
    }

    const lines = newShops.map(s => `${s.url} ${s.name}`.trim());
    const appendContent = (existing.endsWith('\n') || !existing ? '' : '\n') + lines.join('\n') + '\n';
    await writeFile(SHOPS_FILE, existing + appendContent, 'utf-8');

    divider('店铺发现');
    success(`发现 ${shops.length} 家店铺，新增 ${newShops.length} 家写入 ${SHOPS_FILE}`);
    for (const s of newShops.slice(0, 10)) {
      console.log(`  + ${s.name || s.url}`);
    }
    if (newShops.length > 10) {
      console.log(`  ... 还有 ${newShops.length - 10} 家`);
    }

  } finally {
    await browser.close();
  }
}
