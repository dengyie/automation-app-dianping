import type { AppConfig } from '../storage/config.js';
import type { ScrapedShopData } from '../storage/drafts.js';

function resolveApi(): { baseUrl: string; token: string } {
  const baseUrl = process.env.ANTHROPIC_BASE_URL || 'https://api.anthropic.com';
  const token = process.env.ANTHROPIC_AUTH_TOKEN || '';
  if (!token) {
    throw new Error('ANTHROPIC_AUTH_TOKEN 未设置。请在环境变量或 .env 文件中配置。');
  }
  return { baseUrl, token };
}

export async function callAI(
  systemPrompt: string,
  userMessage: string,
  config: AppConfig,
  model?: string
): Promise<string> {
  const { baseUrl, token } = resolveApi();
  const url = `${baseUrl.replace(/\/$/, '')}/v1/messages`;

  const body = {
    model: model || config.ai.model,
    max_tokens: config.ai.maxTokens,
    temperature: config.ai.temperature,
    system: systemPrompt,
    messages: [{ role: 'user', content: userMessage }],
  };

  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': token,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(`AI API 请求失败 (${resp.status}): ${errText.slice(0, 200)}`);
  }

  const data = await resp.json() as any;
  const textBlocks = data.content?.filter((b: any) => b.type === 'text') || [];
  return textBlocks.map((b: any) => b.text).join('\n');
}

export async function generateReview(
  scrapedData: ScrapedShopData,
  config: AppConfig
): Promise<{ content: string; ratings: { taste: number; environment: number; service: number } }> {
  const systemPrompt = buildSystemPrompt();
  const userMessage = buildUserMessage(scrapedData);

  let rawResponse = '';
  try {
    rawResponse = await callAI(systemPrompt, userMessage, config);
  } catch (err) {
    // Retry with fallback model
    console.log(`主模型失败，尝试备用模型 ${config.ai.fallbackModel}...`);
    rawResponse = await callAI(systemPrompt, userMessage, config, config.ai.fallbackModel);
  }

  return parseReviewResponse(rawResponse);
}

function buildSystemPrompt(): string {
  return `你是一个大众点评老用户，写评价经验丰富。你的评价风格：真实、有细节、语气自然口语化。

要求：
1. 评价需 100 字以上（中文）
2. 提到具体的菜品名称和口感，不能泛泛而谈
3. 环境和服务也要提及，但不需太长
4. 评分不能全部 5 星，要体现真实感受的区分度
5. 语气像朋友推荐，不用广告语

输出格式（严格 JSON）：
{
  "content": "评价正文...",
  "ratings": { "taste": 4, "environment": 4, "service": 4 }
}`;
}

function buildUserMessage(data: ScrapedShopData): string {
  const hasData = data.category || data.recommendedDishes.length > 0 || data.sampleReviews.length > 0;
  const parts = [`为以下店铺写一条大众点评评价：`, ``, `店名：${data.name}`];

  if (data.category) parts.push(`类别：${data.category}`);
  if (data.address) parts.push(`地址：${data.address}`);
  if (data.avgPricePerPerson) parts.push(`人均：约${data.avgPricePerPerson}元`);

  if (data.recommendedDishes.length > 0) {
    parts.push(`推荐菜：${data.recommendedDishes.join('、')}`);
  }
  if (data.features.length > 0) {
    parts.push(`特色：${data.features.join('、')}`);
  }

  if (data.sampleReviews.length > 0) {
    parts.push(``);
    parts.push(`其他用户的评价参考（了解风格和关注点即可，不要抄）：`);
    for (const r of data.sampleReviews.slice(0, 3)) {
      parts.push(`- [${r.rating}星] ${r.content.slice(0, 100)}...`);
    }
  }

  if (!hasData) {
    parts.push(``);
    parts.push(`注意：店铺详细数据不足。请你根据店名和类别，用你的知识补充该店的常见推荐菜、大概人均、环境风格等信息来写评价。务必真实可信，不要编造明显不合理的细节。`);
  }

  parts.push(``);
  parts.push(`请根据以上信息生成评价。输出严格 JSON 格式。`);

  return parts.join('\n');
}

function parseReviewResponse(raw: string): { content: string; ratings: { taste: number; environment: number; service: number } } {
  // Try to extract JSON from markdown code blocks
  let jsonStr = raw;
  const match = raw.match(/```(?:json)?\s*\n?([\s\S]*?)\n?```/);
  if (match) {
    jsonStr = match[1];
  }

  try {
    const parsed = JSON.parse(jsonStr.trim());
    return {
      content: parsed.content || '',
      ratings: {
        taste: parsed.ratings?.taste || 4,
        environment: parsed.ratings?.environment || 4,
        service: parsed.ratings?.service || 4,
      },
    };
  } catch {
    // Fallback: use raw text as content
    return {
      content: raw.trim(),
      ratings: { taste: 4, environment: 4, service: 4 },
    };
  }
}
