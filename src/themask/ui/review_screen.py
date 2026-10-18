"""The review screen: what the analysis found, for the owner to check before anything is masked.

This is the first, bare version, which the window needs to show a finished analysis; Task 21 gives
it the highlighted text, the grouped list and the actions.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from themask.detect.lists import CaseLists, UserLists
from themask.detect.pipeline import CombinedText
from themask.review import ReviewState


class ReviewScreen(QWidget):
    """Shows a ``ReviewState`` over the text it was made on (``load``)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.review = ReviewState("", [], [], UserLists([], []), CaseLists([], [], set()))
        self.combined = CombinedText("", [])
        self.summary_label = QLabel()
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)

    def load(self, review: ReviewState, combined: CombinedText) -> None:
        """Show ``review``, made on ``combined``."""
        self.review = review
        self.combined = combined
        counts = review.counts()
        self.summary_label.setText(f"{counts.groups} values found")

    def group_count(self) -> int:
        """How many groups the review has."""
        return len(self.review.groups)
