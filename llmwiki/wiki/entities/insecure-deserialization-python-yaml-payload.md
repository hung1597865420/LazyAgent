---
title: Python YAML Exploit Payload
type: entity
related: [[Python Pickle Deserialization]]
---

Payload YAML được nhắc đến:

```yaml
!!python/object/apply:os.system ['id']
```

Payload này nguy hiểm khi `yaml.load` được dùng thay vì `yaml.safe_load`.