import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname } from 'node:path';

const DATA_DIR = 'data';
const CONFIG_PATH = `${DATA_DIR}/config.json`;

export interface CaptchaSelectors {
  slider_btn: string;
  slider_track: string;
  bg_img: string;
  piece_img: string;
  track_width: string;
  slider_alt: string[];
  result_url_pattern: string[];
  success_code: number;
}

export interface AppConfig {
  account: {
    name: string;
    sessionFile: string;
  };
  captcha: {
    enabled: boolean;
    pythonPath: string;
    selectors: CaptchaSelectors;
    maxRetries: number;
  };
  publishing: {
    maxPerDay: number;
    minIntervalMinutes: number;
    maxIntervalMinutes: number;
    minReviewChars: number;
    typingSpeedMs: { min: number; max: number };
    browseBeforeWriteSeconds: { min: number; max: number };
  };
  ai: {
    model: string;
    fallbackModel: string;
    maxTokens: number;
    temperature: number;
  };
  photos: {
    localDir: string;
    webSearchEnabled: boolean;
    maxPhotos: number;
  };
  browser: {
    headless: boolean;
    executablePath: string;
    viewport: { width: number; height: number };
    locale: string;
    timezoneId: string;
  };
}

export const DEFAULTS: AppConfig = {
  account: {
    name: 'default',
    sessionFile: 'data/sessions/default.json',
  },
  captcha: {
    enabled: true,
    pythonPath: 'python3',
    selectors: {
      slider_btn: '.geetest_slider_button',
      slider_track: '.geetest_slider_track',
      bg_img: '.geetest_canvas_bg canvas',
      piece_img: '.geetest_canvas_slice canvas',
      track_width: '.geetest_slider_track',
      slider_alt: ['.geetest_slider_button', '.geetest_btn'],
      result_url_pattern: ['/api/v4/slider'],
      success_code: 0,
    },
    maxRetries: 3,
  },
  publishing: {
    maxPerDay: 2,
    minIntervalMinutes: 60,
    maxIntervalMinutes: 120,
    minReviewChars: 100,
    typingSpeedMs: { min: 40, max: 120 },
    browseBeforeWriteSeconds: { min: 20, max: 45 },
  },
  ai: {
    model: 'deepseek-v4-pro',
    fallbackModel: 'deepseek-v4-flash',
    maxTokens: 2000,
    temperature: 0.8,
  },
  photos: {
    localDir: 'data/photos',
    webSearchEnabled: true,
    maxPhotos: 6,
  },
  browser: {
    headless: false,
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    viewport: { width: 1280, height: 900 },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  },
};

export async function loadConfig(): Promise<AppConfig> {
  if (!existsSync(CONFIG_PATH)) {
    await saveConfig(DEFAULTS);
    return { ...DEFAULTS };
  }
  const raw = await readFile(CONFIG_PATH, 'utf-8');
  const userConfig = JSON.parse(raw);
  return deepMerge(DEFAULTS, userConfig);
}

export async function saveConfig(config: AppConfig): Promise<void> {
  await ensureDir(dirname(CONFIG_PATH));
  await writeFile(CONFIG_PATH, JSON.stringify(config, null, 2), 'utf-8');
}

function deepMerge<T extends Record<string, any>>(base: T, override: Partial<T>): T {
  const result = { ...base };
  for (const key of Object.keys(override) as (keyof T)[]) {
    if (override[key] && typeof override[key] === 'object' && !Array.isArray(override[key])) {
      (result as any)[key] = deepMerge(base[key], override[key] as any);
    } else {
      (result as any)[key] = override[key];
    }
  }
  return result;
}

async function ensureDir(dir: string): Promise<void> {
  if (!existsSync(dir)) {
    await mkdir(dir, { recursive: true });
  }
}
