"""Tests for the index-dependent CW rules (CW103, CW120, CW121)."""

from civlint import engine, fixer
from civlint.context import PageContext
from civlint.index import SiteIndex


def _lint(title, text, index, code):
    return engine.lint(PageContext(title, text, index=index), select=[code])


# --- CW103: redlinks ---

LINK_INDEX = SiteIndex.from_pages(
    {
        "Mount Augusta": "A city.",
        "MTA": "#REDIRECT [[Mount Augusta]]",
        "Category:Towns": "",
        "File:Map.png": None,
        "LoopA": "#REDIRECT [[LoopB]]",
        "LoopB": "#REDIRECT [[LoopA]]",
    }
)


def test_civ103_existing_and_redirected_targets():
    text = "See [[Mount Augusta]] and [[MTA|the city]] and [[mount Augusta]]."
    assert _lint("P", text, LINK_INDEX, "CW103") == []


def test_civ103_missing_target():
    findings = _lint("P", "See [[Missing Page|here]].", LINK_INDEX, "CW103")
    assert [f.message for f in findings] == [
        "links to nonexistent page 'Missing Page'"
    ]


def test_civ103_interwiki_skipped():
    text = "[[wikipedia:Nonexistent]] [[fr:Accueil]] [[mc:Iron Ingot|iron]]"
    assert _lint("P", text, LINK_INDEX, "CW103") == []


def test_civ103_category_links():
    # membership tags are skipped even when missing; :Category links are
    # real links and get checked
    text = "[[Category:Nope]] [[:Category:Towns]] [[:Category:Nope]]"
    findings = _lint("P", text, LINK_INDEX, "CW103")
    assert [f.message for f in findings] == [
        "links to nonexistent page 'Category:Nope'"
    ]


def test_civ103_fragment_only_link_skipped():
    assert _lint("P", "See [[#History]].", LINK_INDEX, "CW103") == []


def test_civ103_file_links():
    text = "[[File:Map.png|thumb|[[Mount Augusta]]]] [[File:Missing.png]]"
    findings = _lint("P", text, LINK_INDEX, "CW103")
    assert [f.message for f in findings] == [
        "links to nonexistent page 'File:Missing.png'"
    ]


def test_civ103_redirect_loop_is_a_redlink():
    findings = _lint("P", "See [[LoopA]].", LINK_INDEX, "CW103")
    assert len(findings) == 1


def test_civ103_shielded_skipped():
    text = "<nowiki>[[Missing Page]]</nowiki> <!-- [[Missing Page]] -->"
    assert _lint("P", text, LINK_INDEX, "CW103") == []


# --- CW120: redundant parent category ---

CAT_INDEX = SiteIndex.from_pages(
    {
        "Category:Geography": "top-level",
        "Category:Settlements": "[[Category:Geography]]",
        "Category:Cities": "[[Category:Settlements]]",
        # C1 in C2 in C3 in C4 in C5: C4 is 3 levels above C1, C5 is 4
        "Category:C1": "[[Category:C2]]",
        "Category:C2": "[[Category:C3]]",
        "Category:C3": "[[Category:C4]]",
        "Category:C4": "[[Category:C5]]",
        "Category:C5": "x",
        "Category:CycA": "[[Category:CycB]]",
        "Category:CycB": "[[Category:CycA]]",
    }
)


def test_civ120_direct_parent():
    text = "Body.\n[[Category:Cities]]\n[[Category:Settlements]]\n"
    findings = _lint("P", text, CAT_INDEX, "CW120")
    assert [f.message for f in findings] == [
        "category 'Settlements' is redundant:"
        " the page is already in its subcategory 'Cities'"
    ]


def test_civ120_transitive_parent():
    text = "Body.\n[[Category:Geography]]\n[[Category:Cities]]\n"
    findings = _lint("P", text, CAT_INDEX, "CW120")
    assert len(findings) == 1
    assert "'Geography'" in findings[0].message


def test_civ120_depth_limit():
    fires = _lint("P", "[[Category:C1]] [[Category:C4]]", CAT_INDEX, "CW120")
    assert len(fires) == 1  # 3 levels up: within reach
    quiet = _lint("P", "[[Category:C1]] [[Category:C5]]", CAT_INDEX, "CW120")
    assert quiet == []  # 4 levels up: out of reach


def test_civ120_category_cycle_terminates_quietly():
    text = "[[Category:CycA]]\n[[Category:CycB]]\n"
    assert _lint("P", text, CAT_INDEX, "CW120") == []


def test_civ120_unrelated_categories():
    text = "[[Category:Geography]]\n[[Category:C1]]\n"
    assert _lint("P", text, CAT_INDEX, "CW120") == []


def test_civ120_fix_removes_line():
    text = "Body.\n\n[[Category:Settlements]]\n[[Category:Cities]]\n"
    fixed, applied, _ = fixer.apply_fixes(
        text, lambda t: _lint("P", t, CAT_INDEX, "CW120"), unsafe=True
    )
    assert fixed == "Body.\n\n[[Category:Cities]]\n"
    assert applied == {"CW120": 1}


