---
title: .NET Json.NET Type Payload
type: entity
related: [[.NET Deserialization]]
---

Payload Json.NET được nhắc đến:

```json
{"$type":"System.Windows.Data.ObjectDataProvider, PresentationFramework", ...}
```

Payload này có thể nguy hiểm khi `TypeNameHandling` không phải `None`.