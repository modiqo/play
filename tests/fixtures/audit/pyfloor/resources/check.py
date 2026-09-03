import sys
import tomllib


def line_of(text: str, needle: str) -> int | None:
    return text.find(needle) or None


def main(argv: list[str]) -> int:
    print(line_of(argv[0], "x"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
