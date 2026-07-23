# Azure OpenAI -> 9Router Migration Guide

Tài liệu này dùng để đưa cho agent/dev trong repo khác migrate AI backend từ Azure OpenAI sang 9Router/OpenAI-compatible endpoint.

> Không commit API key thật. Đưa key qua `.env.local`, secret manager, CI secret, hoặc biến môi trường runtime.

## Mục Tiêu

- Bỏ phụ thuộc Azure OpenAI bị khóa/bị ban quota.
- Chuyển code sang OpenAI-compatible API qua 9Router.
- Giữ interface nội bộ của app càng ít đổi càng tốt.
- Có smoke test để biết cấu hình mới thật sự trả lời được.

## Thông Tin 9Router

```env
OPENAI_BASE_URL=https://apipool.n8ntinhdao.com/v1
OPENAI_API_KEY=<9ROUTER_API_KEY>
AI_MODEL=<MODEL_ID_TREN_9ROUTER>
```

Nếu app có nhiều loại tác vụ, nên tách model:

```env
AI_MODEL_DEFAULT=<model-rẻ/nhanh>
AI_MODEL_CODING=<model-mạnh-cho-code>
AI_MODEL_REASONING=<model-mạnh-cho-phân-tích>
AI_MODEL_SUMMARY=<model-rẻ-cho-tóm-tắt>
```

Model ID phải lấy đúng từ dashboard 9Router. Không dùng Azure deployment name nếu 9Router không có model ID đó.

## Mapping Biến Môi Trường

| Azure hiện tại | 9Router/OpenAI-compatible |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | `OPENAI_BASE_URL=https://apipool.n8ntinhdao.com/v1` |
| `AZURE_OPENAI_API_KEY` | `OPENAI_API_KEY=<9ROUTER_API_KEY>` |
| `AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_DEPLOYMENT_NAME` | `AI_MODEL=<MODEL_ID_TREN_9ROUTER>` |
| `AZURE_OPENAI_API_VERSION` | Bỏ, 9Router `/v1` không cần `api-version` |
| `api-key` header | `Authorization: Bearer <OPENAI_API_KEY>` |
| Azure deployment parameter | OpenAI-compatible `model` parameter |

## Checklist Tìm Code Azure

Chạy trong repo cần migrate:

```bash
rg -n "AzureOpenAI|azureOpenAI|AZURE_OPENAI|api-version|deployment|azure_endpoint|api-key|openai.azure|AzureChatOpenAI"
```

Các file thường cần sửa:

- `.env.example`, `.env.local.example`, CI secrets docs.
- Config loader: `config.ts`, `config.py`, `settings.py`, `env.ts`.
- AI client wrapper: `ai.ts`, `llm.ts`, `openai.ts`, `model.py`, `llm_client.py`.
- LangChain/Vercel AI SDK integration nếu có.
- Tests/mock liên quan Azure deployment.

## Pattern Chuẩn

Ưu tiên tạo một wrapper nội bộ duy nhất, ví dụ `createAiClient()` hoặc `get_llm_client()`. Những chỗ khác trong app không nên biết provider là Azure hay 9Router.

### Python: OpenAI SDK

Trước, thường là Azure:

```python
from openai import AzureOpenAI

client = AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)

response = client.chat.completions.create(
    model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    messages=[{"role": "user", "content": "ping"}],
)
```

Sau, chuyển sang 9Router:

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://apipool.n8ntinhdao.com/v1"),
)

response = client.chat.completions.create(
    model=os.environ["AI_MODEL"],
    messages=[{"role": "user", "content": "ping"}],
)

print(response.choices[0].message.content)
```

### Node/TypeScript: OpenAI SDK

Trước, thường là Azure endpoint/deployment:

```ts
// Ví dụ minh họa: tên class/import có thể khác tùy repo.
const client = new AzureOpenAI({
  endpoint: process.env.AZURE_OPENAI_ENDPOINT,
  apiKey: process.env.AZURE_OPENAI_API_KEY,
  apiVersion: process.env.AZURE_OPENAI_API_VERSION,
});
```

Sau:

```ts
import OpenAI from "openai";

export const ai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: process.env.OPENAI_BASE_URL ?? "https://apipool.n8ntinhdao.com/v1",
});

export async function askAi(prompt: string) {
  const res = await ai.chat.completions.create({
    model: process.env.AI_MODEL!,
    messages: [{ role: "user", content: prompt }],
  });

  return res.choices[0]?.message?.content ?? "";
}
```

### Raw HTTP

Nếu repo đang tự gọi HTTP:

```bash
curl https://apipool.n8ntinhdao.com/v1/chat/completions \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "'"$AI_MODEL"'",
    "messages": [
      {"role": "user", "content": "Reply only: ok"}
    ]
  }'
