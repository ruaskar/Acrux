def parse_header(buf: bytes) -> dict:
    return {"len": len(buf)}


class Parser:
    def parse(self, stream) -> list:
        return [parse_header(b"x")]
