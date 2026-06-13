import { readdir, copyFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, basename, extname } from 'node:path';
import { info, success, warn } from '../utils/logger.js';

/**
 * 准备照片：复制到统一目录，重命名为手机友好格式
 *
 * 目标：
 * - 所有照片集中到 data/photos/prepared/
 * - 文件名格式：shop-{店铺slug}-{序号}.jpg
 * - 便于手机识别和选择
 */
export async function preparePhotosCommand(draftId?: string) {
  const photosDir = 'data/photos';
  const preparedDir = join(photosDir, 'prepared');

  if (!existsSync(photosDir)) {
    warn('photos 目录不存在');
    return;
  }

  // 创建 prepared 目录
  await mkdir(preparedDir, { recursive: true });

  if (draftId) {
    // 处理单个草稿的照片
    const shopDir = join(photosDir, draftId);
    if (!existsSync(shopDir)) {
      warn(`未找到草稿 ${draftId} 的照片目录`);
      return;
    }

    await processShopPhotos(shopDir, draftId, preparedDir);
  } else {
    // 处理所有草稿的照片
    info('扫描所有店铺照片...');
    const dirs = await readdir(photosDir);

    let totalCopied = 0;
    for (const dir of dirs) {
      if (dir === 'prepared' || dir === '_downloaded') continue;

      const shopDir = join(photosDir, dir);
      const stat = await import('node:fs/promises').then(fs => fs.stat(shopDir).catch(() => null));
      if (!stat?.isDirectory()) continue;

      const copied = await processShopPhotos(shopDir, dir, preparedDir);
      totalCopied += copied;
    }

    success(`已准备 ${totalCopied} 张照片到 ${preparedDir}`);
  }
}

async function processShopPhotos(shopDir: string, shopSlug: string, preparedDir: string): Promise<number> {
  const files = await readdir(shopDir);
  const imageFiles = files.filter(f => /\.(jpg|jpeg|png|webp)$/i.test(f));

  if (imageFiles.length === 0) {
    return 0;
  }

  info(`处理 ${shopSlug} 的 ${imageFiles.length} 张照片...`);

  let copied = 0;
  for (let i = 0; i < imageFiles.length; i++) {
    const srcPath = join(shopDir, imageFiles[i]);
    const ext = extname(imageFiles[i]).toLowerCase();
    const destName = `shop-${shopSlug}-${String(i + 1).padStart(2, '0')}${ext}`;
    const destPath = join(preparedDir, destName);

    try {
      await copyFile(srcPath, destPath);
      copied++;
    } catch (err) {
      warn(`复制失败 ${imageFiles[i]}: ${err}`);
    }
  }

  info(`✓ ${shopSlug}: ${copied}/${imageFiles.length} 张照片已准备`);
  return copied;
}

/**
 * 清理 prepared 目录
 */
export async function cleanPreparedPhotos() {
  const preparedDir = 'data/photos/prepared';

  if (!existsSync(preparedDir)) {
    info('prepared 目录不存在，无需清理');
    return;
  }

  const files = await readdir(preparedDir);

  for (const file of files) {
    const filePath = join(preparedDir, file);
    try {
      await import('node:fs/promises').then(fs => fs.unlink(filePath));
    } catch (err) {
      warn(`删除失败 ${file}: ${err}`);
    }
  }

  success(`已清理 ${files.length} 个文件`);
}
