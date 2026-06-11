import { readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, extname, resolve } from 'node:path';
import { info, warn } from '../utils/logger.js';

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.heic', '.gif']);
const MAX_SIZE = 20 * 1024 * 1024; // 20MB

export async function scanPhotos(
  photoDir: string,
  shopName?: string
): Promise<string[]> {
  const results: string[] = [];

  // Try shop-specific directory first
  if (shopName) {
    const shopDir = join(photoDir, shopName);
    if (existsSync(shopDir)) {
      const found = await scanDir(shopDir);
      if (found.length > 0) {
        info(`在 ${shopDir} 找到 ${found.length} 张图片`);
        return found.slice(0, 6);
      }
    }
  }

  // Try fuzzy match on subdirectory names
  if (shopName && existsSync(photoDir)) {
    const entries = await readdir(photoDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (fuzzyMatch(entry.name, shopName)) {
        const found = await scanDir(join(photoDir, entry.name));
        if (found.length > 0) {
          info(`在 ${entry.name}/ 模糊匹配到 ${found.length} 张图片`);
          results.push(...found);
        }
      }
    }
  }

  // Fallback: root-level images in photoDir
  if (existsSync(photoDir)) {
    const rootImages = await scanDir(photoDir);
    results.push(...rootImages);
  }

  info(`本地共找到 ${results.length} 张图片`);
  return results.slice(0, 6);
}

async function scanDir(dir: string): Promise<string[]> {
  if (!existsSync(dir)) return [];
  const files = await readdir(dir);
  const results: string[] = [];

  for (const file of files) {
    const fullPath = resolve(join(dir, file));
    try {
      const s = await stat(fullPath);
      if (!s.isFile()) continue;
      if (!IMAGE_EXTS.has(extname(file).toLowerCase())) continue;
      if (s.size > MAX_SIZE) {
        warn(`跳过过大文件: ${file}`);
        continue;
      }
      results.push(fullPath);
    } catch {
      continue;
    }
  }

  return results;
}

function fuzzyMatch(dirName: string, shopName: string): boolean {
  // Check if significant words from shopName appear in dirName
  const dirLower = dirName.toLowerCase();
  const nameLower = shopName.toLowerCase();

  // Extract 2+ char tokens from shop name
  const tokens = shopName
    .replace(/[（）()【】\[\]·]/g, ' ')
    .split(/\s+/)
    .filter(t => t.length >= 2);

  const matches = tokens.filter(t => dirLower.includes(t.toLowerCase()));
  return matches.length >= Math.min(2, tokens.length) || matches.length >= tokens.length * 0.5;
}
