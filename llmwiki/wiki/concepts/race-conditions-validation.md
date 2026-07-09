---
title: Race Conditions Validation
type: concept
related: [[Race Conditions Testing Methodology]]
---

Validation cần chứng minh:

- single request bị từ chối nhưng N concurrent requests lại thành công
- state change bền vững
- tái lập được với HTTP/2 hoặc last-byte sync
- có evidence across channels nếu áp dụng
- có before/after state và exact request set