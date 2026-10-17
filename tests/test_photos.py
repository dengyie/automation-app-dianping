"""Photo-resolution chain tests.

Covers the documented priority: newest staged photo under
``data/photos/<slug>/`` -> CPA gpt-image-2 generation -> fixed default photo.
"""

from pathlib import Path

from automation_app_dianping.photos import (
    _latest_staged_photos,
    resolve_review_photos,
    resolve_review_photos_enabled,
)


def _touch(path: Path, mtime: float) -> None:
    path.write_bytes(b"data")
    import os

    os.utime(path, (mtime, mtime))


def test_priority_returns_newest_staged_photo(tmp_path: Path):
    slug_dir = tmp_path / "photos" / "weixiangzhai"
    slug_dir.mkdir(parents=True)
    older = slug_dir / "older.jpg"
    newer = slug_dir / "newer.png"
    _touch(older, 1_000.0)
    _touch(newer, 2_000.0)

    result = resolve_review_photos(
        slug="weixiangzhai", shop_name="味香斋", data_dir=str(tmp_path), env={}
    )
    assert result == [str(newer)]


def test_latest_staged_ignores_non_image_files(tmp_path: Path):
    slug_dir = tmp_path / "photos" / "shop"
    slug_dir.mkdir(parents=True)
    (slug_dir / "note.txt").write_text("x")
    _touch(slug_dir / "dish.jpg", 2_000.0)
    assert _latest_staged_photos(str(tmp_path), "shop", 5) == [str(slug_dir / "dish.jpg")]


def test_directory_key_cannot_escape_data_dir(tmp_path: Path):
    # A stored draft slug must never be usable as a traversal path component.
    inside = tmp_path / "photos" / "etc" / "inside.jpg"
    inside.parent.mkdir(parents=True)
    _touch(inside, 1_000.0)
    decoy = tmp_path / "outside.jpg"
    _touch(decoy, 2_000.0)

    result = resolve_review_photos(
        slug="../../etc", shop_name="x", data_dir=str(tmp_path), env={}
    )
    assert result == [str(inside)]


def test_mtime_returns_zero_for_missing_file(tmp_path: Path):
    from automation_app_dianping.photos import _mtime

    assert _mtime(tmp_path / "gone.jpg") == 0.0


def test_falls_back_to_default_when_no_staged_and_no_key(tmp_path: Path):
    from automation_app_dianping.config import DEFAULT_REVIEW_PHOTO

    result = resolve_review_photos(
        slug="empty", shop_name="无名", data_dir=str(tmp_path), env={}
    )
    assert result == ([str(DEFAULT_REVIEW_PHOTO)] if DEFAULT_REVIEW_PHOTO.is_file() else [])


def test_uses_generated_photo_when_no_staged(monkeypatch, tmp_path: Path):
    generated = tmp_path / "photos" / "shop" / "gen.png"
    generated.parent.mkdir(parents=True)
    monkeypatch.setattr(
        "automation_app_dianping.photos.generate_review_photo",
        lambda **kwargs: str(generated),
    )
    result = resolve_review_photos(
        slug="shop",
        shop_name="小店",
        data_dir=str(tmp_path),
        env={"DIANPING_CPA_API_KEY": "k"},
    )
    assert result == [str(generated)]


def test_disabled_resolver_skips_generation(monkeypatch, tmp_path: Path):
    # allow_generate=False stops generation and falls to the default; the
    # DIANPING_PHOTO_RESOLVE env opt-out is enforced at the live.py layer.
    from automation_app_dianping.config import DEFAULT_REVIEW_PHOTO

    monkeypatch.setattr(
        "automation_app_dianping.photos.generate_review_photo",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not generate")),
    )
    result = resolve_review_photos(
        slug="shop",
        shop_name="小店",
        data_dir=str(tmp_path),
        env={"DIANPING_CPA_API_KEY": "k"},
        allow_generate=False,
    )
    assert result == ([str(DEFAULT_REVIEW_PHOTO)] if DEFAULT_REVIEW_PHOTO.is_file() else [])


def test_resolve_review_photos_enabled_toggle():
    assert resolve_review_photos_enabled({}) is True
    assert resolve_review_photos_enabled({"DIANPING_PHOTO_RESOLVE": "1"}) is True
    assert resolve_review_photos_enabled({"DIANPING_PHOTO_RESOLVE": "0"}) is False
    assert resolve_review_photos_enabled({"DIANPING_PHOTO_RESOLVE": "off"}) is False


# --- imagegen pure helpers (no network) ---


def test_sanitize_slug_keeps_alnum_and_dashes():
    from automation_app_dianping.imagegen import _sanitize_slug

    assert _sanitize_slug("味香斋 Yandang") == "味香斋-yandang"
    assert _sanitize_slug("A!!B__C") == "a-b__c"
    assert _sanitize_slug("") == "image"


