"""Command line: python -m pascal_mds encode|decode|info ..."""

from __future__ import annotations

import argparse
import sys

from .codec import DecodeError, encode
from .layout import LEVELS, SIZES, max_erasures, version


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pascal_mds", description="PASCAL-MDS 2D barcode")
    sub = ap.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encode", help="make a symbol (.svg, .png or text art)")
    enc.add_argument("text", help="text to encode (use - to read bytes from stdin)")
    enc.add_argument("-o", "--output", help="output file (.svg or .png); omit for terminal art")
    enc.add_argument("-l", "--level", default="M", choices=list(LEVELS))
    enc.add_argument("-s", "--size", type=int, choices=SIZES)
    enc.add_argument("-m", "--mode", default="auto", choices=["auto", "bytes", "text"])
    enc.add_argument("--module-px", type=int, default=10)

    dec = sub.add_parser("decode", help="read every symbol in an image")
    dec.add_argument("image")

    sub.add_parser("info", help="print the capacity table")

    args = ap.parse_args(argv)
    if args.cmd == "encode":
        data = sys.stdin.buffer.read() if args.text == "-" else args.text.encode("utf-8")
        sym = encode(data, args.level, args.size, args.mode)
        v = sym.version
        print(f"{v.n}x{v.n} level {v.level}: {v.N} symbols, corrects {v.t} errors "
              f"or {max_erasures(v)} erasures", file=sys.stderr)
        if not args.output:
            for row in sym.modules:
                print("".join("██" if x else "  " for x in row))
        elif args.output.endswith(".svg"):
            from .render import to_svg

            with open(args.output, "w") as fh:
                fh.write(to_svg(sym, args.module_px))
        else:
            from .render import to_image

            to_image(sym, args.module_px).save(args.output)
        return 0
    if args.cmd == "decode":
        from .reader import read

        results = read(args.image)
        if not results:
            print("no symbol decoded", file=sys.stderr)
            return 1
        for det in results:
            d = det.decoded
            print(f"[{d.version.n}x{d.version.n} {d.version.level}, {d.errors} errors, "
                  f"{d.erasures} erasures{', mirrored' if d.mirrored else ''}]", file=sys.stderr)
            sys.stdout.write(d.text + "\n")
        return 0
    print("size  level  N    K    t   erasures  capacity(bytes)")
    for n in SIZES:
        for lv in LEVELS:
            v = version(n, lv)
            print(f"{n:>4}  {lv:^5}  {v.N:<4} {v.K:<4} {v.t:<3} {max_erasures(v):<9} {v.payload_capacity}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, DecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
