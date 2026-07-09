---
title: Business Logic Numeric and Currency Issues
type: concept
related: [[Business Logic Flaws]]
---

Các lỗi số học và tiền tệ có thể tạo ra lợi thế cho attacker ở biên.

Rủi ro:
- Floating point vs decimal rounding
- Rounding/truncation có lợi cho attacker
- Cross-currency arbitrage với stale rates
- Tax rounding per-item vs per-order
- Negative amounts, zero-price, free shipping thresholds, guardrails min/max

Nguyên tắc:
- Tính toán server-side bằng kiểu dữ liệu phù hợp
- Kiểm tra biên và quy tắc quy đổi tiền tệ