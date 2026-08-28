# nurse-station 主应用操作手册

本目录是护士站主应用的发布包。架构为：宿主机 Nginx 提供 `index.html` 并代理 API；Docker 容器运行 Flask/Gunicorn；MySQL 使用宿主机已有服务。

`his-sync/` 是单独的手工 HIS 医生同步任务，操作命令见 `his-sync/README.md`。

## 发布包文件

```text
clinical-workstation-release/
├── index.html             # Nginx 前端入口
├── nginx.conf             # 宿主机 Nginx 配置
├── backend/               # 主应用 Python 源码
├── Dockerfile             # 主应用镜像构建文件
├── compose.host.yml       # CentOS 宿主机启动文件
├── app.env.example        # 可提交的环境变量模板
├── app.env                # 运行环境变量；不得打入镜像或提交
└── his-sync/              # 单独的 HIS 手工同步镜像
```

## 1. Windows 本地构建主应用镜像

```powershell
Set-Location "D:\WorkSpace\Nurse_station\clinical-workstation-release"

docker build --platform linux/amd64 -t nurse-station:0.1.0 .
```

确认镜像：

```powershell
docker image ls nurse-station
```

导出镜像：

```powershell
docker save -o .\nurse-station_0.1.0.tar nurse-station:0.1.0
```

## 2. 上传到 CentOS 宿主机

将以下文件上传到 `/opt/nurse-station/deploy/`：

```text
nurse-station_0.1.0.tar
compose.host.yml
app.env
```

将前端文件上传为：

```text
/opt/nurse-station/frontend/index.html
```

将 Nginx 配置上传为：

```text
/etc/nginx/conf.d/nurse-station.conf
```

### 环境变量文件

Git 中只提交 `app.env.example`，其中不含密码、HIS 地址、HIS 标识、令牌或密钥。部署时在 Windows 或宿主机复制模板并填写真实配置：

```bash
cp app.env.example app.env
```

`app.env` 中的 `DB_HOST` 必须为 `127.0.0.1`；文件包含敏感配置，宿主机建议设置为仅 root 可读：

```bash
chmod 600 /opt/nurse-station/deploy/app.env
```

不要执行 `git add -f app.env`，也不要将密码、HIS 地址、MESKEY、Token 或 `SECRET_KEY` 写入 README、Dockerfile、Compose 文件和源码。

## 3. 加载并启动主应用

```bash
cd /opt/nurse-station/deploy

docker load -i nurse-station_0.1.0.tar

mkdir -p /opt/nurse-station/logs

docker compose -f compose.host.yml up -d --force-recreate
```

主应用容器名称为 `nurse-station`。容器采用宿主机网络，Gunicorn 仅监听 `127.0.0.1:5000`；不要在 Compose 中添加 `ports:`。

## 4. Nginx 操作

首次部署或更新配置后：

```bash
nginx -t
systemctl reload nginx
```

内网浏览器访问：

```text
http://172.27.107.40/
```

页面请求 `/api/v1/...`，由 Nginx 转发到 `127.0.0.1:5000` 的容器应用。

## 5. 日常运维命令

查看状态：

```bash
docker ps --filter "name=nurse-station"
docker compose -f /opt/nurse-station/deploy/compose.host.yml ps
```

查看容器日志：

```bash
docker logs -f nurse-station
docker logs --tail 200 nurse-station
```

查看应用与 Nginx 日志：

```bash
tail -f /opt/nurse-station/logs/app.log
tail -f /opt/nurse-station/logs/gunicorn-error.log
tail -f /var/log/nginx/nurse-station-access.log
tail -f /var/log/nginx/nurse-station-error.log
```

重启主应用：

```bash
docker compose -f /opt/nurse-station/deploy/compose.host.yml restart
```

停止主应用（不会停止宿主机 MySQL 或 Nginx）：

```bash
docker compose -f /opt/nurse-station/deploy/compose.host.yml down
```

确认容器时区：

```bash
docker exec nurse-station date
```

## 6. 更新版本

在 Windows 使用新版本号构建、导出，例如 `0.1.1`；在 `compose.host.yml` 中同步更新镜像标签后上传宿主机。然后执行：

```bash
cd /opt/nurse-station/deploy

docker load -i nurse-station_0.1.1.tar
docker compose -f compose.host.yml up -d --force-recreate
```

旧镜像在确认新版本稳定前不要删除，以便回退。

## 注意事项

- 不执行旧的 `backend/deploy.sh` 或 `backend/nurse-station.service`；它们属于非 Docker 的旧部署方案。
- 不关闭 SELinux 或 firewalld。Nginx 无法代理本地应用时，使用 `setsebool -P httpd_can_network_connect 1`。
- MySQL 仅监听 `127.0.0.1:3306`，不对内网开放 3306。
- HIS 医生同步会更新并可能删除本地医生数据；仅通过 `his-sync` 的单独手工流程执行。
