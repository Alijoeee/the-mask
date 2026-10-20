"""The owner names a mask on the spot (ruling R127): the "Mask name" field of the inspector, the
name shown where the screen shows a placeholder, a name given with "Hide selection", and a rename
by double click or from the context menu. The groups are made by hand, without the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit, QPushButton

from tests.ui.review_samples import CONTRACT, FAMILY_SPECS, custom_review
from themask.detect.lists import CaseLists, UserLists
from themask.labels import LabelError
from themask.model import Group, PlaceholderType
from themask.review import ReviewState
from themask.ui.review_inspector import caption_of
from themask.ui.review_screen import ReviewScreen

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

COMPANY = PlaceholderType.COMPANY


def screen_of(
    qtbot: QtBot, specs: list[dict[str, Any]] | None = None
) -> tuple[ReviewScreen, ReviewState]:
    combined, state = custom_review(CONTRACT, specs or FAMILY_SPECS)
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.resize(1100, 760)
    screen.show()
    screen.load(state, combined)
    return screen, state


def group_of(state: ReviewState, canonical: str) -> Group:
    return next(g for g in state.groups if g.canonical == canonical)


def select(screen: ReviewScreen, group: Group) -> None:
    item = screen.tree_item_for(group.id)
    screen.tree.clearSelection()
    screen.tree.setCurrentItem(item)
    item.setSelected(True)


def activate(qtbot: QtBot, screen: ReviewScreen) -> None:
    """Make the screen the active window, so that a click moves the keyboard as it does."""
    screen.activateWindow()
    qtbot.waitUntil(screen.isActiveWindow, timeout=3000)


def type_name(qtbot: QtBot, field: QLineEdit, text: str) -> None:
    """The owner clicks into the field, replaces what is there and presses Return."""
    field.setFocus()
    field.selectAll()
    if text:
        qtbot.keyClicks(field, text)
    else:
        qtbot.keyClick(field, Qt.Key.Key_Backspace)
    qtbot.keyClick(field, Qt.Key.Key_Return)


@pytest.fixture
def named(qtbot: QtBot) -> tuple[ReviewScreen, ReviewState, Group]:
    screen, state = screen_of(qtbot)
    group = group_of(state, "Northwind Trading B.V.")
    select(screen, group)
    return screen, state, group


# ---- the field -------------------------------------------------------------------------------


def test_the_field_shows_the_default_as_its_placeholder(
    named: tuple[ReviewScreen, ReviewState, Group],
) -> None:
    screen, _, group = named
    panel = screen.inspector.name_panel
    assert panel.name_field.isEnabled() and panel.name_field.text() == ""
    assert panel.name_field.placeholderText() == group.placeholder == "[COMPANY_1]"
    assert panel.name_field.accessibleName() == "Mask name"
    assert panel.token_label.text() == "Written as [COMPANY_1]"


def test_return_names_the_group_and_shows_the_token(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "Provider")
    assert group.label == "Provider" and state.groups[0].token == "[Provider]"
    assert panel.token_label.text() == "Written as [Provider]"
    assert panel.name_field.text() == "Provider" and panel.message_label.text() == ""
    assert caption_of(group).startswith("[Provider] · ")
    # the row of the list says what will be written, and the group is still the selection
    assert screen.row_for(group.id).data.caption.startswith("[Provider] · ")
    assert screen.tree.selectedItems() == [screen.tree_item_for(group.id)]


def test_the_token_follows_the_typing_before_it_is_committed(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _, group = named
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Data  Provider")
    assert panel.token_label.text() == "Written as [Data Provider]"
    assert group.label is None  # not yet: Return or leaving the field commits


def test_leaving_the_field_commits_too(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _, group = named
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Supplier")
    screen.find_field.setFocus()
    assert group.label == "Supplier"


def test_leaving_the_field_for_another_row_names_the_group_it_was_typed_for(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Supplier")
    other = group_of(state, "Acme Supplies Ltd")
    activate(qtbot, screen)
    panel.name_field.setFocus()
    row = screen.tree_item_for(other.id)
    point = screen.tree.visualItemRect(row).center()
    qtbot.mouseClick(screen.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert group.label == "Supplier" and other.label is None
    assert panel.name_field.text() == ""


def test_an_empty_field_goes_back_to_the_default(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _state, group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "Provider")
    type_name(qtbot, panel.name_field, "")
    assert group.label is None and panel.token_label.text() == "Written as [COMPANY_1]"
    assert caption_of(group).startswith("[COMPANY_1] · ")


def test_a_refused_name_says_why_under_the_field_and_changes_nothing(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "Provider")
    type_name(qtbot, panel.name_field, "Bad [name]")
    expected = None
    with pytest.raises(LabelError) as caught:
        state.set_label(group.id, "Bad [name]")
    expected = str(caught.value)
    assert panel.message_label.text() == f"Northwind Trading B.V.: {expected}"
    assert group.label == "Provider"  # the old name is kept
    assert panel.name_field.text() == "Provider"  # the field goes back to it
    assert panel.token_label.text() == "Written as [Provider]"


def test_the_message_goes_when_the_owner_types_again_but_not_when_another_group_is_chosen(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    # R127 fix round 1 (I2): a refusal used to vanish with the selection, so a click on another
    # row after a refused name hid the reason within milliseconds. It names its group now and
    # stays until the owner types again or a name is accepted.
    screen, state, _group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "123")
    assert panel.message_label.text().startswith("Northwind Trading B.V.: ")
    qtbot.keyClicks(panel.name_field, "x")
    assert panel.message_label.text() == ""
    type_name(qtbot, panel.name_field, "123")
    other = group_of(state, "Acme Supplies Ltd")
    select(screen, other)
    assert panel.message_label.text().startswith("Northwind Trading B.V.: ")
    type_name(qtbot, panel.name_field, "Buyer")  # a name accepted for the other group
    assert panel.message_label.text() == ""


def test_a_refusal_survives_a_real_click_on_another_row(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    activate(qtbot, screen)
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Bad [x]")
    row = screen.tree_item_for(group_of(state, "Acme Supplies Ltd").id)
    point = screen.tree.visualItemRect(row).center()
    qtbot.mouseClick(screen.tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert screen.tree.currentItem() is row  # the click took the keyboard, then selected
    assert "square brackets" in panel.message_label.text()
    assert group.label is None


def test_a_name_another_group_has_is_refused(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, _group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "Provider")
    select(screen, group_of(state, "Acme Supplies Ltd"))
    type_name(qtbot, panel.name_field, "provider")
    assert "already used" in panel.message_label.text()
    assert group_of(state, "Acme Supplies Ltd").label is None


def test_a_group_of_an_existing_case_has_the_field_disabled_with_a_line_that_says_why(
    qtbot: QtBot,
) -> None:
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    first = state.groups[0]
    state = ReviewState(
        state.text,
        state.groups,
        [],
        UserLists([], []),
        CaseLists([], [], set()),
        reserved=[first.placeholder],
        reserved_labels={first.placeholder: "Landlord"},
    )
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.show()
    screen.load(state, combined)
    select(screen, first)
    panel = screen.inspector.name_panel
    assert not panel.name_field.isEnabled() and panel.name_field.text() == "Landlord"
    assert "case" in panel.note_label.text() and not panel.note_label.isHidden()
    assert not screen.rename_action.isEnabled()
    other = next(g for g in state.groups if g.placeholder not in state.reserved)
    select(screen, other)
    assert panel.name_field.isEnabled() and panel.note_label.isHidden()


def test_with_nothing_selected_the_field_is_off_and_says_to_choose_a_value(qtbot: QtBot) -> None:
    screen, _ = screen_of(qtbot)
    screen.tree.clearSelection()
    panel = screen.inspector.name_panel
    assert not panel.name_field.isEnabled()
    assert "Select a value" in panel.note_label.text()


def test_the_field_is_in_the_tab_order_and_has_a_name_for_a_screen_reader(qtbot: QtBot) -> None:
    screen, state = screen_of(qtbot)
    select(screen, state.groups[0])  # the field is off until a value is selected
    inspector = screen.inspector
    assert inspector.name_panel.name_field.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert inspector.name_panel.message_label.accessibleName() == "Mask name problem"
    assert inspector.hide_name_field.accessibleName() == "Name for the hidden text, optional"
    step = inspector.tree.nextInFocusChain()
    while not (
        step.focusPolicy() & Qt.FocusPolicy.TabFocus and step.isEnabled() and not step.isHidden()
    ):
        step = step.nextInFocusChain()  # the scroll bars and other parts are not stops
    assert step is inspector.name_panel.name_field  # Tab goes from the list to the field


def test_the_message_is_in_the_danger_colour_of_the_theme(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    from themask.ui.theme import tokens_of

    screen, _, _ = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "123")
    assert tokens_of(screen).danger.lower() in panel.message_label.styleSheet().lower()
    assert QColor(tokens_of(screen).danger) != QColor(tokens_of(screen).secondary)


# ---- where the name is shown --------------------------------------------------------------


def test_the_tooltip_over_a_named_find_says_what_will_be_written(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    state.set_label(group.id, "Provider")
    screen._rebuild(select=group.id, scroll=False)
    highlight = next(h for h in screen._highlights if h.group_id == group.id)
    cursor = screen.text.textCursor()
    cursor.setPosition(highlight.start + 2)
    rect = screen.text.cursorRect(cursor)
    assert "[Provider]" in screen.tooltip_at(rect.center())
    plain = next(h for h in screen._highlights if h.group_id != group.id)
    cursor.setPosition(plain.start + 2)
    assert screen.tooltip_at(screen.text.cursorRect(cursor).center()) == ""


def test_the_merge_menu_names_the_other_group_by_its_token(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, state, group = named
    other = group_of(state, "Acme Supplies Ltd")
    state.set_label(other.id, "Buyer")
    screen._rebuild(select=group.id, scroll=False)
    menu = screen.context_menu()
    merge = next(a for a in menu.actions() if a.text() == "Merge with…").menu()
    assert merge is not None
    assert [a.text() for a in merge.actions()] == ["Acme Supplies Ltd  [Buyer]"]


# ---- hide selection with a name ---------------------------------------------------------


def select_text(screen: ReviewScreen, word: str) -> None:
    start = screen.review.text.index(word)
    cursor = screen.text.textCursor()
    cursor.setPosition(screen._map.position(start))
    cursor.setPosition(screen._map.position(start + len(word)), cursor.MoveMode.KeepAnchor)
    screen.text.setTextCursor(cursor)


def test_hide_selection_with_a_name_names_the_new_group(qtbot: QtBot) -> None:
    screen, state = screen_of(qtbot)
    select_text(screen, "late payment")
    field = screen.hide_name_field
    assert field.placeholderText() == "Name it (optional)"
    field.setText("Codename")
    screen.hide_selection(PlaceholderType.CUSTOM)
    group = next(g for g in state.groups if g.canonical == "late payment")
    assert group.label == "Codename"
    assert field.text() == "" and screen.inspector.hide_message_label.isHidden()
    assert screen.inspector.name_panel.name_field.text() == "Codename"  # the new group is selected


def test_hide_selection_without_a_name_is_as_before(qtbot: QtBot) -> None:
    screen, state = screen_of(qtbot)
    select_text(screen, "late payment")
    screen.hide_selection(PlaceholderType.CUSTOM)
    assert next(g for g in state.groups if g.canonical == "late payment").label is None


def test_hide_selection_with_a_refused_name_hides_nothing_and_says_why(qtbot: QtBot) -> None:
    screen, state = screen_of(qtbot)
    before = len(state.groups)
    select_text(screen, "late payment")
    screen.hide_name_field.setText("[late payment]")
    screen.hide_selection(PlaceholderType.CUSTOM)
    assert len(state.groups) == before
    assert not screen.inspector.hide_message_label.isHidden()
    assert "square brackets" in screen.inspector.hide_message_label.text()
    assert (
        screen.hide_name_field.text() == "[late payment]"
    )  # kept, so that the owner can correct it
    qtbot.keyClicks(screen.hide_name_field, "x")
    assert screen.inspector.hide_message_label.isHidden()


def test_the_type_menu_passes_the_name_on(qtbot: QtBot) -> None:
    screen, state = screen_of(qtbot)
    select_text(screen, "late payment")
    screen.hide_name_field.setText("Codename")
    menu = screen.hide_button.menu()
    assert menu is not None
    next(a for a in menu.actions() if a.text() == PlaceholderType.CUSTOM.value).trigger()
    assert next(g for g in state.groups if g.canonical == "late payment").label == "Codename"


# ---- rename from the list ---------------------------------------------------------------


def test_rename_in_the_context_menu_puts_the_keyboard_in_the_field(
    named: tuple[ReviewScreen, ReviewState, Group],
) -> None:
    screen, _, _ = named
    menu = screen.context_menu()
    actions = [a.text() for a in menu.actions()]
    assert actions[0] == "Rename mask…"
    assert screen.rename_action.isEnabled()
    screen.rename_action.trigger()
    assert screen.inspector.name_panel.name_field.hasFocus()


def test_double_click_on_a_group_row_renames_it(
    named: tuple[ReviewScreen, ReviewState, Group],
) -> None:
    screen, _, group = named
    screen.tree.itemDoubleClicked.emit(screen.tree_item_for(group.id), 0)
    assert screen.inspector.name_panel.name_field.hasFocus()
    assert not screen.tree_item_for(group.id).isExpanded()


def test_double_click_on_a_stored_group_opens_its_places_as_before(qtbot: QtBot) -> None:
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    first = state.groups[0]
    state.reserved = frozenset({first.placeholder})
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.show()
    screen.load(state, combined)
    screen.tree.itemDoubleClicked.emit(screen.tree_item_for(first.id), 0)
    assert screen.tree_item_for(first.id).isExpanded()


def test_the_state_stays_the_one_truth(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group], monkeypatch: pytest.MonkeyPatch
) -> None:
    screen, state, group = named
    calls: list[tuple[str, str | None]] = []
    real = state.set_label
    monkeypatch.setattr(
        state, "set_label", lambda gid, label: (calls.append((gid, label)), real(gid, label))[1]
    )
    type_name(qtbot, screen.inspector.name_panel.name_field, "Provider")
    assert calls == [(group.id, "Provider")]


# ---- a name typed and not committed is not lost (fix round 1, I1) ------------------------------


def tab_only(button: QPushButton) -> None:
    """A button as a Mac gives it: it takes the keyboard by Tab and not by a click."""
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)


def test_a_typed_name_is_committed_by_a_click_on_a_button_that_takes_no_focus(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _, group = named
    activate(qtbot, screen)
    tab_only(screen.never_button)
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Provider")  # no Return
    qtbot.mouseClick(screen.never_button, Qt.MouseButton.LeftButton)
    assert group.label == "Provider"


def test_a_refused_typed_name_stops_the_button_and_says_why(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group], monkeypatch: pytest.MonkeyPatch
) -> None:
    screen, state, group = named
    activate(qtbot, screen)
    tab_only(screen.never_button)
    changed: list[str] = []
    monkeypatch.setattr(state, "add_never_hide", lambda value: changed.append(value))
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Bad [x]")
    qtbot.mouseClick(screen.never_button, Qt.MouseButton.LeftButton)
    assert changed == [] and group.label is None
    assert "square brackets" in panel.message_label.text()


@pytest.mark.parametrize("action", ["split", "merge", "always", "hide"])
def test_the_other_actions_commit_a_typed_name_first_and_stop_on_a_refusal(
    qtbot: QtBot,
    named: tuple[ReviewScreen, ReviewState, Group],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    screen, state, group = named
    panel = screen.inspector.name_panel
    ran: list[str] = []
    for name in ("add_always_hide", "merge", "split", "hide_text"):
        monkeypatch.setattr(state, name, lambda *a, _n=name, **k: ran.append(_n))
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Bad [x]")
    if action == "split":
        screen._split()
    elif action == "merge":
        screen._merge_groups([group.id, group_of(state, "Acme Supplies Ltd").id])
    elif action == "always":
        screen._always_hide()
    else:
        select_text(screen, "late payment")
        screen.hide_selection(PlaceholderType.CUSTOM)
    assert ran == [] and "square brackets" in panel.message_label.text()


def test_whitespace_only_text_is_no_name_and_a_spaced_name_is_cleaned(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _, group = named
    panel = screen.inspector.name_panel
    type_name(qtbot, panel.name_field, "   ")
    assert (
        group.label is None and panel.name_field.text() == "" and panel.message_label.text() == ""
    )
    type_name(qtbot, panel.name_field, "  Data   Provider ")
    assert group.label == "Data Provider" and panel.name_field.text() == "Data Provider"
    type_name(qtbot, panel.name_field, "  Data   Provider ")  # the same name again: no change
    assert group.label == "Data Provider"


def test_a_redraw_does_not_drop_a_name_typed_and_not_committed(
    qtbot: QtBot, named: tuple[ReviewScreen, ReviewState, Group]
) -> None:
    screen, _state, group = named
    panel = screen.inspector.name_panel
    panel.name_field.setFocus()
    qtbot.keyClicks(panel.name_field, "Provider")
    screen._answer_show(group.id)  # any action that draws the list again
    assert group.label == "Provider"


def test_a_name_set_by_the_review_itself_is_not_taken_off_by_a_redraw(
    named: tuple[ReviewScreen, ReviewState, Group],
) -> None:
    screen, state, group = named
    state.set_label(group.id, "Provider")  # not through the field
    screen._rebuild(select=group.id, scroll=False)
    assert group.label == "Provider"


# ---- names that clash with a value (I3) -------------------------------------------------


def clashing_screen(qtbot: QtBot) -> tuple[ReviewScreen, ReviewState, Group, Group]:
    """A review whose first company has the name "Supplies" from the case's key, which also is a
    word of another value (the case's name cannot change: the other value must go).
    """
    combined, state = custom_review(CONTRACT, FAMILY_SPECS)
    first, other = state.groups[0], state.groups[1]
    state = ReviewState(
        state.text,
        state.groups,
        [],
        UserLists([], []),
        CaseLists([], [], set()),
        reserved=[first.placeholder],
        reserved_labels={first.placeholder: "Supplies"},
    )
    screen = ReviewScreen()
    qtbot.addWidget(screen)
    screen.show()
    screen.load(state, combined)
    return screen, state, first, other


def test_a_name_that_clashes_with_a_masked_value_is_listed_and_marked(qtbot: QtBot) -> None:
    screen, state, first, other = clashing_screen(qtbot)
    problems = state.label_problems()
    assert problems
    panel = screen.inspector.name_panel
    assert panel.problems_label.text() == "\n".join(problems)
    assert not panel.problems_label.isHidden()
    assert "clashes" in screen.row_for(first.id).data.caption
    assert "clashes" not in screen.row_for(other.id).data.caption
    screen.tree_item_for(first.id).setSelected(True)  # the marked group can be selected
    state.set_group_enabled(other.id, False)  # the way out
    screen._rebuild()
    assert (
        panel.problems_label.isHidden() and "clashes" not in screen.row_for(first.id).data.caption
    )
