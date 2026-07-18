import { createAppSession, closeAppSession, launchDianping, isLoggedIn } from '../app/driver.js';
import { APP_SELECTORS, findElement, tapElement, typeText } from '../app/selectors.js';
import { loadConfig } from '../storage/config.js';
import { loadDraft, saveDraft } from '../storage/drafts.js';
import { addEntry } from '../storage/history.js';
import { loadState, saveState, canPublishToday, minutesSinceLastPublish } from '../storage/state.js';
import { validateReview } from '../utils/validate.js';
import { info, success, warn, error, divider } from '../utils/logger.js';
import { sleep, rand } from '../utils/delay.js';

export async function appPublishCommand(draftId: string, deviceUdid?: string) {
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

  // Check daily limits
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

  divider(`发布评价: ${draft.shopName}`);

  let session;
  try {
    // Create Appium session
    session = await createAppSession(config, deviceUdid);
    const { driver } = session;

    // Launch app
    await launchDianping(driver);

    // Check login status
    info('检查登录状态...');
    if (!(await isLoggedIn(driver))) {
      error('未登录。请先在 App 内登录，然后重试。');
      return;
    }

    // Phase 1: Search shop
    info(`步骤 1: 搜索店铺 "${draft.shopName}"...`);
    await sleep(rand(2000, 3000));

    // Tap search bar
    if (!(await tapElement(driver, APP_SELECTORS.SEARCH_BAR, 5000))) {
      error('找不到搜索栏');
      return;
    }
    await sleep(rand(1000, 2000));

    // Type shop name
    if (!(await typeText(driver, APP_SELECTORS.SEARCH_INPUT, draft.shopName, 5000))) {
      error('找不到搜索输入框');
      return;
    }
    await sleep(rand(500, 1000));

    // Press enter to search
    await driver.execute('mobile: performEditorAction', { action: 'search' });
    await sleep(rand(3000, 5000));

    // Phase 2: Click shop in results
    info('步骤 2: 点击搜索结果中的店铺...');
    const shopEl = await findElement(driver, APP_SELECTORS.SHOP_NAME(draft.shopName), 10000);
    if (!shopEl) {
      error(`搜索结果中未找到店铺: ${draft.shopName}`);
      return;
    }
    await shopEl.click();
    await sleep(rand(3000, 5000));

    // Phase 3: Click "写评价" button
    info('步骤 3: 点击"写评价"按钮...');
    if (!(await tapElement(driver, APP_SELECTORS.WRITE_REVIEW_BTN, 10000))) {
      error('找不到"写评价"按钮');
      return;
    }
    await sleep(rand(2000, 4000));

    // Phase 4: Fill review content
    info('步骤 4: 填写评价内容...');
    if (!(await typeText(driver, APP_SELECTORS.REVIEW_TEXTAREA, draft.draft.content, 5000))) {
      error('找不到评价输入框');
      return;
    }
    await sleep(rand(2000, 3000));

    // Phase 5: Set ratings
    info('步骤 5: 设置评分...');
    await setRatings(driver, draft.draft.ratings.taste, draft.draft.ratings.environment, draft.draft.ratings.service);
    await sleep(rand(2000, 3000));

    // Phase 6: Upload photos (if any)
    if (draft.draft.photos.length > 0) {
      info(`步骤 6: 上传 ${draft.draft.photos.length} 张图片...`);
      await uploadPhotos(driver, draft.draft.photos);
      await sleep(rand(2000, 3000));
    }

    // Phase 7: Submit
    info('步骤 7: 提交评价...');
    if (!(await tapElement(driver, APP_SELECTORS.SUBMIT_BTN, 5000))) {
      error('找不到提交按钮');
      return;
    }
    await sleep(rand(3000, 5000));

    // Check success
    const successEl = await findElement(driver, APP_SELECTORS.SUCCESS_MSG, 5000);
    if (successEl) {
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
        photosCount: draft.draft.photos.length,
        publishedAt: draft.publishedAt,
      });

      state.todayPublishedCount++;
      state.lastPublishedTimestamp = draft.publishedAt;
      await saveState(state);

      divider();
      success(`发布成功！${draft.shopName}`);
      console.log(`  今日进度: ${state.todayPublishedCount}/${config.publishing.maxPerDay}`);
    } else {
      warn('发布状态不确定，请在 App 中手动检查。');
    }
  } catch (err) {
    error(`发布过程出错: ${err}`);
  } finally {
    if (session) {
      await closeAppSession(session);
    }
  }
}

async function setRatings(driver: WebdriverIO.Browser, taste: number, environment: number, service: number) {
  const ratings = [
    { label: '口味', value: taste },
    { label: '环境', value: environment },
    { label: '服务', value: service },
  ];

  for (const { label, value } of ratings) {
    try {
      // Find rating label
      const labelEl = await findElement(driver, APP_SELECTORS.RATING_LABEL(label), 3000);
      if (!labelEl) {
        warn(`找不到评分项: ${label}`);
        continue;
      }

      // Find star container near the label
      const parent = await labelEl.parentElement();
      const stars = await parent.$$('android.widget.ImageView');

      if (stars.length >= value) {
        await stars[value - 1].click();
        await sleep(rand(500, 1000));
      } else {
        warn(`评分项 ${label} 星星数不足: ${stars.length} < ${value}`);
      }
    } catch (err) {
      warn(`设置评分失败 (${label}): ${err}`);
    }
  }
}

async function uploadPhotos(driver: WebdriverIO.Browser, photoPaths: string[]) {
  try {
    // Click add photo button
    if (!(await tapElement(driver, APP_SELECTORS.ADD_PHOTO_BTN, 5000))) {
      warn('找不到添加图片按钮');
      return;
    }
    await sleep(rand(1000, 2000));

    // Push photos to device first
    for (let i = 0; i < photoPaths.length; i++) {
      const remotePath = `/sdcard/Pictures/dianping_${Date.now()}_${i}.jpg`;
      info(`推送图片到设备: ${photoPaths[i]} -> ${remotePath}`);
      await driver.pushFile(remotePath, photoPaths[i]);
    }

    await sleep(rand(1000, 2000));

    // Select photos from gallery
    // Note: This is simplified - actual implementation depends on photo picker UI
    const thumbs = await driver.$$(APP_SELECTORS.PHOTO_THUMBNAIL(0));
    for (let i = 0; i < Math.min(photoPaths.length, thumbs.length); i++) {
      await thumbs[i].click();
      await sleep(rand(300, 700));
    }

    // Confirm selection
    await tapElement(driver, APP_SELECTORS.PHOTO_CONFIRM, 3000);
    await sleep(rand(1000, 2000));

    info(`已选择 ${Math.min(photoPaths.length, thumbs.length)} 张图片`);
  } catch (err) {
    warn(`图片上传可能失败: ${err}`);
  }
}
