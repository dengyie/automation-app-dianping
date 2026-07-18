import { loadConfig } from '../storage/config.js';
import { loadDraftByUrl, saveDraft, createDraft, type DraftFile } from '../storage/drafts.js';
import { generateReview } from '../ai/client.js';
import { validateReview } from '../utils/validate.js';
import { info, success, warn, error, divider } from '../utils/logger.js';

export async function generateCommand(url: string, shopName?: string) {
  if (!url.includes('/shop/')) {
    warn('URL 似乎不是有效的店铺链接。');
    return;
  }

  const config = await loadConfig();

  // Find existing draft
  let draft: DraftFile | null = await loadDraftByUrl(url);
  if (!draft || !draft.scrapedData) {
    error('未找到抓取数据，请先运行 scrape 命令。');
    return;
  }

  // If user provided a shop name and the scraped name is just a URL, fix it
  if (shopName) {
    draft.shopName = shopName;
    draft.scrapedData.name = shopName;
  } else if (!draft.shopName || draft.shopName.startsWith('http')) {
    warn('店名未识别到，建议手动提供: generate <URL> "店名"');
  }

  divider('AI 生成评价中...');

  try {
    const result = await generateReview(draft.scrapedData, config);

    const validationError = validateReview(result);
    if (validationError) {
      warn(`验证警告: ${validationError}`);
    }

    draft.draft.content = result.content;
    draft.draft.ratings = result.ratings;
    draft.draft.status = 'generated';
    await saveDraft(draft);

    // Show result
    divider('生成的评价');
    console.log(`\n${result.content}\n`);
    console.log(`评分: 口味${result.ratings.taste} 环境${result.ratings.environment} 服务${result.ratings.service}`);
    divider();

    // Interactive edit
    console.log('\n编辑评价？（直接回车确认 / 输入新文本替换 / :q 退出）');
    const input = await promptLine();

    if (input === ':q') {
      info('已取消，草稿保留。');
      return;
    }

    if (input.trim()) {
      draft.draft.content = input.trim();
      draft.draft.status = 'edited';
    } else {
      draft.draft.status = 'edited'; // confirmed as-is
    }
    draft.draft.editedAt = new Date().toISOString();
    await saveDraft(draft);
    success(`草稿 ${draft.id} 已确认，可以运行 publish 命令发布。`);

  } catch (err) {
    error(`AI 生成失败: ${err}`);
  }
}

function promptLine(): Promise<string> {
  return new Promise((resolve) => {
    const { stdin } = process;
    if (!stdin.isTTY) {
      resolve('');
      return;
    }
    let input = '';
    stdin.setRawMode(true);
    stdin.resume();
    stdin.setEncoding('utf8');
    const onData = (key: string) => {
      if (key === '\r' || key === '\n') {
        stdin.removeListener('data', onData);
        stdin.setRawMode(false);
        stdin.pause();
        process.stdout.write('\n');
        resolve(input);
      } else if (key === '') {
        // Ctrl+C
        stdin.removeListener('data', onData);
        stdin.setRawMode(false);
        stdin.pause();
        process.stdout.write('\n');
        resolve(':q');
      } else if (key === '') {
        // Backspace
        if (input.length > 0) {
          input = input.slice(0, -1);
          process.stdout.write('\b \b');
        }
      } else {
        input += key;
        process.stdout.write(key);
      }
    };
    stdin.on('data', onData);
  });
}
