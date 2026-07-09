# RAG Architecture — Coteccons Portal

## Tổng quan

Hệ thống tìm kiếm tài liệu nội bộ theo phòng ban, kết hợp vector search và AI generation. User hỏi bằng ngôn ngữ tự nhiên, hệ thống tìm trong kho tài liệu nội bộ và trả lời có trích dẫn nguồn.

## Stack

| Layer | Công nghệ | Lý do |
|---|---|---|
| Frontend | Next.js 15 (App Router) | Portal đang dùng |
| Auth | Azure AD + NextAuth.js | SSO company email |
| Vector DB | Supabase pgvector | Đã dùng Supabase, không cần service riêng |
| Embedding | Azure OpenAI `text-embedding-3-large` | Đã có Azure AI Foundry endpoint |
| Generation | Claude API (`claude-opus-4-8`) | Chất lượng cao nhất cho tiếng Việt |
| File parsing | `pdf-parse`, `mammoth` (Word), `xlsx` | Open source, không cần cloud |

---

## Database Schema (Supabase)

```sql
-- Phòng ban
create table departments (
  id uuid primary key default gen_random_uuid(),
  name text not null,           -- "Phòng Kỹ thuật", "Phòng HR"...
  code text unique not null,    -- "KT", "HR", "TC"...
  created_at timestamptz default now()
);

-- Tài liệu gốc
create table documents (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  file_url text,                -- URL file gốc trong Supabase Storage
  file_type text,               -- 'pdf', 'docx', 'xlsx'
  department_id uuid references departments(id),
  is_shared boolean default false,  -- true = tất cả phòng ban đều thấy
  uploaded_by uuid references auth.users(id),
  created_at timestamptz default now()
);

-- Chunks đã embed
create table document_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid references documents(id) on delete cascade,
  department_id uuid references departments(id),  -- denorm để filter nhanh
  is_shared boolean default false,
  content text not null,
  embedding vector(3072),       -- text-embedding-3-large dimension
  chunk_index int,              -- thứ tự chunk trong document
  metadata jsonb,               -- page_number, section, etc.
  created_at timestamptz default now()
);

-- Index vector search
create index on document_chunks
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- Index filter nhanh theo department
create index on document_chunks(department_id, is_shared);
```

### Row Level Security (RLS)

```sql
-- Enable RLS
alter table document_chunks enable row level security;
alter table documents enable row level security;

-- Users chỉ thấy chunks của phòng mình HOẶC shared
create policy "department_access" on document_chunks
  for select using (
    department_id = (
      select department_id from profiles
      where id = auth.uid()
    )
    or is_shared = true
  );

-- Admin thấy tất cả
create policy "admin_access" on document_chunks
  for all using (
    exists (
      select 1 from profiles
      where id = auth.uid() and role = 'admin'
    )
  );
```

### Profiles table (sync từ Azure AD)

```sql
create table profiles (
  id uuid primary key references auth.users(id),
  email text unique not null,
  full_name text,
  department_id uuid references departments(id),
  role text default 'user',     -- 'user' | 'admin' | 'dept_admin'
  azure_oid text unique,        -- Azure AD Object ID
  updated_at timestamptz default now()
);
```

---

## Ingestion Pipeline

```
File upload (PDF/Word/Excel)
        │
        ▼
1. Parse text
   - PDF: pdf-parse
   - Word: mammoth
   - Excel: xlsx (sheet → text)
        │
        ▼
2. Chunk
   - Size: 600 tokens
   - Overlap: 100 tokens
   - Giữ nguyên câu, không cắt giữa câu
        │
        ▼
3. Embed từng chunk
   POST https://{azure-endpoint}/openai/deployments/text-embedding-3-large/embeddings
        │
        ▼
4. Lưu vào Supabase document_chunks
   - kèm department_id, is_shared
   - kèm metadata (page, section)
        │
        ▼
5. Done — chunk sẵn sàng để search
```

### API Route: Upload

```
POST /api/rag/upload
Body: FormData { file, department_id, is_shared }
Auth: JWT (chỉ admin hoặc dept_admin mới upload được)
```

---

## Query Flow

