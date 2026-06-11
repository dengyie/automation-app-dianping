import { execSync } from 'node:child_process';
import type { Page } from 'playwright';
import { SELECTORS } from './selectors.js';
import type { AppConfig } from '../storage/config.js';
import { info, warn, error } from '../utils/logger.js';
import { sleep } from '../utils/delay.js';

export async function detectCaptcha(page: Page): Promise<boolean> {
  for (const sel of SELECTORS.CAPTCHA) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 1000 })) return true;
    } catch { /* next selector */ }
  }
  return false;
}

export async function solveCaptcha(page: Page, config: AppConfig): Promise<boolean> {
  const wsEndpoint = page.context()?.browser()?.wsEndpoint();
  if (!wsEndpoint) {
    error('无法获取浏览器 CDP endpoint');
    return false;
  }

  for (let attempt = 1; attempt <= config.captcha.maxRetries; attempt++) {
    info(`验证码求解第 ${attempt}/${config.captcha.maxRetries} 次尝试...`);

    try {
      const selectorsJson = JSON.stringify(config.captcha.selectors);
      const cmd = [
        config.captcha.pythonPath, '-m', 'slidex.scripts.slide_solve_cdp',
        '--cdp-endpoint', wsEndpoint,
        '--selectors', `'${selectorsJson}'`,
        '--cookie-id', config.account.name || 'default',
      ].join(' ');

      const stdout = execSync(cmd, {
        encoding: 'utf-8',
        timeout: 60_000,
        stdio: ['pipe', 'pipe', 'pipe'],
      }).trim();

      const result = JSON.parse(stdout);
      if (result.success) {
        info(`验证码已解决 (${result.elapsed_ms}ms)`);
        return true;
      }

      warn(`求解失败: ${result.error || 'unknown'}`);
    } catch (err: any) {
      error(`slidex 调用失败: ${err.message?.slice(0, 200)}`);
    }

    if (attempt < config.captcha.maxRetries) {
      await sleep(2000 + Math.random() * 1000);
    }
  }

  return false;
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
