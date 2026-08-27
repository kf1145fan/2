#!/bin/bash
DATA_DIR="${DATA_DIR:-/root/Desktop/oplist-data}"
mkdir -p "${DATA_DIR}/openlist" "${DATA_DIR}/logs" 2>/dev/null || true

# 首次启动：将镜像内初始数据拷贝到 OPENLIST_DATA 目录
OPENLIST_DATA="${OPENLIST_DATA:-/www/1/data}"
if [ ! -f "${OPENLIST_DATA}/data.db" ] && [ -f /app/openlist-init/data.db ]; then
    mkdir -p "${OPENLIST_DATA}" 2>/dev/null || true
    cp /app/openlist-init/data.db /app/openlist-init/config.json "${OPENLIST_DATA}/" 2>/dev/null || true
    echo "[entrypoint] 初始化 openlist 数据 → ${OPENLIST_DATA}"
fi

exec python3 /app/main.py
