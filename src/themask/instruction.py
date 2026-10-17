"""Fixed copy that The MASK writes into masked files and shows to the owner, word for word."""

# First line of every masked file. It uses [COMPANY_1] as its example, so a restore has to take
# this line out before it replaces placeholders.
BANNER_TEXT = (
    "Confidential values in this document are replaced by placeholders such as [COMPANY_1]. "
    "Keep them unchanged."
)

# What stands in for a removed picture or embedded object in a masked file.
IMAGE_NOTE = "[image removed]"
OBJECT_NOTE = "[embedded object removed]"

# The instruction the owner pastes into an AI tool together with the question (spec 8.8).
AI_INSTRUCTION = (
    "This document uses placeholders such as [PERSON_1] and [AMOUNT_2] instead of confidential "
    "values. Keep every placeholder exactly as written, including the square brackets, in your "
    "answer and in any file you create. Do not guess the real values. Please give your result as "
    "a Word (.docx) file."
)
