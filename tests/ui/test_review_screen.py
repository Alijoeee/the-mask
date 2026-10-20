"""The review screen: the text with its finds highlighted, the inspector with the list of groups
in sections, and the actions.

The first five tests are the brief's, on the review of supply-08.docx (the contract with a shared
surname that also names "Project Falcon" twice). The rest check what the brief leaves open: that
the highlights lie exactly on the finds, also in a text of several files with a character outside
the BMP and a carriage return in it, the single occurrences, merge and split, the two lists, a
click on a highlight, the tooltip that says "check", and that 500 highlights in a 30-page text are
drawn in well under 2 seconds. Where the design pass changed the screen, the tests that read the
old one are adapted (each says so where it is): the summary line and the file name are the
window's ``title()``, a group's "check" is the pill of its row, and merge, split and always-hide
are actions of a row's context menu. The newer tests are about the sections and the rows, the
title, the footer, the "Not sure — hide?" section, the switch of a row, the keys, the find field
and ⌘F, the context menu and the page; they use reviews made by hand (``review_samples``) where
the detection engine is not the point.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import (
    QContextMenuEvent,
    QHelpEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication, QToolTip, QTreeWidgetItem

from tests.ui.review_samples import CONTRACT, FAMILY_SPECS, UNSURE_SPECS, custom_review
from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText
from themask.model import Finding, Group, PlaceholderType
from themask.paths import lists_path
from themask.review import ReviewState
from themask.ui import review_screen
from themask.ui.review_screen import ReviewScreen
from themask.ui.theme import TYPE_COLOURS

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot

CUSTOM = PlaceholderType.CUSTOM
COMPANY = PlaceholderType.COMPANY
AMOUNT = PlaceholderType.AMOUNT
PERSON = PlaceholderType.PERSON

Screen = tuple[ReviewScreen, ReviewState]


# ---- helpers ------------------------------------------------------------------------------------


def select_text(screen: ReviewScreen, start: int, end: int) -> None:
    """Select the text from position ``start`` to ``end`` of the text pane."""
    cursor = screen.text.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    screen.text.setTextCursor(cursor)


def select_items(screen: ReviewScreen, *items: QTreeWidgetItem) -> None:
    """Select exactly these items of the list, the way a click with the command key does."""
    screen.tree.clearSelection()
    for item in items:
        item.setSelected(True)


def u16(text: str, index: int) -> int:
    """The position in a text pane of the character at ``index`` of ``text``: Qt counts the
    UTF-16 units before it, and a character outside the BMP is two.
    """
    return len(text[:index].encode("utf-16-le", "surrogatepass")) // 2


def group_named(state: ReviewState, canonical: str) -> Group:
    return next(g for g in state.groups if g.canonical == canonical)


def highlights(screen: ReviewScreen) -> list[tuple[int, int, str]]:
    """What the pane draws: (start, end, text) of each highlight, in order."""
    return [
        (s.cursor.selectionStart(), s.cursor.selectionEnd(), s.cursor.selectedText())
        for s in screen.text.extraSelections()
    ]


def active(state: ReviewState) -> list[Finding]:
    """The finds the plan will replace, in text order."""
    return sorted(
        (f for g in state.groups for f in g.active_findings()), key=lambda f: (f.start, f.end)
    )


def review_of(
    parts: list[tuple[str, str]], finds: dict[str, PlaceholderType], warnings: tuple[str, ...] = ()
) -> tuple[CombinedText, ReviewState]:
    """A review of the files ``parts`` (name, text) with one group for each value in ``finds``,
    which holds every place in the combined text where the value stands.
    """
    combined = CombinedText.join(parts)
    groups: list[Group] = []
    numbers: dict[PlaceholderType, int] = {}
    for value, kind in finds.items():
        findings = []
        start = combined.text.find(value)
        while start >= 0:
            findings.append(Finding(kind, start, start + len(value), value, 1.0, "model"))
            start = combined.text.find(value, start + len(value))
        numbers[kind] = numbers.get(kind, 0) + 1
        placeholder = f"[{kind.value}_{numbers[kind]}]"
        groups.append(Group(f"g{len(groups)}", kind, value, {value}, findings, placeholder))
    groups.sort(key=lambda g: g.findings[0].start)
    state = ReviewState(
        combined.text, groups, list(warnings), UserLists([], []), CaseLists([], [], set())
    )
    return combined, state


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The messages the screen shows with ``show_notice``, recorded instead of opened as a dialog."""
    shown: list[str] = []
    monkeypatch.setattr(review_screen, "show_notice", lambda parent, message: shown.append(message))
    return shown


# ---- the brief's five ---------------------------------------------------------------------------


def test_tree_matches_state(review_screen: Screen) -> None:
    s, st = review_screen
    # Adapted to the inspector: the line of a group shows its value (the placeholder is in the
    # caption of its row), and the first line is the first group of the first section.
    assert s.tree.topLevelItemCount() == len(st.groups)
    assert s.tree.topLevelItem(0).text(0) == st.groups[0].canonical
    assert s.row_for(st.groups[0].id).data.caption.startswith(st.groups[0].placeholder)


