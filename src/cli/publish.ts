import { createBrowser, createContext } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { loadDraft, saveDraft, type DraftFile } from '../storage/drafts.js';
import { addEntry } from '../storage/history.js';
import { loadState, saveState, canPublishToday, minutesSinceLastPublish } from '../storage/state.js';
import { browseNaturally, typeNaturally, clickNaturally } from '../browser/humanize.js';
import { findElement } from '../browser/selectors.js';
import { SELECTORS } from '../browser/selectors.js';
import { handleCaptchaIfNeeded, detectCaptcha, solveCaptcha } from '../browser/captcha.js';
import { validateReview } from '../utils/validate.js';
import { scanPhotos } from '../photo/local.js';
import { webSearchPhotos } from '../photo/search.js';
import { info, success, warn, error, divider } from '../utils/logger.js';
import { rand, sleep } from '../utils/delay.js';

export async function publishCommand(draftId: string) {
  const config = await loadConfig();

  // Load draft
  const draft = await loadDraft(draftId);
  if (!draft) {
    error(`草稿不存在: ${draftId}`);
    return;
  }
  if (draft.draft.status === 'published' && draft.publishedAt) {
    error('该草稿已发布过。');
    return;
  }

  // Validate
  const validationError = validateReview(draft.draft);
  if (validationError) {
    error(`草稿验证失败: ${validationError}`);
    return;
  }

  // Pre-flight: check daily limits
  const state = await loadState();
  if (!(await canPublishToday(state, config.publishing.maxPerDay))) {
    error(`今日发布额度已用完（${state.todayPublishedCount}/${config.publishing.maxPerDay}）。明天再试。`);
    return;
  }

  const mins = await minutesSinceLastPublish(state);
  if (mins !== null && mins < config.publishing.minIntervalMinutes) {
    const remaining = Math.ceil(config.publishing.minIntervalMinutes - mins);
    error(`距上次发布仅 ${Math.floor(mins)} 分钟，需等待至少 ${remaining} 分钟。`);
    return;
  }

  // Collect photos
  let photos = draft.draft.photos;
  if (photos.length === 0) {
    photos = await scanPhotos(config.photos.localDir, draft.shopName);
    if (photos.length === 0 && config.photos.webSearchEnabled) {
      info('本地无图片，尝试网页搜索...');
      const browser = await createBrowser(config);
      const context = await createContext(browser, config, config.account.sessionFile);
      try {
        const query = draft.shopName || draft.scrapedData?.recommendedDishes?.[0] || '';
        photos = await webSearchPhotos(browser, context, query, 3);
      } finally {
        await context.close();
        await browser.close();
      }
    }
  }

  divider(`发布评价: ${draft.shopName}`);

  // Launch browser
  const browser = await createBrowser(config);
  const context = await createContext(browser, config, config.account.sessionFile);

  try {
    const page = await context.newPage();

    // Phase 1: Natural browsing
    info('阶段1: 模拟浏览...');
    await page.goto('https://www.dianping.com/', { waitUntil: 'domcontentloaded' });
    await sleep(rand(2000, 5000));

    // Validate session is still alive
    const loggedIn = await findElement(page, SELECTORS.LOGIN_INDICATOR, 3000);
    if (!loggedIn) {
      error('Session 已过期，请先运行 login 重新登录。');
      return;
    }

    // Navigate to shop — wait for JS to render
    info(`导航到: ${draft.shopUrl}`);
    await page.goto(draft.shopUrl, { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(rand(3000, 5000));

    // Handle captcha/verification redirect (verify.meituan.com)
    if (!await handleCaptchaIfNeeded(page, config)) {
      error('导航时遇到验证码且无法解决，发布中止。');
      return;
    }

    // Wait for shop content
    try {
      await page.waitForSelector('h1, [class*="shop-name"]', { timeout: 10000 });
    } catch {
      warn('店铺页面内容可能未完全加载，继续尝试...');
    }

    // Browse naturally
    const humanizeConfig = {
      typingSpeedMs: config.publishing.typingSpeedMs,
      browseBeforeWriteSeconds: config.publishing.browseBeforeWriteSeconds,
    };
    await browseNaturally(page, humanizeConfig);

    // Phase 2: Click review button
    info('阶段2: 进入写评价...');
    const reviewBtnClicked = await clickReviewButton(page);
    if (!reviewBtnClicked) {
      error('找不到"写评价"按钮，可能需要手动操作。');
      return;
    }
    await sleep(rand(2000, 4000));

    // Phase 2.5: Handle captcha if triggered
    if (!await handleCaptchaIfNeeded(page, config)) {
      error('验证码无法解决，发布中止。');
      return;
    }
    info('阶段3: 输入评价...');
    const textarea = (await findElement(page, SELECTORS.REVIEW_TEXTAREA, 5000))
      || page.locator('textarea, [contenteditable="true"]').first();
    try {
      await textarea.waitFor({ state: 'visible', timeout: 5000 });
      await textarea.click();
      await sleep(rand(500, 1500));
      await typeNaturally(page, draft.draft.content, humanizeConfig);
      info('评价输入完成');
    } catch {
      error('找不到输入框，检查页面是否正常加载。');
      return;
    }

    // Phase 4: Set ratings
    info('阶段4: 设置评分...');
    await setRatings(page, draft.draft.ratings.taste, draft.draft.ratings.environment, draft.draft.ratings.service);
    await sleep(rand(2000, 4000));

    // Phase 5: Upload photos
    if (photos.length > 0) {
      info(`阶段5: 上传 ${photos.length} 张图片...`);
      await uploadPhotos(page, photos.slice(0, config.photos.maxPhotos));
      await sleep(rand(3000, 6000));
    }

    // Phase 6: Submit
    info('阶段6: 提交...');
    await sleep(rand(2000, 4000));
    await clickSubmit(page);

    // Verify success
    await sleep(rand(3000, 5000));

    // Phase 6.5: Handle captcha if triggered after submit
    const hadCaptcha = await detectCaptcha(page);
    if (hadCaptcha) {
      if (!await solveCaptcha(page, config)) {
        warn('提交时遇到验证码，可能未发布成功。草稿已保留。');
        return;
      }
      // Captcha intercepted the submit — re-click and wait
      await sleep(rand(1000, 2000));
      await clickSubmit(page);
      await sleep(rand(3000, 5000));
    }

    // Verify success via specific selectors, not raw HTML substring
    const successEl = await findElement(page, SELECTORS.SUCCESS_INDICATOR, 5000);
    const isSuccess = !!successEl || page.url().includes('review');

    if (isSuccess) {
      // Update records
      draft.draft.status = 'published';
      draft.publishedAt = new Date().toISOString();
      await saveDraft(draft);

      await addEntry({
        shopName: draft.shopName,
        shopUrl: draft.shopUrl,
        draftId: draft.id,
        content: draft.draft.content,
        ratings: draft.draft.ratings,
        photosCount: photos.length,
        publishedAt: draft.publishedAt,
      });

      state.todayPublishedCount++;
      state.lastPublishedTimestamp = draft.publishedAt;
      await saveState(state);

      divider();
      success(`发布成功！${draft.shopName}`);
      console.log(`  今日进度: ${state.todayPublishedCount}/${config.publishing.maxPerDay}`);
    } else {
      warn('发布状态不确定，请手动检查。草稿已保留。');
    }

  } catch (err) {
    error(`发布过程出错: ${err}`);
  } finally {
    await browser.close();
  }
}

async function clickReviewButton(page: any): Promise<boolean> {
  const selectors = ['text=写点评', 'text=写评价', 'text=我要点评', 'button:has-text("点评")', 'a:has-text("点评")'];
  for (const sel of selectors) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.isVisible({ timeout: 3000 })) {
        await clickNaturally(page, sel);
        await sleep(2000);
        return true;
      }
    } catch {
      continue;
    }
  }
  return false;
}

