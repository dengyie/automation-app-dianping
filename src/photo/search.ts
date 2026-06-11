import type { Browser, BrowserContext } from 'playwright';
import { writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, basename } from 'node:path';
import { sleep, rand } from '../utils/delay.js';
import { info, warn } from '../utils/logger.js';

const DOWNLOAD_DIR = 'data/photos/_downloaded';

export async function webSearchPhotos(
  browser: Browser,
  context: BrowserContext,
  query: string,
  maxPhotos: number = 3
): Promise<string[]> {
  const page = await context.newPage();
  const results: string[] = [];

  try {
    // Navigate to Baidu Images
    // Build a specific search query using shop name + dish name
    const queryParts = [query, '美食'].filter(Boolean);
    const searchUrl = `https://image.baidu.com/search/index?tn=baiduimage&word=${encodeURIComponent(queryParts.join(' '))}`;
    info(`搜索图片: ${queryParts.join(' ')}`);
    await page.goto(searchUrl, { timeout: 15000, waitUntil: 'domcontentloaded' });
    await sleep(2000);

    // Scroll to load more images
    for (let i = 0; i < 3; i++) {
      await page.mouse.wheel(0, rand(300, 600));
      await sleep(rand(800, 1500));
    }

    // Extract image URLs from the page
    const imgUrls: string[] = await page.evaluate(() => {
      const imgs = document.querySelectorAll('img.main_img, img[src]');
      const urls: string[] = [];
      for (const img of imgs) {
        const src = (img as HTMLImageElement).src;
        if (src && src.startsWith('http') && !src.includes('data:image')) {
          urls.push(src);
        }
        if (urls.length >= 15) break;
      }
      return urls;
    });

    info(`百度图片搜索找到 ${imgUrls.length} 张候选图`);

    // Download images
    if (!existsSync(DOWNLOAD_DIR)) {
      await mkdir(DOWNLOAD_DIR, { recursive: true });
    }

    for (const url of imgUrls) {
      if (results.length >= maxPhotos) break;
      try {
        const resp = await fetch(url, { signal: AbortSignal.timeout(10000) });
        if (!resp.ok || !resp.headers.get('content-type')?.startsWith('image/')) continue;

        const buffer = Buffer.from(await resp.arrayBuffer());
        if (buffer.length < 10_000) continue; // skip tiny images/thumbnails
        if (buffer.length > 5_000_000) continue; // skip overly large images

        const ext = resp.headers.get('content-type')?.split('/')[1] || 'jpg';
        const filename = `${Date.now()}-${results.length}.${ext}`;
        const filepath = join(DOWNLOAD_DIR, filename);
        await writeFile(filepath, buffer);
        results.push(filepath);
        info(`下载图片: ${filename}`);
      } catch {
        continue;
      }
      await sleep(rand(500, 1500));
    }
  } catch (err) {
    warn(`图片搜索失败: ${err}`);
  } finally {
    await page.close();
  }

  info(`成功下载 ${results.length} 张图片`);
  return results;
}
