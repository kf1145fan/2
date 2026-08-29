FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3-minimal \
        python3-pip \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        firefox-esr \
        fluxbox \
        fonts-wqy-microhei \
        xauth \
        dbus-x11 \
        libegl1 \
        libgl1 \
        procps \
        tini \
        curl \
    && pip3 install --break-system-packages --no-cache-dir aiohttp \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /root/.cache /usr/share/man/* /usr/share/doc/*

WORKDIR /app

COPY app/ /app/
COPY bin/mefrpc /app/mefrpc
COPY bin/openlist /app/openlist
COPY bin/frpc /app/frpc
COPY data/openlist-init /app/openlist-init
RUN chmod +x /app/mefrpc /app/openlist /app/frpc /app/entrypoint.sh

ENV PANEL_PORT=7860 \
    OPENLIST_PORT=5244 \
    OPENLIST_DATA=/root/Desktop/openlist \
    DATA_DIR=/mnt/workspace/oplist-data \
    FIREFOX_URL=about:blank

EXPOSE 7860 5244

ENTRYPOINT ["/usr/bin/tini", "--", "/bin/bash", "/app/entrypoint.sh"]
