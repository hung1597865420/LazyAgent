---
title: Jinja2 / Mako SSTI
type: concept
related: [[Server-Side Template Injection]]
---

Nhóm Python template engines này thường cho phép class walk qua object model để đi tới builtins hoặc subprocess gadgets.

Sandbox bypass có thể xảy ra qua attribute lookup hoặc framework globals như `request`, `config`, `cycler`.