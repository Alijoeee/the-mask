"""PDF files: the text of a text PDF, read in reading order and written into a fresh Word file.

``extractor.extract_blocks`` reads a PDF's headings, paragraphs and tables and reports what it
left out (pages that are only a picture, running headers and footers); ``to_docx.pdf_to_docx``
writes those blocks into a new .docx, which is then masked like any other Word file.
"""
