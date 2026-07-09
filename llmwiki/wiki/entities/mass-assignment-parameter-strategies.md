---
title: Mass Assignment Parameter Strategies
type: entity
related: [[Mass Assignment Reconnaissance]]
---

Các nhóm field thường được thử:

- flat fields: `isAdmin`, `role`, `roles[]`, `permissions[]`, `status`, `plan`, `tier`, `premium`, `verified`, `emailVerified`
- ownership/tenancy: `userId`, `ownerId`, `accountId`, `organizationId`, `tenantId`, `workspaceId`
- limits/quotas: `usageLimit`, `seatCount`, `maxProjects`, `creditBalance`
- feature flags/gates: `features`, `flags`, `betaAccess`, `allowImpersonation`
- billing: `price`, `amount`, `currency`, `prorate`, `nextInvoice`, `trialEnd`

Đây là dictionary field nhạy cảm để fuzz.