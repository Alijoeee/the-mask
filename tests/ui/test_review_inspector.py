"""The inspector of the review: the sections of the list, the rows, the switch and the pane.

The groups here are made by hand, without the detection engine: the sections and the captions
follow the brief and the approved mockup (the caption of the mockup's own first row is a test),
and the widgets are looked at the way an owner sees them: what they paint, in both appearances,
and what a click and a key do.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QCheckBox, QLineEdit, QTreeWidgetItem

from themask.model import Finding, Group, PlaceholderType
from themask.ui import theme
from themask.ui.review_inspector import (
    FAMILIES,
    NOT_SURE,
    FooterCounts,
    GroupRow,
    GroupTree,
    Inspector,
    RowData,
    ToggleSwitch,
    asks_about,
    caption_of,
    other_spellings,
    sections,
)
from themask.ui.theme import TYPE_COLOURS

if TYPE_CHECKING:
    from pytestqt.qtbot import QtBot

COMPANY = PlaceholderType.COMPANY
PERSON = PlaceholderType.PERSON
AMOUNT = PlaceholderType.AMOUNT
PERCENT = PlaceholderType.PERCENT
EMAIL = PlaceholderType.EMAIL
CUSTOM = PlaceholderType.CUSTOM
APPEARANCES = ["light", "dark"]


def make_group(
    kind: PlaceholderType,
    canonical: str,
    *forms: str,
    placeholder: str = "[X_1]",
    check: bool = False,
    enabled: bool = True,
    source: str = "pattern",
    ident: str | None = None,
    variants: set[str] | None = None,
) -> Group:
    """A group of ``kind`` with a find for each of ``forms`` (the canonical form once, if none)."""
    texts = forms or (canonical,)
    findings = [
        Finding(kind, 20 * k, 20 * k + len(text), text, 1.0, source)  # type: ignore[arg-type]
        for k, text in enumerate(texts)
    ]
    return Group(
        ident or f"g-{canonical}",
        kind,
        canonical,
        variants if variants is not None else set(texts) | {canonical},
        findings,
        placeholder,
        enabled=enabled,
        needs_check=check,
    )


def colour_at(image: QImage, point: QPoint) -> str:
    return image.pixelColor(point).name().upper()


def sized_row(
    qtbot: QtBot, group: Group, appearance: str = "light", width: int = 300, **kwargs: object
) -> GroupRow:
    """A row for ``group`` at ``width`` pixels in the ``appearance``."""
    row = GroupRow(RowData.of(group), width=width, **kwargs)  # type: ignore[arg-type]
    qtbot.addWidget(row)
    row.setPalette(theme.palette(appearance))
    row.resize(width, row.needed_height())
    return row


# ---- the sections -------------------------------------------------------------------------------


def test_every_type_belongs_to_exactly_one_family() -> None:
    for kind in PlaceholderType:
        assert [family.title for family in FAMILIES if kind in family.kinds] != []
        assert len([family for family in FAMILIES if kind in family.kinds]) == 1, kind


def test_the_families_are_the_briefs() -> None:
    held = {family.title: {kind.value for kind in family.kinds} for family in FAMILIES}
    assert list(held) == [
        "COMPANIES",
        "PEOPLE",
        "AMOUNTS, PERCENTAGES",
        "ADDRESSES, E-MAIL, BANK",
        "OTHER",
    ]
    assert held["COMPANIES"] == {"COMPANY"}
    assert held["PEOPLE"] == {"PERSON"}
    assert held["AMOUNTS, PERCENTAGES"] == {"AMOUNT", "PERCENT", "QUANTITY"}
    assert held["ADDRESSES, E-MAIL, BANK"] == {"ADDRESS", "EMAIL", "PHONE", "IBAN", "ID", "URL"}
    assert held["OTHER"] == {"CUSTOM"}


def test_the_sections_follow_the_families_and_leave_out_the_empty_ones() -> None:
    groups = [
        make_group(EMAIL, "j.carter@acme.example", placeholder="[EMAIL_1]"),
        make_group(COMPANY, "Northwind Trading B.V.", placeholder="[COMPANY_1]"),
        make_group(AMOUNT, "EUR 1,250,000", placeholder="[AMOUNT_1]"),
        make_group(COMPANY, "Acme Supplies Ltd", placeholder="[COMPANY_2]"),
        make_group(PERCENT, "8 %", placeholder="[PERCENT_1]"),
    ]
    shown = sections(groups)
    assert [section.title for section in shown] == [
        "COMPANIES · 2",
        "AMOUNTS, PERCENTAGES · 2",
        "ADDRESSES, E-MAIL, BANK · 1",
    ]
    assert not any(section.question for section in shown)
    assert sections([]) == []


def test_the_groups_of_a_section_keep_the_order_of_the_document() -> None:
    groups = [make_group(COMPANY, name, ident=name) for name in ("Zed Ltd", "Acme Ltd", "Mid Ltd")]
    (section,) = sections(groups)
    assert [group.id for group in section.groups] == ["Zed Ltd", "Acme Ltd", "Mid Ltd"]


def test_a_group_to_check_that_is_switched_off_is_asked_about_first() -> None:
    sure = make_group(COMPANY, "Acme Ltd")
    unsure = make_group(COMPANY, "Kraft", check=True, enabled=False)
    shown = sections([sure, unsure])
    assert [section.title for section in shown] == [f"{NOT_SURE} · 1", "COMPANIES · 1"]
    assert shown[0].question and not shown[1].question
    assert shown[0].groups == (unsure,) and shown[1].groups == (sure,)  # once, not twice


def test_the_question_heading_is_the_briefs_copy() -> None:
    assert NOT_SURE == "NOT SURE — HIDE?"


@pytest.mark.parametrize(
    ("check", "enabled", "answered", "asked"),
    [
        (True, False, False, True),
        (True, True, False, False),  # switched on: it is hidden, there is nothing to ask
        (False, False, False, False),  # the analysis was sure; the owner switched it off
        (True, False, True, False),  # the owner answered Show
    ],
)
def test_the_owner_is_asked_about_a_group_the_analysis_was_unsure_of_and_that_is_off(
    check: bool, enabled: bool, answered: bool, asked: bool
) -> None:
    group = make_group(COMPANY, "Kraft", check=check, enabled=enabled, ident="k")
    assert asks_about(group, {"k"} if answered else set()) is asked


# ---- the captions -------------------------------------------------------------------------------


def test_the_caption_of_the_first_row_of_the_mockup() -> None:
    northwind = make_group(
        COMPANY,
        "Northwind Trading B.V.",
        "Northwind Trading B.V.",
        "Northwind Trading B.V.",
        "Northwind",
        "Northwind Trading B.V.",
        "the Buyer’s group",
        "Northwind Trading B.V.",
        placeholder="[COMPANY_1]",
    )
    assert caption_of(northwind) == (
        "[COMPANY_1] · 6 places · also “Northwind”, “the Buyer’s group”"
    )


def test_a_single_place_is_a_place() -> None:
    assert caption_of(make_group(AMOUNT, "EUR 1,250,000", placeholder="[AMOUNT_1]")) == (
        "[AMOUNT_1] · 1 place"
    )


def test_the_caption_names_two_other_spellings_and_then_goes_on() -> None:
    group = make_group(
        PERSON,
        "Mr John Carter",
        "Mr John Carter",
        "Mr Carter",
        "J. Carter",
        "Carter",
        placeholder="[PERSON_1]",
    )
    assert caption_of(group) == "[PERSON_1] · 4 places · also “Mr Carter”, “J. Carter”, …"
    assert other_spellings(group) == ["Mr Carter", "J. Carter", "Carter"]


def test_a_spelling_is_named_once_and_white_space_makes_no_other_spelling() -> None:
    group = make_group(
        COMPANY, "Acme Ltd", "Acme\xa0Ltd", "Acme  Ltd", "Acme", "Acme", placeholder="[COMPANY_2]"
    )
    assert other_spellings(group) == ["Acme"]
    assert caption_of(group) == "[COMPANY_2] · 4 places · also “Acme”"


def test_a_form_the_text_never_shows_is_not_named() -> None:
    # The sweep looks for variants the document may not hold; only what is there is "also".
    group = make_group(PERSON, "Mr Carter", variants={"Mr Carter", "Carter", "J. Carter"})
    assert other_spellings(group) == []


@pytest.mark.parametrize(
    ("kind", "canonical", "source", "check", "reason"),
    [
        (PERSON, "Fatma Yildiz", "model", True, "found by the model only"),
        (PERCENT, "8 %", "pattern", True, "too short for the leak check"),
        (COMPANY, "Kraft Foods", "rule", True, ""),  # unsure for a reason the group does not say
        (PERSON, "Fatma Yildiz", "model", False, ""),  # sure: nothing to explain
    ],
)
def test_a_group_to_check_says_why_when_it_can(
    kind: PlaceholderType, canonical: str, source: str, check: bool, reason: str
) -> None:
    caption = caption_of(make_group(kind, canonical, source=source, check=check))
    assert caption == " · ".join(["[X_1]", "1 place", *([reason] if reason else [])])


def test_the_caption_of_the_mockups_checked_rows() -> None:
    fatma = make_group(PERSON, "Fatma Yildiz", placeholder="[PERSON_2]", source="model", check=True)
    percent = make_group(PERCENT, "8 %", placeholder="[PERCENT_1]", check=True)
    assert caption_of(fatma) == "[PERSON_2] · 1 place · found by the model only"
    assert caption_of(percent) == "[PERCENT_1] · 1 place · too short for the leak check"


# ---- the footer ---------------------------------------------------------------------------------


def test_the_footer_shares_the_groups_between_hidden_to_check_and_shown() -> None:
    groups = [make_group(COMPANY, f"Company {k}", ident=str(k)) for k in range(12)]
    groups += [make_group(PERSON, "Fatma", check=True), make_group(PERSON, "Ali", check=True)]
    counts = FooterCounts.of(groups)
    assert counts == FooterCounts(hidden=12, to_check=2, shown=0)
    assert counts.text() == "12 hidden · 2 to check · 0 shown on purpose"  # the mockup's footer
    groups[0].enabled = False
    groups[12].enabled = False  # a group to check that is off is still asked about: to check
    assert FooterCounts.of(groups) == FooterCounts(hidden=11, to_check=2, shown=1)


def test_the_footer_counts_a_group_still_asked_about_as_to_check() -> None:
    groups = [make_group(PERSON, "Fatma", check=True, ident="f"), make_group(COMPANY, "Acme")]
    groups[0].enabled = False
    assert FooterCounts.of(groups) == FooterCounts(hidden=1, to_check=1, shown=0)
    assert FooterCounts.of(groups, {"f"}) == FooterCounts(hidden=1, to_check=0, shown=1)


# ---- the switch ---------------------------------------------------------------------------------


def test_the_switch_is_a_check_box_that_a_click_and_a_space_toggle(qtbot: QtBot) -> None:
    switch = ToggleSwitch()
    qtbot.addWidget(switch)
    switch.show()
    assert isinstance(switch, QCheckBox) and (switch.width(), switch.height()) == (32, 18)
    qtbot.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert switch.isChecked()
    qtbot.keyClick(switch, Qt.Key.Key_Space)
    assert not switch.isChecked()
    with qtbot.waitSignal(switch.toggled):
        switch.setChecked(True)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_switch_is_the_accent_when_on_and_grey_when_off(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    switch = ToggleSwitch()
    qtbot.addWidget(switch)
    switch.setPalette(theme.palette(appearance))
    switch.resize(32, 18)
    left, right = QPoint(7, 9), QPoint(25, 9)  # the track on either side of the knob
    off = switch.grab().toImage()
    assert colour_at(off, left) == t.panel.upper()  # the knob, on the left
    assert colour_at(off, right) == t.border_strong.upper()  # the grey track
    switch.setChecked(True)
    on = switch.grab().toImage()
    assert colour_at(on, left) == t.accent.upper()  # the track in the accent colour
    assert (
        colour_at(on, right) == t.on_accent.upper()
    )  # the knob, on the right: what is on the accent


# ---- a row --------------------------------------------------------------------------------------


def test_a_row_shows_the_name_the_caption_and_a_switch_that_says_what_it_hides(
    qtbot: QtBot,
) -> None:
    group = make_group(COMPANY, "Northwind Trading B.V.", placeholder="[COMPANY_1]")
    row = sized_row(qtbot, group)
    assert row.data.name == "Northwind Trading B.V."
    assert row.data.caption == "[COMPANY_1] · 1 place"
    assert row.switch is not None and row.switch.isChecked()  # checked = hidden
    assert row.switch.accessibleName() == "Hide Northwind Trading B.V."
    assert row.hide_button is None and row.show_button is None
    assert "Northwind Trading B.V." in row.accessibleDescription()


def test_the_name_of_a_row_is_on_one_line() -> None:
    group = make_group(COMPANY, "Northwind\nTrading\xa0B.V.")
    assert RowData.of(group).name == "Northwind Trading B.V."


def test_only_a_group_to_check_has_the_pill(qtbot: QtBot) -> None:
    sure = sized_row(qtbot, make_group(COMPANY, "Acme Ltd"))
    unsure = sized_row(qtbot, make_group(COMPANY, "Kraft", check=True))
    assert sure.pill_box() is None
    pill = unsure.pill_box()
    assert pill is not None and pill.width() > 30
    assert "to check" in unsure.accessibleDescription()
    assert "to check" not in sure.accessibleDescription()


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_pill_is_drawn_in_the_notice_colours(qtbot: QtBot, appearance: str) -> None:
    t = theme.tokens(appearance)
    row = sized_row(qtbot, make_group(COMPANY, "Kraft", check=True), appearance)
    pill = row.pill_box()
    assert pill is not None
    image = row.grab().toImage()
    inside = QPoint(round(pill.left()) + 2, round(pill.center().y()))
    assert colour_at(image, inside) == t.notice_bg.upper()
    ink = {
        image.pixelColor(x, y).name().upper()
        for x in range(round(pill.left()), round(pill.right()))
        for y in range(round(pill.top()), round(pill.bottom()))
    }
    assert any(QColor(c).lightness() != QColor(t.notice_bg).lightness() for c in ink)  # the letters


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_chip_has_the_colour_of_the_type(qtbot: QtBot, appearance: str) -> None:
    row = sized_row(qtbot, make_group(PERSON, "Mr John Carter"), appearance)
    image = row.grab().toImage()
    row_box = row.row_box()
    chip = QPoint(round(row_box.left()) + 8 + 5, round(row_box.center().y()))
    assert colour_at(image, chip) == TYPE_COLOURS[PERSON].upper()


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_a_selected_row_is_on_the_soft_accent_and_the_others_are_not(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    row = sized_row(qtbot, make_group(COMPANY, "Acme Ltd"), appearance)
    box = row.row_box()
    spot = QPoint(round(box.left()) + 10, round(box.top()) + 2)  # inside the corner, above the text
    assert not row.selected
    assert colour_at(row.grab().toImage(), spot) != t.accent_soft.upper()
    row.set_marked(selected=True, current=True, focused=False)
    assert row.selected
    assert colour_at(row.grab().toImage(), spot) == t.accent_soft.upper()
    row.set_marked(selected=False, current=False, focused=False)
    assert not row.selected
    assert colour_at(row.grab().toImage(), spot) != t.accent_soft.upper()


def test_the_row_that_starts_a_section_has_its_heading_above_it(qtbot: QtBot) -> None:
    group = make_group(COMPANY, "Acme Ltd")
    plain = sized_row(qtbot, group)
    first = sized_row(qtbot, group, heading="COMPANIES · 2", leading=True)
    later = sized_row(qtbot, group, heading="PEOPLE · 1")
    assert plain.heading is None and first.heading == "COMPANIES · 2"
    assert plain.needed_height() < later.needed_height() < first.needed_height()
    assert first.row_box().top() == 8 + 8 + 16 + 4  # the list's padding, the heading's, its line
    assert later.row_box().top() == 10 + 16 + 4


def test_a_caption_of_several_lines_makes_a_taller_row(qtbot: QtBot) -> None:
    short = make_group(COMPANY, "Acme Ltd", placeholder="[COMPANY_1]")
    long = make_group(
        COMPANY,
        "Northwind Trading B.V.",
        "Northwind",
        "the Buyer’s group",
        placeholder="[COMPANY_1]",
    )
    one = sized_row(qtbot, short)
    several = sized_row(qtbot, long)
    assert several.needed_height() > one.needed_height()
    assert one.needed_height() == 7 + 17 + 14 + 7 + 2  # padding, name, a line of caption, gap
    assert several.fit(600) == one.needed_height()  # with room enough it is one line again


def test_a_long_name_is_cut_short_before_the_pill(qtbot: QtBot) -> None:
    name = "Northwind Trading Company of the Netherlands and Its Subsidiaries B.V."
    row = sized_row(qtbot, make_group(COMPANY, name, check=True))
    pill = row.pill_box()
    assert pill is not None
    assert pill.right() <= 300 - 6 - 8 - 32 - 10  # before the switch, whatever the name


def test_moving_the_switch_says_so_and_setting_it_does_not(qtbot: QtBot) -> None:
    row = sized_row(qtbot, make_group(COMPANY, "Acme Ltd"))
    assert row.switch is not None
    with qtbot.waitSignal(row.switched) as moved:
        qtbot.mouseClick(row.switch, Qt.MouseButton.LeftButton)
    assert moved.args == [False] and not row.switch.isChecked()
    with qtbot.assertNotEmitted(row.switched):
        row.set_checked(True)
    assert row.switch.isChecked() and row.data.hidden


def test_a_row_of_the_question_has_a_hide_and_a_show_button_and_no_switch(qtbot: QtBot) -> None:
    group = make_group(COMPANY, "Kraft", check=True, enabled=False)
    row = GroupRow(RowData.of(group, question=True))
    qtbot.addWidget(row)
    assert row.switch is None and row.hide_button is not None and row.show_button is not None
    assert (row.hide_button.text(), row.show_button.text()) == ("Hide", "Show")
    assert row.hide_button.accessibleName() == "Hide Kraft"
    assert row.show_button.accessibleName() == "Show Kraft"
    with qtbot.waitSignal(row.hideClicked):
        row.hide_button.click()
    with qtbot.waitSignal(row.showClicked):
        row.show_button.click()


# ---- the pane -----------------------------------------------------------------------------------


def test_the_pane_has_the_find_field_the_two_buttons_the_list_and_the_footer(
    qtbot: QtBot,
) -> None:
    pane = Inspector()
    qtbot.addWidget(pane)
    assert pane.accessibleName() == "What was found"
    assert pane.find_field.placeholderText() == "Find in document  ⌘F"
    assert pane.find_field.isClearButtonEnabled()
    assert pane.find_field.accessibleName() == "Find in document"
    assert (pane.hide_button.text(), pane.never_button.text()) == ("Hide selection", "Show always")
    assert pane.counts_label.text() == "0 hidden · 0 to check · 0 shown on purpose"
    assert pane.hint_label.text() == "Space toggles · ↑↓ moves"
    assert isinstance(pane.find_field, QLineEdit) and isinstance(pane.tree, GroupTree)


def test_the_pane_is_between_300_and_360_pixels_wide(qtbot: QtBot) -> None:
    pane = Inspector()
    qtbot.addWidget(pane)
    assert (pane.minimumWidth(), pane.maximumWidth()) == (300, 360)


def test_the_tab_order_goes_from_the_find_field_to_the_buttons_and_the_list(qtbot: QtBot) -> None:
    pane = Inspector()
    qtbot.addWidget(pane)
    pane.show()
    qtbot.waitExposed(pane)
    chain = [pane.find_field]
    while len(chain) < 12 and pane.tree not in chain:
        chain.append(chain[-1].nextInFocusChain())
    # The clear button of the field may stand between them; the order of the four is the point.
    assert chain.index(pane.find_field) < chain.index(pane.hide_button)
    assert chain.index(pane.hide_button) < chain.index(pane.never_button) < chain.index(pane.tree)


# ---- the list -----------------------------------------------------------------------------------


def test_space_on_a_line_that_can_be_switched_asks_for_it_and_on_one_that_cannot_does_not(
    qtbot: QtBot,
) -> None:
    tree = GroupTree()
    qtbot.addWidget(tree)
    group = QTreeWidgetItem(["Acme Ltd"])
    group.setFlags(
        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
    )
    group.setCheckState(0, Qt.CheckState.Checked)
    plain = QTreeWidgetItem(["Nothing to switch"])
    plain.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    tree.addTopLevelItems([group, plain])
    asked: list[QTreeWidgetItem] = []
    tree.toggleRequested.connect(asked.append)
    tree.setCurrentItem(group)
    qtbot.keyClick(tree, Qt.Key.Key_Space)
    assert asked == [group]
    tree.setCurrentItem(plain)
    qtbot.keyClick(tree, Qt.Key.Key_Space)
    assert asked == [group]
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier
    )
    tree.setCurrentItem(group)
    tree.keyPressEvent(event)  # with a modifier it is not a switch
    assert asked == [group]


# ---- the colours come from the theme --------------------------------------------------------------------------


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_caption_of_a_selected_row_has_the_text_colour_made_for_the_soft_accent(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    row = sized_row(qtbot, make_group(COMPANY, "Acme Ltd"), appearance)
    assert row.caption_colour().name().upper() == t.secondary.upper()
    row.set_marked(selected=True, current=True, focused=True)
    assert row.caption_colour().name().upper() == t.accent_text_on_soft.upper()


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_the_name_of_a_value_shown_on_purpose_is_in_the_secondary_colour(
    qtbot: QtBot, appearance: str
) -> None:
    t = theme.tokens(appearance)
    off = make_group(COMPANY, "Acme Ltd", enabled=False)
    row = sized_row(qtbot, off, appearance)
    assert row.name_colour().name().upper() == t.secondary.upper()
    row.set_marked(selected=True, current=True, focused=False)
    assert row.name_colour().name().upper() == t.accent_text_on_soft.upper()
    row.set_checked(True)  # hidden again: the text colour, selected or not
    assert row.name_colour().name().upper() == t.text.upper()
    asked = GroupRow(RowData.of(make_group(COMPANY, "Kraft", check=True, enabled=False), True))
    qtbot.addWidget(asked)
    asked.setPalette(theme.palette(appearance))
    assert asked.name_colour().name().upper() == t.text.upper()  # a question wants to be read


def test_the_review_is_drawn_with_the_tokens_of_the_theme_and_no_colour_of_its_own() -> None:
    # Ruling R124: a colour that is changed in the theme is changed everywhere, so the code of the
    # review holds no colour of its own (the tints of the types come from the theme as well), and
    # asks for the tertiary colour never: that is for a placeholder in a field and for what is
    # disabled, which the palette draws.
    folder = Path(theme.__file__).parent
    for name in ("review_inspector.py", "review_screen.py"):
        code = (folder / name).read_text(encoding="utf-8")
        assert re.findall(r"#[0-9A-Fa-f]{6}\b", code) == [], name
        assert ".tertiary" not in code, name
        assert "white" not in code.lower().replace("white space", ""), name
