# LLMWiki — Agent Schema

## Purpose
Distill project knowledge into structured wiki pages. Claude và harness agents đọc wiki/ TRƯỚC khi đọc source files.

## Structure
```
raw/              ← Drop docs vào đây (BRD, spec, meeting notes, architecture)
wiki/
  concepts/       ← Patterns, constraints, architectural decisions
  entities/       ← Data models, API contracts, schemas
  sources/        ← Processed source pages (1 file per raw/ doc)
  sources/draft/  ← Unprocessed / incomplete
```

## Operations

### ingest  (`/ingest` skill)
1. Scan raw/ → tìm files chưa có trong wiki/sources/
2. Với mỗi file: extract concepts → wiki/concepts/, entities → wiki/entities/, tạo source page → wiki/sources/
3. Cross-link related pages với `[[page-name]]` syntax
4. Move processed raw/ file reference sang wiki/sources/

### query  (`/query` skill)
Search wiki/ cho relevant pages. Return concepts + entities matching query.

### lint  (`/lint` skill)
Check: broken [[links]], empty pages, raw/ files chưa ingest, orphaned pages.

## Page Format
```markdown
---
title: Page Title
type: concept|entity|source
related: [[other-page]]
source: raw/filename.md   # chỉ dùng cho source pages
---

Content here.
```

## Auto-injection Rules (áp dụng tự động)
Khi Claude hoặc harness agents cần context:
1. Đọc wiki/concepts/ trước (distilled patterns)
2. Đọc wiki/entities/ cho data models  
3. Fallback đọc source files khi wiki chưa đủ
4. wiki/ là source of truth cho domain knowledge; code files là source of truth cho implementation
