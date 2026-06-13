import { readdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { DraftFile } from '../storage/drafts.js';
import { info, success, warn } from '../utils/logger.js';

interface MobileItem {
  shopName: string;
  rating: { taste: number; environment: number; service: number };
  review: string;
  reviewLength: number;
}

export async function exportMobileCommand(options: { output?: string } = {}) {
  const draftsDir = 'data/drafts';

  if (!existsSync(draftsDir)) {
    warn('drafts 目录不存在');
    return;
  }

  info('读取 drafts...');
  const files = await readdir(draftsDir);
  const draftFiles = files.filter(f => f.endsWith('.json') && !f.endsWith('.bak'));

  if (draftFiles.length === 0) {
    warn('未找到草稿文件。');
    return;
  }

  const items: MobileItem[] = [];

  for (const file of draftFiles) {
    try {
      const content = await readFile(join(draftsDir, file), 'utf-8');
      const draft: DraftFile = JSON.parse(content);

      if (!draft.draft.content) continue;

      items.push({
        shopName: draft.shopName || '未知店铺',
        rating: draft.draft.ratings,
        review: draft.draft.content,
        reviewLength: draft.draft.content.length,
      });
    } catch (err) {
      warn(`读取 ${file} 失败: ${err}`);
    }
  }

  if (items.length === 0) {
    warn('未找到有效的草稿。');
    return;
  }

  const html = generateMobileHTML(items);
  const output = options.output || 'data/mobile-checklist.html';
  await writeFile(output, html, 'utf-8');
  success(`手机版清单已保存到 ${output}`);
  console.log('\n在手机浏览器打开此文件，可直接复制评价内容。');
}

function generateMobileHTML(items: MobileItem[]): string {
  const itemsHTML = items.map((item, idx) => `
    <div class="shop-card">
      <div class="shop-header">
        <div class="shop-index">${idx + 1}</div>
        <div class="shop-name">${escapeHTML(item.shopName)}</div>
      </div>

      <div class="rating-section">
        <div class="rating-item">
          <span class="label">口味</span>
          <span class="stars">${renderStarsHTML(item.rating.taste)}</span>
          <span class="score">${item.rating.taste}</span>
        </div>
        <div class="rating-item">
          <span class="label">环境</span>
          <span class="stars">${renderStarsHTML(item.rating.environment)}</span>
          <span class="score">${item.rating.environment}</span>
        </div>
        <div class="rating-item">
          <span class="label">服务</span>
          <span class="stars">${renderStarsHTML(item.rating.service)}</span>
          <span class="score">${item.rating.service}</span>
        </div>
      </div>

      <div class="review-section">
        <div class="review-header">
          <span>评价内容</span>
          <span class="review-length">${item.reviewLength} 字</span>
        </div>
        <div class="review-content" id="review-${idx}">
          ${escapeHTML(item.review)}
        </div>
        <button class="copy-btn" onclick="copyReview(${idx})">
          📋 复制评价
        </button>
      </div>
    </div>
  `).join('\n');

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>大众点评发布清单</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: #f5f5f5;
      padding: 16px;
      line-height: 1.6;
      color: #333;
    }

    .header {
      text-align: center;
      margin-bottom: 20px;
      padding: 16px;
      background: white;
      border-radius: 12px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }

    .header h1 {
      font-size: 20px;
      margin-bottom: 8px;
      color: #ff6600;
    }

    .header p {
      font-size: 14px;
      color: #999;
    }

    .shop-card {
      background: white;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }

    .shop-header {
      display: flex;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid #f0f0f0;
    }

    .shop-index {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: linear-gradient(135deg, #ff6600, #ff8833);
      color: white;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      margin-right: 12px;
      flex-shrink: 0;
    }

    .shop-name {
      font-size: 18px;
      font-weight: 600;
      color: #333;
      flex: 1;
    }

    .rating-section {
      display: flex;
      gap: 12px;
      margin-bottom: 16px;
    }

    .rating-item {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 12px 8px;
      background: #f9f9f9;
      border-radius: 8px;
    }

    .rating-item .label {
      font-size: 12px;
      color: #999;
      margin-bottom: 4px;
    }

    .rating-item .stars {
      font-size: 16px;
      margin-bottom: 4px;
    }

    .rating-item .score {
      font-size: 14px;
      font-weight: 600;
      color: #ff6600;
    }

    .review-section {
      margin-top: 16px;
    }

    .review-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
      font-size: 14px;
      color: #666;
    }

    .review-length {
      color: #999;
      font-size: 12px;
    }

    .review-content {
      background: #f9f9f9;
      padding: 16px;
      border-radius: 8px;
      font-size: 15px;
      line-height: 1.8;
      color: #333;
      margin-bottom: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .copy-btn {
      width: 100%;
      padding: 14px;
      background: linear-gradient(135deg, #ff6600, #ff8833);
      color: white;
      border: none;
      border-radius: 8px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
      box-shadow: 0 4px 12px rgba(255, 102, 0, 0.3);
    }

    .copy-btn:active {
      transform: scale(0.98);
      box-shadow: 0 2px 6px rgba(255, 102, 0, 0.3);
    }

    .toast {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: rgba(0, 0, 0, 0.8);
      color: white;
      padding: 16px 24px;
      border-radius: 8px;
      font-size: 16px;
      z-index: 9999;
      display: none;
      animation: fadeIn 0.3s;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
      to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
    }

    .footer {
      text-align: center;
      padding: 20px;
      color: #999;
      font-size: 12px;
    }
  </style>
</head>
<body>
  <div class="header">
    <h1>📝 大众点评发布清单</h1>
    <p>点击复制按钮，然后到大众点评 App 粘贴</p>
  </div>

  ${itemsHTML}

  <div class="footer">
    生成时间：${new Date().toLocaleString('zh-CN')}
  </div>

  <div class="toast" id="toast">✓ 已复制到剪贴板</div>

  <script>
    function copyReview(index) {
      const reviewEl = document.getElementById('review-' + index);
      const text = reviewEl.innerText;

      // 使用 Clipboard API (现代浏览器)
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
          showToast();
        }).catch(() => {
          // Fallback
          fallbackCopy(text);
        });
      } else {
        // Fallback for older browsers or non-HTTPS
        fallbackCopy(text);
      }
    }

    function fallbackCopy(text) {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        showToast();
      } catch (err) {
        alert('复制失败，请手动长按选择文本复制');
      }
      document.body.removeChild(textarea);
    }

    function showToast() {
      const toast = document.getElementById('toast');
      toast.style.display = 'block';
      setTimeout(() => {
        toast.style.display = 'none';
      }, 2000);
    }
  </script>
</body>
</html>`;
}

function renderStarsHTML(rating: number): string {
  const full = Math.floor(rating);
  const empty = 5 - full;
  return '⭐'.repeat(full) + '☆'.repeat(empty);
}

function escapeHTML(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
