#!/bin/bash
DATA_DIR="${DATA_DIR:-/root/Desktop/oplist-data}"
mkdir -p "${DATA_DIR}/openlist" "${DATA_DIR}/logs" /root/Desktop/storage 2>/dev/null || true

# 每次启动：用镜像内初始数据覆盖 OPENLIST_DATA（确保云端数据一致）
OPENLIST_DATA="${OPENLIST_DATA:-/www/1/data}"
if [ -f /app/openlist-init/data.db ]; then
    mkdir -p "${OPENLIST_DATA}" 2>/dev/null || true
    cp -f /app/openlist-init/data.db /app/openlist-init/config.json "${OPENLIST_DATA}/" 2>/dev/null || true
    echo "[entrypoint] 已写入 openlist 数据 → ${OPENLIST_DATA}"
fi

exec python3 /app/main.py
