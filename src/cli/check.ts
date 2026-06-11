import { existsSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { loadConfig, DEFAULTS } from '../storage/config.js';
import { info, success, warn, error, divider } from '../utils/logger.js';

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

async function runChecks(): Promise<CheckResult[]> {
  const results: CheckResult[] = [];

  // 1. Config
  let config;
  try {
    config = await loadConfig();
    results.push({ name: '配置文件', ok: true, detail: 'data/config.json 正常' });
  } catch (err: any) {
    results.push({ name: '配置文件', ok: false, detail: `加载失败: ${err.message}` });
    return results; // can't continue without config
  }

  // 2. AI API token
  const token = process.env.ANTHROPIC_AUTH_TOKEN || '';
  if (token) {
    results.push({ name: 'API Token', ok: true, detail: `ANTHROPIC_AUTH_TOKEN 已设置 (${token.slice(0, 8)}...)` });
  } else {
    results.push({ name: 'API Token', ok: false, detail: 'ANTHROPIC_AUTH_TOKEN 未设置（scrape/generate 需要）' });
  }

  // 3. Browser path
  const browserPath = config.browser.executablePath;
  if (existsSync(browserPath)) {
    results.push({ name: '浏览器', ok: true, detail: browserPath });
  } else {
    results.push({ name: '浏览器', ok: false, detail: `路径不存在: ${browserPath}` });
  }

  // 4. Session file
  const sessionPath = config.account.sessionFile;
  if (existsSync(sessionPath)) {
    results.push({ name: 'Session', ok: true, detail: `${sessionPath} 存在` });
  } else {
    results.push({ name: 'Session', ok: false, detail: `未找到 ${sessionPath}，请先运行 login` });
  }

  // 5. Python + slidex
  try {
    const pyVersion = execSync(`${config.captcha.pythonPath} --version`, { encoding: 'utf-8', timeout: 5000 }).trim();
    results.push({ name: 'Python', ok: true, detail: pyVersion });
  } catch {
    results.push({ name: 'Python', ok: false, detail: `${config.captcha.pythonPath} 不可用` });
  }

  try {
    execSync(`${config.captcha.pythonPath} -c "import slidex"`, { encoding: 'utf-8', timeout: 5000 });
    results.push({ name: 'slidex', ok: true, detail: '验证码求解库已安装' });
  } catch {
    results.push({ name: 'slidex', ok: false, detail: 'slidex 未安装（验证码自动解决不可用）' });
  }

  // 6. Playwright
  try {
    execSync(`${config.captcha.pythonPath} -c "import playwright"`, { encoding: 'utf-8', timeout: 5000 });
    results.push({ name: 'Playwright', ok: true, detail: 'Python playwright 已安装' });
  } catch {
    results.push({ name: 'Playwright', ok: false, detail: 'Python playwright 未安装' });
  }

  // 7. Data directories
  for (const dir of ['data/drafts', 'data/photos', config.photos.localDir]) {
    if (existsSync(dir)) {
      results.push({ name: `目录 ${dir}`, ok: true, detail: '存在' });
    } else {
      results.push({ name: `目录 ${dir}`, ok: false, detail: '不存在（首次使用时自动创建）' });
    }
  }

  return results;
}

export async function checkCommand() {
  divider('环境检查');

  const results = await runChecks();
  let failures = 0;

  for (const r of results) {
    if (r.ok) {
      success(`${r.name}: ${r.detail}`);
    } else {
      warn(`${r.name}: ${r.detail}`);
      failures++;
    }
  }

  divider();
  if (failures === 0) {
    success('所有检查通过，可以开始使用。');
  } else {
    warn(`${failures} 项检查未通过，部分功能可能不可用。`);
  }
}
