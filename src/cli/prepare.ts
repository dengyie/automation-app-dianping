import { readdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { info, success, warn, error } from '../utils/logger.js';
import type { DraftFile } from '../storage/drafts.js';

interface PublishItem {
  shopName: string;
  shopUrl: string;
  rating: number;
  review: string;
  photos: string[];
  status: 'pending' | 'published';
  ratings: { taste: number; environment: number; service: number };
  recommendedDishes: string[];
  address: string;
  avgPrice: number | null;
}

interface PublishChecklist {
  shops: PublishItem[];
  createdAt: string;
}

export async function prepareCommand(options: { json?: boolean; output?: string } = {}) {
  const draftsDir = 'data/drafts';

  if (!existsSync(draftsDir)) {
    error('drafts 目录不存在，请先运行 scrape 和 generate 命令。');
    return;
  }

  info('读取 drafts...');
  const files = await readdir(draftsDir);
  const draftFiles = files.filter(f => f.endsWith('.json') && !f.endsWith('.bak'));

  if (draftFiles.length === 0) {
    warn('未找到草稿文件。');
    return;
  }

  const items: PublishItem[] = [];

  for (const file of draftFiles) {
    try {
      const content = await readFile(join(draftsDir, file), 'utf-8');
      const draft: DraftFile = JSON.parse(content);

      // Calculate average rating
      const ratings = draft.draft.ratings;
      const avgRating = ratings.taste && ratings.environment && ratings.service
        ? ((ratings.taste + ratings.environment + ratings.service) / 3)
        : (draft.scrapedData?.overallRating || 4.5);

      items.push({
        shopName: draft.shopName || '未知店铺',
        shopUrl: draft.shopUrl || '',
        rating: avgRating,
        review: draft.draft.content || '',
        photos: draft.draft.photos || [],
        status: 'pending',
        // 添加额外信息
        ratings: draft.draft.ratings,
        recommendedDishes: draft.scrapedData?.recommendedDishes || [],
        address: draft.scrapedData?.address || '',
        avgPrice: draft.scrapedData?.avgPricePerPerson || null,
      });
    } catch (err) {
      warn(`读取 ${file} 失败: ${err}`);
    }
  }

  if (items.length === 0) {
    warn('未找到有效的草稿。');
    return;
  }

  success(`找到 ${items.length} 条待发布评价`);

  const checklist: PublishChecklist = {
    shops: items,
    createdAt: new Date().toISOString(),
  };

  // 输出格式
  if (options.json) {
    const output = options.output || 'data/publish-checklist.json';
    await writeFile(output, JSON.stringify(checklist, null, 2), 'utf-8');
    success(`JSON 清单已保存到 ${output}`);
  } else {
    const markdown = generateMarkdown(checklist);
    const output = options.output || 'data/publish-checklist.md';
    await writeFile(output, markdown, 'utf-8');
    success(`Markdown 清单已保存到 ${output}`);

    // 同时输出到控制台
    console.log('\n' + markdown);
  }
}

function generateMarkdown(checklist: PublishChecklist): string {
  const lines: string[] = [];

  lines.push('# 大众点评发布清单');
  lines.push('');
  lines.push(`生成时间：${new Date(checklist.createdAt).toLocaleString('zh-CN')}`);
  lines.push(`待发布：${checklist.shops.length} 条`);
  lines.push('');
  lines.push('---');
  lines.push('');

  checklist.shops.forEach((shop, idx) => {
    lines.push(`## ${idx + 1}. ${shop.shopName}`);
    lines.push('');
    lines.push(`**店铺链接**：${shop.shopUrl}`);
    if (shop.address) {
      lines.push(`**地址**：${shop.address}`);
    }
    if (shop.avgPrice) {
      lines.push(`**人均**：¥${shop.avgPrice}`);
    }
    lines.push(`**综合评分**：${renderStars(shop.rating)} (${shop.rating.toFixed(1)})`);
    if (shop.ratings.taste || shop.ratings.environment || shop.ratings.service) {
      lines.push(`**分项评分**：口味${shop.ratings.taste}分 | 环境${shop.ratings.environment}分 | 服务${shop.ratings.service}分`);
    }
    if (shop.recommendedDishes.length > 0) {
      lines.push(`**推荐菜**：${shop.recommendedDishes.slice(0, 5).join('、')}`);
    }
    lines.push(`**照片**：${shop.photos.length} 张`);
    lines.push('');

    lines.push('### 📝 评价内容（' + shop.review.length + ' 字）');
    lines.push('```');
    lines.push(shop.review.trim());
    lines.push('```');
    lines.push('');

    if (shop.photos.length > 0) {
      lines.push('### 📸 照片列表');
      shop.photos.forEach((photo, photoIdx) => {
        lines.push(`${photoIdx + 1}. \`${photo}\``);
      });
      lines.push('');
    }

    lines.push('### ✅ 操作步骤');
    lines.push('1. 打开大众点评 App');
    lines.push(`2. 搜索店铺：**${shop.shopName}**`);
    lines.push('3. 点击"写评价"按钮');
    lines.push(`4. 点击星星设置评分：`);
    lines.push(`   - 口味：${renderStars(shop.ratings.taste)} (${shop.ratings.taste}星)`);
    lines.push(`   - 环境：${renderStars(shop.ratings.environment)} (${shop.ratings.environment}星)`);
    lines.push(`   - 服务：${renderStars(shop.ratings.service)} (${shop.ratings.service}星)`);
    lines.push('5. 复制上方评价内容，粘贴到评价框');
    if (shop.photos.length > 0) {
      lines.push('6. 上传照片（从相册选择上述照片）');
      lines.push('7. 点击发布');
    } else {
      lines.push('6. 点击发布');
    }
    lines.push('');
    lines.push('---');
    lines.push('');
  });

  return lines.join('\n');
}

function renderStars(rating: number): string {
  const full = Math.floor(rating);
  const half = rating % 1 >= 0.5 ? 1 : 0;
  const empty = 5 - full - half;

  return '⭐'.repeat(full) + (half ? '⭐' : '') + '☆'.repeat(empty);
}
