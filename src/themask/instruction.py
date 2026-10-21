"""Fixed copy that The MASK writes into masked files and shows to the owner, word for word."""

# First line of every masked file. It uses [COMPANY_1] as its example, so a restore has to take
# this line out before it replaces placeholders.
BANNER_TEXT = (
    "Confidential values in this document are replaced by placeholders such as [COMPANY_1]. "
    "Keep them unchanged."
)

# What stands in for a removed picture, embedded object, equation or embedded document in a
# masked file. The cleaner writes each note apart from the text beside it, and the analysis cuts
# a finding at a note as at a line break (ruling R113).
IMAGE_NOTE = "[image removed]"
OBJECT_NOTE = "[embedded object removed]"
EQUATION_NOTE = "[equation removed]"
ALTCHUNK_NOTE = "[embedded content removed]"
NOTES = (IMAGE_NOTE, OBJECT_NOTE, EQUATION_NOTE, ALTCHUNK_NOTE)

# The instruction the owner pastes into an AI tool together with the question (spec 8.8).
AI_INSTRUCTION = (
    "This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of confidential "
    "values. Keep every placeholder exactly as written, including the square brackets, in your "
    "answer and in any file you create. Do not guess the real values. Please give your result as "
    "a Word (.docx) file."
)

# The same two texts for a case in which the owner named some placeholders (ruling R127): a name
# such as [Provider] stands in for [COMPANY_1], so the texts say that every name in square
# brackets is a placeholder. A restore takes out either version of both lines.
BANNER_TEXT_NAMED = (
    "Confidential values in this document are replaced by placeholders: every name in square "
    "brackets, such as [COMPANY_1], stands for one. Keep them unchanged."
)
AI_INSTRUCTION_NAMED = (
    "This document uses placeholders instead of confidential values: every name in square "
    "brackets, such as [PERSON_1], [AMOUNT_2] or [Provider], is a placeholder. Keep every "
    "placeholder exactly as written, including the square brackets, in your answer and in any "
    "file you create. Do not guess the real values. Please give your result as a Word (.docx) "
    "file."
)


def banner_text(named: bool) -> str:
    """The first line of a masked file; ``named`` when some placeholder has an owner's name."""
    return BANNER_TEXT_NAMED if named else BANNER_TEXT


def ai_instruction(named: bool) -> str:
    """The instruction for the AI tool; ``named`` when some placeholder has an owner's name."""
    return AI_INSTRUCTION_NAMED if named else AI_INSTRUCTION
