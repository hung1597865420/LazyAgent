---
title: Insecure File Uploads Special Contexts
type: concept
related: [[Insecure File Uploads]]
---

Các bối cảnh đặc biệt cần chú ý:

- rich text editors
- mobile clients
- serverless and CDN flows

Các bối cảnh này thường làm lệch MIME, metadata, cache behavior, hoặc delegate security decisions sang frontend/CDN.