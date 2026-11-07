# Changelog

## 0.3.2

- Detect PNG, JPEG, GIF, WebP, and BMP by their binary signatures before considering SVG conversion.
- Avoid mistaking PNG files containing embedded SVG metadata for SVG documents.
- Isolate image-slot failures so one invalid image no longer prevents camera, media, or Ecovacs slots from updating.

## 0.3.1

- Fetch `image.*` entities through Home Assistant's documented image proxy.
- Rasterize SVG image entities such as Ecovacs floor maps before KAC JPEG conversion.
- Reject external references inside SVG input and report useful byte signatures for unsupported image responses.

## 0.3.0

- Added a Home Assistant ingress Web UI with searchable entity and alias fields.
- Added camera snapshots, media-player artwork, and generic proxied `entity_picture` sources.
- Added direct static-image uploads to the add-on configuration folder.
- Added automatic 240×240 fitting and adaptive baseline-JPEG compression with a configurable target size.
- Image entities refresh at a configurable interval and upload only when their content changes.
- Existing 0.2 graphical options and legacy `kac.yaml` configurations remain valid migration sources.

## 0.2.0

- Configure entities, format templates, devices, pages, rows, and images through Home Assistant's graphical add-on options.
- Existing `kac.yaml` installations remain active until at least one device is saved in the UI.
- Removed first-start example-file creation and its confusing error-level log entry.
- Added German and English labels for nested configuration fields.

## 0.1.0

- Initial Home Assistant add-on.
- Reads arbitrary Home Assistant states through the Supervisor Core API proxy.
- Supports all documented KAC row types (`h`, `k`, `d`, `u`, `b`, `g`, `s`, `-`).
- Supports multi-part page updates, multiple KAC devices, named templates, sparkline history, and image slots 1–5.
- Converts local still images to baseline 240×240 JPG and animations to constrained GIF before upload.
