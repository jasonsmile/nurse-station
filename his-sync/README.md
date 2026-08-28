# HIS 医生同步镜像

该镜像为手工一次性任务，不常驻运行。运行时必须通过 `--env-file` 传入部署目录的 `app.env`，并使用 `--network host` 访问宿主机 MySQL 与内网 HIS。

同步会更新本地 `doctors` 数据，并删除本次 HIS 返回结果中不存在的本地医生。仅在 HIS 报文与数据库字段均确认后执行。

## 1. Windows 本地构建镜像

在发布目录执行：

```powershell
Set-Location "D:\WorkSpace\Nurse_station\clinical-workstation-release"

docker build --platform linux/amd64 -t nurse-station-sync:0.1.0 .\his-sync
```

确认镜像：

```powershell
docker image ls nurse-station-sync
```

## 2. 导出镜像文件

```powershell
docker save -o .\nurse-station-sync_0.1.0.tar nurse-station-sync:0.1.0
```

将生成的 `nurse-station-sync_0.1.0.tar` 上传至 CentOS：

```text
/opt/nurse-station/deploy/nurse-station-sync_0.1.0.tar
```

## 3. CentOS 宿主机加载镜像

```bash
cd /opt/nurse-station/deploy

docker load -i nurse-station-sync_0.1.0.tar

docker image ls nurse-station-sync
```

## 4. 手工执行医生同步

确认 `app.env` 位于 `/opt/nurse-station/deploy/app.env` 后执行：

```bash
docker run --rm \
  --name nurse-station-sync \
  --network host \
  --env-file /opt/nurse-station/deploy/app.env \
  nurse-station-sync:0.1.0
```

该命令等同于在容器内执行：

```bash
python /app/init_sync.py
```

脚本完成后容器会因 `--rm` 自动删除；同步过程和结果直接输出在当前终端。

## 执行前检查

- HIS G0076 接口必须能返回正确 JSON；当前的 `Error reading JObject` 未解决前不要执行。
- 数据库 `doctors` 表需包含同步代码使用的 `sort_order` 与 `sync_status` 字段。
- 该同步会删除本次 HIS 未返回的本地医生记录，应先在测试数据或经确认的正式数据上执行。