def test_safe_prompt_grounds_dish_hint():
    from automation_app_dianping.imagegen import _safe_prompt

    prompt = _safe_prompt("味香斋", "焖蹄面")
    assert "焖蹄面" in prompt
    assert "味香斋" not in prompt
    generic = _safe_prompt("味香斋")
    assert "招牌菜品" in generic


def test_decode_image_handles_b64_and_url(monkeypatch):
    import base64

    from automation_app_dianping.imagegen import _decode_image

    assert _decode_image({"data": []}) is None
    assert _decode_image({}) is None
    assert _decode_image(None) is None
    good = base64.b64encode(b"\x89PNGfake").decode("ascii")
    decoded = _decode_image({"data": [{"b64_json": good}]})
    assert decoded == b"\x89PNGfake"

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"url-bytes"

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp())
    assert _decode_image({"data": [{"url": "https://x/y.png"}]}) == b"url-bytes"


def test_generate_review_photo_skips_without_key(tmp_path):
    from automation_app_dianping.imagegen import generate_review_photo

    result = generate_review_photo(
        shop_name="味香斋", out_dir=str(tmp_path), env={}
    )
    assert result is None
    assert not list(tmp_path.iterdir())


def test_decode_image_bytes_salvages_raw_and_enveloped():
    import base64

    from automation_app_dianping.imagegen import _decode_image_bytes

    png = b"\x89PNG\r\n\x1a\nrestofpng"
    jpeg = b"\xff\xd8\xff\xe0jpegstuff"
    assert _decode_image_bytes(png) == png
    assert _decode_image_bytes(jpeg) == jpeg
    wrapped = base64.b64encode(png).decode("ascii")
    assert _decode_image_bytes(b'{"data": [{"b64_json": "%s"}]}' % wrapped.encode()) == png
    assert _decode_image_bytes(b"not an image") is None
    assert _decode_image_bytes(None) is None
    assert _decode_image_bytes(b'{"error": "origin timeout"}') is None


def test_generate_review_photo_salvages_524_with_image(monkeypatch, tmp_path):
    import base64
    import io
    import json
    import pathlib
    import urllib.error
    import urllib.request

    from automation_app_dianping.imagegen import generate_review_photo

    png = b"\x89PNG\r\n\x1a\nfake-generated"
    calls = []

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        calls.append(timeout)
        body = json.dumps(
            {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}
        ).encode()
        raise urllib.error.HTTPError(
            request.full_url, 524, "Origin Timeout", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    result = generate_review_photo(
        shop_name="味香斋", out_dir=str(tmp_path), env={"DIANPING_CPA_API_KEY": "sk-test"}
    )
    assert result is not None
    assert pathlib.Path(result).read_bytes() == png
    assert calls == [150.0]  # a salvaged 524 counts as success on attempt one


def test_generate_review_photo_never_raises_on_http_error(monkeypatch, tmp_path):
    import io
    import urllib.error
    import urllib.request

    from automation_app_dianping.imagegen import generate_review_photo

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error":"no"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr("automation_app_dianping.imagegen._GEN_RETRIES", 0)
    result = generate_review_photo(
        shop_name="店", out_dir=str(tmp_path), env={"DIANPING_CPA_API_KEY": "sk-test"}
    )
    assert result is None


def test_generate_review_photo_reads_os_environ_when_env_none(monkeypatch, tmp_path):
    import base64
    import json
    import pathlib
    import urllib.request

    from automation_app_dianping.imagegen import generate_review_photo

    png = b"\x89PNG\r\n\x1a\nfake-from-os-environ"
    seen = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]}
            ).encode()

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        seen["auth"] = request.get_header("Authorization")
        return _FakeResp()

    monkeypatch.setenv("DIANPING_CPA_API_KEY", "sk-from-os-environ")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    result = generate_review_photo(shop_name="店", out_dir=str(tmp_path))
    assert seen["auth"] == "Bearer sk-from-os-environ"
    assert result is not None
    assert pathlib.Path(result).read_bytes() == png


def test_generate_review_photo_400_fails_fast(monkeypatch, tmp_path):
    import io
    import urllib.error
    import urllib.request

    from automation_app_dianping.imagegen import generate_review_photo

    calls = []

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        calls.append(timeout)
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"bad key"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    result = generate_review_photo(
        shop_name="店", out_dir=str(tmp_path), env={"DIANPING_CPA_API_KEY": "sk-test"}
    )
    assert result is None
    assert len(calls) == 1  # 4xx cannot change on a retry -- no budget burned


