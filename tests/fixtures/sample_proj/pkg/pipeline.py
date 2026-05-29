from pkg.parser import Parser, parse_header


def run(stream) -> list:
    p = Parser()
    rows = p.parse(stream)
    rows.append(parse_header(b"hdr"))
    return rows
