// Centralized Dianping DOM selectors.
// Each selector has primary + fallback. Update here when the site changes.

export const SELECTORS = {
  SHOP_NAME: ['h1', '[class*="shop-name"]', '[class*="ShopName"]'],
  AVG_PRICE: ['text=人均', '[class*="avgPrice"]', '[class*="AveragePrice"]'],
  RATING_OVERALL: ['[class*="star"]', '[class*="rating"]'],
  RATING_TASTE: ['text=口味', '[class*="taste"]'],
  RATING_ENVIRONMENT: ['text=环境', '[class*="environment"]'],
  RATING_SERVICE: ['text=服务', '[class*="service"]'],
  RECOMMENDED_DISHES: ['text=推荐菜', '[class*="recommend"]'],
  REVIEW_LIST: ['[class*="review"]', '[class*="comment"]'],
  REVIEW_BUTTON: ['text=写点评', 'text=写评价', 'text=我要点评', 'button:has-text("点评")'],
  REVIEW_TEXTAREA: ['textarea', '[contenteditable="true"]', '[class*="editor"]'],
  RATING_STARS_TASTE: ['text=口味 >> xpath=following-sibling::*[1]'],
  RATING_STARS_ENV: ['text=环境 >> xpath=following-sibling::*[1]'],
  RATING_STARS_SERVICE: ['text=服务 >> xpath=following-sibling::*[1]'],
  PHOTO_UPLOAD: ['text=添加图片', 'text=上传图片', '[class*="upload"]'],
  SUBMIT_BUTTON: ['button:has-text("发布")', 'button:has-text("提交")', 'text=发布评价'],
  LOGIN_INDICATOR: ['[class*="avatar"]', '[class*="user"]', 'text=个人中心'],
  SUCCESS_INDICATOR: ['text=发布成功', 'text=评价成功', 'text=审核中'],
  CAPTCHA: ['text=验证码', 'text=滑块验证', 'text=请完成验证', 'text=拖动滑块',
    '.geetest_panel', '.geetest_wind', '.geetest_widget',
    '.yidun_modal', '.yidun_panel',
    '.captcha-wrapper', '.captcha-modal', '.verify-wrap'],
} as const;

export async function findElement(page: any, selectors: readonly string[], timeout = 5000) {
  for (const selector of selectors) {
    try {
      const el = page.locator(selector).first();
      await el.waitFor({ state: 'visible', timeout });
      return el;
    } catch {
      continue;
    }
  }
  return null;
}

export async function extractText(page: any, selectors: readonly string[]): Promise<string> {
  const el = await findElement(page, selectors, 5000);
  if (!el) return '';
  return (await el.textContent())?.trim() || '';
}

export async function extractNumber(page: any, selectors: readonly string[]): Promise<number | null> {
  const text = await extractText(page, selectors);
  if (!text) return null;
  const match = text.match(/[\d.]+/);
  return match ? parseFloat(match[0]) : null;
}