def test_generate_review_photo_retries_5xx(monkeypatch, tmp_path):
    import io
    import urllib.error
    import urllib.request

    import automation_app_dianping.imagegen as imagegen
    from automation_app_dianping.imagegen import generate_review_photo

    calls = []

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        calls.append(timeout)
        raise urllib.error.HTTPError(
            request.full_url, 503, "Service Unavailable", {}, io.BytesIO(b"boom")
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(imagegen.time, "sleep", lambda _s: None)
    result = generate_review_photo(
        shop_name="店", out_dir=str(tmp_path), env={"DIANPING_CPA_API_KEY": "sk-test"}
    )
    assert result is None
    assert len(calls) == imagegen._GEN_RETRIES + 1


def test_generate_review_photo_budget_exhausted_skips_attempts(monkeypatch, tmp_path):
    import urllib.request

    import automation_app_dianping.imagegen as imagegen
    from automation_app_dianping.imagegen import generate_review_photo

    def _fake_urlopen(request, timeout=None, *args, **kwargs):
        raise AssertionError("must not attempt once the budget is spent")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(imagegen, "_GEN_TOTAL_BUDGET_S", -1.0)
    result = generate_review_photo(
        shop_name="店", out_dir=str(tmp_path), env={"DIANPING_CPA_API_KEY": "sk-test"}
    )
    assert result is None


def test_save_image_uniquifies_same_second_collision(monkeypatch, tmp_path):
    import pathlib

    from automation_app_dianping.imagegen import _save_image

    monkeypatch.setattr(
        "automation_app_dianping.imagegen.time.strftime",
        lambda _fmt: "20260925-120000",
    )
    first = _save_image(b"one", out_dir=str(tmp_path), shop_name="味香斋")
    second = _save_image(b"two", out_dir=str(tmp_path), shop_name="味香斋")
    assert first.endswith("味香斋-20260925-120000.png")
    assert second.endswith("味香斋-20260925-120000-2.png")
    assert pathlib.Path(first).read_bytes() == b"one"
    assert pathlib.Path(second).read_bytes() == b"two"


# --- .env loader (env.py) ---


def test_parse_env_file_skips_junk_and_empty(tmp_path: Path):
    from automation_app_dianping.env import parse_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nKEY=value\nQUOTED=\"a b\"\nEXPORTED=export X=1\n"
        "BAD KEY=x\n1STARTS=no\nNOEQUALS\n",
        encoding="utf-8",
    )
    values = parse_env_file(str(env_file))
    assert values["KEY"] == "value"
    assert values["QUOTED"] == "a b"
    assert "BAD" not in values
    assert "1STARTS" not in values


def test_load_dotenv_never_overrides_existing_env(tmp_path: Path, monkeypatch):
    import os

    from automation_app_dianping.env import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("DIANPING_A=1\nDIANPING_B=2\n", encoding="utf-8")
    monkeypatch.setenv("DIANPING_A", "existing")
    load_dotenv(str(env_file))
    assert os.environ["DIANPING_A"] == "existing"
    assert os.environ["DIANPING_B"] == "2"


def test_parse_env_file_strips_inline_comments_keeps_quoted_hash(tmp_path: Path):
    from automation_app_dianping.env import parse_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        'A=1 # comment\nB="x # y"\nC=#hash\nD=\'q\' # t\nE=a#b\n',
        encoding="utf-8",
    )
    values = parse_env_file(str(env_file))
    assert values["A"] == "1"
    assert values["B"] == "x # y"
    assert values["C"] == "#hash"
    assert values["D"] == "q"
    assert values["E"] == "a#b"


# --- live.py photo wiring ---


def test_resolve_publish_photos_keeps_authored_paths(tmp_path: Path):
    from automation_app_dianping.live import _resolve_publish_photos

    authored = [str(tmp_path / "custom.jpg")]
    assert (
        _resolve_publish_photos(
            authored, shop_name="店", data_dir=str(tmp_path), env={}
        )
        == authored
    )


def test_resolve_publish_photos_pins_default_when_disabled(tmp_path: Path):
    from automation_app_dianping.config import DEFAULT_REVIEW_PHOTO
    from automation_app_dianping.live import _resolve_publish_photos

    resolved = _resolve_publish_photos(
        [], shop_name="店", data_dir=str(tmp_path), env={"DIANPING_PHOTO_RESOLVE": "0"}
    )
    expected = [str(DEFAULT_REVIEW_PHOTO)] if DEFAULT_REVIEW_PHOTO.is_file() else []
    assert resolved == expected


def test_resolve_publish_photos_resolves_default_slot(tmp_path: Path, default_photo):
    from automation_app_dianping.config import DEFAULT_REVIEW_PHOTO
    from automation_app_dianping.live import _resolve_publish_photos

    staged = tmp_path / "photos" / "weixiangzhai" / "newest.jpg"
    staged.parent.mkdir(parents=True)
    _touch(staged, 3_000.0)
    resolved = _resolve_publish_photos(
        [str(DEFAULT_REVIEW_PHOTO)],
        shop_name="味香斋",
        slug="weixiangzhai",
        data_dir=str(tmp_path),
        env={},
    )
    assert resolved == [str(staged)]
