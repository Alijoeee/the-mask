"""The review screen: the text with its finds highlighted, the list of groups and the actions.

The first five tests are the brief's, on the review of supply-08.docx (the contract with a shared
surname that also names "Project Falcon" twice). The rest check what the brief leaves open: that
the highlights lie exactly on the finds, also in a text of several files with a character outside
the BMP and a carriage return in it, the single occurrences, merge and split, the two lists, a
click on a highlight, the tooltip that says "check", and that 500 highlights in a 30-page text are
drawn in well under 2 seconds.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QToolTip, QTreeWidgetItem

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
    assert s.tree.topLevelItemCount() == len(st.groups) and s.tree.topLevelItem(0).text(0).endswith(
        st.groups[0].placeholder
    )


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
    flagged = [g for g in st.groups if g.needs_check]
    assert flagged and all(s.tree_item_for(g.id).text(1) == "check" for g in flagged)


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
    assert item.text(0) == f"Project Falcon — 2 times — {falcon.placeholder}"
    assert item.childCount() == 2
    for k, finding in enumerate(falcon.findings):
        assert "Project Falcon" in item.child(k).text(0) and item.child(k).childCount() == 0
    once = next(g for g in st.groups if len(g.findings) == 1)
    assert s.tree_item_for(once.id).text(0) == f"{once.canonical} — 1 time — {once.placeholder}"
    assert s.tree_item_for(once.id).text(1) == ("check" if once.needs_check else "")


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
    counts = st.counts()
    assert f"{counts.groups} values" in s.summary_label.text()
    assert f"{counts.replacements} places" in s.summary_label.text()
    assert f"{counts.needs_check} to check" in s.summary_label.text()
    s.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert f"{st.counts().replacements} places" in s.summary_label.text()


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
    assert s.tree_item_for(pays.id).text(0).endswith(pays.placeholder)


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


def test_merge_needs_two_groups_and_makes_them_one(qtbot: QtBot, review_screen: Screen) -> None:
    s, st = review_screen
    one, two = group_named(st, "2 per cent"), group_named(st, "10 per cent")
    assert not s.merge_button.isEnabled()
    select_items(s, s.tree_item_for(one.id))
    assert not s.merge_button.isEnabled()
    select_items(s, s.tree_item_for(one.id), s.tree_item_for(two.id))
    assert s.merge_button.isEnabled()
    groups = len(st.groups)
    qtbot.mouseClick(s.merge_button, Qt.MouseButton.LeftButton)
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
    qtbot.mouseClick(s.merge_button, Qt.MouseButton.LeftButton)
    assert notices == ["Only groups of the same type can be merged."]
    assert len(st.groups) == groups


def test_split_moves_the_selected_occurrences_into_a_group_of_their_own(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    group = group_named(st, "Pennine Workwear Ltd")
    item = s.tree_item_for(group.id)
    assert not s.split_button.isEnabled()
    select_items(s, item)
    assert not s.split_button.isEnabled()  # a split needs occurrences, not a group
    moved = [group.findings[1], group.findings[3]]
    select_items(s, item.child(1), item.child(3))
    assert s.split_button.isEnabled()
    groups, total = len(st.groups), len(group.findings)
    qtbot.mouseClick(s.split_button, Qt.MouseButton.LeftButton)
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
    assert s.split_button.isEnabled()
    select_items(s, item.child(0), item.child(1))
    assert not s.split_button.isEnabled()  # the group would be left with nothing


def test_split_needs_the_occurrences_of_one_group(review_screen: Screen) -> None:
    s, st = review_screen
    one, two = group_named(st, "Pennine Workwear Ltd"), group_named(st, "Lindenhof Hotels GmbH")
    select_items(s, s.tree_item_for(one.id).child(0), s.tree_item_for(two.id).child(0))
    assert not s.split_button.isEnabled()


# ---- the two lists ------------------------------------------------------------------------------


def test_always_hide_puts_the_value_of_the_group_on_the_list_for_every_document(
    qtbot: QtBot, review_screen: Screen
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")
    assert not s.always_button.isEnabled() and not s.never_button.isEnabled()
    select_items(s, s.tree_item_for(falcon.id))
    assert s.always_button.isEnabled() and s.never_button.isEnabled()
    qtbot.mouseClick(s.always_button, Qt.MouseButton.LeftButton)
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
    assert s.always_button.isEnabled()
    qtbot.mouseClick(s.always_button, Qt.MouseButton.LeftButton)
    assert st.user_lists.always_hide == ["Project Falcon"]


def test_the_lists_need_one_group(review_screen: Screen) -> None:
    s, _ = review_screen
    select_items(s, s.tree.topLevelItem(0), s.tree.topLevelItem(1))
    assert not s.always_button.isEnabled() and not s.never_button.isEnabled()


def test_a_list_that_cannot_be_saved_is_explained(
    qtbot: QtBot, review_screen: Screen, notices: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s, st = review_screen
    falcon = group_named(st, "Project Falcon")

    def refuse(self: UserLists, path: Path) -> None:
        raise PermissionError(13, "Permission denied", "/Users/someone/lists.json")

    monkeypatch.setattr(UserLists, "save", refuse)
    select_items(s, s.tree_item_for(falcon.id))
    qtbot.mouseClick(s.always_button, Qt.MouseButton.LeftButton)
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
    assert loaded < 2.0 and switched < 2.0
