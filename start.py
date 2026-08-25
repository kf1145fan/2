#!/usr/bin/env python3
# 本地一键启动脚本：确保 OpenList / mefrpc 二进制存在（缺失则自动下载），
# 然后在本机拉起管理面板（默认 http://localhost:7860）。
#
# 用法：
#   pip install -r requirements.txt
#   python3 start.py
#
# 环境变量（可选）：
#   OPENLIST_VERSION  指定 OpenList 版本，如 v4.2.5，或 latest（默认 v4.2.5）
#   PANEL_PORT        面板端口（默认 7860）
#   DATA_DIR          数据目录（默认 <项目>/data）
#   DISABLE_GUI       设为 1 可在没有桌面环境的机器上跳过 Firefox/VNC
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(ROOT, "bin")
OPENLIST_BIN = os.path.join(BIN, "openlist")
MEFRPC_BIN = os.path.join(BIN, "mefrpc")
ARCH = "amd64"
OPENLIST_VERSION = os.environ.get("OPENLIST_VERSION", "v4.2.5")


def _log(msg):
    print(f"[start.py] {msg}", flush=True)


def download(url, dest):
    _log(f"下载 {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    urllib.request.urlretrieve(url, dest)


def resolve_openlist_tag():
    if OPENLIST_VERSION != "latest":
        return OPENLIST_VERSION
    with urllib.request.urlopen(
        "https://api.github.com/repos/OpenListTeam/OpenList/releases/latest", timeout=30
    ) as r:
        return json.load(r)["tag_name"]


def ensure_openlist():
    if os.path.exists(OPENLIST_BIN) and os.path.getsize(OPENLIST_BIN) > 1_000_000:
        _log("OpenList 已存在，跳过下载")
        return
    tag = resolve_openlist_tag()
    url = f"https://github.com/OpenListTeam/OpenList/releases/download/{tag}/openlist-linux-{ARCH}.tar.gz"
    tgz = os.path.join(BIN, "openlist.tar.gz")
    download(url, tgz)
    with tarfile.open(tgz) as t:
        for m in t.getmembers():
            if m.name == "openlist":
                m.name = "openlist"
                t.extract(m, BIN)
                break
    os.chmod(OPENLIST_BIN, 0o755)
    os.remove(tgz)
    _log(f"OpenList 已就绪（{tag}）")


def ensure_mefrpc():
    if os.path.exists(MEFRPC_BIN) and os.path.getsize(MEFRPC_BIN) > 1_000_000:
        _log("mefrpc 已存在，跳过下载")
        return
    if shutil.which("docker"):
        _log("尝试从 menetx/frpc 镜像提取 mefrpc ...")
        subprocess.run(["docker", "pull", "menetx/frpc:latest"], check=True)
        cid = subprocess.run(
            ["docker", "create", "--name", "frpc_extract_tmp", "menetx/frpc:latest"],
            capture_output=True, text=True,
        ).stdout.strip()
        try:
            subprocess.run(["docker", "cp", f"{cid}:/mefrpc", MEFRPC_BIN], check=True)
        finally:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
        os.chmod(MEFRPC_BIN, 0o755)
        _log("mefrpc 已提取")
        return
    sys.exit(
        "未找到 bin/mefrpc 且本机没有 docker。\n"
        "请手动把 ME Frp 的 mefrpc 二进制放到 bin/mefrpc 后再运行。\n"
        "（ME Frp 官网 https://www.mefrp.com 的「下载」页面可获取对应系统版本）"
    )


def main():
    ensure_openlist()
    ensure_mefrpc()

    env = dict(os.environ)
    env.setdefault("DISABLE_GUI", "1")  # 本地无桌面环境时跳过 Firefox/VNC
    env.setdefault("PANEL_PORT", "7860")
    env.setdefault("DATA_DIR", os.path.join(ROOT, "data"))
    env.setdefault("OPENLIST_ADMIN_PASSWORD", "admin123")

    main_py = os.path.join(ROOT, "app", "main.py")
    _log(f"启动管理面板 → http://localhost:{env['PANEL_PORT']}  (Ctrl+C 退出)")
    os.execve(sys.executable, [sys.executable, main_py], env)


if __name__ == "__main__":
    main()
