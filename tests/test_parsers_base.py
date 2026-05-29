from keymd.engine.parsers import base


def test_parseresult_shape():
    r = base.ParseResult(symbols=[], edges=[], line_count=3)
    assert r.line_count == 3 and r.symbols == [] and r.edges == []


def test_register_and_dispatch():
    class Dummy:
        extensions = (".dummy",)

        def parse(self, path):
            return base.ParseResult(symbols=[], edges=[], line_count=0)

    base.register(Dummy())
    from pathlib import Path
    p = base.get_parser_for(Path("/x/y.dummy"))
    assert p is not None
    assert base.get_parser_for(Path("/x/y.unknown")) is None
    assert ".dummy" in base.config.REGISTERED_EXTENSIONS
