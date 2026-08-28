#!/bin/bash
set -e

OPENLIST_DIR="/root/Desktop/openlist"
mkdir -p "${OPENLIST_DIR}" /root/Desktop/storage 2>/dev/null || true

# 复制 openlist 到固定目录
cp -f /app/openlist "${OPENLIST_DIR}/openlist"
chmod +x "${OPENLIST_DIR}/openlist"

# 1. 启动一次初始化
cd "${OPENLIST_DIR}"
echo "[entrypoint] 启动 openlist 初始化…"
./openlist server &
OL_PID=$!
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:5244/ping" >/dev/null 2>&1; then
        echo "[entrypoint] openlist 已就绪"
        break
    fi
    sleep 0.5
done

# 2. 停掉
kill "${OL_PID}" 2>/dev/null; wait "${OL_PID}" 2>/dev/null

# 3. 替换 data.db（用镜像内自带的那份）
echo "[entrypoint] 替换 data.db…"
ls -la /app/openlist-init/ 2>/dev/null
cp -f /app/openlist-init/data.db "${OPENLIST_DIR}/data/data.db"
echo "[entrypoint] 替换完成，校验："
md5sum "${OPENLIST_DIR}/data/data.db" /app/openlist-init/data.db

# 4. 正式启动
exec python3 /app/main.py
