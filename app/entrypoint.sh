#!/bin/bash
set -e

OPENLIST_DIR="/root/Desktop/openlist"
mkdir -p "${OPENLIST_DIR}/data" /root/Desktop/storage 2>/dev/null || true

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

# 2. 彻底杀掉
echo "[entrypoint] 停止 openlist (pid=${OL_PID})…"
kill -9 "${OL_PID}" 2>/dev/null || true
pkill -9 -f "openlist server" 2>/dev/null || true
sleep 1

# 3. 替换 data.db
mkdir -p "${OPENLIST_DIR}/data"
echo "[entrypoint] 替换前: $(ls -la ${OPENLIST_DIR}/data/data.db 2>&1)"
cp -f /app/openlist-init/data.db "${OPENLIST_DIR}/data/data.db"
echo "[entrypoint] 替换后: $(ls -la ${OPENLIST_DIR}/data/data.db)"
md5sum /app/openlist-init/data.db "${OPENLIST_DIR}/data/data.db"

# 4. 正式启动
exec python3 /app/main.py
