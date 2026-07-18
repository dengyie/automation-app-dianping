import { readFile, writeFile, rename } from 'node:fs/promises';
import { existsSync } from 'node:fs';

const HISTORY_PATH = 'data/history.json';

export interface HistoryEntry {
  shopName: string;
  shopUrl: string;
  draftId: string;
  content: string;
  ratings: { taste: number; environment: number; service: number };
  photosCount: number;
  publishedAt: string;
}

export interface HistoryData {
  reviews: HistoryEntry[];
}

async function load(): Promise<HistoryData> {
  if (!existsSync(HISTORY_PATH)) return { reviews: [] };
  const raw = await readFile(HISTORY_PATH, 'utf-8');
  return JSON.parse(raw);
}

async function save(data: HistoryData): Promise<void> {
  const tmp = `${HISTORY_PATH}.tmp`;
  await writeFile(tmp, JSON.stringify(data, null, 2), 'utf-8');
  await rename(tmp, HISTORY_PATH);
}

export async function addEntry(entry: HistoryEntry): Promise<void> {
  const data = await load();
  data.reviews.push(entry);
  await save(data);
}

export async function getHistory(): Promise<HistoryData> {
  return load();
}

export function countThisMonth(history: HistoryData): number {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  return history.reviews.filter(r => {
    const d = new Date(r.publishedAt);
    return d.getFullYear() === year && d.getMonth() === month;
  }).length;
}

export function countTotal(history: HistoryData): number {
  return history.reviews.length;
}
