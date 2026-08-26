#!/bin/bash
mkdir -p "${DATA_DIR:-/root/Desktop/oplist-data}/openlist" "${DATA_DIR:-/root/Desktop/oplist-data}/logs" /www/1/data 2>/dev/null || true
exec python3 /app/main.py
