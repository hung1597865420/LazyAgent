---
title: Next.js Attack Surface
type: concept
related: [[Next.js]]
---

Bề mặt tấn công của Next.js tập trung vào các lớp sau:

- Routers: App Router (`app/`), Pages Router (`pages/`), Route Handlers (`app/api/**`), API routes (`pages/api/**`), `middleware.ts`
- Runtimes: Node.js và Edge
- Rendering & caching: SSR, SSG, ISR, on-demand revalidation, RSC, draft/preview mode
- Data paths: Server Components, Client Components, Server Actions, `getServerSideProps`, `getStaticProps`
- Integrations: NextAuth.js, `next/image`

Đây là các khu vực cần map trước khi kiểm thử bảo mật Next.js.