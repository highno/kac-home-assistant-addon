# Changelog

## 0.1.0

- Initial Home Assistant add-on.
- Reads arbitrary Home Assistant states through the Supervisor Core API proxy.
- Supports all documented KAC row types (`h`, `k`, `d`, `u`, `b`, `g`, `s`, `-`).
- Supports multi-part page updates, multiple KAC devices, named templates, sparkline history, and image slots 1–5.
- Converts local still images to baseline 240×240 JPG and animations to constrained GIF before upload.