```

Không dùng:

```text
?api-version=...
api-key: ...
/openai/deployments/<deployment>/chat/completions
```

## LangChain/Vercel AI SDK

### LangChain Python

Nếu đang dùng Azure class như `AzureChatOpenAI`, chuyển sang OpenAI-compatible class/config tương đương:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model=os.environ["AI_MODEL"],
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
)
```

### LangChain JS

```ts
import { ChatOpenAI } from "@langchain/openai";

export const llm = new ChatOpenAI({
  model: process.env.AI_MODEL,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL,
  },
});
```

### Vercel AI SDK

Tùy version đang dùng, ý chính là tạo OpenAI provider với `baseURL` và `apiKey`, rồi truyền model ID của 9Router. Không giữ Azure deployment/API version.

## Những Chỗ Hay Gãy

1. **Sai model name**

   Azure dùng deployment name, 9Router dùng model ID. Nếu trả `model not found`, kiểm lại dashboard 9Router.

2. **Sai base URL**

   Base URL nên là:

   ```env
   OPENAI_BASE_URL=https://apipool.n8ntinhdao.com/v1
   ```

   Không nối thêm `/chat/completions` vào `base_url` của SDK.

3. **Sai header**

   Azure hay dùng `api-key`. OpenAI-compatible dùng:

   ```http
   Authorization: Bearer <key>
   ```

4. **Còn `api-version`**

   9Router `/v1` không cần query `api-version`. Nếu code vẫn append `?api-version=...`, bỏ đi.

5. **Streaming khác shape**

   Nếu app stream token, test riêng streaming. Một số router/model có thể khác behavior ở chunk cuối, `finish_reason`, usage, hoặc tool call delta.

6. **Tool/function calling**

   Nếu app dùng tools/function calling, test riêng vì không phải mọi model trên router đều hỗ trợ giống nhau.

7. **Embeddings**

   Nếu app dùng embeddings, phải chọn embedding model có trong 9Router. Không dùng chat model cho embeddings.

8. **JSON mode/structured output**

   Nếu code phụ thuộc `response_format`, kiểm model 9Router có hỗ trợ không. Nếu không, fallback bằng prompt + JSON parser tolerant.

## Smoke Test Bắt Buộc

Tạo script nhỏ trước khi migrate sâu.

### Python

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ["OPENAI_BASE_URL"],
)

res = client.chat.completions.create(
    model=os.environ["AI_MODEL"],
    messages=[{"role": "user", "content": "Reply exactly: 9router-ok"}],
    temperature=0,
)

print(res.choices[0].message.content)
```

Chạy:

```bash
python smoke_9router.py
```

### Node

```ts
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: process.env.OPENAI_BASE_URL,
});

const res = await client.chat.completions.create({
  model: process.env.AI_MODEL!,
  messages: [{ role: "user", content: "Reply exactly: 9router-ok" }],
  temperature: 0,
});

console.log(res.choices[0]?.message?.content);
```

Chạy:

```bash
node smoke_9router.js
```

Pass khi output có `9router-ok`.

## Migration Plan Cho Agent

1. Scan toàn repo bằng `rg` để tìm Azure references.
2. Xác định một AI client wrapper trung tâm.
3. Đổi env schema sang `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `AI_MODEL`.
4. Thay Azure SDK/client bằng OpenAI-compatible client.
5. Giữ function signature nội bộ cũ nếu có thể để giảm blast radius.
6. Sửa tests/mock để không còn Azure deployment/API version.
7. Chạy smoke test 9Router.
8. Chạy test app chính.
9. Xóa hoặc deprecate env Azure trong `.env.example`.
10. Ghi README migration note.

## Acceptance Criteria

- `rg "AzureOpenAI|AZURE_OPENAI|api-version|azure_endpoint|AzureChatOpenAI"` không còn hit runtime code, trừ docs migration hoặc compatibility comments.
- App boot được chỉ với:

  ```env
  OPENAI_BASE_URL=https://apipool.n8ntinhdao.com/v1
  OPENAI_API_KEY=<secret>
  AI_MODEL=<model-id>
  ```

- Smoke chat trả lời được.
- Không commit key thật.
- CI/test liên quan AI client pass hoặc được mock rõ ràng.

## Rollback

Nếu cần rollback tạm:

- Giữ interface nội bộ như `askAi()`, `generateText()`, `embedText()` không đổi.
- Cho config có `AI_PROVIDER=azure|9router` trong 1-2 release.
- Mặc định production dùng `9router`.
- Xóa Azure provider sau khi ổn định.

Ví dụ:

```env
AI_PROVIDER=9router
```

Trong code, provider switch chỉ nằm ở AI client wrapper, không rải khắp app.

