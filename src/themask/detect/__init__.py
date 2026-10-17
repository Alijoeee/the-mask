"""Detection: finding the confidential values in a contract's text.

``engine.Engine`` runs Presidio's analyzer over spaCy's English model together with the pattern
recognizers in ``patterns`` and returns every value it finds as a ``Finding``.
"""