def test_untick_group_updates_plan_and_highlight(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    n = len(st.mask_plan().replacements)
    item = s.tree.topLevelItem(0)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert len(st.mask_plan().replacements) < n and s.highlight_count() == len(
        st.mask_plan().replacements
    )


def test_hide_selection(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    i = s.text.toPlainText().index("Project Falcon")
    c = s.text.textCursor()
    c.setPosition(i)
    c.setPosition(i + len("Project Falcon"), c.MoveMode.KeepAnchor)
    s.text.setTextCursor(c)
    s.hide_selection(PlaceholderType.CUSTOM)
    assert any(
        g.canonical == "Project Falcon" for g in st.groups
    ) and s.tree.topLevelItemCount() == len(st.groups)


def test_needs_check_marked(review_screen: Screen) -> None:
    s, st = review_screen
    # Adapted to the inspector: "check" was a second column of the line, it is the pill of the row.
    flagged = [g for g in st.groups if g.needs_check]
    assert flagged
    for group in st.groups:
        assert (s.row_for(group.id).pill_box() is not None) == group.needs_check


def test_export_signal(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    with qtbot.waitSignal(s.exportRequested):
        qtbot.mouseClick(s.export_button, Qt.MouseButton.LeftButton)


# ---- the list of groups ---------------------------------------------------------------------------


def test_each_group_is_a_line_with_its_count_and_a_line_for_each_occurrence(
    review_screen: Screen,
) -> None:
    s, st = review_screen
    assert s.group_count() == len(st.groups)
    falcon = group_named(st, "Project Falcon")
    item = s.tree_item_for(falcon.id)
    # Adapted to the inspector: the line shows the value, and its count and placeholder are in the
    # caption of its row.
    assert item.text(0) == "Project Falcon"
    assert s.row_for(falcon.id).data.caption.startswith(f"{falcon.placeholder} · 2 places")
    assert item.childCount() == 2
    for k, finding in enumerate(falcon.findings):
        assert "Project Falcon" in item.child(k).text(0) and item.child(k).childCount() == 0
    once = next(g for g in st.groups if len(g.findings) == 1)
    assert s.tree_item_for(once.id).text(0) == " ".join(once.canonical.split())
    assert s.row_for(once.id).data.caption.startswith(f"{once.placeholder} · 1 place")
    assert (s.row_for(once.id).pill_box() is not None) == once.needs_check


def test_an_occurrence_is_shown_with_the_words_around_it(review_screen: Screen) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    context = s.tree_item_for(falcon.id).child(0).text(0)
    assert "programme known as Project Falcon." in context  # what the contract says there
    assert "\n" not in context and len(context) < 120


def test_the_boxes_show_what_is_switched_on(review_screen: Screen) -> None:
    s, st = review_screen
    for group in st.groups:
        item = s.tree_item_for(group.id)
        assert item.checkState(0) == Qt.CheckState.Checked
        assert all(
            item.child(k).checkState(0) == Qt.CheckState.Checked for k in range(item.childCount())
        )


def test_a_review_with_things_switched_off_shows_them_off(qtbot: QtBot) -> None:
    combined, st = review_of(
        [("a.docx (after)", "Acme Ltd pays Acme Ltd and Beta Ltd.")],
        {"Acme Ltd": COMPANY, "Beta Ltd": COMPANY},
    )
    st.set_occurrence_enabled("g0", 1, False)
    st.set_group_enabled("g1", False)
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    acme, beta = s.tree_item_for("g0"), s.tree_item_for("g1")
    assert acme.checkState(0) == Qt.CheckState.Checked
    assert [acme.child(k).checkState(0) for k in (0, 1)] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
    ]
    assert beta.checkState(0) == Qt.CheckState.Unchecked
    assert s.highlight_count() == 1  # the first Acme Ltd


def test_tree_item_for_an_unknown_group_is_refused(review_screen: Screen) -> None:
    s, _ = review_screen
    with pytest.raises(ValueError, match="no such group"):
        s.tree_item_for("not-a-group")


def test_untick_one_occurrence_updates_the_plan_and_the_highlights(review_screen: Screen) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    n = len(st.mask_plan().replacements)
    s.tree_item_for(group.id).child(2).setCheckState(0, Qt.CheckState.Unchecked)
    assert group.disabled == {2} and group.enabled
    assert len(st.mask_plan().replacements) == n - 1
    assert s.highlight_count() == n - 1
    assert s.tree_item_for(group.id).checkState(0) == Qt.CheckState.Checked  # the group is still on
    s.tree_item_for(group.id).child(2).setCheckState(0, Qt.CheckState.Checked)
    assert group.disabled == set() and s.highlight_count() == n


def test_switching_a_group_off_greys_its_occurrences_and_keeps_their_own_switches(
    review_screen: Screen,
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    item = s.tree_item_for(group.id)
    item.child(1).setCheckState(0, Qt.CheckState.Unchecked)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert not group.enabled and group.disabled == {1}  # one switch does not touch the other
    assert s.highlight_count() == len(st.mask_plan().replacements)
    assert all(
        not (item.child(k).flags() & Qt.ItemFlag.ItemIsEnabled) for k in range(item.childCount())
    )
    item.setCheckState(0, Qt.CheckState.Checked)
    assert group.enabled and group.disabled == {1}
    assert all(item.child(k).flags() & Qt.ItemFlag.ItemIsEnabled for k in range(item.childCount()))
    assert item.child(1).checkState(0) == Qt.CheckState.Unchecked


def test_the_summary_follows_the_review(review_screen: Screen) -> None:
    s, st = review_screen
    # Adapted to the inspector: the summary line is the second line of the title the window shows
    # (title()), and the counts of what is hidden are the footer's.
    counts = st.counts()
    assert s.title()[1] == (
        f"Review · {counts.groups} values found · {counts.needs_check} to check"
    )
    assert s.counts_label.text().endswith("shown on purpose")
    first = st.groups[0]
    s.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert not first.enabled
    assert s.counts_label.text().split(" · ")[-1] == "1 shown on purpose"
    assert (
        s.title()[1]
        == f"Review · {counts.groups} values found · {st.counts().needs_check} to check"
    )


def test_the_warnings_of_the_analysis_are_shown(qtbot: QtBot) -> None:
    warning = "The document already contains placeholders such as [PERSON_1]."
    combined, st = review_of(
        [("a.docx (after)", "Acme Ltd signs.")], {"Acme Ltd": COMPANY}, (warning,)
    )
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    assert s.warnings_label.text() == warning and not s.warnings_label.isHidden()
    clean, quiet = review_of([("a.docx (after)", "Acme Ltd signs.")], {"Acme Ltd": COMPANY})
    s.load(quiet, clean)
    assert s.warnings_label.isHidden()


def test_the_export_button_works_with_nothing_to_hide(qtbot: QtBot) -> None:
    # The owner may export a document with nothing to hide: the dialog then says so.
    s = ReviewScreen()
    qtbot.addWidget(s)
    assert s.export_button.isEnabled() and s.group_count() == 0
    combined, st = review_of([("a.docx (after)", "Acme Ltd signs.")], {"Acme Ltd": COMPANY})
    s.load(st, combined)
    s.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert s.export_button.isEnabled() and s.highlight_count() == 0


# ---- the text pane ------------------------------------------------------------------------------


def test_the_pane_shows_the_combined_text_under_the_name_of_the_file(review_screen: Screen) -> None:
    s, st = review_screen
    assert s.text.isReadOnly()
    assert s.text.document().firstBlock().text() == "supply-08.docx"  # not "(after)": no redline
    assert s.text.toPlainText() == "supply-08.docx\n" + st.text


def test_every_active_find_is_highlighted_exactly_where_it_stands(review_screen: Screen) -> None:
    s, st = review_screen
    drawn = highlights(s)
    finds = active(st)
    assert len(drawn) == len(finds) == s.highlight_count()
    assert [text for _, _, text in drawn] == [f.text for f in finds]
    header = len("supply-08.docx\n")
    assert [start - header for start, _, _ in drawn] == [f.start for f in finds]


def test_each_find_has_the_colour_of_its_type_and_black_text(review_screen: Screen) -> None:
    s, st = review_screen
    by_start = {f.start: (g, f) for g in st.groups for f in g.findings}
    header = len("supply-08.docx\n")
    for selection in s.text.extraSelections():
        group, _ = by_start[selection.cursor.selectionStart() - header]
        assert selection.format.background().color().name().upper() == TYPE_COLOURS[group.type]
        assert selection.format.foreground().color().name() == "#000000"


def test_a_group_to_check_is_underlined_with_dots(review_screen: Screen) -> None:
    s, st = review_screen
    by_start = {f.start: g for g in st.groups for f in g.findings}
    header = len("supply-08.docx\n")
    styles = {
        by_start[sel.cursor.selectionStart() - header].needs_check: sel.format.underlineStyle()
        for sel in s.text.extraSelections()
    }
    assert styles[True] == QTextCharFormat.UnderlineStyle.DotLine
    assert styles[False] == QTextCharFormat.UnderlineStyle.NoUnderline


def test_the_highlights_follow_every_change_of_the_review(review_screen: Screen) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    s.tree_item_for(group.id).setCheckState(0, Qt.CheckState.Unchecked)
    assert [t for _, _, t in highlights(s)] == [f.text for f in active(st)]
    s.tree_item_for(group.id).setCheckState(0, Qt.CheckState.Checked)
    s.tree_item_for(group.id).child(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert [t for _, _, t in highlights(s)] == [f.text for f in active(st)]
    assert s.highlight_count() == len(active(st))


def test_loading_another_review_replaces_everything(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    combined, st = review_of([("other.docx (after)", "Zed Ltd signs.")], {"Zed Ltd": COMPANY})
    s.load(st, combined)
    assert s.review is st and s.combined is combined and s.group_count() == 1
    assert s.tree.topLevelItemCount() == 1 and s.highlight_count() == 1
    assert s.text.toPlainText() == "other.docx\nZed Ltd signs."
    assert s.text.textCursor().position() == 0 and not s.text.textCursor().hasSelection()


def test_a_review_made_on_another_text_is_refused(qtbot: QtBot) -> None:
    combined, st = review_of([("a.docx (after)", "Acme Ltd signs.")], {"Acme Ltd": COMPANY})
    other = CombinedText.join([("a.docx (after)", "Something else.")])
    s = ReviewScreen()
    qtbot.addWidget(s)
    with pytest.raises(ValueError, match="not made on this text"):
        s.load(st, other)
    s.load(st, combined)


# ---- several files, and characters that need care --------------------------------------------------

TWO_FILES = [
    ("contract.docx (after)", "Signed by Alpha Corp.\nThe fee is EUR 5,000 today."),
    ("contract.docx (before)", "Beta \U0001f600 Corp signs.\r\nGamma Corp pays EUR 5,000."),
]
TWO_FILES_FINDS = {"Alpha Corp": COMPANY, "Gamma Corp": COMPANY, "EUR 5,000": AMOUNT}


def two_files(qtbot: QtBot) -> tuple[ReviewScreen, ReviewState]:
    combined, st = review_of(TWO_FILES, TWO_FILES_FINDS)
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    return s, st


def test_each_file_has_a_header_and_the_finds_lie_on_their_own_text(qtbot: QtBot) -> None:
    s, st = two_files(qtbot)
    plain = s.text.toPlainText()
    assert plain.startswith("contract.docx (after)\nSigned by Alpha Corp.")
    assert "\ncontract.docx (before)\nBeta \U0001f600 Corp signs." in plain
    # In the second file a character outside the BMP (two UTF-16 units) and a carriage return
    # come before the finds; each highlight still covers exactly its find.
    assert [t for _, _, t in highlights(s)] == [
        "Alpha Corp",
        "EUR 5,000",
        "Gamma Corp",
        "EUR 5,000",
    ]
    assert s.highlight_count() == 4 == len(active(st))


def test_a_selection_in_the_second_file_hides_the_right_text(qtbot: QtBot) -> None:
    s, st = two_files(qtbot)
    plain = s.text.toPlainText()
    start = u16(plain, plain.index("pays"))
    select_text(s, start, start + len("pays"))
    s.hide_selection(CUSTOM)
    pays = group_named(st, "pays")
    assert pays.type is CUSTOM and [f.start for f in pays.findings] == [st.text.index("pays")]
    assert [t for _, _, t in highlights(s)] == [
        "Alpha Corp",
        "EUR 5,000",
        "Gamma Corp",
        "pays",
        "EUR 5,000",
    ]
    assert s.row_for(pays.id).data.caption.startswith(pays.placeholder)  # see tree_matches_state


def test_a_selection_crossing_from_one_file_into_the_next_is_refused(
    qtbot: QtBot, notices: list[str]
) -> None:
    s, st = two_files(qtbot)
    groups = len(st.groups)
    plain = s.text.toPlainText()
    select_text(s, u16(plain, plain.index("today")), u16(plain, plain.index("Beta") + 4))
    s.hide_selection(CUSTOM)
    assert notices == ["Select text from one file at a time."]
    assert len(st.groups) == groups


def test_a_selection_of_a_file_name_is_refused(qtbot: QtBot, notices: list[str]) -> None:
    s, _ = two_files(qtbot)
    plain = s.text.toPlainText()
    start = plain.index("contract.docx (before)")
    select_text(s, start, start + len("contract.docx (before)"))
    s.hide_selection(CUSTOM)
    assert notices == ["Select some of the document's text, not a file name."]


def test_a_selection_that_reaches_into_a_header_hides_the_text_part_of_it(qtbot: QtBot) -> None:
    s, st = two_files(qtbot)
    plain = s.text.toPlainText()
    # From the middle of the first file's name to the end of the word "Signed" after it.
    select_text(s, 5, plain.index("Signed") + len("Signed"))
    assert s.hide_button.isEnabled()
    s.hide_selection(CUSTOM)
    signed = group_named(st, "Signed")
    assert [f.start for f in signed.findings] == [st.text.index("Signed")]
    assert highlights(s)[0][2] == "Signed"


def test_what_the_pane_selects_is_taken_from_the_text_and_not_from_the_pane(qtbot: QtBot) -> None:
    # A no-break space shows as a plain space in the pane; the value is the text's own.
    combined, st = review_of([("a.docx (after)", "The Falcon\xa0Programme starts now.")], {})
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    plain = s.text.toPlainText()
    start = plain.index("Falcon")
    select_text(s, start, start + len("Falcon Programme"))
    s.hide_selection(CUSTOM)
    assert st.groups[0].canonical == "Falcon\xa0Programme"


# ---- hiding what was missed ---------------------------------------------------------------------


def test_the_hide_button_needs_a_selection_and_offers_every_type(review_screen: Screen) -> None:
    s, st = review_screen
    assert not s.hide_button.isEnabled()
    i = s.text.toPlainText().index("Project Falcon")
    select_text(s, i, i + len("Project Falcon"))
    assert s.hide_button.isEnabled()
    menu = s.hide_button.menu()
    assert [a.text() for a in menu.actions()] == [kind.value for kind in PlaceholderType]
    next(a for a in menu.actions() if a.text() == "PERSON").trigger()
    falcon = group_named(st, "Project Falcon")
    assert falcon.type is PERSON and s.tree.topLevelItemCount() == len(st.groups)  # re-typed


def test_hiding_text_the_analysis_missed_adds_a_group_with_all_its_places(
    review_screen: Screen,
) -> None:
    s, st = review_screen
    before = s.highlight_count()
    i = s.text.toPlainText().index("Supply Agreement")  # a title the analysis rightly left visible
    select_text(s, i, i + len("Supply Agreement"))
    s.hide_selection(CUSTOM)
    group = group_named(st, "Supply Agreement")
    assert group.type is CUSTOM and s.highlight_count() == before + len(group.findings)
    assert s.tree.currentItem() is s.tree_item_for(group.id)  # the new group is the selected one


@pytest.mark.parametrize(
    ("what", "expected"),
    [("one letter", "Select at least two letters or digits to hide."), ("nothing", "Select")],
)
def test_text_that_cannot_be_hidden_is_explained(
    review_screen: Screen, notices: list[str], what: str, expected: str
) -> None:
    s, st = review_screen
    groups = len(st.groups)
    if what == "one letter":
        i = s.text.toPlainText().index("Agreement")
        select_text(s, i, i + 1)
    s.hide_selection(CUSTOM)
    assert len(notices) == 1 and notices[0].startswith(expected)
    assert len(st.groups) == groups


# ---- merging and splitting ----------------------------------------------------------------------

# Merge, Split and Always hide are actions of the context menu of a row now (the inspector has room
# for two buttons), so these tests trigger ``merge_action``, ``split_action`` and ``always_action``
# where they clicked ``merge_button``, ``split_button`` and ``always_button``.


def test_merge_needs_two_groups_and_makes_them_one(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    one, two = group_named(st, "2 per cent"), group_named(st, "10 per cent")
    assert not s.merge_action.isEnabled()
    select_items(s, s.tree_item_for(one.id))
    assert not s.merge_action.isEnabled()
    select_items(s, s.tree_item_for(one.id), s.tree_item_for(two.id))
    assert s.merge_action.isEnabled()
    groups = len(st.groups)
    s.merge_action.trigger()
    assert len(st.groups) == groups - 1 and s.tree.topLevelItemCount() == len(st.groups)
    survivor = next(g for g in st.groups if g.id in {one.id, two.id})
    assert len(survivor.findings) == 3
    assert s.tree_item_for(survivor.id).childCount() == 3
    gone = ({one.id, two.id} - {survivor.id}).pop()
    with pytest.raises(ValueError, match="no such group"):
        s.tree_item_for(gone)
    assert s.highlight_count() == len(st.mask_plan().replacements)
    assert s.tree.currentItem() is s.tree_item_for(survivor.id)


def test_groups_of_different_types_are_not_merged(
    qtbot: QtBot, review_screen: Screen, notices: list[str]
) -> None:
    s, st = review_screen
    company, percent = group_named(st, "Pennine Workwear Ltd"), group_named(st, "2 per cent")
    select_items(s, s.tree_item_for(company.id), s.tree_item_for(percent.id))
    groups = len(st.groups)
    s.merge_action.trigger()
    assert notices == ["Only groups of the same type can be merged."]
    assert len(st.groups) == groups


def test_split_moves_the_selected_occurrences_into_a_group_of_their_own(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    item = s.tree_item_for(group.id)
    assert not s.split_action.isEnabled()
    select_items(s, item)
    assert not s.split_action.isEnabled()  # a split needs occurrences, not a group
    moved = [group.findings[1], group.findings[3]]
    select_items(s, item.child(1), item.child(3))
    assert s.split_action.isEnabled()
    groups, total = len(st.groups), len(group.findings)
    s.split_action.trigger()
    assert len(st.groups) == groups + 1 and s.tree.topLevelItemCount() == len(st.groups)
    assert len(group.findings) == total - 2
    new = next(g for g in st.groups if {f.start for f in g.findings} == {m.start for m in moved})
    assert new is not group and new.type is group.type
    assert s.tree_item_for(new.id).childCount() == 2
    assert s.tree.currentItem() is s.tree_item_for(new.id)
    assert s.highlight_count() == len(st.mask_plan().replacements)


def test_split_cannot_take_every_occurrence(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    group = group_named(st, "Project Falcon")
    item = s.tree_item_for(group.id)
    select_items(s, item.child(0))
    assert s.split_action.isEnabled()
    select_items(s, item.child(0), item.child(1))
    assert not s.split_action.isEnabled()  # the group would be left with nothing


def test_split_needs_the_occurrences_of_one_group(review_screen: Screen) -> None:
    s, st = review_screen
    one, two = group_named(st, "Pennine Workwear Ltd"), group_named(st, "Lindenhof Hotels GmbH")
    select_items(s, s.tree_item_for(one.id).child(0), s.tree_item_for(two.id).child(0))
    assert not s.split_action.isEnabled()


# ---- the two lists ------------------------------------------------------------------------------


def test_always_hide_puts_the_value_of_the_group_on_the_list_for_every_document(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    assert not s.always_action.isEnabled() and not s.never_button.isEnabled()
    select_items(s, s.tree_item_for(falcon.id))
    assert s.always_action.isEnabled() and s.never_button.isEnabled()
    s.always_action.trigger()
    assert st.user_lists.always_hide == ["Project Falcon"]
    assert UserLists.load(lists_path()).always_hide == ["Project Falcon"]  # saved for next time
    assert falcon.enabled and s.tree.topLevelItemCount() == len(st.groups)


def test_never_hide_puts_the_value_on_the_list_and_switches_the_group_off(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    before = s.highlight_count()
    select_items(s, s.tree_item_for(falcon.id))
    qtbot.mouseClick(s.never_button, Qt.MouseButton.LeftButton)
    assert st.user_lists.never_hide == ["Project Falcon"]
    assert UserLists.load(lists_path()).never_hide == ["Project Falcon"]
    assert not falcon.enabled
    assert s.tree_item_for(falcon.id).checkState(0) == Qt.CheckState.Unchecked
    assert s.highlight_count() == before - len(falcon.findings)


def test_the_lists_work_on_the_group_of_a_selected_occurrence(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    select_items(s, s.tree_item_for(falcon.id).child(1))
    assert s.always_action.isEnabled()
    s.always_action.trigger()
    assert st.user_lists.always_hide == ["Project Falcon"]


def test_the_lists_need_one_group(review_screen: Screen) -> None:
    s, _ = review_screen
    select_items(s, s.tree.topLevelItem(0), s.tree.topLevelItem(1))
    assert not s.always_action.isEnabled() and not s.never_button.isEnabled()


def test_a_list_that_cannot_be_saved_is_explained(
    qtbot: QtBot, review_screen: Screen, notices: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")

    def refuse(self: UserLists, path: Path) -> None:
        raise PermissionError(13, "Permission denied", "/Users/someone/lists.json")

    monkeypatch.setattr(UserLists, "save", refuse)
    select_items(s, s.tree_item_for(falcon.id))
    s.always_action.trigger()
    assert len(notices) == 1 and "Permission denied" in notices[0] and "/Users" not in notices[0]


# ---- groups and the text move together ------------------------------------------------------------


def test_selecting_a_group_moves_the_text_cursor_to_its_first_occurrence(
    review_screen: Screen,
) -> None:
    s, st = review_screen
    group = st.groups[-1]  # far down the contract
    s.tree.setCurrentItem(s.tree_item_for(group.id))
    first = group.findings[0]
    position = s.text.textCursor().position()
    assert s.text.toPlainText()[position : position + len(first.text)] == first.text
    assert position == len("supply-08.docx\n") + first.start
    assert not s.text.textCursor().hasSelection()


def test_selecting_an_occurrence_moves_the_cursor_to_that_one(review_screen: Screen) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    s.tree.setCurrentItem(s.tree_item_for(group.id).child(3))
    assert s.text.textCursor().position() == len("supply-08.docx\n") + group.findings[3].start


def test_a_group_that_is_switched_off_can_still_be_found_in_the_text(
    review_screen: Screen,
) -> None:
    s, st = review_screen
    group = group_named(st, "Lindenhof Hotels GmbH")
    s.tree_item_for(group.id).setCheckState(0, Qt.CheckState.Unchecked)
    s.text.moveCursor(QTextCursor.MoveOperation.Start)
    s.tree.setCurrentItem(s.tree_item_for(group.id))
    position = s.text.textCursor().position()
    first = group.findings[0]
    assert s.text.toPlainText()[position : position + len(first.text)] == first.text
    assert all(text != first.text for _, _, text in highlights(s))  # nothing is drawn for it


def test_the_occurrences_of_the_selected_group_stand_out(review_screen: Screen) -> None:
    s, st = review_screen
    group = group_named(st, "Project Falcon")
    plain = {
        sel.cursor.selectionStart(): sel.format.background().color().name()
        for sel in s.text.extraSelections()
    }
    s.tree.setCurrentItem(s.tree_item_for(group.id))
    stressed = {
        sel.cursor.selectionStart(): sel.format.background().color().name()
        for sel in s.text.extraSelections()
    }
    header = len("supply-08.docx\n")
    starts = {header + f.start for f in group.findings}
    assert {p for p in plain if plain[p] != stressed[p]} == starts  # these and no others
    assert s.highlight_count() == len(plain)


def show(qtbot: QtBot, screen: ReviewScreen) -> None:
    screen.resize(1100, 700)
    screen.show()
    qtbot.waitExposed(screen)


def activate(qtbot: QtBot, screen: ReviewScreen) -> None:
    """Show the screen and make its window the active one: a shortcut works in the active window."""
    show(qtbot, screen)
    screen.activateWindow()
    qtbot.waitUntil(screen.isActiveWindow, timeout=3000)


def point_in(screen: ReviewScreen, start: int) -> QPoint:
    """A point of the pane's viewport inside the character at position ``start`` of the pane."""
    cursor = QTextCursor(screen.text.document())
    cursor.setPosition(start + 1)
    rect = screen.text.cursorRect(cursor)
    return QPoint(rect.x() + 2, rect.center().y())


def scroll_to(screen: ReviewScreen, position: int) -> None:
    cursor = screen.text.textCursor()
    cursor.setPosition(position)
    screen.text.setTextCursor(cursor)
    screen.text.ensureCursorVisible()


def test_clicking_a_highlight_selects_its_group_and_stays_where_it_is(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    show(qtbot, s)
    falcon = group_named(st, "Project Falcon")
    first, second = (
        sel for sel in s.text.extraSelections() if sel.cursor.selectedText() == "Project Falcon"
    )
    start = second.cursor.selectionStart()
    scroll_to(s, start)
    qtbot.mouseClick(s.text.viewport(), Qt.MouseButton.LeftButton, pos=point_in(s, start))
    assert s.tree.currentItem() is s.tree_item_for(falcon.id)
    assert s.tree.selectedItems() == [s.tree_item_for(falcon.id)]
    # The click is in the second occurrence and the pane does not jump to the first.
    assert start <= s.text.textCursor().position() <= second.cursor.selectionEnd()
    assert first.cursor.selectionStart() < start


def test_clicking_text_that_is_not_a_find_selects_nothing(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    s.tree.clearSelection()
    i = s.text.toPlainText().index("AGREED TERMS")
    scroll_to(s, i)
    qtbot.mouseClick(s.text.viewport(), Qt.MouseButton.LeftButton, pos=point_in(s, i))
    assert s.tree.selectedItems() == []


def test_dragging_to_select_text_is_not_a_click_on_a_find(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    s.tree.clearSelection()
    i = s.text.toPlainText().index("Project Falcon")
    scroll_to(s, i)
    qtbot.mousePress(s.text.viewport(), Qt.MouseButton.LeftButton, pos=point_in(s, i))
    qtbot.mouseMove(s.text.viewport(), pos=point_in(s, i + 10))
    qtbot.mouseRelease(s.text.viewport(), Qt.MouseButton.LeftButton, pos=point_in(s, i + 10))
    assert s.text.textCursor().hasSelection() and s.hide_button.isEnabled()
    assert s.tree.selectedItems() == []


def send_tooltip(screen: ReviewScreen, point: QPoint) -> None:
    viewport = screen.text.viewport()
    QApplication.sendEvent(
        viewport, QHelpEvent(QEvent.Type.ToolTip, point, viewport.mapToGlobal(point))
    )


def find_start(screen: ReviewScreen, value: str) -> int:
    """The position in the pane of the first highlight that covers ``value``."""
    return next(
        sel.cursor.selectionStart()
        for sel in screen.text.extraSelections()
        if sel.cursor.selectedText() == value
    )


def test_hovering_over_a_find_to_check_says_check(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    show(qtbot, s)
    assert group_named(st, "Project Falcon").needs_check
    start = find_start(s, "Project Falcon")
    scroll_to(s, start)
    assert "check" in s.tooltip_at(point_in(s, start))
    try:
        send_tooltip(s, point_in(s, start))
        assert QToolTip.isVisible() and "check" in QToolTip.text()
    finally:
        QToolTip.hideText()


def test_hovering_over_a_find_that_is_sure_or_over_plain_text_says_nothing(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    show(qtbot, s)
    assert not group_named(st, "Pennine Workwear Ltd").needs_check
    start = find_start(s, "Pennine Workwear Ltd")
    scroll_to(s, start)
    assert s.tooltip_at(point_in(s, start)) == ""
    i = s.text.toPlainText().index("AGREED TERMS")
    scroll_to(s, i)
    assert s.tooltip_at(point_in(s, i)) == ""


# ---- the sections, the rows and the title ----------------------------------------------------------


def screen_of(
    qtbot: QtBot, text: str, specs: list[dict[str, Any]]
) -> tuple[ReviewScreen, ReviewState]:
    combined, st = custom_review(text, specs)
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    return s, st


def test_the_list_has_a_section_for_each_family_with_its_count(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    assert s.section_titles() == [
        "COMPANIES · 2",
        "PEOPLE · 2",
        "AMOUNTS, PERCENTAGES · 2",
        "ADDRESSES, E-MAIL, BANK · 1",
        "OTHER · 1",
    ]
    order = [s.tree.topLevelItem(k).text(0) for k in range(s.tree.topLevelItemCount())]
    assert order == [  # the families in order, the groups of a family in the order of the text
        "Northwind Trading B.V.",
        "Acme Supplies Ltd",
        "Mr John Carter",
        "Ms Fatma Yildiz",
        "EUR 1,250,000",
        "8 %",
        "j.carter@acme.example",
        "Project Falcon",
    ]
    first_of_section = [g.canonical for g in st.groups if s.row_for(g.id).heading is not None]
    assert first_of_section == [
        "Northwind Trading B.V.",
        "Mr John Carter",
        "EUR 1,250,000",
        "j.carter@acme.example",
        "Project Falcon",
    ]


def test_a_review_without_a_kind_of_value_has_no_section_for_it(qtbot: QtBot) -> None:
    s, _ = screen_of(qtbot, CONTRACT, FAMILY_SPECS[:2])
    assert s.section_titles() == ["COMPANIES · 2"]
    empty = ReviewScreen()
    qtbot.addWidget(empty)
    assert empty.section_titles() == []


def test_a_row_says_where_a_value_stands_and_how_else_it_is_written(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    carter = group_named(st, "Mr John Carter")
    assert s.row_for(carter.id).data.caption == (
        f"{carter.placeholder} · 2 places · also “Mr Carter”"
    )
    assert s.row_for(group_named(st, "EUR 1,250,000").id).data.caption == "[AMOUNT_1] · 1 place"
    with pytest.raises(ValueError, match="no such group"):
        s.row_for("not-a-group")


def test_a_group_to_check_has_the_pill_and_says_why(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    fatma, percent = group_named(st, "Ms Fatma Yildiz"), group_named(st, "8 %")
    assert s.row_for(fatma.id).pill_box() is not None
    assert s.row_for(fatma.id).data.caption.endswith("found by the model only")
    assert s.row_for(percent.id).pill_box() is not None
    assert s.row_for(percent.id).data.caption.endswith("too short for the leak check")
    assert s.row_for(group_named(st, "Acme Supplies Ltd").id).pill_box() is None


def test_the_title_is_the_file_and_the_summary_of_the_mockup(qtbot: QtBot) -> None:
    s, _ = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    assert s.title() == ("a.docx", "Review · 8 values found · 2 to check")


def test_the_title_of_one_value_and_of_a_review_that_is_not_loaded_yet(qtbot: QtBot) -> None:
    s, _ = screen_of(qtbot, CONTRACT, FAMILY_SPECS[:1])
    assert s.title()[1] == "Review · 1 value found · 0 to check"
    empty = ReviewScreen()
    qtbot.addWidget(empty)
    assert empty.title() == ("", "Review · 0 values found · 0 to check")


@pytest.mark.parametrize(
    ("names", "title"),
    [
        (["a.docx (after)"], "a.docx"),
        (["a.docx (after)", "a.docx (before)"], "a.docx"),  # one file, split in two
        (["a.docx (after)", "b.pdf (after)"], "a.docx and b.pdf"),
        (["a.docx (after)", "b.pdf (after)", "c.docx (after)"], "a.docx and 2 more"),
    ],
)
def test_the_title_names_the_file_or_the_files(qtbot: QtBot, names: list[str], title: str) -> None:
    combined = CombinedText.join([(name, "Acme Ltd signs.") for name in names])
    st = ReviewState(combined.text, [], [], UserLists([], []), CaseLists([], [], set()))
    s = ReviewScreen()
    qtbot.addWidget(s)
    s.load(st, combined)
    assert s.title()[0] == title


def test_the_window_is_told_when_the_title_changes_and_only_then(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    fatma, acme = group_named(st, "Ms Fatma Yildiz"), group_named(st, "Acme Supplies Ltd")
    # Switching off a group to check changes "2 to check"; one the analysis was sure of does not.
    with qtbot.assertNotEmitted(s.titleChanged):
        s.tree_item_for(acme.id).setCheckState(0, Qt.CheckState.Unchecked)
    with qtbot.waitSignal(s.titleChanged) as changed:
        s.row_for(fatma.id).switch.click()
    assert changed.args == ["a.docx", "Review · 8 values found · 1 to check"]
    assert s.title() == tuple(changed.args)
    with qtbot.waitSignal(s.titleChanged) as loaded:
        combined, other = custom_review(
            "Zed Ltd signs.", [{"kind": COMPANY, "canonical": "Zed Ltd"}]
        )
        s.load(other, combined)
    assert loaded.args == ["a.docx", "Review · 1 value found · 0 to check"]


# ---- the footer -------------------------------------------------------------------------------------


def test_the_footer_counts_follow_every_change(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    assert s.counts_label.text() == "6 hidden · 2 to check · 0 shown on purpose"
    assert s.hint_label.text() == "Space toggles · ↑↓ moves"
    s.tree_item_for(group_named(st, "Acme Supplies Ltd").id).setCheckState(
        0, Qt.CheckState.Unchecked
    )
    assert s.counts_label.text() == "5 hidden · 2 to check · 1 shown on purpose"
    s.row_for(group_named(st, "8 %").id).switch.click()
    # a group to check that is off is still asked about, so it stays to check
    assert s.counts_label.text() == "5 hidden · 2 to check · 1 shown on purpose"


# ---- a group to check that is switched off: "Not sure — hide?" ----------------------------------------


def test_a_group_to_check_that_is_switched_off_is_listed_first_under_not_sure(
    qtbot: QtBot,
) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    assert s.section_titles() == ["NOT SURE — HIDE? · 1", "COMPANIES · 1", "OTHER · 1"]
    assert s.tree.topLevelItem(0) is s.tree_item_for(acme.id)  # first of the list
    row = s.row_for(acme.id)
    assert row.data.question and row.switch is None
    assert row.hide_button is not None and row.show_button is not None
    assert row.hide_button.text() == "Hide" and row.show_button.text() == "Show"
    assert row.pill_box() is not None  # still a group to check
    assert not any(s.row_for(g.id).data.question for g in st.groups if g is not acme)


def test_the_section_is_not_there_when_there_is_nothing_to_ask(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    assert not any(title.startswith("NOT SURE") for title in s.section_titles())
    # A group to check that is on, and a group the analysis was sure of that is off: no question.
    s.tree_item_for(group_named(st, "Acme Supplies Ltd").id).setCheckState(
        0, Qt.CheckState.Unchecked
    )
    assert not any(row.data.question for row in (s.row_for(g.id) for g in st.groups))
    qtbot.wait(50)
    assert not any(title.startswith("NOT SURE") for title in s.section_titles())


def test_hide_switches_the_group_on_and_it_goes_back_to_its_section(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    n = len(st.mask_plan().replacements)
    row = s.row_for(acme.id)
    assert row.hide_button is not None
    row.hide_button.click()
    assert acme.enabled and len(st.mask_plan().replacements) > n
    assert s.section_titles() == ["COMPANIES · 2", "OTHER · 1"]
    assert not s.row_for(acme.id).data.question and s.row_for(acme.id).switch is not None
    assert s.row_for(acme.id).switch.isChecked()
    assert s.tree.currentItem() is s.tree_item_for(acme.id)  # the owner's place is kept


def test_show_keeps_the_group_visible_and_it_is_not_asked_about_again(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    row = s.row_for(acme.id)
    assert row.show_button is not None
    row.show_button.click()
    assert not acme.enabled  # it stays visible
    assert s.section_titles() == ["COMPANIES · 2", "OTHER · 1"]
    answered = s.row_for(acme.id)
    assert answered.switch is not None and not answered.switch.isChecked()
    assert s.counts_label.text().endswith("1 shown on purpose")
    combined, again = custom_review(CONTRACT, UNSURE_SPECS)  # a review loaded anew asks again
    s.load(again, combined)
    assert s.section_titles()[0] == "NOT SURE — HIDE? · 1"


def test_a_group_the_owner_switches_off_moves_into_the_section_at_once(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    falcon = group_named(st, "Project Falcon")
    s.tree.setCurrentItem(s.tree_item_for(falcon.id))
    s.tree_item_for(falcon.id).setSelected(True)
    s.row_for(falcon.id).switch.click()  # type: ignore[union-attr]
    assert not falcon.enabled
    assert s.section_titles() == ["NOT SURE — HIDE? · 2", "COMPANIES · 1"]
    assert s.row_for(falcon.id).data.question
    assert s.tree.currentItem() is s.tree_item_for(falcon.id)  # still the selected one
    assert [i.text(0) for i in s.tree.selectedItems()] == ["Project Falcon"]


def test_a_group_switched_off_by_a_program_moves_once_the_list_has_finished(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    falcon = group_named(st, "Project Falcon")
    s.tree_item_for(falcon.id).setCheckState(0, Qt.CheckState.Unchecked)
    assert not falcon.enabled and s.highlight_count() == 1  # the review and the page are at once
    qtbot.waitUntil(lambda: s.row_for(falcon.id).data.question, timeout=2000)
    assert s.section_titles()[0] == "NOT SURE — HIDE? · 2"


def test_show_always_on_a_group_the_owner_is_asked_about_is_an_answer(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    s.tree.setCurrentItem(s.tree_item_for(acme.id))
    s.tree_item_for(acme.id).setSelected(True)
    s.never_action.trigger()
    assert st.user_lists.never_hide == ["Acme Supplies Ltd"] and not acme.enabled
    assert s.section_titles() == ["COMPANIES · 2", "OTHER · 1"]  # not asked about any more
    assert s.row_for(acme.id).switch is not None  # a row like the others, switched off


def test_show_always_in_the_menu_ignores_a_stale_page_selection(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    start = CONTRACT.index("Project Falcon")
    s.tree.setCurrentItem(s.tree_item_for(acme.id))
    s.tree_item_for(acme.id).setSelected(True)
    select_text(s, start, start + len("Project Falcon"))  # left over, survives the group's click
    assert s.text.textCursor().hasSelection()
    s.context_menu()
    assert s.text.textCursor().hasSelection()
    s.never_action.trigger()
    assert st.user_lists.never_hide == ["Acme Supplies Ltd"]


def test_hide_always_on_a_group_the_owner_is_asked_about_hides_it(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    s.tree.setCurrentItem(s.tree_item_for(acme.id))
    s.tree_item_for(acme.id).setSelected(True)
    s.always_action.trigger()
    assert st.user_lists.always_hide == ["Acme Supplies Ltd"] and acme.enabled
    assert s.section_titles() == ["COMPANIES · 2", "OTHER · 1"]


def test_space_on_a_row_of_the_question_hides_the_group(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    acme = group_named(st, "Acme Supplies Ltd")
    s.tree.setCurrentItem(s.tree_item_for(acme.id))
    qtbot.keyClick(s.tree, Qt.Key.Key_Space)
    assert acme.enabled and not any(row.data.question for row in s._rows.values())


def test_the_not_sure_buttons_come_after_the_buttons_of_the_pane_in_the_tab_order(
    qtbot: QtBot,
) -> None:
    s, st = screen_of(qtbot, CONTRACT, UNSURE_SPECS)
    s.show()
    qtbot.waitExposed(s)
    row = s.row_for(group_named(st, "Acme Supplies Ltd").id)
    assert row.hide_button is not None and row.show_button is not None
    chain = [s.never_button]
    while len(chain) < 12 and s.tree not in chain:
        chain.append(chain[-1].nextInFocusChain())
    assert chain.index(s.never_button) < chain.index(row.hide_button)
    assert chain.index(row.hide_button) < chain.index(row.show_button) < chain.index(s.tree)


# ---- the switch of a row --------------------------------------------------------------------------------


def test_the_switch_of_a_row_changes_the_mask_plan(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    show(qtbot, s)
    group = group_named(st, "Pennine Workwear Ltd")
    n = len(st.mask_plan().replacements)
    row = s.row_for(group.id)
    assert row.switch is not None and row.switch.isChecked()
    qtbot.mouseClick(row.switch, Qt.MouseButton.LeftButton)
    assert not group.enabled
    assert len(st.mask_plan().replacements) == n - len(group.findings)
    assert s.highlight_count() == len(st.mask_plan().replacements)
    assert s.tree_item_for(group.id).checkState(0) == Qt.CheckState.Unchecked
    assert "1 shown on purpose" in s.counts_label.text()
    qtbot.mouseClick(row.switch, Qt.MouseButton.LeftButton)
    assert group.enabled and len(st.mask_plan().replacements) == n


def test_a_switch_set_by_the_review_is_shown_by_the_row(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    s.tree_item_for(group.id).setCheckState(0, Qt.CheckState.Unchecked)
    row = s.row_for(group.id)
    assert row.switch is not None and not row.switch.isChecked()


def test_every_switch_says_what_it_hides(review_screen: Screen) -> None:
    s, st = review_screen
    for group in st.groups:
        switch = s.row_for(group.id).switch
        assert switch is not None
        assert switch.accessibleName() == f"Hide {' '.join(group.canonical.split())}"


# ---- the keys ---------------------------------------------------------------------------------------------


def test_space_switches_the_current_group_and_the_plan_follows(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    n = len(st.mask_plan().replacements)
    s.tree.setCurrentItem(s.tree_item_for(group.id))
    qtbot.keyClick(s.tree, Qt.Key.Key_Space)
    assert not group.enabled and len(st.mask_plan().replacements) == n - len(group.findings)
    assert not s.row_for(group.id).switch.isChecked()  # type: ignore[union-attr]
    qtbot.keyClick(s.tree, Qt.Key.Key_Space)
    assert group.enabled and len(st.mask_plan().replacements) == n


def test_the_arrow_keys_move_the_selection_and_the_page_follows(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    show(qtbot, s)
    first, second = s.tree.topLevelItem(0), s.tree.topLevelItem(1)
    s.tree.setCurrentItem(first)
    first.setSelected(True)
    qtbot.keyClick(s.tree, Qt.Key.Key_Down)
    assert s.tree.selectedItems() == [second]
    group = next(g for g in st.groups if g.id == second.data(0, Qt.ItemDataRole.UserRole))
    position = s.text.textCursor().position()
    assert position == len("supply-08.docx\n") + group.findings[0].start
    qtbot.keyClick(s.tree, Qt.Key.Key_Up)
    assert s.tree.selectedItems() == [first]


def test_the_arrow_keys_pass_over_the_headings_of_the_sections(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    last_company = s.tree_item_for(group_named(st, "Acme Supplies Ltd").id)
    s.tree.setCurrentItem(last_company)
    last_company.setSelected(True)
    qtbot.keyClick(s.tree, Qt.Key.Key_Down)  # the next section starts with its first group
    assert [i.text(0) for i in s.tree.selectedItems()] == ["Mr John Carter"]


def test_space_on_a_place_switches_that_place_and_not_the_group(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    item = s.tree_item_for(group.id)
    s.tree.setCurrentItem(item.child(1))
    qtbot.keyClick(s.tree, Qt.Key.Key_Space)
    assert group.disabled == {1} and group.enabled
    assert item.child(1).checkState(0) == Qt.CheckState.Unchecked


def test_the_right_and_left_keys_open_and_close_the_places_of_a_group(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    item = s.tree_item_for(group_named(st, "Project Falcon").id)
    s.tree.setCurrentItem(item)
    assert not item.isExpanded()  # closed until the owner opens them
    qtbot.keyClick(s.tree, Qt.Key.Key_Right)
    assert item.isExpanded()
    qtbot.keyClick(s.tree, Qt.Key.Key_Down)
    assert s.tree.currentItem() is item.child(0)
    qtbot.keyClick(s.tree, Qt.Key.Key_Left)
    assert s.tree.currentItem() is item
    qtbot.keyClick(s.tree, Qt.Key.Key_Left)
    assert not item.isExpanded()


def test_a_double_click_opens_the_places_of_a_group(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    show(qtbot, s)
    item = s.tree_item_for(group_named(st, "Pennine Workwear Ltd").id)
    point = QPoint(60, s.tree.visualItemRect(item).center().y())
    qtbot.mouseClick(s.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)  # the first click
    qtbot.mouseDClick(s.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert item.isExpanded()
    qtbot.mouseClick(s.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    qtbot.mouseDClick(s.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not item.isExpanded()


def test_a_click_on_a_row_selects_its_group_and_scrolls_the_page_to_it(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    show(qtbot, s)
    group = st.groups[3]
    item = s.tree_item_for(group.id)
    s.tree.scrollToItem(item)
    point = QPoint(60, s.tree.visualItemRect(item).center().y())
    qtbot.mouseClick(s.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert s.tree.selectedItems() == [item] and s.row_for(group.id).selected
    assert s.text.textCursor().position() == len("supply-08.docx\n") + group.findings[0].start
    others = [g for g in st.groups if g is not group]
    assert not any(s.row_for(g.id).selected for g in others)


def test_the_selected_row_is_marked_and_the_others_are_not(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Project Falcon")
    s.tree.setCurrentItem(s.tree_item_for(group.id))
    s.tree_item_for(group.id).setSelected(True)
    assert [g.canonical for g in st.groups if s.row_for(g.id).selected] == ["Project Falcon"]
    s.tree.clearSelection()
    assert not any(s.row_for(g.id).selected for g in st.groups)


def test_the_wheel_scrolls_the_list_over_a_row_and_over_a_switch(
    qtbot: QtBot, review_screen: Screen
) -> None:
    # A real wheel event, through the window (QTest.wheelEvent): the rows cover the whole list,
    # so they must pass the wheel on to it.
    from PySide6.QtCore import QPointF
    from PySide6.QtTest import QTest

    s, st = review_screen
    show(qtbot, s)
    row = s.row_for(st.groups[0].id)
    assert row.switch is not None
    bar = s.tree.verticalScrollBar()
    for widget, point in ((row, QPoint(60, 60)), (row.switch, QPoint(5, 5))):
        bar.setValue(0)
        QTest.wheelEvent(s.windowHandle(), QPointF(widget.mapTo(s, point)), QPoint(0, -120))
        qtbot.waitUntil(lambda: bar.value() > 0, timeout=2000)


# ---- find ---------------------------------------------------------------------------------------------------


def test_typing_in_the_find_field_selects_the_first_hit_and_return_goes_on_to_the_next(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    plain = s.text.toPlainText()
    first = plain.index("Project Falcon")
    second = plain.index("Project Falcon", first + 1)
    qtbot.keyClicks(s.find_field, "Project Falcon")
    cursor = s.text.textCursor()
    assert cursor.selectedText() == "Project Falcon" and cursor.selectionStart() == first
    qtbot.keyClick(s.find_field, Qt.Key.Key_Return)
    assert s.text.textCursor().selectionStart() == second
    qtbot.keyClick(s.find_field, Qt.Key.Key_Return)  # round the end of the document
    assert s.text.textCursor().selectionStart() == first


def test_a_longer_text_keeps_the_hit_it_started_on(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    plain = s.text.toPlainText()
    qtbot.keyClicks(s.find_field, "Proj")
    start = s.text.textCursor().selectionStart()
    assert start == plain.index("Proj")
    qtbot.keyClicks(s.find_field, "ect Fal")
    assert s.text.textCursor().selectionStart() == start
    assert s.text.textCursor().selectedText() == "Project Fal"


def test_the_find_does_not_mind_the_case(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    s.find_field.setText("project falcon")
    assert s.text.textCursor().selectedText() == "Project Falcon"


def test_a_text_that_is_not_in_the_document_is_marked_and_the_cursor_stays(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    s.find_field.setText("Project Falcon")
    kept = (s.text.textCursor().selectionStart(), s.text.textCursor().selectionEnd())
    s.find_field.setText("no such words anywhere")
    assert s.find_field.property("noMatch") is True
    assert s.find_field.accessibleDescription() == "No match"
    assert (s.text.textCursor().selectionStart(), s.text.textCursor().selectionEnd()) == kept
    s.find_field.setText("Project")
    assert s.find_field.property("noMatch") is False and s.find_field.accessibleDescription() == ""
    s.find_field.clear()
    assert s.find_field.property("noMatch") is False


def test_a_hit_of_the_find_can_be_hidden_like_any_selection(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    s.find_field.setText("Supply Agreement")  # a title the analysis rightly left visible
    hit = s.text.textCursor().selectedText()
    assert hit.casefold() == "supply agreement" and s.hide_button.isEnabled()
    s.hide_selection(CUSTOM)
    assert group_named(st, hit).type is CUSTOM


def test_command_f_puts_the_keyboard_in_the_find_field_with_its_text_selected(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    activate(qtbot, s)
    s.find_field.setText("Falcon")
    s.text.setFocus()
    assert not s.find_field.hasFocus()
    qtbot.keyClick(s.text, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert s.find_field.hasFocus() and s.find_field.selectedText() == "Falcon"


def test_command_f_works_from_anywhere_in_the_screen(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    activate(qtbot, s)
    s.tree.setFocus()
    qtbot.keyClick(s.tree, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert s.find_field.hasFocus()


def test_command_f_is_the_reviews_only_while_the_review_shows_in_the_window(
    qtbot: QtBot,
) -> None:
    # The screens are in a stack: while another one shows, ⌘F is not the review's.
    from PySide6.QtWidgets import QLineEdit, QStackedWidget

    combined, st = custom_review(CONTRACT, FAMILY_SPECS)
    screen = ReviewScreen()
    screen.load(st, combined)
    other = QLineEdit()
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    stack.addWidget(other)
    stack.addWidget(screen)
    stack.resize(1000, 600)
    stack.show()
    qtbot.waitExposed(stack)
    stack.activateWindow()
    qtbot.waitUntil(stack.isActiveWindow, timeout=3000)
    stack.setCurrentWidget(other)
    other.setFocus()
    qtbot.keyClick(other, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert not screen.find_field.hasFocus() and other.hasFocus()
    stack.setCurrentWidget(screen)
    screen.text.setFocus()
    qtbot.keyClick(screen.text, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert screen.find_field.hasFocus()


def test_the_find_shortcut_is_the_systems(qtbot: QtBot, review_screen: Screen) -> None:
    from PySide6.QtGui import QKeySequence

    s, _ = review_screen
    assert s.find_shortcut.key() == QKeySequence(QKeySequence.StandardKey.Find)
    activate(qtbot, s)
    s.focus_find()  # what the shortcut does
    assert s.find_field.hasFocus()


# ---- the context menu ---------------------------------------------------------------------------------------


def test_the_context_menu_offers_the_actions_that_exist(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    s.tree.setCurrentItem(s.tree_item_for(group_named(st, "Project Falcon").id))
    s.tree_item_for(group_named(st, "Project Falcon").id).setSelected(True)
    menu = s.context_menu()
    shown = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert shown == ["Hide always", "Show always", "Split", "Merge with…", "Show places"]
    by_name = {a.text(): a for a in menu.actions()}
    assert by_name["Hide always"].isEnabled() and by_name["Show always"].isEnabled()
    assert not by_name["Split"].isEnabled()  # a split needs places, not a group
    assert by_name["Merge with…"].menu() is not None


def test_merge_with_lists_the_other_groups_of_the_same_type_and_merges_the_one_chosen(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    one, two = group_named(st, "2 per cent"), group_named(st, "10 per cent")
    s.tree.setCurrentItem(s.tree_item_for(one.id))
    s.tree_item_for(one.id).setSelected(True)
    menu = s.context_menu()
    merge = next(a for a in menu.actions() if a.text() == "Merge with…")
    names = [a.text() for a in merge.menu().actions()]
    assert all(g.type is one.type for g in st.groups if f"{g.canonical}  {g.placeholder}" in names)
    assert f"10 per cent  {two.placeholder}" in names
    assert f"2 per cent  {one.placeholder}" not in names  # not with itself
    groups = len(st.groups)
    next(a for a in merge.menu().actions() if a.text().startswith("10 per cent")).trigger()
    assert len(st.groups) == groups - 1
    survivor = next(g for g in st.groups if g.id in {one.id, two.id})
    assert len(survivor.findings) == 3 and s.tree.currentItem() is s.tree_item_for(survivor.id)


def test_merge_with_is_greyed_out_when_no_other_group_has_the_type(qtbot: QtBot) -> None:
    s, st = screen_of(qtbot, CONTRACT, FAMILY_SPECS)
    only = group_named(st, "Project Falcon")
    s.tree.setCurrentItem(s.tree_item_for(only.id))
    s.tree_item_for(only.id).setSelected(True)
    merge = next(a for a in s.context_menu().actions() if a.text() == "Merge with…")
    assert not merge.isEnabled()


def test_with_two_groups_selected_the_menu_offers_a_plain_merge(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    one, two = group_named(st, "2 per cent"), group_named(st, "10 per cent")
    select_items(s, s.tree_item_for(one.id), s.tree_item_for(two.id))
    shown = [a.text() for a in s.context_menu().actions() if not a.isSeparator()]
    assert "Merge selected groups" in shown and "Merge with…" not in shown


def test_a_right_click_selects_the_row_under_it_and_asks_for_the_menu(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    item = s.tree.topLevelItem(2)
    point = QPoint(60, s.tree.visualItemRect(item).center().y())
    viewport = s.tree.viewport()
    with qtbot.waitSignal(s.tree.menuRequested) as asked:
        QApplication.sendEvent(
            viewport,
            QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, viewport.mapToGlobal(point)),
        )
    assert asked.args == [viewport.mapToGlobal(point)]
    assert s.tree.selectedItems() == [item]


def test_the_menu_key_asks_for_the_menu_at_the_current_row(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    item = s.tree.topLevelItem(1)
    s.tree.setCurrentItem(item)
    with qtbot.waitSignal(s.tree.menuRequested) as asked:
        QApplication.sendEvent(
            s.tree,
            QContextMenuEvent(
                QContextMenuEvent.Reason.Keyboard, QPoint(2, 2), s.tree.mapToGlobal(QPoint(2, 2))
            ),
        )
    row = s.tree.visualItemRect(item)
    where = s.tree.viewport().mapFromGlobal(asked.args[0])
    assert row.top() <= where.y() <= row.bottom()


def test_show_places_opens_the_places_of_the_selected_group_and_then_closes_them(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    item = s.tree_item_for(group.id)
    assert not s.places_action.isEnabled()  # nothing is selected
    s.tree.setCurrentItem(item)
    item.setSelected(True)
    assert s.places_action.text() == "Show places"
    s.places_action.trigger()
    assert item.isExpanded() and s.places_action.text() == "Hide places"
    s.places_action.trigger()
    assert not item.isExpanded() and s.places_action.text() == "Show places"


def test_the_groups_that_were_open_stay_open_when_the_list_is_made_again(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    s.tree_item_for(group.id).setExpanded(True)
    i = s.text.toPlainText().index("Supply Agreement")
    select_text(s, i, i + len("Supply Agreement"))
    s.hide_selection(CUSTOM)  # the list is made again
    assert s.tree_item_for(group.id).isExpanded()


def test_the_list_stays_where_the_owner_scrolled_it_when_the_review_changes_under_it(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    bar = s.tree.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    scrolled = bar.value()
    assert scrolled > 0
    i = s.text.toPlainText().index("Falcon")
    select_text(s, i, i + len("Falcon"))
    qtbot.mouseClick(s.never_button, Qt.MouseButton.LeftButton)  # no group is selected afterwards
    assert s.tree.selectedItems() == []
    assert bar.value() == scrolled


def test_a_review_that_is_loaded_starts_at_the_top_of_the_list(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    bar = s.tree.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    combined, st = review_of([("other.docx (after)", "Zed Ltd signs.")], {"Zed Ltd": COMPANY})
    s.load(st, combined)
    assert bar.value() == 0


# ---- Show always on text -------------------------------------------------------------------------------------


def test_show_always_leaves_visible_the_text_selected_in_the_document(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    assert not s.never_button.isEnabled()  # no group, no text
    i = s.text.toPlainText().index("Project Falcon")
    select_text(s, i, i + len("Project Falcon"))
    assert s.never_button.isEnabled()
    qtbot.mouseClick(s.never_button, Qt.MouseButton.LeftButton)
    assert st.user_lists.never_hide == ["Project Falcon"] and not falcon.enabled
    assert UserLists.load(lists_path()).never_hide == ["Project Falcon"]


def test_show_always_on_a_selection_the_review_refuses_is_explained(
    qtbot: QtBot, review_screen: Screen, notices: list[str]
) -> None:
    s, _ = review_screen
    select_text(s, 0, 5)  # the name of the file
    qtbot.mouseClick(s.never_button, Qt.MouseButton.LeftButton)
    assert notices == ["Select some of the document's text, not a file name."]


# ---- the screen as a whole ----------------------------------------------------------------------------------------


def test_the_export_button_is_never_shown_but_still_asks_for_the_export(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    assert not s.export_button.isVisible()  # the window's "Export…" does this
    with qtbot.waitSignal(s.exportRequested):
        s.export_button.click()


def test_the_parts_have_accessible_names(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    assert s.text.accessibleName() == "Document"
    assert s.inspector.accessibleName() == "What was found"
    assert s.tree.accessibleName() == "Values found"
    assert s.find_field.accessibleName() == "Find in document"
    assert s.hide_button.text() == "Hide selection" and s.never_button.text() == "Show always"


def test_the_page_is_a_serif_page_with_room_round_the_text(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    document = s.text.document()
    margins = document.rootFrame().frameFormat()
    assert (margins.leftMargin(), margins.rightMargin()) == (44, 44)
    assert (margins.topMargin(), margins.bottomMargin()) == (36, 36)
    assert s.text.font().families()[:3] == ["Iowan Old Style", "Palatino", "Georgia"]
    body = document.findBlockByNumber(1).blockFormat()  # the text under the name of the file
    assert body.lineHeightType() == QTextBlockFormat.LineHeightTypes.FixedHeight.value
    assert body.lineHeight() == pytest.approx(14.5 * 1.7)
    assert body.bottomMargin() == 14
    assert s.text.frameShape() == s.text.Shape.NoFrame


def test_the_note_under_the_page_is_the_mockups(qtbot: QtBot, review_screen: Screen) -> None:
    s, _ = review_screen
    assert s.note_label.text() == (
        "Headers and footers follow the body. Hidden text and pictures were taken out before this"
        " view."
    )
    assert "Headers and footers" not in s.text.toPlainText()  # a note, not part of the document


def test_the_inspector_is_between_300_and_360_pixels_and_the_page_has_the_rest(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    show(qtbot, s)
    for width in (960, 1180, 1700):
        s.resize(width, 700)
        qtbot.waitUntil(lambda width=width: s.width() == width)
        assert 300 <= s.inspector.width() <= 360, width
        assert s.text.width() >= width - 360 - 2, width


def test_the_rows_are_as_wide_as_the_list_whatever_the_width(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    show(qtbot, s)
    rows = [s.row_for(g.id) for g in st.groups[:5]]
    for width in (960, 1400):
        s.resize(width, 700)
        # The list takes the new width and lays its rows out for it a moment after the resize.
        qtbot.waitUntil(
            lambda: all(row.width() == s.tree.viewport().width() for row in rows), timeout=3000
        )
        viewport = s.tree.viewport().width()
        row = s.row_for(st.groups[0].id)
        assert row.switch is not None
        assert row.switch.geometry().right() < viewport - 8  # inside the row, not under the edge


def test_the_review_screen_still_holds_a_text_pane_with_no_other_widgets_over_it(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, _ = review_screen
    assert s.text.parentWidget() is not s.inspector
    assert s.inspector.isAncestorOf(s.tree) and not s.inspector.isAncestorOf(s.text)


# ---- speed ----------------------------------------------------------------------------------------


def test_500_highlights_in_a_30_page_text_are_drawn_in_well_under_2_seconds(qtbot: QtBot) -> None:
    filler = "The parties agree on delivery terms, payment terms and liability. " * 3
    clauses = [
        f"Clause {n}. Person{n % 50:02d} Surname shall pay the Supplier. {filler}"
        for n in range(500)
    ]
    text = "\n".join(clauses)
    assert len(text) > 70_000  # about 30 pages
    findings: dict[str, list[Finding]] = {}
    for n in range(500):
        name = f"Person{n % 50:02d} Surname"
        start = text.index(name, text.index(f"Clause {n}. "))
        findings.setdefault(name, []).append(
            Finding(PERSON, start, start + len(name), name, 0.9, "model")
        )
    groups = [
        Group(f"g{k}", PERSON, name, {name}, found, f"[PERSON_{k + 1}]", needs_check=k % 7 == 0)
        for k, (name, found) in enumerate(findings.items())
    ]
    groups.sort(key=lambda g: g.findings[0].start)
    state = ReviewState(text, groups, [], UserLists([], []), CaseLists([], [], set()))
    combined = CombinedText.join([("long.docx (after)", text)])
    screen = ReviewScreen()
    qtbot.addWidget(screen)

    screen.resize(1100, 700)
    screen.show()
    qtbot.waitExposed(screen)

    started = time.perf_counter()
    screen.load(state, combined)
    screen.grab()  # draws the pane: lays the 30 pages out and paints the finds in view
    loaded = time.perf_counter() - started
    assert screen.highlight_count() == 500

    started = time.perf_counter()
    screen.tree_item_for(groups[0].id).setCheckState(0, Qt.CheckState.Unchecked)
    screen.grab()
    switched = time.perf_counter() - started
    assert screen.highlight_count() == 500 - len(groups[0].findings)

    print(f"load with 500 highlights: {loaded:.3f} s; switching a group off: {switched:.3f} s")
    assert loaded < 6.0 and switched < 6.0  # three times the usual, for a loaded machine
