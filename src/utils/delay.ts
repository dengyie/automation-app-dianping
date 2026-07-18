export function rand(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export function randFloat(min: number, max: number): number {
  return Math.random() * (max - min) + min;
}

export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export async function jitter(baseMs: number, pct: number = 0.3): Promise<void> {
  const delta = baseMs * pct;
  const delay = randFloat(baseMs - delta, baseMs + delta);
  await sleep(delay);
}

export function chance(probability: number): boolean {
  return Math.random() < probability;
}
