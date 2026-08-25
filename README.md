---
title: OpenList × ME-Frp 一体化控制台
---

# OpenList × ME-Frp × Firefox 一体化容器

单容器集成三个服务，统一从 **7860** 端口的网页控制台管理，专为魔搭创空间（Docker 类型）制作：

| 路径 | 说明 |
|---|---|
| `/` | 管理面板：服务状态 / 日志 / 启停控制 / mefrpc 命令配置 |
| `/openlist/…` | OpenList 反向代理（内部 5244），根路径透传同样可用 |
| `/firefox/vnc_lite.html?path=firefox%2Fwebsockify` | 容器内网页版 Firefox（noVNC），可用于给空间"保温" |
| `/_ctrl/firefox_console` | Firefox 全屏操作页（备用入口） |

内置组件：

- **OpenList v4.2.5 (lite)** —— AList 社区分支，网盘列表程序
- **mefrpc v0.67.1** —— ME Frp（幻缘映射）官方客户端，提取自 `menetx/frpc` 镜像
- **Firefox ESR + Xvfb + x11vnc + noVNC** —— 无头浏览器，网页直接操作

## 目录结构

```
├── Dockerfile            # 镜像构建入口（魔搭自动识别）
├── ms_deploy.json        # 魔搭部署配置（docker 类型 / 7860 端口 / 免费 CPU 资源）
├── bin/
│   ├── openlist          # OpenList linux-amd64 二进制
│   └── mefrpc            # ME Frp 客户端二进制
└── app/
    ├── entrypoint.sh     # 入口脚本
    ├── main.py           # 控制台后端（进程守护 + 反向代理 + WebSocket 桥接）
    └── static/           # 前端页面
```

## 一、部署到魔搭创空间

> ⚠️ **看不到 Docker 选项？** Docker 类型仅对**完成实名认证**的账号开放（需先绑定阿里云账号并做云账号实名认证；Gradio/Streamlit 不需要实名）。若创建时 SDK 类型里没有 Docker，先去账号设置做完实名，刷新页面就会出现。
>
> 上传包含 `Dockerfile` + `ms_deploy.json` 的**整个项目文件夹**后，平台会**自动识别为 Docker 类型**，无需手动选框架。

### 方式 A：网页上传（最简单）

1. 打开 [modelscope.cn/studios](https://modelscope.cn/studios) → 点右上角「**我要创建**」
2. 填写：名称、简介、可见性（先私有便于调试）
3. **SDK 类型选「Docker」**（看不到就先做实名，见上方提示）；资源配置选**免费 CPU（2v CPU/16G）**
4. 进入「空间文件」页，**上传整个项目文件夹**（保持 `bin/`、`app/`、`Dockerfile`、`ms_deploy.json` 的目录结构）
5. 「部署设置」里确认框架为 Docker、资源为免费 CPU，点「确认并部署」
6. 首次构建约 3~5 分钟，状态变「运行中」即可打开

### 方式 B：Git 推送

1. 创建创空间（同上，SDK 选 Docker）后，进入管理页「通过 Git 上传」拿到仓库地址
2. 把本项目所有文件复制进去并保持目录结构，提交推送：

```bash
git clone https://www.modelscope.cn/<你的用户名>/<空间名>.git
cd <空间名>
cp -r /path/to/oplist-space/* .
git add . && git commit -m "init: openlist + mefrpc console"
git push
```

推送后魔搭自动构建并启动。

### 访问

构建完成后打开空间页面即可看到控制台。对外地址形如：
`https://<用户名>-<空间名>.ms.show/`

## 二、使用指南

1. **ME-Frp**：在 [mefrp.com](https://www.mefrp.com) 隧道管理里「生成启动配置」，把整条命令粘进控制台输入框，点「启动」：
   ```
   ./mefrpc -t 1937c3dc1e6e767536c92fea786b0a48 -p 174053
   ```
   勾选「开机自启+崩溃自动重连」后，空间重启会自动恢复隧道。
2. **OpenList**：点卡片上的 `/openlist/` 进入；管理员账号 `admin`，初始密码 `admin123`
   （可在魔搭空间的「环境变量」里设置 `OPENLIST_ADMIN_PASSWORD` 修改）。
3. **Firefox**：点「打开 Firefox 窗口」在浏览器里操作容器内浏览器；修改 URL 后点「应用 URL 并重启」可让它常驻打开某个页面。

## 三、数据持久化

所有可变数据（OpenList 配置数据库、mefrpc 命令记录、日志）默认写入官方推荐的持久化目录：

```
/mnt/workspace/oplist-data/
```

该目录在容器重启后保留。若不可写（部分资源形态未挂载），会自动回退到 `/root/Desktop/oplist-data` 或容器内 `/app/data`（重启即丢）。**重要配置请自行备份**（控制台「系统」日志或状态接口可见当前实际数据目录）。

## 四、常见问题

- **想用全功能版 OpenList？** lite 版精简了部分小众网盘驱动。去 [Releases](https://github.com/OpenListTeam/OpenList/releases) 下载 `openlist-linux-amd64.tar.gz`，替换 `bin/openlist` 后重新推送即可。
- **端口要求**：Docker 类型创空间只能暴露 7860，且 8080 被平台进程占用，请勿改动 `PANEL_PORT`。
- **隧道不通？** 先看控制台 mefrpc 日志；ME Frp 节点与魔搭机房之间的连通性由服务商决定。
- **安全提示**：本控制台未设密码，公开空间时任何人都能看到你的 token 与隧道状态，建议空间设为私有，或自行给 `main.py` 加鉴权。

## 五、本地运行（可选）

```bash
docker build -t olist-console .
docker run -d -p 7860:7860 --name olist olist-console
# 打开 http://127.0.0.1:7860
```

无 GUI 依赖的调试模式：`DISABLE_GUI=1 python3 app/main.py`（跳过 Firefox/VNC 栈）。

## 致谢

- [OpenList](https://github.com/OpenListTeam/OpenList) (AGPL-3.0)
- [ME Frp](https://www.mefrp.com) / menetx/frpc
- [noVNC](https://github.com/novnc/noVNC) / [fatedier/frp](https://github.com/fatedier/frp)
