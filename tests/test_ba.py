"""In-memory index tests for the BA (broken section anchor) rules."""

from civlint import engine
from civlint.context import PageContext
from civlint.index import SiteIndex

PAGES = {
    "Main Page": (
        "== History ==\n"
        "Old stuff.\n"
        "== Economy ==\n"
        "{{anchor|Trade|Commerce}}\n"
        "Markets.\n"
    ),
    "Old Name": "#REDIRECT [[Main Page]]",
    "Broken Redirect": "#REDIRECT [[Main Page#Founding]]",
    "Good Redirect": "#REDIRECT [[Main Page#History]]",
}


def lint(text, code, title="Some Page"):
    ctx = PageContext(title, text, index=SiteIndex.from_pages(PAGES))
    return engine.lint(ctx, select=[code])


def test_valid_anchor():
    assert lint("See [[Main Page#History]].", "BA001") == []


def test_valid_anchor_with_label_and_underscores():
    assert lint("See [[Main Page#History|the past]].", "BA001") == []
    assert lint("See [[Main_Page#History]].", "BA001") == []


def test_broken_anchor_with_suggestion():
    findings = lint("See [[Main Page#Histroy]].", "BA001")
    assert len(findings) == 1
    assert findings[0].code == "BA001"
    assert "did you mean 'History'?" in findings[0].message


def test_broken_anchor_case_insensitive_suggestion():
    findings = lint("See [[Main Page#history]].", "BA001")
    assert len(findings) == 1
    assert "did you mean 'History'?" in findings[0].message


def test_broken_anchor_no_suggestion():
    findings = lint("See [[Main Page#Zzzzzz]].", "BA001")
    assert len(findings) == 1
    assert "did you mean" not in findings[0].message


def test_anchor_template_target():
    assert lint("See [[Main Page#Trade]].", "BA001") == []
    assert lint("See [[Main Page#Commerce]].", "BA001") == []


def test_same_page_link():
    text = "== Local ==\n[[#Local]] is fine but [[#Missing]] is not.\n"
    findings = lint(text, "BA001")
    assert len(findings) == 1
    assert "#Missing" in findings[0].message


def test_link_through_redirect():
    assert lint("See [[Old Name#History]].", "BA001") == []
    findings = lint("See [[Old Name#Nope]].", "BA001")
    assert len(findings) == 1
    assert "[[Main Page]]" in findings[0].message


def test_missing_target_skipped():
    # a link to a page that doesn't exist is CW103's job, not BA001's
    assert lint("See [[Nonexistent#Foo]].", "BA001") == []


def test_interwiki_skipped():
    assert lint("See [[:wikipedia:Foo#Bar]].", "BA001") == []


def test_shielded_skipped():
    assert lint("<nowiki>[[Main Page#Nope]]</nowiki>", "BA001") == []


def test_finding_offsets():
    text = "See [[Main Page#Nope]]."
    (finding,) = lint(text, "BA001")
    assert text[finding.start : finding.end] == "[[Main Page#Nope]]"


def test_ba001_skips_redirect_pages():
    text = PAGES["Broken Redirect"]
    assert lint(text, "BA001", title="Broken Redirect") == []


def test_ba002_broken_redirect():
    text = PAGES["Broken Redirect"]
    findings = lint(text, "BA002", title="Broken Redirect")
    assert len(findings) == 1
    assert findings[0].code == "BA002"
    assert "#Founding" in findings[0].message


def test_ba002_valid_redirect():
    assert lint(PAGES["Good Redirect"], "BA002", title="Good Redirect") == []
    assert lint(PAGES["Old Name"], "BA002", title="Old Name") == []


def test_ba002_suggestion():
    findings = lint("#REDIRECT [[Main Page#Histroy]]", "BA002", title="R")
    assert len(findings) == 1
    assert "did you mean 'History'?" in findings[0].message
