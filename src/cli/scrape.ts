import { createBrowser, createContext } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { createDraft, saveDraft, type ScrapedShopData } from '../storage/drafts.js';
import { callAI } from '../ai/client.js';
import { scrollNaturally } from '../browser/humanize.js';
import { info, success, warn, divider } from '../utils/logger.js';
import { sleep } from '../utils/delay.js';

const PARSE_SYSTEM_PROMPT = `你是一个数据提取助手。从大众点评店铺页面文本中提取结构化信息。

输出严格 JSON 格式：
{
  "name": "店名",
  "address": "地址",
  "avgPricePerPerson": 人均价格数字或null,
  "category": "菜系类别",
  "overallRating": 总评分数字或null,
  "ratings": { "taste": 口味评分, "environment": 环境评分, "service": 服务评分 },
  "recommendedDishes": ["推荐菜1", "推荐菜2"],
  "features": ["特色标签"],
  "sampleReviews": [{"content": "评价内容片段"}]
}

注意：
- 评分数字不要带"分"字，直接提取数值
- 人均价格只提取数字
- 推荐菜只要菜名，不要其他文字
- 如果信息不存在则填null或空数组`;

// Dianping shop pages use CSS obfuscation to prevent scraping.
// This function tries multiple strategies to extract shop data.
async function extractShopData(page: any, url: string, config: any): Promise<{ data: ScrapedShopData; quality: 'api' | 'text' | 'minimal' }> {
  const pageTitle = await page.title();
  const shopId = url.match(/\/shop\/([A-Za-z0-9]+)/)?.[1] || '';

  // Strategy 1: Try internal API (most reliable, returns clean JSON)
  try {
    const apiData = await page.evaluate(async (shopUuid: string) => {
      const endpoints = [
        `https://m.dianping.com/wxmapi/shop/shopservice?device_system=MACINTOSH&lat=0&lng=0&shopUuid=${shopUuid}`,
        `https://m.dianping.com/wxmapi/shop/basicinfo?shopUuid=${shopUuid}`,
      ];

      const results: any = {};
      for (const ep of endpoints) {
        try {
          const resp = await fetch(ep);
          const text = await resp.text();
          results[ep] = text.slice(0, 2000);
        } catch { /* ignore */ }
      }
      return results;
    }, shopId);

    // Parse any useful API data
    const apiText = Object.values(apiData).join('\n');
    if (apiText.length > 100) {
      const userMsg = `店铺URL: ${url}\n页面标题: ${pageTitle}\n\nAPI响应数据:\n${apiText}`;
      const rawResponse = await callAI(PARSE_SYSTEM_PROMPT, userMsg, config);
      const parsed = parseAIResponse(rawResponse);
      return {
        data: {
          name: parsed.name || cleanTitle(pageTitle) || url,
          address: parsed.address || '',
          avgPricePerPerson: parsed.avgPricePerPerson,
          category: parsed.category || '',
          overallRating: parsed.overallRating,
          ratings: parsed.ratings || { taste: null, environment: null, service: null },
          recommendedDishes: parsed.recommendedDishes || [],
          features: parsed.features || [],
          sampleReviews: parsed.sampleReviews || [],
        },
        quality: 'api',
      };
    }
  } catch { /* fall through */ }

  // Strategy 2: Extract visible page text (may be empty due to CSS obfuscation)
  const pageText = await page.evaluate(() => {
    const body = document.body;
    if (!body) return '';
    const clone = body.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());
    return clone.innerText.slice(0, 8000);
  });

  if (pageText.length > 300) {
    info(`页面文本: ${pageText.length} 字符`);
    try {
      const userMsg = `店铺URL: ${url}\n页面标题: ${pageTitle}\n\n页面文本:\n${pageText}`;
      const rawResponse = await callAI(PARSE_SYSTEM_PROMPT, userMsg, config);
      const parsed = parseAIResponse(rawResponse);
      return {
        data: {
          name: parsed.name || cleanTitle(pageTitle) || url,
          address: parsed.address || '',
          avgPricePerPerson: parsed.avgPricePerPerson,
          category: parsed.category || '',
          overallRating: parsed.overallRating,
          ratings: parsed.ratings || { taste: null, environment: null, service: null },
          recommendedDishes: parsed.recommendedDishes || [],
          features: parsed.features || [],
          sampleReviews: parsed.sampleReviews || [],
        },
        quality: 'text',
      };
    } catch { /* fall through */ }
  }

  // Strategy 3: Minimal data (shop has CSS protection)
  warn('店铺页面受CSS反爬保护，使用最小数据');
  return {
    data: {
      name: cleanTitle(pageTitle) || url,
      address: '',
      avgPricePerPerson: null,
      category: '',
      overallRating: null,
      ratings: { taste: null, environment: null, service: null },
      recommendedDishes: [],
      features: [],
      sampleReviews: [],
    },
    quality: 'minimal',
  };
}

function cleanTitle(title: string): string {
  return title
    .replace(/[-–—|【】].*/g, '')
    .replace(/大众点评.*/g, '')
    .replace(/\[undefined\]/g, '')
    .trim() || '';
}

function parseAIResponse(raw: string): any {
  let jsonStr = raw;
  const match = raw.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (match) jsonStr = match[1];
  return JSON.parse(jsonStr.trim());
}

export async function scrapeCommand(url: string, shopName?: string) {
  if (!url.includes('/shop/')) {
    warn('URL 似乎不是有效的店铺链接，请确认包含 /shop/ 路径。');
    return;
  }

  const config = await loadConfig();
  const sessionPath = config.account.sessionFile;

  info(`抓取店铺: ${url}${shopName ? ` (${shopName})` : ''}`);

  const browser = await createBrowser(config);
  const context = await createContext(browser, config, sessionPath);

  try {
    const page = await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(3000);

    // Scroll to trigger lazy loading
    await scrollNaturally(page);

    const { data: scrapedData, quality } = await extractShopData(page, url, config);

    // Use user-provided name if available
    if (shopName) {
      scrapedData.name = shopName;
    }

    const finalName = scrapedData.name || shopName || url;
    const draft = createDraft(url, finalName);
    draft.scrapedAt = new Date().toISOString();
    draft.scrapedData = scrapedData;
    await saveDraft(draft);

    divider('抓取结果');
    console.log(`  数据质量: ${quality === 'api' ? '✅ API提取' : quality === 'text' ? '⚠️ 页面文本' : '❌ 最小数据'}`);
    console.log(`  店名:     ${scrapedData.name}`);
    console.log(`  类别:     ${scrapedData.category || '未知'}`);
    console.log(`  地址:     ${scrapedData.address || '未知'}`);
    console.log(`  人均:     ${scrapedData.avgPricePerPerson ? '¥' + scrapedData.avgPricePerPerson : '未知'}`);
    console.log(`  评分:     ${scrapedData.overallRating || '未知'} (口味${scrapedData.ratings.taste || '?'} 环境${scrapedData.ratings.environment || '?'} 服务${scrapedData.ratings.service || '?'})`);
    console.log(`  推荐菜:   ${scrapedData.recommendedDishes.join('、') || '无'}`);
    console.log(`  评价参考: ${scrapedData.sampleReviews.length} 条`);
    divider();

    if (quality === 'minimal') {
      warn('提示: 店铺数据不足，generate 阶段 AI 将根据店名自行补充。');
      warn('如果知道具体信息（人均、推荐菜），可在生成后编辑草稿。');
    }

    success(`草稿已保存: ${draft.id}`);

  } finally {
    await browser.close();
  }
}
