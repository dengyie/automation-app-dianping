import json
from pathlib import Path

from automation_app_dianping.storage import (
    DraftRecord,
    DraftReview,
    DraftStore,
    ReviewRatings,
    StateStore,
    build_publish_items,
    generate_publish_markdown,
    slug_from_url,
    write_publish_checklist,
)


def test_slug_from_url_and_draft_roundtrip(tmp_path: Path):
    assert slug_from_url("https://www.dianping.com/shop/H5ZxKG4hgG") == "H5ZxKG4hgG"
    store = DraftStore(tmp_path)
    draft = DraftRecord(
        id="shop-1",
        shop_url="https://www.dianping.com/shop/shop1",
        shop_name="测试店",
        shop_slug="shop1",
        draft=DraftReview(
            content="很好吃" * 40,
            ratings=ReviewRatings(taste=5, environment=4, service=4),
            photos=["a.jpg"],
            status="edited",
        ),
        scraped_data={"address": "南京东路", "recommendedDishes": [{"name": "红烧肉"}]},
    )
    store.save(draft)
    loaded = store.load("shop-1")
    assert loaded is not None
    assert loaded.shop_name == "测试店"
    assert loaded.draft.ratings.taste == 5
    assert store.list()[0].id == "shop-1"


def test_state_store_daily_quota_and_interval(tmp_path: Path):
    store = StateStore(tmp_path)
    state = store.load()
    assert store.can_publish_today(state, 2) is True
    state.today_published_count = 2
    assert store.can_publish_today(state, 2) is False
    state.today_published_count = 0
    state.last_published_timestamp = "2099-01-01T00:00:00Z"
    minutes = store.minutes_since_last_publish(state)
    assert minutes is not None


def test_publish_checklist_generation(tmp_path: Path):
    draft = DraftRecord(
        id="shop-2",
        shop_url="https://www.dianping.com/shop/shop2",
        shop_name="清单店",
        shop_slug="shop2",
        draft=DraftReview(content="内容" * 40, ratings=ReviewRatings(4, 3, 4), photos=[]),
    )
    DraftStore(tmp_path).save(draft)
    items = build_publish_items(DraftStore(tmp_path).list())
    assert len(items) == 1
    md = generate_publish_markdown(items)
    assert "清单店" in md
    path = write_publish_checklist(items, data_dir=tmp_path, as_json=True)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["shops"][0]["shopName"] == "清单店"
