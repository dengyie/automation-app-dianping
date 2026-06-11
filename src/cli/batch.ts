import { readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { loadConfig } from '../storage/config.js';
import { loadState, canPublishToday, minutesSinceLastPublish } from '../storage/state.js';
import { loadDraftByUrl, listDrafts } from '../storage/drafts.js';
import { scrapeCommand } from './scrape.js';
import { generateCommand } from './generate.js';
import { publishCommand } from './publish.js';
import { info, success, warn, error, divider } from '../utils/logger.js';
import { sleep } from '../utils/delay.js';

const SHOPS_FILE = 'data/shops.txt';

interface ShopEntry {
  url: string;
  name?: string;
}

function parseShopLine(line: string): ShopEntry | null {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) return null;

  // Format: URL [店名]
  const parts = trimmed.split(/\s+/);
  const url = parts[0];
  if (!url.includes('/shop/')) return null;
  return { url, name: parts.slice(1).join(' ') || undefined };
}

async function loadShopList(args: string[]): Promise<ShopEntry[]> {
  // From command-line args
  if (args.length > 0) {
    return args.map(arg => {
      const parts = arg.split(/\s+/);
      return { url: parts[0], name: parts.slice(1).join(' ') || undefined };
    }).filter(s => s.url.includes('/shop/'));
  }

  // From file
  if (!existsSync(SHOPS_FILE)) {
    error(`店铺列表文件不存在: ${SHOPS_FILE}`);
    info('创建示例文件...');
    await writeFile(SHOPS_FILE, `# 每行一个店铺URL，后面可选跟店名
# https://www.dianping.com/shop/xxxxx 店名
`, 'utf-8');
    return [];
  }

  const content = await readFile(SHOPS_FILE, 'utf-8');
  return content.split('\n').map(parseShopLine).filter((s): s is ShopEntry => s !== null);
}

export async function batchCommand(args: string[]) {
  const config = await loadConfig();
  const shops = await loadShopList(args);

  if (shops.length === 0) {
    warn('没有待处理的店铺。编辑 data/shops.txt 添加店铺 URL。');
    return;
  }

  divider(`批量处理: ${shops.length} 家店铺`);

  // Phase 1: Scrape + Generate for all shops
  let generated = 0;
  for (const shop of shops) {
    const existing = await loadDraftByUrl(shop.url);
    if (existing?.draft?.status === 'edited' || existing?.draft?.status === 'published') {
      info(`跳过 ${shop.name || shop.url}（已有草稿）`);
      continue;
    }

    info(`抓取: ${shop.name || shop.url}`);
    try {
      await scrapeCommand(shop.url, shop.name);
      await sleep(2000);
    } catch (err) {
      error(`抓取失败: ${err}`);
      continue;
    }

    info(`生成评价: ${shop.name || shop.url}`);
    try {
      await generateCommand(shop.url, shop.name);
      generated++;
    } catch (err) {
      error(`生成失败: ${err}`);
    }

    await sleep(3000);
  }

  if (generated > 0) {
    success(`生成了 ${generated} 条评价草稿`);
  }

  // Phase 2: Publish drafts respecting limits
  const drafts = (await listDrafts()).filter(d => d.draft.status === 'edited');

  if (drafts.length === 0) {
    info('没有待发布的草稿。');
    return;
  }

  divider(`发布草稿: ${drafts.length} 条待发布`);
  let published = 0;

  for (const draft of drafts) {
    // Reload state from disk each iteration (publishCommand updates it)
    const state = await loadState();

    // Check daily limit
    if (!(await canPublishToday(state, config.publishing.maxPerDay))) {
      warn(`今日额度已满 (${state.todayPublishedCount}/${config.publishing.maxPerDay})，剩余草稿明天再发布。`);
      break;
    }

    // Check interval
    const mins = await minutesSinceLastPublish(state);
    if (mins !== null && mins < config.publishing.minIntervalMinutes) {
      const waitMin = Math.ceil(config.publishing.minIntervalMinutes - mins);
      warn(`需等待 ${waitMin} 分钟后才能发布下一条。剩余草稿稍后再发布。`);
      break;
    }

    info(`发布: ${draft.shopName} (${draft.id})`);
    try {
      await publishCommand(draft.id);
      published++;
    } catch (err) {
      error(`发布失败: ${err}`);
    }

    await sleep(5000);
  }

  const finalState = await loadState();
  divider();
  success(`批量完成: ${generated} 生成, ${published} 发布`);
  if (published > 0) {
    console.log(`  今日进度: ${finalState.todayPublishedCount}/${config.publishing.maxPerDay}`);
  }
}