# --- CW121: double redirects ---

REDIR_INDEX = SiteIndex.from_pages(
    {
        "Final Page": "content",
        "Middle": "#REDIRECT [[Final Page]]",
        "Broken Mid": "#REDIRECT [[Nowhere]]",
        "LoopA": "#REDIRECT [[LoopB]]",
        "LoopB": "#REDIRECT [[LoopA]]",
    }
)


def test_civ121_fix_retargets_to_final():
    fixed, applied, _ = fixer.apply_fixes(
        "#REDIRECT [[Middle]]",
        lambda t: _lint("Old", t, REDIR_INDEX, "CW121"),
    )
    assert fixed == "#REDIRECT [[Final Page]]"
    assert applied == {"CW121": 1}


def test_civ121_fix_keeps_fragment():
    fixed, _, _ = fixer.apply_fixes(
        "#redirect: [[Middle#History]]",
        lambda t: _lint("Old", t, REDIR_INDEX, "CW121"),
    )
    assert fixed == "#redirect: [[Final Page#History]]"


def test_civ121_single_redirect_ok():
    assert _lint("Old", "#REDIRECT [[Final Page]]", REDIR_INDEX, "CW121") == []


def test_civ121_not_a_redirect_page():
    text = "Prose mentioning #REDIRECT [[Middle]] mid-page."
    assert _lint("P", text, REDIR_INDEX, "CW121") == []


def test_civ121_broken_chain_reports_without_fix():
    findings = _lint("Old", "#REDIRECT [[Broken Mid]]", REDIR_INDEX, "CW121")
    assert len(findings) == 1
    assert findings[0].fix is None
    assert "broken or loops" in findings[0].message


def test_civ121_redirect_loop_reports_without_fix():
    findings = _lint("Entry", "#REDIRECT [[LoopA]]", REDIR_INDEX, "CW121")
    assert len(findings) == 1
    assert findings[0].fix is None


# --- CW101: blank line rendered at top of article ---
# Template expansion behavior mirrors the wiki: "Infobox civilization"'s
# expansion ends with a newline, "Infobox alliance"'s doesn't (semantics
# validated against the live parse API on a 22-page sample).

CW101_INDEX = SiteIndex.from_pages(
    {"P": "x"},
    template_info={
        "Infobox civilization": (False, 1),
        "Infobox alliance": (False, 0),
    },
)


def _cw101_fix(text):
    fixed, _, _ = fixer.apply_fixes(
        text,
        lambda t: _lint("P", t, CW101_INDEX, "CW101"),
        unsafe=True,
    )
    return fixed


def test_civ101_tailing_template_one_blank_line_fires():
    text = "{{Infobox civilization|name=T}}\n\nBody text.\n"
    assert len(_lint("P", text, CW101_INDEX, "CW101")) == 1
    assert _cw101_fix(text) == "{{Infobox civilization|name=T}}\nBody text.\n"


def test_civ101_tailless_template_one_blank_line_ok():
    text = "{{Infobox alliance|name=T}}\n\nBody text.\n"
    assert _lint("P", text, CW101_INDEX, "CW101") == []


def test_civ101_tailless_template_two_blank_lines_fires():
    text = "{{Infobox alliance|name=T}}\n\n\nBody text.\n"
    assert len(_lint("P", text, CW101_INDEX, "CW101")) == 1
    assert _cw101_fix(text) == "{{Infobox alliance|name=T}}\n\nBody text.\n"


def test_civ101_magic_word_at_page_start():
    # DISPLAYTITLE expands to nothing, so the page start's virtual newline
    # applies: one blank line already renders a gap
    text = "{{DISPLAYTITLE:p}}\n\nBody text.\n"
    assert len(_lint("P", text, CW101_INDEX, "CW101")) == 1
    assert _cw101_fix(text) == "{{DISPLAYTITLE:p}}\nBody text.\n"


def test_civ101_unknown_template_conservative():
    # not in template_info: only a gap that renders regardless (n >= 3) fires
    assert _lint("P", "{{Mystery}}\n\nBody.\n", CW101_INDEX, "CW101") == []
    assert len(_lint("P", "{{Mystery}}\n\n\nBody.\n", CW101_INDEX, "CW101")) == 1


def test_civ101_gap_between_templates():
    text = "{{Infobox civilization|name=T}}\n\n{{Infobox alliance|name=U}}\nBody.\n"
    assert len(_lint("P", text, CW101_INDEX, "CW101")) == 1


def test_civ101_blank_lines_in_prose_ok():
    text = "{{Infobox alliance|name=T}}\nBody text.\n\n\nMore prose.\n"
    assert _lint("P", text, CW101_INDEX, "CW101") == []


def test_civ101_trailing_whitespace_only_ok():
    assert _lint("P", "{{Infobox civilization|name=T}}\n\n", CW101_INDEX, "CW101") == []
