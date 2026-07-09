---
title: HTTP Request Smuggling Validation
type: concept
related: [[HTTP Request Smuggling Testing Methodology]]
---

Tiêu chí validation cho request smuggling:

- Timing differential 10+ giây trên probe CL.TE hoặc TE.CL
- Bypass thành công tới `/admin` hoặc endpoint bị hạn chế
- Capture được `Cookie` hoặc `Authorization` của user khác
- Có unique marker string để loại trừ noise
- Cung cấp raw bytes chính xác của smuggled request

Validation phải chứng minh được tác động thực tế, không chỉ là anomaly.