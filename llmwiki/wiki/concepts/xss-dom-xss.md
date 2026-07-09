---
title: DOM XSS
type: concept
related: [[XSS]]
---

DOM XSS xảy ra khi dữ liệu từ source phía client đi vào sink nguy hiểm trong DOM.

Nguồn thường gặp:
- location
- document.referrer
- postMessage
- storage
- service worker messages

Sink thường gặp:
- innerHTML / outerHTML / insertAdjacentHTML
- document.write
- setAttribute
- setTimeout / setInterval với string
- eval / Function
- new Worker với blob URL