"""graph.py — import-gated caller heuristic over the edges table.

Ported verbatim from aotc-harness/refresh.py. The leaf-name caller match is
gated on an import-of-the-defining-module signal so `OpBus.close` does not
match all 221 `.close()` calls. Stems colliding with the stdlib drop the
bare-stem patterns to avoid false positives on `import os`-style lines.
"""
from __future__ import annotations

import os
import sqlite3

from keymd.engine import config

STDLIB_STEMS = frozenset({
    "abc", "argparse", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "cmath", "cmd", "code", "codecs",
    "collections", "colorsys", "concurrent", "configparser", "contextlib",
    "contextvars", "copy", "copyreg", "csv", "ctypes", "curses",
    "dataclasses", "datetime", "decimal", "difflib", "dis", "doctest",
    "email", "encodings", "enum", "errno", "faulthandler", "filecmp",
    "fileinput", "fnmatch", "fractions", "functools", "gc", "getopt",
    "getpass", "gettext", "glob", "graphlib", "grp", "gzip", "hashlib",
    "heapq", "hmac", "html", "http", "imaplib", "importlib", "inspect",
    "io", "ipaddress", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "mailbox", "math", "mimetypes",
    "mmap", "multiprocessing", "netrc", "numbers", "operator", "optparse",
    "os", "pathlib", "pdb", "pickle", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pty", "pwd",
    "py_compile", "pyclbr", "queue", "quopri", "random", "re", "readline",
    "reprlib", "resource", "runpy", "sched", "secrets", "select",
    "selectors", "shelve", "shlex", "shutil", "signal", "site", "smtplib",
    "socket", "socketserver", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "symtable", "sys",
    "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
    "termios", "textwrap", "threading", "time", "timeit", "tkinter",
    "token", "tokenize", "tomllib", "trace", "traceback", "tracemalloc",
    "tty", "turtle", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp",
    "zipfile", "zipimport", "zlib", "zoneinfo",
})


def relpath(p: str) -> str:
    try:
        return os.path.relpath(p, config.project_root())
    except ValueError:
        return p


def is_project_import(name: str) -> bool:
    head = name.split(".", 1)[0]
    return head in config.project_pkg_prefixes()


def callers_for_symbol(cur: sqlite3.Cursor, sym: str, defining_path: str,
                       defining_stem: str) -> set[str]:
    """Files that plausibly call `sym` (defined in `defining_path`)."""
    leaf = sym.rsplit(".", 1)[-1] if "." in sym else sym
    class_name = sym.split(".", 1)[0] if "." in sym else None
    is_class_method = "." in sym

    callers: set[str] = set()
    if is_class_method:
        cur.execute(
            "SELECT DISTINCT from_path FROM edges "
            "WHERE kind='call' AND from_path != ? AND to_name = ?",
            (defining_path, sym))
        callers |= {r[0] for r in cur.fetchall()}

    if defining_stem in STDLIB_STEMS:
        like_patterns: list[str] = []
    else:
        like_patterns = [
            f"%.{defining_stem}", defining_stem,
            f"{defining_stem}.%", f"%.{defining_stem}.%",
        ]
    if class_name:
        like_patterns.append(f"%.{class_name}")
        like_patterns.append(class_name)
    if like_patterns:
        placeholders = " OR ".join(["i.to_name LIKE ?"] * len(like_patterns))
        cur.execute(
            f"""SELECT DISTINCT e.from_path FROM edges e
                  WHERE e.kind='call' AND e.from_path != ? AND e.to_name = ?
                    AND EXISTS (
                      SELECT 1 FROM edges i
                      WHERE i.from_path = e.from_path AND i.kind='import'
                        AND ({placeholders}))""",
            (defining_path, leaf, *like_patterns))
        callers |= {r[0] for r in cur.fetchall()}
    return callers
