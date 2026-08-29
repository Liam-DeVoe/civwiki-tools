from civlint.report import diff_html


def test_intraline_highlight_marks_only_the_changed_word():
    out = diff_html(
        "a long line with Transfered inside it",
        "a long line with Transferred inside it",
    )
    assert '<span class="addseg">' in out
    # the unchanged parts of the line are not inside highlight segments
    assert "a long line with" not in out.split("addseg")[1].split("</span>")[0]


def test_whitespace_only_change_is_visible():
    out = diff_html("trailing   \nnext", "trailing\nnext")
    assert "···" in out


def test_unpaired_lines_render_plain():
    out = diff_html("kept\ndeleted line\n", "kept\n")
    assert '<pre class="del">-deleted line</pre>' in out
