---
title: CSRF Special Contexts
type: concept
related: [[CSRF]]
---

Một số ngữ cảnh đặc biệt cần kiểm thử riêng:

- Mobile/SPA: deep links, embedded WebViews, hybrid apps
- Integrations: webhooks và back-office tools

Các bối cảnh này có thể tự động gửi cookies hoặc có state-changing GETs.