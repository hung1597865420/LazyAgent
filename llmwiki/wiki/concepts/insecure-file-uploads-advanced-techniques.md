---
title: Insecure File Uploads Advanced Techniques
type: concept
related: [[Insecure File Uploads]]
---

Các kỹ thuật nâng cao gồm:

- resumable multipart manipulation
- filename and path tricks
- processing races
- metadata abuse
- header manipulation

Chúng thường khai thác sự khác biệt giữa lúc upload, lúc finalize, lúc scan, và lúc serve.