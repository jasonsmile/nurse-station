# 护士工作站内网域名访问配置记录

## 当前方案

系统仅供指定护士站电脑在院内网络使用，未部署独立 DNS 服务。通过 Windows `hosts` 文件将内部名称解析到护士站服务器。

| 项目 | 当前值 |
| --- | --- |
| 内部访问名称 | `nurse-station.hospital.internal` |
| 服务器 IP | `172.27.107.40` |
| 访问地址 | `http://nurse-station.hospital.internal/` |
| 适用范围 | 已配置 hosts 的指定护士站电脑 |
| 协议 | HTTP（内网） |

## 护士站电脑配置

以管理员权限编辑下列文件：

```text
C:\Windows\System32\drivers\etc\hosts
```

在文件末尾增加：

```text
172.27.107.40 nurse-station.hospital.internal
```

保存后执行：

```bat
ipconfig /flushdns
ping nurse-station.hospital.internal
```

解析结果应为 `172.27.107.40`，随后使用上述访问地址打开系统。

> Windows 7 若目录中没有 `hosts` 文件，可用管理员身份新建名为 `hosts` 的无扩展名文件；保存类型选择“所有文件”，避免生成 `hosts.txt`。

## 服务器 Nginx 配置

护士站的 Nginx 虚拟主机应同时接受域名和原 IP，便于切换期间保留既有访问方式：

```nginx
server {
    listen 80 default_server;
    server_name nurse-station.hospital.internal 172.27.107.40;

    root /opt/nurse-station/frontend;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
    }
}
```

更新配置后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 前端 API 要求

前端不得把 API 固定为 `http://localhost:5000`。应使用同源相对路径（例如 `/api/v1/...`），以保证页面经内部名称访问时，API 请求仍由同一台 Nginx 转发到后端。

## 维护与后续

- 新增护士站电脑时，按“护士站电脑配置”添加相同 hosts 映射。
- 服务器 IP 变更时，必须同步更新每台已配置终端的 hosts 文件。
- 终端数量增加或变动频繁时，迁移到 DHCP 下发的内部 DNS。
- 后续如需 HTTPS，应申请医院内部 CA 证书；不要使用 `.local` 后缀，以避免与 mDNS 冲突。
