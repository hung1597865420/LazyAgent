---
title: AWS Metadata Endpoints
type: entity
related: [[SSRF High-Value Targets]]
---

Các endpoint AWS được nhắc đến:

- IMDSv1 `http://169.254.169.254/latest/meta-data/`
- `/iam/security-credentials/{role}`
- `/user-data`
- IMDSv2 token endpoint `/latest/api/token`
- header `X-aws-ec2-metadata-token-ttl-seconds`
- header `X-aws-ec2-metadata-token`
- ECS/EKS task credentials `http://169.254.170.2$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`