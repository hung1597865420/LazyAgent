---
title: CSRF
type: concept
related: [[CSRF Attack Surface]]
---

Cross-site request forgery (CSRF) là kiểu tấn công lợi dụng ambient authority như cookies hoặc HTTP auth giữa các origin.

Nguyên tắc phòng thủ:
- Không dựa vào CORS בלבד
- Mỗi state change phải yêu cầu token không thể replay
- Phải kiểm tra Origin và/hoặc Referer một cách nghiêm ngặt

CSRF chỉ bị loại bỏ khi server yêu cầu một bí mật mà attacker không thể cung cấp và xác minh được origin của caller.