import { execFileSync } from 'node:child_process';
import type { Page } from 'playwright';
import { SELECTORS } from './selectors.js';
import type { AppConfig } from '../storage/config.js';
import { info, warn, error } from '../utils/logger.js';
import { sleep, rand } from '../utils/delay.js';

// ── Meituan/Dianping native slider (verify.meituan.com) ──
const MEITUAN_SELECTORS = {
  slider_btn: '#yodaBox',
  slider_track: '#yodaBoxWrapper',
  wrapper: '.yoda-slider-wrapper',
  title: '.slider-title',
};

export async function detectCaptcha(page: Page): Promise<boolean> {
  // Check URL first — meituan verification redirects to verify.meituan.com
  if (page.url().includes('verify.meituan.com')) return true;

  for (const sel of SELECTORS.CAPTCHA) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 500 })) return true;
    } catch { /* next selector */ }
  }
  return false;
}

// ── Solve meituan native slider (simple drag, no image matching) ──
async function solveMeituanSlider(page: Page): Promise<boolean> {
  for (let attempt = 1; attempt <= 3; attempt++) {
    info(`美团滑块验证第 ${attempt}/3 次尝试...`);

    try {
      const btn = page.locator(MEITUAN_SELECTORS.slider_btn);
      const track = page.locator(MEITUAN_SELECTORS.slider_track);

      await btn.waitFor({ state: 'visible', timeout: 5000 });
      const btnBox = await btn.boundingBox();
      const trackBox = await track.boundingBox();

      if (!btnBox || !trackBox) {
        warn('滑块元素不可见');
        continue;
      }

      const startX = btnBox.x + btnBox.width / 2;
      const startY = btnBox.y + btnBox.height / 2;
      const distance = trackBox.width - btnBox.width - 2; // -2 for margin

      // Human-like drag
      await page.mouse.move(startX + rand(-3, 3), startY + rand(-3, 3));
      await sleep(rand(100, 300));
      await page.mouse.down();
      await sleep(rand(50, 150));

      // Slide with variable speed (slow start, fast middle, slow end)
      const steps = rand(15, 25);
      for (let i = 1; i <= steps; i++) {
        const progress = i / steps;
        // Ease-in-out curve
        const eased = progress < 0.5
          ? 2 * progress * progress
          : 1 - Math.pow(-2 * progress + 2, 2) / 2;
        const x = startX + distance * eased + rand(-2, 2);
        const y = startY + rand(-3, 3);
        await page.mouse.move(x, y);
        await sleep(rand(8, 25));
      }

      // Final position + small overshoot + correction
      await page.mouse.move(startX + distance + rand(1, 4), startY + rand(-1, 1));
      await sleep(rand(50, 100));
      await page.mouse.move(startX + distance, startY);
      await sleep(rand(30, 80));
      await page.mouse.up();

      // Wait for redirect
      await sleep(rand(2000, 4000));

      // Check if we left the verify page
      const url = page.url();
      if (!url.includes('verify.meituan.com')) {
        info('美团滑块验证通过');
        return true;
      }

      warn(`仍在验证页面: ${url.slice(0, 80)}`);
    } catch (err) {
      warn(`滑块操作失败: ${err}`);
    }

    await sleep(rand(1500, 3000));
  }

  return false;
}

// ── Solve via slidex (image-based captchas: GeeTest, Shumei, etc.) ──
async function solveWithSlidex(page: Page, config: AppConfig): Promise<boolean> {
  const browser = page.context().browser();
  if (!browser) {
    error('浏览器连接已断开');
    return false;
  }
  const wsEndpoint = browser.wsEndpoint();
  if (!wsEndpoint) {
    error('无法获取 CDP endpoint');
    return false;
  }

  for (let attempt = 1; attempt <= config.captcha.maxRetries; attempt++) {
    info(`slidex 求解第 ${attempt}/${config.captcha.maxRetries} 次尝试...`);

    try {
      const args = [
        '-m', 'slidex.scripts.slide_solve_cdp',
        '--cdp-endpoint', wsEndpoint,
        '--selectors', JSON.stringify(config.captcha.selectors),
        '--cookie-id', config.account.name || 'default',
      ];

      const stdout = execFileSync(config.captcha.pythonPath, args, {
        encoding: 'utf-8',
        timeout: 60_000,
      }).trim();

      const jsonStart = stdout.indexOf('{');
      const jsonEnd = stdout.lastIndexOf('}');
      if (jsonStart === -1 || jsonEnd === -1) {
        warn(`slidex 输出不含 JSON: ${stdout.slice(0, 200)}`);
        continue;
      }

      const result = JSON.parse(stdout.slice(jsonStart, jsonEnd + 1));
      if (result && result.success) {
        info(`slidex 验证码已解决 (${result.elapsed_ms}ms)`);
        await sleep(rand(1500, 3000));
        return true;
      }

      warn(`slidex 求解失败: ${result?.error || 'unknown'}`);
    } catch (err: any) {
      const stderr = err.stderr?.toString()?.slice(0, 500) || '';
      const msg = err.message?.slice(0, 200) || '';
      error(`slidex 调用失败: ${msg}${stderr ? '\n' + stderr : ''}`);
    }

    if (attempt < config.captcha.maxRetries) {
      await sleep(rand(2000, 3000));
    }
  }

  return false;
}

// ── Main entry: detect provider and dispatch ──
export async function solveCaptcha(page: Page, config: AppConfig): Promise<boolean> {
  // Meituan native slider (verify.meituan.com)
  if (page.url().includes('verify.meituan.com') ||
      await page.locator(MEITUAN_SELECTORS.wrapper).isVisible().catch(() => false)) {
    return await solveMeituanSlider(page);
  }

  // Image-based captchas via slidex
  return await solveWithSlidex(page, config);
}

export async function handleCaptchaIfNeeded(page: Page, config: AppConfig): Promise<boolean> {
  if (!config.captcha.enabled) return true;

  const hasCaptcha = await detectCaptcha(page);
  if (!hasCaptcha) return true;

  info('检测到验证码，尝试自动解决...');
  const solved = await solveCaptcha(page, config);
  if (!solved) {
    error('验证码无法自动解决，请手动完成验证后重试。');
  }
  return solved;
}
