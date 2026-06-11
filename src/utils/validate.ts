export interface ReviewRatings {
  taste: number;
  environment: number;
  service: number;
}

export interface ReviewDraft {
  content: string;
  ratings: ReviewRatings;
}

export function validateReview(draft: ReviewDraft): string | null {
  if (!draft.content || draft.content.trim().length === 0) {
    return '评价内容不能为空';
  }
  const chineseCount = countChineseChars(draft.content);
  if (chineseCount < 100) {
    return `中文字符不足100字（当前 ${chineseCount} 字），不满足橙V要求`;
  }
  const { taste, environment, service } = draft.ratings;
  for (const [key, val] of Object.entries({ taste, environment, service })) {
    if (typeof val !== 'number' || val < 1 || val > 5) {
      return `评分 "${key}" 无效：${val}，需在 1-5 之间`;
    }
  }
  if (taste === 5 && environment === 5 && service === 5) {
    return '全部5星容易被判定为刷分，建议有区分度地打分';
  }
  return null;
}

export function countChineseChars(text: string): number {
  let count = 0;
  for (const ch of text) {
    if (/[一-鿿]/.test(ch)) count++;
  }
  return count;
}
