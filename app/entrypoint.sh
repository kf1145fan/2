#!/bin/bash
DATA_DIR="${DATA_DIR:-/root/Desktop/oplist-data}"
mkdir -p "${DATA_DIR}/openlist" "${DATA_DIR}/logs" /root/Desktop/storage 2>/dev/null || true

OPENLIST_DATA="${OPENLIST_DATA:-/www/1/data}"

# 复制 openlist 到固定路径，确保可执行
cp -f /app/openlist /usr/local/bin/openlist
chmod +x /usr/local/bin/openlist
mkdir -p "${OPENLIST_DATA}" 2>/dev/null || true

# 1. 先启动一次 openlist 初始化
echo "[entrypoint] 启动 openlist 初始化…"
/usr/local/bin/openlist server --data "${OPENLIST_DATA}" &
OL_PID=$!
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:5244/ping" >/dev/null 2>&1; then
        echo "[entrypoint] openlist 已就绪"
        break
    fi
    sleep 0.5
done

# 2. 停掉，替换 data.db
kill "${OL_PID}" 2>/dev/null; wait "${OL_PID}" 2>/dev/null
echo "[entrypoint] 替换 data.db…"
cp -f /app/openlist-init/data.db /app/openlist-init/config.json "${OPENLIST_DATA}/" 2>/dev/null || true

# 3. 正式启动
exec python3 /app/main.py
