"""The interface of The MASK, built with Qt for Python (QtCore, QtGui and QtWidgets only).

Everything that needs a screen is here and nothing else is: the core of the app (detection, the
Word and PDF files, the key, the export) knows nothing of Qt. That keeps the licence of the
packaged app simple, since the other Qt modules include GPL ones (tests/ui/test_qt_modules.py
checks it), and lets the core be tested without a window.
"""
