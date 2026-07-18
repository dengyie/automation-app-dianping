import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { basename, join } from 'node:path';
import { info, success } from '../utils/logger.js';

const DRAFTS_DIR = 'data/drafts';

export type DraftStatus = 'scraped' | 'generated' | 'edited' | 'published';

export interface DraftFile {
  version: number;
  id: string;
  shopUrl: string;
  shopName: string;
  shopSlug: string;
  scrapedAt: string | null;
  scrapedData: ScrapedShopData | null;
  draft: {
    content: string;
    ratings: { taste: number; environment: number; service: number };
    photos: string[];
    status: DraftStatus;
    editedAt: string | null;
  };
  publishedAt: string | null;
  createdAt: string;
}

export interface ScrapedShopData {
  name: string;
  address: string;
  avgPricePerPerson: number | null;
  category: string;
  overallRating: number | null;
  ratings: { taste: number | null; environment: number | null; service: number | null };
  recommendedDishes: string[];
  features: string[];
  sampleReviews: SampleReview[];
}

export interface SampleReview {
  username: string;
  rating: number;
  content: string;
  date: string;
}

export function slugFromUrl(url: string): string {
  const match = url.match(/\/shop\/([A-Za-z0-9]+)/);
  return match ? match[1] : url.replace(/[^a-zA-Z0-9]/g, '-').slice(0, 30);
}

export function draftPath(id: string): string {
  return join(DRAFTS_DIR, `${id}.json`);
}

export async function loadDraft(id: string): Promise<DraftFile | null> {
  const path = draftPath(id);
  if (!existsSync(path)) return null;
  const raw = await readFile(path, 'utf-8');
  return JSON.parse(raw);
}

export async function loadDraftByUrl(url: string): Promise<DraftFile | null> {
  const slug = slugFromUrl(url);
  if (!existsSync(DRAFTS_DIR)) return null;
  const files = await readdir(DRAFTS_DIR);
  for (const f of files) {
    if (f.startsWith(slug)) {
      return loadDraft(f.replace('.json', ''));
    }
  }
  return null;
}

export async function saveDraft(draft: DraftFile): Promise<void> {
  if (!existsSync(DRAFTS_DIR)) {
    await mkdir(DRAFTS_DIR, { recursive: true });
  }
  const path = draftPath(draft.id);
  // Backup existing
  if (existsSync(path)) {
    const bak = await readFile(path, 'utf-8');
    await writeFile(`${path}.bak`, bak, 'utf-8');
  }
  // Atomic write
  const tmp = `${path}.tmp`;
  await writeFile(tmp, JSON.stringify(draft, null, 2), 'utf-8');
  const { rename } = await import('node:fs/promises');
  await rename(tmp, path);
  success(`草稿已保存: ${draft.id}`);
}

export function createDraft(url: string, shopName: string): DraftFile {
  const slug = slugFromUrl(url);
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const id = `${slug}-${date}`;
  return {
    version: 1,
    id,
    shopUrl: url,
    shopName,
    shopSlug: slug,
    scrapedAt: null,
    scrapedData: null,
    draft: {
      content: '',
      ratings: { taste: 4, environment: 4, service: 4 },
      photos: [],
      status: 'scraped',
      editedAt: null,
    },
    publishedAt: null,
    createdAt: new Date().toISOString(),
  };
}

export async function listDrafts(): Promise<DraftFile[]> {
  if (!existsSync(DRAFTS_DIR)) return [];
  const files = await readdir(DRAFTS_DIR);
  const drafts: DraftFile[] = [];
  for (const f of files) {
    if (f.endsWith('.json') && !f.endsWith('.bak') && !f.endsWith('.tmp')) {
      const draft = await loadDraft(f.replace('.json', ''));
      if (draft) drafts.push(draft);
    }
  }
  drafts.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return drafts;
}
