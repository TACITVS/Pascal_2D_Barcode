# PM257-PHOTO-PROTOCOL-2026-10-19-v1

Open START_PHOTO_TEST.html on the computer whose screen you will photograph.
The file works offline. Use a normal desktop browser, 100% browser zoom, and
the Full screen button (or F11). This is a target viewer, not a camera decoder.

## The four targets

| Target | Existing / new | Useful payload | Grid |
|---|---|---:|---:|
| A1 | Existing Dense-A | 128 bytes | 50 x 50 |
| A2 | New global optical code, rate 0.55 | The same 128 bytes | 50 x 50 |
| B1 | Existing Dense-A | 582 bytes | 94 x 94 |
| B2 | New global optical code, rate 0.85 | 800 bytes | 94 x 94 |

A1/A2 compare identical payload and area. B1/B2 compare the capacity increase
at identical area. All include the same eight-byte integrity allowance.
The white quiet zone is included in code area. Four external corner markers
assist registration and identification; full-board area must also be reported
when assessing this assisted fixture. This does not test unaided barcode
location or an ordinary phone scanner's compatibility with the new format.

## Start with four close photos

1. Select payload set V1. Keep it selected for the initial sweep. V2/V3 are
   independently generated payloads reserved for later confirmation after
   reader settings are frozen.
2. At about 0.5 m, photograph A1, A2, B1 and B2 once each. Include all four
   corner markers and the whole code. Do not fill the image by digital zoom.
3. Upload these four original files first. They establish that the displayed
   targets and the photographic reader work before you collect a large set.
   They are calibration/development photos, not held-out validation data.

## Distance sweep

Use 1.0, 1.5, 2.0, 2.5 and 3.0 m, measured from screen plane to camera lens.
If both formats still read at 3 m, extend to 3.5 and 4 m. Add a 0.25 m step
around the transition from success to failure. At every distance, take five
separate photos of each target (20 photos/distance). Release/refocus between
shots; burst frames are not independent trials.

Keep the target-size slider fixed within each pair, and keep browser zoom,
screen brightness, camera lens, photo resolution, lighting, and phone
processing mode fixed for the series. The viewer snaps every module to an
integer number of physical screen pixels. If it warns about fewer than four
pixels per module, enlarge the window/full-screen display first.

Suggested phone setup: normal Photo mode, 1x main camera, flash off, no digital
zoom, one fixed photo resolution. Hold the camera roughly perpendicular to the
screen. Use a support or a short self-timer where possible. Let autofocus settle
for each shot. Avoid glare. If whites are visibly blown out, lower screen
brightness or exposure before starting and keep that setting fixed thereafter.

The four corner markers must remain visible. Keep all images, including blurry
or failed shots. Do not select only the best takes. Record unusually bad focus,
motion, glare, or clipping as quality observations.

Set distance and shot number in the viewer. After each photo, the Record button
adds it to a local capture log and advances the shot number. Save the log and
upload it with the photos. The target can also be identified from its markers.
If you rename files, use A2-V1_150cm_03.heic, for example. Original phone names
are fine if you preserve the capture order and provide distances.

If possible, measure the barcode square including its white quiet zone with a
ruler, between the small gray guide ticks above or below it. Enter its width
in millimetres in the optional field and record it.
Re-measure after resizing, zoom changes, full-screen changes, or switching
between the A and B pairs. Do not assume CSS millimetres equal physical ones.

## Upload and interpretation

Upload the original HEIC/JPEG files as attachments, plus capture_log.json and
manifest.json. Do not send screenshots of the photos, messaging-app copies,
resized files, or edited crops. Full originals preserve corner geometry,
resolution, exposure information, and the failed examples. Keep them locally
until the analysis is complete.

Analysis should report exact payload/hash recovery, detected target and
variant, captured symbol size and pixels/module, registration quality, and
read failures by distance. Pixel widths give a fairer optical comparison than
distance alone. Marker detection is registration assistance, not a successful
payload decode. Ground truth must never be used as a bit prior in the decoder.

Screen photographs test a display-to-camera channel, including display pixel
structure and moire. They do not establish printed-paper performance. Five
photos/distance locate a transition but do not establish a 99% success rate.
For example, even 5/5 successes have a one-sided 95% exact lower bound of about
54.9%. Later reliability validation needs fresh payloads and a larger sample.

The close-up images may reveal model mismatch requiring reader development.
Record all changes and reserve fresh captures/payload sets for confirmation.

The targets are arbitrary deterministic high-entropy bytes. Their original
bytes, grid rows, profile settings, hashes, and marker geometry are stored in
manifest.json. targets/*.png are exact fallback boards rendered at four pixels
per module. Prefer the HTML viewer for its size controls and capture labels.
