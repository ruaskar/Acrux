"""parsers package — importing it registers every available parser.

Registration is a module-import side effect (parsers/python.py and
parsers/treesitter.py call base.register at import). Centralizing it here means
ANY code that touches the parser registry — index.build(), sync_one, refresh,
the watcher, the proxy — gets a populated registry simply by importing
keymd.engine.parsers.base (which runs this __init__ first), instead of the
registry being empty in every process except the CLI.
"""
from keymd.engine.parsers import python  # noqa: F401  (registers the .py parser)
from keymd.engine.parsers import markdown  # noqa: F401  (registers the .md doc parser)

try:  # JS/TS parsers register only if the `lang` extra (tree-sitter) is installed
    from keymd.engine.parsers import treesitter  # noqa: F401
except Exception:
    pass
