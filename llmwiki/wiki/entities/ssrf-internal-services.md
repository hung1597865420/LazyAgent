---
title: Internal Services
type: entity
related: [[SSRF High-Value Targets]]
---

Các dịch vụ nội bộ được nhắc đến:

- Docker API `http://localhost:2375/v1.24/containers/json`
- Redis `dict://localhost:11211/stat`
- Memcached
- Elasticsearch/OpenSearch `http://localhost:9200/_cat/indices`
- RabbitMQ
- Kafka REST
- Celery/Flower
- Jenkins crumb APIs
- FastCGI/PHP-FPM `gopher://localhost:9000/`