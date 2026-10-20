# PB-COMPARE-01 — Equal compression for Pascal, Data Matrix and QR

2026-10-20. **Compression helps every format; this experiment does not establish a universal winner.** Our high-rate profile has a modest nominal size advantage on the long random/text examples. Data Matrix is smaller on the short random/contact examples. The reliability of those operating points has not been matched.

## Measured encoded sizes

Each format receives exactly the same chosen application envelope and the same eight-byte integrity allowance. Dimensions below are in modules **including quiet zones**, at equal module pitch. All fitting cases were read from a clean raster and decompressed back to the exact original bytes.

| Original input | Original bytes | Envelope bytes | Our Turbo / 0.85 | Data Matrix ECC200 | QR-L | QR-M |
|---|---:|---:|---:|---:|---:|---:|
| Random bytes | 128 | 133 | 50×50 | 46×46 | 53×53 | 57×57 |
| Actual B2 random payload | 800 | 805 | 102×102 | 106×106 | 105×105 | 117×117 |
| Research text | 1200 | 554 | 86×86 | 90×90 | 89×89 | 101×101 |
| Structured sensor JSON | 749 | 136 | 50×50 | 50×50 | 53×53 | 57×57 |
| Contact record | 198 | 128 | 50×50 | 46×46 | 53×53 | 57×57 |
| Already-compressed PNG | 340 | 345 | 74×74 | 74×74 | 73×73 | 81×81 |

The envelope column includes a five-byte compression/version/original-length header. The common eight-byte integrity tag is additional and is included in every displayed symbol size. Native symbol headers, framing and ECC are included automatically by the encoders.

For the actual 800-byte B2 source, the high-rate prototype uses **7.4% less nominal area than Data Matrix** and **5.6% less than QR-L** in this binary-envelope protocol. These percentages are area savings for that example, not the earlier 37.46% payload increase over Dense-A. Different ECC profiles and photographic read margins prevent interpreting them as reliable-density advantages.

Data Matrix is smaller for the 128-byte random source and the contact record. It ties our high-rate profile for the JSON and PNG examples. QR-L is slightly smaller for the PNG example. The full JSON includes Turbo rates 0.55/0.65/0.85, Dense-A, QR L/M/Q/H, and two Data Matrix writer configurations; a single favorable profile is not the entire comparison.

## Identical compression opportunity

Every source is offered raw bytes, the existing compact-text representation, DEFLATE/zlib level 9, bzip2 level 9, XZ/LZMA preset 9, Brotli quality 11, and Zstandard level 19. Selection minimizes the complete envelope length, including metadata, with a deterministic tie break. All seven candidates are independently decompressed and checked before symbol generation.

The 1,200-byte text sample selects Brotli and occupies a 554-byte envelope. The 749-byte JSON sample selects Brotli and occupies 136 bytes. The contact record occupies 128 bytes after Brotli and framing. Neither random sample nor the PNG benefits: raw storage wins after overhead is counted.

Compression reduces the JSON example from **98×98 to 50×50** for both our rate-0.85 code and Data Matrix. QR-L improves from **101×101 to 53×53**. This is a compression benefit shared by the competing formats, not an exclusive property of our barcode.

No Base64 or externally provided dictionary is used. A codec's built-in models/dictionaries are part of its shared implementation. The logical envelope-plus-tag SHA-256 is asserted identical across all formats for every source and representation. The application header and compressed bytes are also protected by each barcode's own ECC.

## Data Matrix writer sensitivity

The first run used the library's default binary ECI identifier. For the 800-byte source that produced a 122×122 exterior. Source inspection identified optional ECI overhead near a discrete symbol-size boundary. A byte-preserving writer setting with ECI 0 reduced the exterior to **106×106**; that smaller result is used throughout the main comparison.

The default binary-ECI configuration is retained as the separate Data Matrix / binaryECI control in the JSON. A test transports every byte value 0–255 through the optimized Data Matrix and QR paths, checks the integrity tag, and compares the recovered source. Avoiding the optional identifier does not discard payload bytes or require an external dictionary.

## Verification and limits

- 6 deterministic sources × 2 representation policies × 10 format/profile configurations = **120 cases**.
- **106 symbols fit and all 106 decoded/decompressed exactly**, with zero incorrect accepted sources.
- 14 cases exceed the existing implementation/profile capacities. They are recorded as “does not fit”, not decode failures. Low-rate Pascal profiles currently stop at a 94-module side.
- **12 compression/transport regression tests pass**, together with the existing **391 Python tests**, JavaScript port checks and viewer-navigation check in CI.
- These are clean-image reads at four raster pixels/module. Our clean reader receives exact geometry; standard readers locate their clean symbols. This is not equal-photographic-condition read-rate testing.
- Quiet zones are counted. Auxiliary experimental photograph markers are absent from these nominal footprints; future assisted camera comparisons must count equivalent assistance for every format.
- ECC profiles differ. Equal compression does not establish equal noise/damage tolerance.
- Six illustrative inputs do not characterize all data distributions. The shared binary envelope also does not optimize every format's native text-mode protocol.
- The prior frozen simulated validation and the physical v1.1 reference HTML/patterns are unchanged. No user photographs are published.

A reliable-density comparison still needs fresh photos or a predeclared capture model, common physical sizes, matched success-rate targets, and adequate held-out trials. The current experiment settles the compression-opportunity question and exposes the nominal size tradeoffs.

## Reproduce and inspect

Tested source commit: [a1238d08013700413aff7337d04d58c6231f146b](https://github.com/TACITVS/Pascal_2D_Barcode/commit/a1238d08013700413aff7337d04d58c6231f146b).

[Executed comparison and downloadable JSON/Markdown artifact](https://github.com/TACITVS/Pascal_2D_Barcode/actions/runs/39464581179) · [Full regression run](https://github.com/TACITVS/Pascal_2D_Barcode/actions/runs/39464581497).

```bash
python -m pip install -e ".[dev,bench]" "zxing-cpp>=3.0,<4" brotli zstandard
python -m pytest research/density/test_compression_compare.py -q
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python research/density/compression_compare.py --out comparison-results.json
```

The committed [results JSON](compression_comparison_results.json) includes individual outcomes, source/packet hashes, candidate lengths, encoder/compressor versions, and CI provenance. It contains the emitted experimental results with additional provenance metadata. Sources are deterministic, including the exact existing B2-V1 arbitrary-byte payload; the text input is the first 1,200 bytes of this study's README at the tested source revision.

No production format, encoder, reference target or compatibility promise is changed by this research comparison.
