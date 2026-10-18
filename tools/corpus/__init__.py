"""The parts of the corpus generator behind ``tools.make_corpus``.

``model`` holds the format-neutral contract (blocks of text runs, tables, notes) and its ground
truth, ``pools`` the made-up companies, places and numbers it draws on, ``parties`` and ``truth``
make the people, companies and secrets of one document, ``clauses``, ``agreements``, ``annexes``
and ``long`` hold the contract wording, ``build`` puts a contract together, ``docx_writer`` turns a
contract into a Word file and ``pdf_writer`` into a PDF file (with a text layer, scanned, or mixed).
"""