async function setRatings(page: any, taste: number, environment: number, service: number) {
  const ratings = [
    { label: SELECTORS.RATING_TASTE, value: taste },
    { label: SELECTORS.RATING_ENVIRONMENT, value: environment },
    { label: SELECTORS.RATING_SERVICE, value: service },
  ];

  for (const { label, value } of ratings) {
    try {
      // Find the rating row by label text
      const row = await findElement(page, label, 3000);
      if (!row) { warn(`找不到评分行: ${label[0]}`); continue; }

      // Find star-like elements within this row's scope
      const stars = await row.$$('img, span[class*="star"], li, a');
      if (stars.length >= value) {
        const target = stars[value - 1];
        await target.scrollIntoViewIfNeeded();
        await sleep(rand(200, 500));
        await target.click();
      } else {
        warn(`评分行星星数不足: ${stars.length} < ${value}`);
      }
      await sleep(rand(500, 1500));
    } catch {
      warn(`评分设置失败: ${label[0]}`);
    }
  }
}

async function uploadPhotos(page: any, photos: string[]) {
  try {
    // Try direct input[type="file"] first (no dialog needed)
    const fileInput = page.locator('input[type="file"]').first();
    try {
      await fileInput.waitFor({ state: 'attached', timeout: 3000 });
      await fileInput.setInputFiles(photos);
      info(`已上传 ${photos.length} 张图片`);
      return;
    } catch { /* no direct file input, try button approach */ }

    // Button approach: find button, then listen for filechooser, then click
    const uploadBtn = await findElement(page, SELECTORS.PHOTO_UPLOAD, 3000);
    if (!uploadBtn) { warn('找不到图片上传入口'); return; }

    const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
    await uploadBtn.click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(photos);
    info(`已上传 ${photos.length} 张图片`);
  } catch {
    warn('图片上传可能失败，请手动添加。');
  }
}

async function clickSubmit(page: any) {
  try {
    const submitBtn = await findElement(page, SELECTORS.SUBMIT_BUTTON, 5000);
    if (!submitBtn) { warn('找不到发布按钮'); return; }
    await submitBtn.scrollIntoViewIfNeeded();
    await sleep(rand(200, 500));
    await submitBtn.click();
    info('已点击发布按钮');
  } catch {
    warn('找不到发布按钮，请手动点击。');
  }
}
