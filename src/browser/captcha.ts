import { execFileSync } from 'node:child_process';
import type { Page } from 'playwright';
import { SELECTORS } from './selectors.js';
import type { AppConfig } from '../storage/config.js';
import { info, warn, error } from '../utils/logger.js';
import { sleep, rand } from '../utils/delay.js';

export async function detectCaptcha(page: Page): Promise<boolean> {
  for (const sel of SELECTORS.CAPTCHA) {
    try {
      const el = page.locator(sel).first();
      if (await el.isVisible({ timeout: 500 })) return true;
    } catch { /* next selector */ }
  }
  return false;
}

export async function solveCaptcha(page: Page, config: AppConfig): Promise<boolean> {
  const browser = page.context().browser();
  if (!browser) {
    error('浏览器连接已断开，无法获取 CDP endpoint');
    return false;
  }
  const wsEndpoint = browser.wsEndpoint();
  if (!wsEndpoint) {
    error('无法获取浏览器 CDP endpoint');
    return false;
  }

  for (let attempt = 1; attempt <= config.captcha.maxRetries; attempt++) {
    info(`验证码求解第 ${attempt}/${config.captcha.maxRetries} 次尝试...`);

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

      // Extract JSON from stdout (skip any non-JSON preamble from Python)
      const jsonStart = stdout.indexOf('{');
      const jsonEnd = stdout.lastIndexOf('}');
      if (jsonStart === -1 || jsonEnd === -1) {
        warn(`slidex 输出不含 JSON: ${stdout.slice(0, 200)}`);
        continue;
      }

      const result = JSON.parse(stdout.slice(jsonStart, jsonEnd + 1));
      if (result && result.success) {
        info(`验证码已解决 (${result.elapsed_ms}ms)`);
        await sleep(rand(1500, 3000));
        return true;
      }

      warn(`求解失败: ${result?.error || 'unknown'}`);
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
