"""Business storage helpers migrated from the legacy TypeScript CLI.

These modules own Dianping domain data only. They do not implement runtime,
retry, report, or provider internals.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_DATA_DIR = Path("data")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def slug_from_url(url: str) -> str:
    match = re.search(r"/shop/([A-Za-z0-9]+)", url or "")
    if match:
        return match.group(1)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", url or "").strip("-")
    return cleaned[:30] or "shop"


@dataclass
class ReviewRatings:
    taste: int = 4
    environment: int = 4
    service: int = 4


@dataclass
class DraftReview:
    content: str = ""
    ratings: ReviewRatings = field(default_factory=ReviewRatings)
    photos: List[str] = field(default_factory=list)
    status: str = "scraped"
    edited_at: Optional[str] = None


@dataclass
class DraftRecord:
    id: str
    shop_url: str
    shop_name: str
    shop_slug: str
    draft: DraftReview
    scraped_data: Optional[Dict[str, Any]] = None
    scraped_at: Optional[str] = None
    published_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: _iso(_utc_now()))
    version: int = 1

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DraftRecord":
        draft_payload = payload.get("draft") or {}
        ratings_payload = draft_payload.get("ratings") or {}
        ratings = ReviewRatings(
            taste=int(ratings_payload.get("taste", 4)),
            environment=int(ratings_payload.get("environment", 4)),
            service=int(ratings_payload.get("service", 4)),
        )
        draft = DraftReview(
            content=str(draft_payload.get("content") or ""),
            ratings=ratings,
            photos=list(draft_payload.get("photos") or []),
            status=str(draft_payload.get("status") or "scraped"),
            edited_at=draft_payload.get("editedAt") or draft_payload.get("edited_at"),
        )
        return cls(
            id=str(payload.get("id") or ""),
            shop_url=str(payload.get("shopUrl") or payload.get("shop_url") or ""),
            shop_name=str(payload.get("shopName") or payload.get("shop_name") or ""),
            shop_slug=str(payload.get("shopSlug") or payload.get("shop_slug") or ""),
            draft=draft,
            scraped_data=payload.get("scrapedData") or payload.get("scraped_data"),
            scraped_at=payload.get("scrapedAt") or payload.get("scraped_at"),
            published_at=payload.get("publishedAt") or payload.get("published_at"),
            created_at=str(payload.get("createdAt") or payload.get("created_at") or _iso(_utc_now())),
            version=int(payload.get("version") or 1),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "shopUrl": self.shop_url,
            "shopName": self.shop_name,
            "shopSlug": self.shop_slug,
            "scrapedAt": self.scraped_at,
            "scrapedData": self.scraped_data,
            "draft": {
                "content": self.draft.content,
                "ratings": asdict(self.draft.ratings),
                "photos": list(self.draft.photos),
                "status": self.draft.status,
                "editedAt": self.draft.edited_at,
            },
            "publishedAt": self.published_at,
            "createdAt": self.created_at,
        }


class DraftStore:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.drafts_dir = self.data_dir / "drafts"

    def path_for(self, draft_id: str) -> Path:
        return self.drafts_dir / ("%s.json" % draft_id)

    def load(self, draft_id: str) -> Optional[DraftRecord]:
        path = self.path_for(draft_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DraftRecord.from_dict(payload)

    def list(self) -> List[DraftRecord]:
        if not self.drafts_dir.exists():
            return []
        records: List[DraftRecord] = []
        for path in sorted(self.drafts_dir.glob("*.json")):
            if path.name.endswith(".bak") or path.name.endswith(".tmp"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records.append(DraftRecord.from_dict(payload))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def save(self, record: DraftRecord) -> Path:
        path = self.path_for(record.id)
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        _atomic_write(path, json.dumps(record.to_dict(), ensure_ascii=False, indent=2))
        return path


@dataclass
class RuntimeState:
    last_published_date: Optional[str] = None
    today_published_count: int = 0
    last_published_timestamp: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "RuntimeState":
        return cls(
            last_published_date=payload.get("lastPublishedDate") or payload.get("last_published_date"),
            today_published_count=int(payload.get("todayPublishedCount") or payload.get("today_published_count") or 0),
            last_published_timestamp=payload.get("lastPublishedTimestamp") or payload.get("last_published_timestamp"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lastPublishedDate": self.last_published_date,
            "todayPublishedCount": self.today_published_count,
            "lastPublishedTimestamp": self.last_published_timestamp,
        }


class StateStore:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.path = Path(data_dir) / "state.json"

    def load(self) -> RuntimeState:
        if not self.path.exists():
            return RuntimeState()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        state = RuntimeState.from_dict(payload)
        self.refresh(state)
        return state

    def save(self, state: RuntimeState) -> None:
        _atomic_write(self.path, json.dumps(state.to_dict(), ensure_ascii=False, indent=2))

    def refresh(self, state: RuntimeState) -> RuntimeState:
        today = date.today().isoformat()
        if state.last_published_date != today:
            state.today_published_count = 0
            state.last_published_date = today
        return state

    def can_publish_today(self, state: RuntimeState, max_per_day: int) -> bool:
        self.refresh(state)
        return state.today_published_count < max_per_day

    def minutes_since_last_publish(self, state: RuntimeState) -> Optional[float]:
        self.refresh(state)
        if not state.last_published_timestamp:
            return None
        last = datetime.fromisoformat(state.last_published_timestamp.replace("Z", "+00:00"))
        now = _utc_now()
        return (now - last).total_seconds() / 60.0


@dataclass
class PublishItem:
    shop_name: str
    shop_url: str
    review: str
    ratings: ReviewRatings
    photos: List[str]
    draft_id: str
    status: str = "pending"
    recommended_dishes: List[str] = field(default_factory=list)
    address: str = ""
    avg_price: Optional[float] = None

    @property
    def average_rating(self) -> float:
        values = [self.ratings.taste, self.ratings.environment, self.ratings.service]
        return sum(values) / float(len(values))


def build_publish_items(drafts: Iterable[DraftRecord]) -> List[PublishItem]:
    items: List[PublishItem] = []
    for draft in drafts:
        if draft.published_at or draft.draft.status == "published":
            continue
        scraped = draft.scraped_data or {}
        recommended = scraped.get("recommendedDishes") or scraped.get("recommended_dishes") or []
        if recommended and isinstance(recommended[0], dict):
            recommended = [str(item.get("name") or "") for item in recommended if item.get("name")]
        items.append(
            PublishItem(
                shop_name=draft.shop_name or "unknown shop",
                shop_url=draft.shop_url,
                review=draft.draft.content,
                ratings=draft.draft.ratings,
                photos=list(draft.draft.photos),
                draft_id=draft.id,
                status="pending",
                recommended_dishes=list(recommended),
                address=str(scraped.get("address") or ""),
                avg_price=scraped.get("avgPricePerPerson") or scraped.get("pricePerPerson"),
            )
        )
    return items


def render_stars(rating: float) -> str:
    full = int(rating)
    empty = max(0, 5 - full)
    return ("*" * full) + ("-" * empty)


def generate_publish_markdown(items: List[PublishItem], *, created_at: Optional[str] = None) -> str:
    created = created_at or _iso(_utc_now())
    lines = [
        "# 大众点评发布清单",
        "",
        "生成时间：%s" % created,
        "待发布：%s 条" % len(items),
        "",
        "---",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                "## %s. %s" % (index, item.shop_name),
                "",
                "**店铺链接**：%s" % item.shop_url,
                "**综合评分**：%s (%.1f)" % (render_stars(item.average_rating), item.average_rating),
                "**分项评分**：口味%s | 环境%s | 服务%s"
                % (item.ratings.taste, item.ratings.environment, item.ratings.service),
                "**照片**：%s 张" % len(item.photos),
                "",
                "### 评价内容（%s 字）" % len(item.review.strip()),
                "```",
                item.review.strip(),
                "```",
                "",
                "### 操作步骤",
                "1. 打开大众点评 App",
                "2. 搜索店铺：**%s**" % item.shop_name,
                "3. 点击写评价",
                "4. 设置评分并粘贴评价内容",
                "5. 上传照片后发布" if item.photos else "5. 点击发布",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def write_publish_checklist(
    items: List[PublishItem],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    as_json: bool = False,
    output: Optional[Path] = None,
) -> Path:
    created_at = _iso(_utc_now())
    if as_json:
        path = Path(output) if output else Path(data_dir) / "publish-checklist.json"
        payload = {
            "createdAt": created_at,
            "shops": [
                {
                    "draftId": item.draft_id,
                    "shopName": item.shop_name,
                    "shopUrl": item.shop_url,
                    "review": item.review,
                    "ratings": asdict(item.ratings),
                    "photos": item.photos,
                    "status": item.status,
                    "recommendedDishes": item.recommended_dishes,
                    "address": item.address,
                    "avgPrice": item.avg_price,
                }
                for item in items
            ],
        }
        _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
        return path

    path = Path(output) if output else Path(data_dir) / "publish-checklist.md"
    _atomic_write(path, generate_publish_markdown(items, created_at=created_at))
    return path
