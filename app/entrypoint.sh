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

# 2. 停掉，替换数据
kill "${OL_PID}" 2>/dev/null; wait "${OL_PID}" 2>/dev/null
echo "[entrypoint] 替换 data.db + config.json…"
cp -f /app/openlist-init/data.db /app/openlist-init/config.json "${OPENLIST_DATA}/" 2>/dev/null || true

# 3. 强制清空 site_url（反代后不能写死域名，否则 cookie 丢失）
CFG="${OPENLIST_DATA}/config.json"
if [ -f "${CFG}" ]; then
    python3 -c "
import json, sys
try:
    c = json.load(open('${CFG}'))
    c.setdefault('scheme', {})['site_url'] = ''
    c['scheme']['force_https'] = False
    json.dump(c, open('${CFG}', 'w'), indent=2, ensure_ascii=False)
except Exception as e:
    print('warn:', e, file=sys.stderr)
" 2>&1 && echo "[entrypoint] site_url 已清空"
fi

# 4. 正式启动
exec python3 /app/main.py
