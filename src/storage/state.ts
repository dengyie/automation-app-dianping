import { readFile, writeFile, rename } from 'node:fs/promises';
import { existsSync } from 'node:fs';

const STATE_PATH = 'data/state.json';

export interface RuntimeState {
  lastPublishedDate: string | null;
  todayPublishedCount: number;
  lastPublishedTimestamp: string | null;
}

export async function loadState(): Promise<RuntimeState> {
  if (!existsSync(STATE_PATH)) {
    return { lastPublishedDate: null, todayPublishedCount: 0, lastPublishedTimestamp: null };
  }
  const raw = await readFile(STATE_PATH, 'utf-8');
  const state = JSON.parse(raw) as RuntimeState;
  // Reset daily counter if it's a new day
  const today = new Date().toISOString().slice(0, 10);
  if (state.lastPublishedDate !== today) {
    state.todayPublishedCount = 0;
    state.lastPublishedDate = today;
  }
  return state;
}

export async function saveState(state: RuntimeState): Promise<void> {
  const tmp = `${STATE_PATH}.tmp`;
  await writeFile(tmp, JSON.stringify(state, null, 2), 'utf-8');
  await rename(tmp, STATE_PATH);
}

export async function canPublishToday(state: RuntimeState, maxPerDay: number): Promise<boolean> {
  await refreshState(state);
  return state.todayPublishedCount < maxPerDay;
}

export async function minutesSinceLastPublish(state: RuntimeState): Promise<number | null> {
  await refreshState(state);
  if (!state.lastPublishedTimestamp) return null;
  const last = new Date(state.lastPublishedTimestamp).getTime();
  const now = Date.now();
  return (now - last) / 60000;
}

async function refreshState(state: RuntimeState): Promise<void> {
  const today = new Date().toISOString().slice(0, 10);
  if (state.lastPublishedDate !== today) {
    state.todayPublishedCount = 0;
    state.lastPublishedDate = today;
    await saveState(state);
  }
}