```
User gõ câu hỏi
        │
        ▼
1. Lấy department_id từ JWT (Azure AD claim)
        │
        ▼
2. Embed câu hỏi
   Azure OpenAI text-embedding-3-large
        │
        ▼
3. Vector search có filter
   SELECT content, metadata, documents.title
   FROM document_chunks
   WHERE (department_id = $user_dept OR is_shared = true)  ← RLS enforce thêm lần nữa
   ORDER BY embedding <=> $query_vector
   LIMIT 5
        │
        ▼
4. Build prompt cho Claude
   - System: "Chỉ trả lời dựa trên context được cung cấp..."
   - Context: 5 chunks tìm được
   - User: câu hỏi gốc
        │
        ▼
5. Stream response từ Claude
        │
        ▼
6. Trả về answer + danh sách nguồn tài liệu
```

### API Route: Query

```
POST /api/rag/query
Body: { question: string }
Auth: JWT required
Response: { answer: string, sources: [{ title, chunk_index }] }
```

---

## Access Control Matrix

| Role | Docs phòng mình | Shared docs | Docs phòng khác | Upload | Xóa |
|---|---|---|---|---|---|
| user | ✅ | ✅ | ❌ | ❌ | ❌ |
| dept_admin | ✅ | ✅ | ❌ | ✅ (phòng mình) | ✅ (phòng mình) |
| admin | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Sync Azure AD → Supabase

Khi user login lần đầu qua Azure AD, NextAuth callback tự động:

```typescript
// app/api/auth/[...nextauth]/route.ts
callbacks: {
  async signIn({ user, account, profile }) {
    // Lấy department từ Azure AD groups
    const groups = profile?.groups ?? []
    const deptCode = mapGroupToDept(groups) // mapping Azure group → dept code

    // Upsert vào Supabase profiles
    await supabase.from('profiles').upsert({
      id: user.id,
      email: user.email,
      full_name: user.name,
      azure_oid: profile?.oid,
      department_id: await getDeptId(deptCode),
    })
    return true
  }
}
```

**Lưu ý:** Cần map Azure AD Security Groups → department_id trong Supabase. Đây là bước setup 1 lần.

---

## Folder Structure (Next.js)

```
app/
├── (portal)/
│   └── knowledge/
│       ├── page.tsx          # Chat UI
│       └── upload/
│           └── page.tsx      # Upload document UI
├── api/
│   └── rag/
│       ├── query/route.ts    # POST: tìm kiếm + generate
│       └── upload/route.ts   # POST: ingest document
lib/
├── rag/
│   ├── embedder.ts           # Azure OpenAI embedding
│   ├── chunker.ts            # Text chunking logic
│   ├── parser.ts             # PDF/Word/Excel parser
│   └── retriever.ts          # Supabase vector search
└── supabase/
    └── types.ts              # Generated types
```

---

## Phụ thuộc cần cài

```bash
npm install pdf-parse mammoth xlsx ai @ai-sdk/anthropic
```

- `pdf-parse` — đọc PDF
- `mammoth` — đọc Word (.docx)
- `xlsx` — đọc Excel
- `ai` + `@ai-sdk/anthropic` — Vercel AI SDK cho streaming response

---

## MVP Roadmap

| Sprint | Việc cần làm |
|---|---|
| Sprint 1 | Setup schema + RLS, sync Azure AD → profiles |
| Sprint 2 | Ingestion pipeline (PDF trước), upload UI |
| Sprint 3 | Query API + Chat UI cơ bản |
| Sprint 4 | Hiển thị nguồn tài liệu, dept_admin upload UI |
| Sprint 5 | Test với data thật, tune chunk size + top-k |

---

## Điểm phức tạp cần chú ý

1. **Chunk size** — 600 tokens là điểm khởi đầu, cần tune sau khi test với tài liệu thực tế của Coteccons
2. **Tiếng Việt** — `text-embedding-3-large` hỗ trợ tốt tiếng Việt, nhưng cần test với thuật ngữ xây dựng chuyên ngành
3. **File Excel** — cần quyết định convert sheet thành text như nào (row-by-row vs table format)
4. **Re-indexing** — khi tài liệu cập nhật, phải xóa chunks cũ và tạo lại
