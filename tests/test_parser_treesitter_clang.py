"""Java / C / C++ parsers (spec-driven tree-sitter walker).

Guarded by importorskip so the suite still passes where the C-family grammar
wheels are absent (they ride in via the `lang` extra)."""
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter_java")
pytest.importorskip("tree_sitter_c")
pytest.importorskip("tree_sitter_cpp")

from keymd.engine.parsers.base import get_parser_for  # noqa: E402
import keymd.engine.parsers.treesitter  # noqa: E402,F401  (registers the grammars)


def _parse(tmp_path, name, src):
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    parser = get_parser_for(f)
    assert parser is not None, f"no parser registered for {name}"
    return parser.parse(f)


JAVA = '''package demo;
import java.util.List;
public class Main {
    public Main() {}
    void run() {
        Helper h = new Helper();
        h.greet("secret-value");
    }
    int add(int a, int b) { return a + b; }
    static class Inner { void ping() {} }
}'''


def test_java_symbols_edges(tmp_path):
    r = _parse(tmp_path, "Main.java", JAVA)
    by = {s.name: s for s in r.symbols}
    assert by["Main"].kind == "class"
    assert by["Main.run"].kind == "method"
    assert by["Main.add"].signature == "int add(int a, int b)"
    assert by["Main.Inner"].kind == "class"        # nested class qualified under Main
    assert by["Main.Inner.ping"].kind == "method"
    assert by["Main.Main"].kind == "method"        # constructor
    callees = {e.to_name for e in r.edges if e.kind == "call"}
    assert "greet" in callees                      # method_invocation leaf
    assert "Helper" in callees                     # object_creation_expression -> type
    imports = {e.to_name for e in r.edges if e.kind == "import"}
    assert "java.util.List" in imports
    # SECURITY: the string arg never becomes a value anywhere in a signature
    assert all("secret-value" not in (s.signature or "") for s in r.symbols)


C = '''#include <stdio.h>
#include "local.h"
int square(int x) { return x * x; }
int main() { return square(5); }'''


def test_c_symbols_edges(tmp_path):
    r = _parse(tmp_path, "calc.c", C)
    by = {s.name: s for s in r.symbols}
    assert by["square"].kind == "function"
    assert by["square"].signature == "int square(int x)"
    assert by["main"].kind == "function"
    callees = {e.to_name for e in r.edges if e.kind == "call"}
    assert "square" in callees                     # call inside main -> maps main.c->calc.c
    imports = {e.to_name for e in r.edges if e.kind == "import"}
    assert "stdio.h" in imports and "local.h" in imports


CPP = '''#include <iostream>
class Calc {
public:
    int square(int x);
    std::string* name() const;
};
int Calc::square(int x) { return x * x; }
int f(std::string s = "topsecret") { return 0; }
int main() { Calc c; c.square(5); }'''


def test_cpp_symbols_edges_and_string_hiding(tmp_path):
    r = _parse(tmp_path, "calc.cpp", CPP)
    by = {s.name: s for s in r.symbols}
    assert by["Calc"].kind == "class"
    assert by["Calc.square"].signature == "int square(int x)"   # in-class declaration
    assert "Calc::square" in by                                 # out-of-line definition
    assert by["Calc.name"].signature == "std::string* name() const"
    # SECURITY: C++ default-arg string is hidden structurally
    assert by["f"].signature == "int f(std::string s = <str>)"
    assert all("topsecret" not in (s.signature or "") for s in r.symbols)
    callees = {e.to_name for e in r.edges if e.kind == "call"}
    assert "square" in callees                                  # c.square(5) field_expression leaf


CPP_REFS = '''class Box {
public:
    int& at(int i);
    Box& operator=(const Box& o);
    const std::string& name() const;
};
int& at(int i) { return slot; }
Box&& take() { return std::move(b); }'''


def test_cpp_reference_return_functions_are_emitted(tmp_path):
    """Regression: reference/rvalue-ref returns (T&, T&&) use `reference_declarator`,
    which (unlike pointer_declarator) doesn't expose its inner via the `declarator`
    field — a field-only name walk silently dropped every such function. Idiomatic
    C++ (operator=, accessors, fluent setters) must NOT vanish from the index."""
    r = _parse(tmp_path, "box.cpp", CPP_REFS)
    by = {s.name: s for s in r.symbols}
    assert "Box.at" in by                       # in-class int& at(int)
    assert "Box.operator=" in by                # Box& operator=
    assert "Box.name" in by                     # const std::string& name() const
    assert "at" in by                            # free int& at(int)
    assert "take" in by                          # Box&& take()


def test_java_wildcard_import_preserved(tmp_path):
    r = _parse(tmp_path, "W.java", "import a.b.*;\nimport a.b.C;\npublic class W {}")
    imports = {e.to_name for e in r.edges if e.kind == "import"}
    assert "a.b.*" in imports                     # wildcard kept distinct
    assert "a.b.C" in imports                     # type import unaffected


CPP_FNPTR = '''class Reg {
    int (*handler)(int);
    int (*table[4])(char*);
};
int (*global_fp)(int);
int realFn(int x) { return x; }'''


def test_cpp_function_pointer_variables_not_emitted(tmp_path):
    """Regression: a function-POINTER variable (`int (*fp)(int)`) is shaped by
    tree-sitter with a nested function_declarator, so a naive DFS would emit it as
    a bogus function symbol. Only identifier-like declarator names are real
    functions; fn-ptr variables (parenthesized_declarator) must be rejected."""
    r = _parse(tmp_path, "reg.cpp", CPP_FNPTR)
    names = {s.name for s in r.symbols}
    assert "Reg" in names                          # the class itself
    assert "realFn" in names                       # the one real function
    # none of the fn-pointer fields/globals leak in as symbols
    assert not any("handler" in n or "table" in n or "global_fp" in n or "*" in n
                   for n in names)
