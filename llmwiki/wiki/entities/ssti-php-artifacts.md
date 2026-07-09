---
title: PHP SSTI Artifacts
type: entity
related: [[Smarty / Twig / Blade SSTI]]
---

Các artifact PHP được nhắc đến:

- Twig `_self.env.registerUndefinedFilterCallback("system")`
- Twig `_self.env.getFilter("id")`
- Smarty `{php}...{/php}`
- `{$smarty.template_object->smarty->...}`
- `{Smarty_Internal_Write_File::writeFile(...)}`
- `Blade::render(...)`
- `Blade::compileString(...)`
- `@php ... @endphp`