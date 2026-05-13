---
name: docker-deploy
description: 使用 Docker Compose 将应用部署到服务器。Use when user asks to 部署应用、docker部署、启动容器、上线服务、发布新版本。
---

# Docker Deploy

使用 Docker Compose 完成应用的构建、部署和验证。

## 前置检查

1. 确认 Dockerfile 存在且语法正确
2. 确认 docker-compose.yml 配置正确，环境变量已注入
3. 确认目标服务器可访问（SSH 或 CI/CD 环境）

## 部署流程

```bash
# 1. 构建镜像
docker-compose build --no-cache

# 2. 平滑停止旧版本
docker-compose down

# 3. 启动新版本（后台运行）
docker-compose up -d

# 4. 验证运行状态
docker-compose ps
docker-compose logs --tail=50
```

## 验收标准

- `docker-compose ps` 所有服务状态为 `Up`
- 日志中无 ERROR 级别输出
- 健康检查接口（如 /health）返回 200

## 回滚方案

```bash
docker-compose down
git checkout HEAD~1
docker-compose up -d
```

## 注意事项

- 生产环境部署前必须在 staging 验证
- 部署前备份数据库
- 保留最近 3 个版本的镜像以便快速回滚
