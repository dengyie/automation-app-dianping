/**
 * Dianping App UI Selectors
 *
 * Use UiAutomator2 selector strategies:
 * - android=new UiSelector()...  (UiAutomator API)
 * - ~accessibilityId  (accessibility label)
 * - id:com.dianping.v1:id/...  (resource ID)
 * - -android uiautomator:...  (UiAutomator expression)
 */

export const APP_SELECTORS = {
  // Home page
  HOME_TAB: '~首页',
  SEARCH_BAR: 'android=new UiSelector().resourceId("com.dianping.v1:id/search_bar")',
  SEARCH_INPUT: 'android=new UiSelector().className("android.widget.EditText")',

  // Search results
  SHOP_ITEM: 'android=new UiSelector().className("android.widget.RelativeLayout").descriptionContains("店铺")',
  SHOP_NAME: (name: string) => `android=new UiSelector().textContains("${name}")`,

  // Shop detail page
  WRITE_REVIEW_BTN: [
    '~写评价',
    'android=new UiSelector().text("写评价")',
    'android=new UiSelector().textContains("写点评")',
    'android=new UiSelector().resourceId("com.dianping.v1:id/write_review")',
  ],

  // Write review page
  REVIEW_TEXTAREA: [
    'android=new UiSelector().className("android.widget.EditText").instance(0)',
    'android=new UiSelector().resourceId("com.dianping.v1:id/review_content")',
    'android=new UiSelector().textContains("分享")',
  ],

  // Rating stars (taste, environment, service)
  RATING_LABEL: (label: string) => `android=new UiSelector().text("${label}")`,
  STAR_CONTAINER: 'android=new UiSelector().className("android.widget.LinearLayout")',
  STAR_IMAGE: (index: number) => `android=new UiSelector().className("android.widget.ImageView").instance(${index})`,

  // Photo upload
  ADD_PHOTO_BTN: [
    '~添加图片',
    'android=new UiSelector().textContains("添加图片")',
    'android=new UiSelector().resourceId("com.dianping.v1:id/add_photo")',
    'android=new UiSelector().className("android.widget.ImageView").descriptionContains("相机")',
  ],
  PHOTO_PICKER_GRID: 'android=new UiSelector().className("android.widget.GridView")',
  PHOTO_THUMBNAIL: (index: number) => `android=new UiSelector().className("android.widget.ImageView").instance(${index})`,
  PHOTO_CONFIRM: [
    '~完成',
    'android=new UiSelector().text("完成")',
    'android=new UiSelector().text("确定")',
  ],

  // Submit
  SUBMIT_BTN: [
    '~发布',
    'android=new UiSelector().text("发布")',
    'android=new UiSelector().textContains("提交")',
    'android=new UiSelector().resourceId("com.dianping.v1:id/submit")',
  ],

  // Success indicator
  SUCCESS_MSG: [
    'android=new UiSelector().textContains("发布成功")',
    'android=new UiSelector().textContains("评价成功")',
    'android=new UiSelector().textContains("审核中")',
  ],

  // Common
  BACK_BTN: 'android=new UiSelector().description("返回")',
  CLOSE_BTN: 'android=new UiSelector().description("关闭")',
  DIALOG_CONFIRM: 'android=new UiSelector().text("确定")',
  DIALOG_CANCEL: 'android=new UiSelector().text("取消")',
} as const;

/**
 * Find element with multiple selector fallbacks
 */
export async function findElement(
  driver: WebdriverIO.Browser,
  selectors: string | readonly string[],
  timeout = 5000
): Promise<WebdriverIO.Element | null> {
  const selectorArray = Array.isArray(selectors) ? selectors : [selectors];

  for (const selector of selectorArray) {
    try {
      const el = await driver.$(selector);
      await el.waitForDisplayed({ timeout });
      return el;
    } catch {
      // Try next selector
    }
  }

  return null;
}

/**
 * Wait for element and tap it
 */
export async function tapElement(
  driver: WebdriverIO.Browser,
  selectors: string | readonly string[],
  timeout = 5000
): Promise<boolean> {
  const el = await findElement(driver, selectors, timeout);
  if (!el) return false;

  await el.click();
  return true;
}

/**
 * Type text into element
 */
export async function typeText(
  driver: WebdriverIO.Browser,
  selectors: string | readonly string[],
  text: string,
  timeout = 5000
): Promise<boolean> {
  const el = await findElement(driver, selectors, timeout);
  if (!el) return false;

  await el.clearValue();
  await el.setValue(text);
  return true;
}
