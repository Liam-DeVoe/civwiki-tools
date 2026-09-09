"""Tests for the index-dependent CW rules (CW101, CW103, CW121, CW132)."""

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
    assert [f.message for f in findings] == ["links to nonexistent page 'Missing Page'"]


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


# comment semantics (validated via the parse API): \n<!-- c -->\n collapses
# to \n, but a comment at the very start of the page is deleted without
# consuming a newline


def test_civ101_comment_only_lines_at_top_ok():
    text = "<!-- a -->\n<!-- b -->\nBody text.\n"
    assert _lint("P", text, CW101_INDEX, "CW101") == []


def test_civ101_page_start_comment_then_blank_fires():
    text = "<!-- a -->\n\nBody text.\n"
    assert len(_lint("P", text, CW101_INDEX, "CW101")) == 1
    assert _cw101_fix(text) == "<!-- a -->\nBody text.\n"


def test_civ101_comment_line_swallows_one_newline():
    # expands to </table>\n + \n + (comment line collapses \n\n to \n):
    # three newlines render, but no single-gap edit can fix it
    text = "{{Infobox civilization|name=T}}\n<!-- note -->\n\nBody.\n"
    findings = _lint("P", text, CW101_INDEX, "CW101")
    assert len(findings) == 1
    assert findings[0].fix is None


# --- CW132: unnamed argument to a template with no positional parameters ---

CW132_INDEX = SiteIndex.from_pages(
    {
        # named-only: reads name/alt/motto; the {{{fake}}} in <noinclude>
        # documentation must not count as a declared parameter
        "Template:Infobox paper": (
            "{{{name|}}} {{{alt|}}} {{{motto|}}}"
            "<noinclude>doc says {{{fake}}}</noinclude>"
        ),
        "Template:Wrap": "{{{1}}} in {{{style|}}}",  # positional
        "Template:Lua": "{{#invoke:Foo|bar}}",
        "Template:Dynamic": "{{{ {{{which}}} |}}}",
        "Template:Static": "no parameters at all",
        "Template:IP": "#REDIRECT [[Template:Infobox paper]]",
    }
)


def _cw132_fix(text):
    fixed, applied, _ = fixer.apply_fixes(
        text, lambda t: _lint("P", t, CW132_INDEX, "CW132"), unsafe=True
    )
    return fixed, applied


def test_cw132_missing_equals_fix():
    text = "{{Infobox paper|name=X|alt|Some caption|motto=Y}}"
    findings = _lint("P", text, CW132_INDEX, "CW132")
    assert len(findings) == 1
    assert "missing '='" in findings[0].message
    fixed, applied = _cw132_fix(text)
    assert fixed == "{{Infobox paper|name=X|alt=Some caption|motto=Y}}"
    assert applied == {"CW132": 1}


def test_cw132_stray_double_pipe_fix():
    fixed, applied = _cw132_fix("{{Infobox paper|name=X||motto=Y}}")
    assert fixed == "{{Infobox paper|name=X|motto=Y}}"
    assert applied == {"CW132": 1}


def test_cw132_stray_pipe_keeps_line_layout():
    # only the pipe is deleted; the newline stays so lines don't join
    fixed, _ = _cw132_fix("{{Infobox paper|name=X|\n|motto=Y\n}}")
    assert fixed == "{{Infobox paper|name=X\n|motto=Y\n}}"


def test_cw132_stray_pipe_before_closing_braces():
    # a value ending in `}` stays separated from the closing `}}` by the
    # argument's newline, so the deletion is offered and harmless
    fixed, _ = _cw132_fix("{{Infobox paper|name={x}|\n}}")
    assert fixed == "{{Infobox paper|name={x}\n}}"


def test_cw132_brace_glue_blocks_fix():
    # with no whitespace, deleting the pipe would glue `}` onto `}}` and
    # move the preprocessor's closing point; report-only
    text = "{{Infobox paper|name={x}|}}"
    findings = _lint("P", text, CW132_INDEX, "CW132")
    assert len(findings) == 1
    assert findings[0].fix is None
    fixed, applied = _cw132_fix(text)
    assert fixed == text and not applied


def test_cw132_generic_unnamed_is_report_only():
    findings = _lint("P", "{{Infobox paper|name=X|stray}}", CW132_INDEX, "CW132")
    assert len(findings) == 1
    assert findings[0].fix is None


def test_cw132_noinclude_param_not_declared():
    # "fake" only appears in the template's <noinclude> doc, so it doesn't
    # qualify for the missing-= fix
    findings = _lint("P", "{{Infobox paper|fake|x}}", CW132_INDEX, "CW132")
    assert len(findings) == 2
    assert all(f.fix is None for f in findings)


def test_cw132_bare_name_run_not_merged():
    # two declared names in a row is a run of bare names (values deleted or
    # never filled in), not a name|value pair
    findings = _lint("P", "{{Infobox paper|alt|motto|name=X}}", CW132_INDEX, "CW132")
    assert len(findings) == 2
    assert all(f.fix is None for f in findings)


def test_cw132_existing_named_key_blocks_merge():
    # merging would create a duplicate alt=; report only
    findings = _lint("P", "{{Infobox paper|alt=A|alt|caption}}", CW132_INDEX, "CW132")
    assert len(findings) == 2
    assert all(f.fix is None for f in findings)


def test_cw132_positional_template_skipped():
    assert _lint("P", "{{Wrap|text|style=big}}", CW132_INDEX, "CW132") == []


def test_cw132_lua_template_skipped():
    assert _lint("P", "{{Lua|anything}}", CW132_INDEX, "CW132") == []


def test_cw132_dynamic_params_skipped():
    assert _lint("P", "{{Dynamic|x|which=1}}", CW132_INDEX, "CW132") == []


def test_cw132_unknown_template_skipped():
    assert _lint("P", "{{Mystery|arg}}", CW132_INDEX, "CW132") == []


def test_cw132_no_params_template_fires():
    findings = _lint("P", "{{Static|stray}}", CW132_INDEX, "CW132")
    assert len(findings) == 1
    assert findings[0].fix is None


def test_cw132_redirect_followed():
    fixed, _ = _cw132_fix("{{IP|name=X|alt|caption}}")
    assert fixed == "{{IP|name=X|alt=caption}}"


def test_cw132_named_only_call_ok():
    text = "{{Infobox paper|name=X|alt=Y|motto=Z}}"
    assert _lint("P", text, CW132_INDEX, "CW132") == []


def test_cw132_nested_template_checked():
    text = "{{Infobox paper|name={{Static|stray}}}}"
    findings = _lint("P", text, CW132_INDEX, "CW132")
    assert len(findings) == 1


def test_cw132_multiline_call():
    text = "{{Infobox paper\n|name=X\n|alt\n|Some caption\n|motto=Y\n}}"
    fixed, _ = _cw132_fix(text)
    assert fixed == "{{Infobox paper\n|name=X\n|alt=Some caption\n|motto=Y\n}}"


def test_cw132_shielded_skipped():
    text = "<nowiki>{{Infobox paper|alt|x}}</nowiki>"
    assert _lint("P", text, CW132_INDEX, "CW132") == []
