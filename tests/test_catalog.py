import json

import pytest

from app.catalog import DUMMY_URI, CatalogEntry, CatalogError, CatalogIndex


# ---------- helpers for tiny synthetic catalogs (no Samsung data needed) ----------
def make_entry(i, uri=None, validation=None, entry_id=None):
    return CatalogEntry(
        id=entry_id or f"DL-{i:04d}",
        uri=uri or f"bixby://masked/act/{i:010d}",
        description=f"Opens setting number {i}.",
        message=f"Setting {i}",
        qna_description=f"Explains setting {i}.",
        original_type="onURL",
        control_type=None,
        validation=validation,
    )


def dummy_entry():
    return make_entry(0, uri=DUMMY_URI, entry_id="DL-DUMMY")


# ---------- integrity rules (synthetic) ----------
def test_duplicate_uri_is_rejected():
    entries = [make_entry(1), make_entry(2, uri=make_entry(1).uri), dummy_entry()]
    with pytest.raises(CatalogError, match="duplicate deeplink URI"):
        CatalogIndex(entries)


def test_duplicate_id_is_rejected():
    entries = [make_entry(1), make_entry(2, entry_id="DL-0001"), dummy_entry()]
    with pytest.raises(CatalogError, match="duplicate catalog id"):
        CatalogIndex(entries)


def test_catalog_without_dummy_is_rejected():
    with pytest.raises(CatalogError, match="no bixby://dummy_positive"):
        CatalogIndex([make_entry(1)])


def test_invalid_validation_object_is_rejected():
    bad = make_entry(1, validation={"deeplink": "bixby://masked/val/x", "key": "k", "resultType": "not-a-type"})
    with pytest.raises(CatalogError, match="invalid validation object"):
        CatalogIndex([bad, dummy_entry()])


def test_count_mismatch_is_rejected(tmp_path):
    path = tmp_path / "deeplinks.json"
    path.write_text(json.dumps({"count": 5, "deeplinks": []}), encoding="utf-8")
    with pytest.raises(CatalogError, match="count=5"):
        CatalogIndex.from_file(path)


def test_missing_file_gives_clear_error(tmp_path):
    with pytest.raises(CatalogError, match="not found"):
        CatalogIndex.from_file(tmp_path / "nope.json")


def test_malformed_json_gives_clear_error(tmp_path):
    path = tmp_path / "deeplinks.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="not valid JSON"):
        CatalogIndex.from_file(path)


# ---------- the real Samsung catalog ----------
def test_real_catalog_size_and_dummy(catalog):
    assert len(catalog) == 578
    assert len(catalog.real_entries) == 577
    assert catalog.dummy.uri == DUMMY_URI


def test_all_real_uris_are_unique_and_recognised(catalog):
    uris = [e.uri for e in catalog.real_entries]
    assert len(set(uris)) == len(uris)
    assert all(catalog.is_real_uri(u) for u in uris)


def test_search_text_is_never_empty_and_never_contains_a_uri(catalog):
    for entry in catalog.real_entries:
        assert entry.search_text.strip()
        assert "bixby://" not in entry.search_text


def test_catalog_text_contains_no_web_urls(catalog):
    # Zero-URL-leak rule: nothing we could copy into a plan may contain a web link.
    for entry in catalog.real_entries:
        text = f"{entry.description} {entry.message} {entry.qna_description}".lower()
        assert "http" not in text and "www." not in text, entry.id


# ---------- closed-world membership: invented things must be rejected ----------
@pytest.mark.parametrize(
    "fake",
    [
        "https://www.samsung.com/support",
        "bixby://masked/act/0000000000",
        "bixby://masked/act/",
        "settings://display",
        "",
        "   ",
        None,
        12345,
    ],
)
def test_invented_uris_are_rejected(catalog, fake):
    assert not catalog.is_allowed_uri(fake)
    assert not catalog.is_real_uri(fake)
    assert catalog.get(fake) is None


def test_slightly_altered_real_uri_is_rejected(catalog):
    real = catalog.real_entries[0].uri
    for altered in (real.upper(), real + " ", " " + real, real[:-1], real + "0", real.replace("act", "val")):
        assert not catalog.is_allowed_uri(altered), altered


def test_dummy_is_allowed_but_is_not_a_real_uri(catalog):
    assert catalog.is_allowed_uri(DUMMY_URI)
    assert not catalog.is_real_uri(DUMMY_URI)


def test_dummy_placeholder_text_cannot_be_copied_into_a_plan(catalog):
    with pytest.raises(ValueError, match="dummy"):
        catalog.to_deeplink(catalog.dummy)


def test_validation_uris_are_recognised_only_as_validation(catalog):
    with_validation = [e for e in catalog.real_entries if catalog.to_validation_deeplink(e)]
    assert len(with_validation) > 500
    for entry in with_validation:
        val_uri = catalog.to_validation_deeplink(entry).deeplink
        assert catalog.is_real_validation_uri(val_uri)
        assert not catalog.is_real_uri(val_uri)  # a validation URI is not an action URI


# ---------- copying from the catalog reproduces Samsung's own sample ----------
def test_catalog_copy_reproduces_samsung_sample_deeplinks(catalog, sample_output):
    auto_action = sample_output["response"]["contexts"][0]["actions"][0]
    group = auto_action["stepGroups"][0]
    expected_action = group["actionableDeeplink"]
    expected_validation = group["validationDeeplink"]

    entry = catalog.get(expected_action["deeplink"])
    assert entry is not None

    built_action = catalog.to_deeplink(entry).model_dump(mode="json", exclude_none=True)
    assert built_action == expected_action

    built_validation = catalog.to_validation_deeplink(entry).model_dump(mode="json", exclude_none=True)
    assert built_validation == expected_validation
