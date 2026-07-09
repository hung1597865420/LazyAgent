---
title: Media and Document Pipeline RCE
type: concept
related: [[RCE]]
---

Các pipeline xử lý media/document có thể trở thành sink RCE nếu delegate, parser, hoặc external tool bị lạm dụng.

Các công cụ được nhắc đến:
- ImageMagick/GraphicsMagick
- Ghostscript
- ExifTool
- LaTeX
- ffmpeg

Cần coi converter/renderers là first-class sinks.