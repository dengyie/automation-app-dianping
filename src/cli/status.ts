import { loadConfig } from '../storage/config.js';
import { getHistory, countThisMonth, countTotal } from '../storage/history.js';
import { loadState, canPublishToday, minutesSinceLastPublish } from '../storage/state.js';
import { listDrafts } from '../storage/drafts.js';
import { divider } from '../utils/logger.js';

export async function statusCommand() {
  const config = await loadConfig();
  const history = await getHistory();
  const state = await loadState();
  const drafts = await listDrafts();

  const total = countTotal(history);
  const thisMonth = countThisMonth(history);
  const needForOrangeV = 4;
  const remaining = Math.max(0, needForOrangeV - thisMonth);

  divider(`大众点评账号状态 -- ${config.account.name}`);

  console.log(`  累计评价:      ${total} 条`);
  console.log(`  本月评价:      ${thisMonth} 条`);

  if (thisMonth >= needForOrangeV) {
    console.log(`  橙V 状态:      ✅ 已完成 ${thisMonth}/${needForOrangeV}`);
  } else {
    const bar = '█'.repeat(thisMonth) + '░'.repeat(needForOrangeV - thisMonth);
    console.log(`  橙V 进度:      ${bar} ${thisMonth}/${needForOrangeV} (还需 ${remaining} 条)`);
  }

  // Daily slots
  const canPublish = await canPublishToday(state, config.publishing.maxPerDay);
  const slotsLeft = config.publishing.maxPerDay - state.todayPublishedCount;
  console.log(`  今日额度:      ${state.todayPublishedCount}/${config.publishing.maxPerDay} (剩余 ${Math.max(0, slotsLeft)} 条)`);

  if (state.todayPublishedCount >= config.publishing.maxPerDay) {
    console.log(`                  ⚠️ 今日额度已用完`);
  } else if (state.todayPublishedCount > 0) {
    const mins = await minutesSinceLastPublish(state);
    if (mins !== null && mins < config.publishing.minIntervalMinutes) {
      const remaining = Math.ceil(config.publishing.minIntervalMinutes - mins);
      console.log(`                  ⏳ 下一条可在 ${remaining} 分钟后发布`);
    }
  }

  divider();

  // Drafts
  if (drafts.length > 0) {
    console.log(`\n📝 草稿箱 (${drafts.length}):`);
    const statusLabels: Record<string, string> = {
      scraped: '已抓取',
      generated: '已生成',
      edited: '待发布',
      published: '已发布',
    };
    for (const d of drafts) {
      const label = statusLabels[d.draft.status] || d.draft.status;
      const icon = d.draft.status === 'edited' ? '🟢' : d.draft.status === 'published' ? '✅' : '🟡';
      console.log(`  ${icon} [${label}] ${d.shopName} (${d.id})`);
    }
  } else {
    console.log(`\n📝 草稿箱: 空`);
  }

  console.log('');
}
