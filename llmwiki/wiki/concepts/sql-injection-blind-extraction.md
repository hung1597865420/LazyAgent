---
title: Blind Extraction
type: concept
related: [[SQL Injection]]
---

Blind extraction dựa trên việc thay đổi predicate đúng/sai để suy ra dữ liệu từng bit hoặc từng ký tự.

Kỹ thuật được nhắc đến:
- `SUBSTRING`/`ASCII`
- `LEFT`/`RIGHT`
- JSON/array operators
- binary search trên character space
- gate delays trong subquery

Mục tiêu là giảm số request và giảm noise.