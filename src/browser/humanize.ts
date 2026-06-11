import { Page } from 'playwright';
import { rand, randFloat, sleep, chance } from '../utils/delay.js';

interface HumanizeConfig {
  typingSpeedMs: { min: number; max: number };
  browseBeforeWriteSeconds: { min: number; max: number };
}

// Slow, incremental scrolling
export async function scrollNaturally(page: Page, config?: HumanizeConfig) {
  const height = await page.evaluate(() => document.body.scrollHeight);
  const steps = rand(4, 8);
  for (let i = 0; i < steps; i++) {
    const scrollTo = (height / steps) * (i + 1);
    await page.evaluate((y) => window.scrollTo({ top: y, behavior: 'smooth' }), scrollTo);
    await sleep(rand(300, 1200));
  }
  // Scroll back up a bit
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await sleep(rand(500, 1500));
}

// Move mouse with intermediate waypoints (not straight line)
export async function moveMouseNaturally(page: Page, targetX: number, targetY: number) {
  const startPos = await page.evaluate(() => ({ x: window.innerWidth / 2, y: window.innerHeight / 2 }));
  const steps = rand(3, 6);
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // Bezier-like easing
    const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
    const x = startPos.x + (targetX - startPos.x) * ease + rand(-30, 30);
    const y = startPos.y + (targetY - startPos.y) * ease + rand(-20, 20);
    await page.mouse.move(x, y);
    await sleep(rand(50, 200));
  }
  await page.mouse.move(targetX, targetY);
}

// Human-like typing: variable speed, occasional pauses, simulated typos
export async function typeNaturally(
  page: Page,
  text: string,
  config: HumanizeConfig
) {
  let charsSincePause = 0;
  const pauseThreshold = rand(25, 50);

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const delay = rand(config.typingSpeedMs.min, config.typingSpeedMs.max);
    await sleep(delay);

    await page.keyboard.insertText(char);

    charsSincePause++;

    // 3% chance: thinking pause
    if (chance(0.03)) {
      await sleep(rand(800, 2000));
      charsSincePause = 0;
    }

    // Long pause every 25-50 chars
    if (charsSincePause >= pauseThreshold) {
      await sleep(rand(1000, 3000));
      // slight scroll to appear active
      await page.mouse.wheel(0, rand(-50, 50));
      charsSincePause = 0;
    }

    // 2% chance: simulate typo (delete 1-2 chars, retype)
    if (chance(0.02) && i > 2) {
      const deleteCount = rand(1, 2);
      for (let d = 0; d < deleteCount; d++) {
        await page.keyboard.press('Backspace');
        await sleep(rand(200, 500));
      }
      await sleep(rand(300, 800));
      // Retype what was deleted
      const deleted = text.slice(i - deleteCount + 1, i + 1);
      for (const c of deleted) {
        await page.keyboard.insertText(c);
        await sleep(rand(config.typingSpeedMs.min, config.typingSpeedMs.max));
      }
    }
  }
}

// Human-like browsing: scroll, hover, read
export async function browseNaturally(page: Page, config: HumanizeConfig) {
  const browseTime = rand(
    config.browseBeforeWriteSeconds.min * 1000,
    config.browseBeforeWriteSeconds.max * 1000
  );
  const deadline = Date.now() + browseTime;

  // Scroll through page
  await scrollNaturally(page, config);

  while (Date.now() < deadline) {
    await sleep(rand(2000, 5000));
    // Simulate reading by hovering over elements
    const reviewCards = page.locator('[class*="review"], [class*="comment"]');
    const count = await reviewCards.count();
    if (count > 0) {
      const idx = rand(0, count - 1);
      const card = reviewCards.nth(idx);
      const box = await card.boundingBox();
      if (box) {
        await page.mouse.move(
          box.x + rand(50, box.width - 50),
          box.y + rand(20, box.height / 2)
        );
      }
    }
    // Scroll a bit
    await page.mouse.wheel(0, rand(100, 400));
  }
}

// Click element with human-like behavior
export async function clickNaturally(page: Page, selector: string) {
  const el = page.locator(selector).first();
  await el.waitFor({ state: 'visible', timeout: 10000 });
  const box = await el.boundingBox();
  if (!box) throw new Error(`Element not found: ${selector}`);

  const targetX = box.x + rand(box.width * 0.2, box.width * 0.8);
  const targetY = box.y + rand(box.height * 0.2, box.height * 0.8);

  await moveMouseNaturally(page, targetX, targetY);
  await sleep(rand(100, 400));
  await page.mouse.click(targetX, targetY);
}
