---
title: PHP Phar Deserialization
type: entity
related: [[PHP unserialize()]]
---

Phar deserialization được nhắc đến qua wrapper `phar://`.

Đặc điểm:
- metadata deserialization có thể bị trigger khi file operations chạm vào archive
- có thể xảy ra qua upload hoặc reference đến file Phar

Đây là một vector object injection đặc thù của PHP.