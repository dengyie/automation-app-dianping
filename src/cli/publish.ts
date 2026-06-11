import { createBrowser, createContext } from '../browser/launch.js';
import { loadConfig } from '../storage/config.js';
import { loadDraft, saveDraft, type DraftFile } from '../storage/drafts.js';
import { addEntry } from '../storage/history.js';
import { loadState, saveState, canPublishToday, minutesSinceLastPublish } from '../storage/state.js';
import { browseNaturally, typeNaturally, clickNaturally } from '../browser/humanize.js';
import { handleCaptchaIfNeeded } from '../browser/captcha.js';
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

    // Navigate to shop
    await page.goto(draft.shopUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(2000);

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
      await browser.close();
      return;
    }
    await sleep(rand(2000, 4000));

    // Phase 2.5: Handle captcha if triggered
    if (!await handleCaptchaIfNeeded(page, config)) {
      error('验证码无法解决，发布中止。');
      await browser.close();
      return;
    }
    info('阶段3: 输入评价...');
    const textarea = page.locator('textarea, [contenteditable="true"]').first();
    try {
      await textarea.waitFor({ state: 'visible', timeout: 5000 });
      await textarea.click();
      await sleep(rand(500, 1500));
      await typeNaturally(page, draft.draft.content, humanizeConfig);
      info('评价输入完成');
    } catch {
      error('找不到输入框，检查页面是否正常加载。');
      await browser.close();
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
    if (!await handleCaptchaIfNeeded(page, config)) {
      warn('提交时遇到验证码，可能未发布成功。草稿已保留。');
      return;
    }

    const pageContent = await page.content();
    const isSuccess = pageContent.includes('成功') || pageContent.includes('审核') || page.url().includes('review');

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
  // Try to find star rows and click the appropriate star
  try {
    // Look for star elements - usually clickable spans with star icons
    const starRows = page.locator('[class*="star"], li:has(img)');
    const rows = await starRows.all();

    if (rows.length >= 3) {
      // Assume first 3 rows are 口味, 环境, 服务
      await clickStarInRow(rows[0], taste);
      await sleep(rand(500, 1500));
      await clickStarInRow(rows[1], environment);
      await sleep(rand(500, 1500));
      await clickStarInRow(rows[2], service);
    }
  } catch {
    warn('自动评分可能失败，请手动调整。');
  }
}

async function clickStarInRow(row: any, rating: number) {
  const stars = row.locator('[class*="star"], img, span');
  const count = await stars.count();
  if (count >= rating) {
    const targetStar = stars.nth(rating - 1);
    await targetStar.scrollIntoViewIfNeeded();
    await targetStar.click();
  }
}

async function uploadPhotos(page: any, photos: string[]) {
  try {
    const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 });
    const uploadBtn = page.locator('text=添加图片, text=上传图片, [class*="upload"], input[type="file"]').first();
    await uploadBtn.click({ timeout: 3000 });
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(photos);
    info(`已上传 ${photos.length} 张图片`);
  } catch {
    warn('图片上传可能失败，请手动添加。');
  }
}

async function clickSubmit(page: any) {
  try {
    const submitBtn = page.locator('button:has-text("发布"), button:has-text("提交"), text=发布评价').first();
    await submitBtn.waitFor({ state: 'visible', timeout: 5000 });
    await clickNaturally(page, 'button:has-text("发布")');
    info('已点击发布按钮');
  } catch {
    warn('找不到发布按钮，请手动点击。');
  }
}
