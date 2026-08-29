"""Non-fixture tests for TY001's dictionary loading."""

from civlint.rules.ty import _TYPOS


def test_dictionary_loads():
    assert len(_TYPOS) > 50_000
    assert _TYPOS["teh"] == ["the"]
    # ambiguous entries carry multiple candidates
    assert len(_TYPOS["wich"]) > 1


def test_curated_deletions_absent():
    # words deleted from typos.txt because they are correct on civwiki
    for word in ("memer", "welp", "hel", "pheonix", "causalities", "ointed"):
        assert word not in _TYPOS, f"{word} should have been curated out"


def test_curated_overrides():
    # corrections overridden from the upstream dictionaries for civwiki
    assert _TYPOS["articules"] == ["articles"]
    # "abl" stays: the all-caps guard covers the acronym usage
    assert _TYPOS["abl"] == ["able"]
