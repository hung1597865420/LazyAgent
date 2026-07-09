---
title: JavaScript SSTI Artifacts
type: entity
related: [[Handlebars / Nunjucks / EJS SSTI]]
---

Các artifact JavaScript được nhắc đến:

- `<%= require('child_process').execSync('id').toString() %>`
- `range.constructor("return require('child_process').execSync('id')")()`
- custom helpers
- `eval`
- `Function`
- `child_process`
- prototype pollution
- `process.mainModule.require(...)`