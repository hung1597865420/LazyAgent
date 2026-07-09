---
title: Enumeration Pipeline
type: concept
related: [[Subdomain Takeover]]
---

Pipeline enumeration gồm:
- subdomain inventory từ CT logs, passive DNS, asset lists, IaC/terraform outputs
- resolver sweep với IPv4/IPv6-aware resolvers
- xây record graph và collapse CNAME chains

Mục tiêu là tìm endpoint bên ngoài và dấu hiệu resource chưa được claim.