"""Restore: the real values put back into the text or the Word file an AI tool gives back.

``matcher.plan_restore`` sorts the placeholders in a text into those the key holds as written,
those the AI changed, which wait for the owner's confirmation, and those the key does not hold,
which stay as they are; ``matcher.suggest_cases`` puts the case that fits a text best first.
``text.restore_text`` restores pasted text and ``docx_restore.restore_docx`` a Word file, into a
new file; ``report.RestoreReport`` says what a restore did.
"""
