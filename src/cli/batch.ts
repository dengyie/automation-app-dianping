import { readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { loadConfig } from '../storage/config.js';
import { loadDraftByUrl, listDrafts } from '../storage/drafts.js';
import { scrapeCommand } from './scrape.js';
import { generateCommand } from './generate.js';
import { prepareCommand } from './prepare.js';
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

  // Phase 2: Generate checklist
  divider('生成发布清单');
  await prepareCommand({});

  divider();
  success(`批量完成: ${generated} 条草稿已生成`);
  info('\n下一步：');
  info('1. 半自动化：打开 data/publish-checklist.md，在 App 内手动发布');
  info('2. 手机版：打开 data/mobile-checklist.html 获取手机友好的清单');
  info('3. 全自动化：运行 app-publish 命令（需要 Android 环境）');
}
