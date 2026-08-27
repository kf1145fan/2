#!/bin/bash
DATA_DIR="${DATA_DIR:-/root/Desktop/oplist-data}"
mkdir -p "${DATA_DIR}/openlist" "${DATA_DIR}/logs" /root/Desktop/storage 2>/dev/null || true

OPENLIST_DATA="${OPENLIST_DATA:-/www/1/data}"
OPENLIST_BIN="${OPENLIST_BIN:-/app/openlist}"
OPENLIST_PORT="${OPENLIST_PORT:-5244}"

# 1. 先启动一次 openlist，让它初始化数据库/目录
mkdir -p "${OPENLIST_DATA}" 2>/dev/null || true
echo "[entrypoint] 启动 openlist 初始化…"
"${OPENLIST_BIN}" server --data "${OPENLIST_DATA}" &
OL_PID=$!
# 等待就绪（最多 15 秒）
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${OPENLIST_PORT}/ping" >/dev/null 2>&1; then
        echo "[entrypoint] openlist 已就绪"
        break
    fi
    sleep 0.5
done

# 2. 停掉，替换 data.db
kill "${OL_PID}" 2>/dev/null; wait "${OL_PID}" 2>/dev/null
echo "[entrypoint] 替换 data.db…"
cp -f /app/openlist-init/data.db /app/openlist-init/config.json "${OPENLIST_DATA}/" 2>/dev/null || true

# 3. 交给 main.py 正式启动（会再拉起 openlist）
exec python3 /app/main.py
