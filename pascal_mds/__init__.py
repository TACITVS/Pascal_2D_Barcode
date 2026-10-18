"""PASCAL-MDS: a compact 2D matrix barcode built on a Pascal-basis
Reed-Solomon code over GF(257).  See SPEC.md."""

from .codec import Decoded, DecodeError, Symbol, decode_modules, encode
from .layout import LEVELS, SIZES, Version, version

__all__ = [
    "Decoded",
    "DecodeError",
    "LEVELS",
    "SIZES",
    "Symbol",
    "Version",
    "decode_modules",
    "encode",
    "version",
]
__version__ = "1.0.0"
