---
title: Command Injection Argument Injection
type: entity
related: [[Command Injection]]
---

Các dạng argument injection được nhắc đến:

- inject flags/filenames như `--output=/tmp/x`, `--config=`
- break out of quoted segments
- environment expansion như `$PATH`, `${HOME}`
- Windows `%TEMP%`, `!VAR!`, PowerShell `$(...)`

Mục tiêu là điều khiển tham số của CLI thay vì chỉ shell syntax.