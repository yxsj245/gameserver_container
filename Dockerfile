FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    STEAM_USER=steam \
    STEAM_HOME=/home/steam \
    STEAMCMD_DIR=/home/steam/steamcmd \
    GAMES_DIR=/home/steam/games

# 将apt源改为中国镜像源（阿里云）
# 移除旧的、传统的sources.list文件，并使用DEB822格式创建新的源配置
# 这种新格式在Debian 12 (Bookworm)中具有更高优先级
RUN rm -f /etc/apt/sources.list && \
    printf "Types: deb\nURIs: http://mirrors.aliyun.com/debian/\nSuites: bookworm\nComponents: main contrib non-free non-free-firmware\n" > /etc/apt/sources.list.d/debian.sources && \
    printf "\nTypes: deb\nURIs: http://mirrors.aliyun.com/debian/\nSuites: bookworm-updates\nComponents: main contrib non-free non-free-firmware\n" >> /etc/apt/sources.list.d/debian.sources && \
    printf "\nTypes: deb\nURIs: http://mirrors.aliyun.com/debian-security\nSuites: bookworm-security\nComponents: main contrib non-free non-free-firmware\n" >> /etc/apt/sources.list.d/debian.sources


# 不使用deadsnakes PPA，直接使用Debian官方Python包

# 安装SteamCMD和常见依赖（包括32位库）
RUN apt-get update && apt-get upgrade -y \
    && dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        aria2 \
        ca-certificates \
        locales \
        wget \
        curl \
        jq \
        docker.io \
        xdg-user-dirs \
        libncurses5:i386 \
        libbz2-1.0:i386 \
        libicu72:i386 \
        libxml2:i386 \
        libstdc++6:i386 \
        lib32gcc-s1 \
        libc6-i386 \
        lib32stdc++6 \
        libcurl4-gnutls-dev:i386 \
        libcurl4-gnutls-dev \
        libgl1-mesa-glx:i386 \
        libssl3:i386 \
        libopenal1:i386 \
        libtinfo6:i386 \
        libtcmalloc-minimal4:i386 \
        # .NET和Mono相关依赖（ECO服务器等需要）
        libgdiplus \
        libc6-dev \
        libasound2 \
        libpulse0 \
        pulseaudio \
        libpulse-dev \
        libnss3 \
        libgconf-2-4 \
        libcap2 \
        libatk1.0-0 \
        libcairo2 \
        libcups2 \
        libgtk-3-0 \
        libgdk-pixbuf2.0-0 \
        libpango-1.0-0 \
        libx11-6 \
        libxt6 \
        # Unity游戏服务端额外依赖（7日杀等）
        libsdl2-2.0-0:i386 \
        libsdl2-2.0-0 \
        libpulse0:i386 \
        libfontconfig1:i386 \
        libfontconfig1 \
        libudev1:i386 \
        libudev1 \
        libpugixml1v5 \
        libvulkan1 \
        libvulkan1:i386 \
        libgconf-2-4:i386 \
        # 额外的Unity引擎依赖（特别针对7日杀）
        libatk1.0-0:i386 \
        libxcomposite1 \
        libxcomposite1:i386 \
        libxcursor1 \
        libxcursor1:i386 \
        libxrandr2 \
        libxrandr2:i386 \
        libxss1 \
        libxss1:i386 \
        libxtst6 \
        libxtst6:i386 \
        libxi6 \
        libxi6:i386 \
        libxkbfile1 \
        libxkbfile1:i386 \
        libasound2:i386 \
        libgtk-3-0:i386 \
        libdbus-1-3 \
        libdbus-1-3:i386 \
        # ARK: Survival Evolved（方舟生存进化）服务器额外依赖
        libelf1 \
        libelf1:i386 \
        libatomic1 \
        libatomic1:i386 \
        nano \
        net-tools \
        netcat-openbsd \
        procps \
        python3 \
        python3-dev \
        python3-pip \
        tar \
        unzip \
        bzip2 \
        xz-utils \
        zlib1g:i386 \
        fonts-wqy-zenhei \
        fonts-wqy-microhei \
        libc6 \
        libc6:i386 \
    && rm -rf /var/lib/apt/lists/*

# 安装Node.js (用于运行Web界面)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get update && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 配置npm使用淘宝源
RUN npm config set registry https://registry.npmmirror.com

# 设置 locales
RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && sed -i -e 's/# zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen
ENV LANG=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:zh \
    LC_ALL=zh_CN.UTF-8

# 创建steam用户
RUN useradd -m -s /bin/bash ${STEAM_USER} \
    && mkdir -p ${STEAMCMD_DIR} ${GAMES_DIR} \
    && chown -R ${STEAM_USER}:${STEAM_USER} ${STEAM_HOME}

# 配置pip使用国内源 (这里放在创建用户之后)
RUN mkdir -p /root/.pip /home/steam/.pip \
    && echo '[global]\n\
index-url = https://pypi.tuna.tsinghua.edu.cn/simple\n\
trusted-host = pypi.tuna.tsinghua.edu.cn' > /root/.pip/pip.conf \
    && cp /root/.pip/pip.conf /home/steam/.pip/pip.conf \
    && chown -R ${STEAM_USER}:${STEAM_USER} /home/steam/.pip


# 切换到root用户安装SteamCMD（确保有足够权限）
USER root
WORKDIR /home/steam

# 下载并安装SteamCMD
RUN mkdir -p ${STEAMCMD_DIR} \
    && cd ${STEAMCMD_DIR} \
    && (if curl -s --connect-timeout 3 http://192.168.10.43:7890 >/dev/null 2>&1 || wget -q --timeout=3 --tries=1 http://192.168.10.23:7890 -O /dev/null >/dev/null 2>&1; then \
          echo "代理服务器可用，使用代理下载和初始化"; \
          export http_proxy=http://192.168.10.23:7890; \
          export https_proxy=http://192.168.10.23:7890; \
          wget -t 5 --retry-connrefused --waitretry=1 --read-timeout=20 --timeout=15 -O steamcmd_linux.tar.gz https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
          || wget -t 5 --retry-connrefused --waitretry=1 --read-timeout=20 --timeout=15 -O steamcmd_linux.tar.gz https://media.steampowered.com/installer/steamcmd_linux.tar.gz; \
          tar -xzvf steamcmd_linux.tar.gz; \
          rm steamcmd_linux.tar.gz; \
          chown -R ${STEAM_USER}:${STEAM_USER} ${STEAMCMD_DIR}; \
          chmod +x ${STEAMCMD_DIR}/steamcmd.sh; \
          su - ${STEAM_USER} -c "export http_proxy=http://192.168.10.23:7890 && export https_proxy=http://192.168.10.23:7890 && cd ${STEAMCMD_DIR} && ./steamcmd.sh +quit"; \
          unset http_proxy https_proxy; \
        else \
          echo "代理服务器不可用，使用直接连接"; \
          wget -t 5 --retry-connrefused --waitretry=1 --read-timeout=20 --timeout=15 -O steamcmd_linux.tar.gz https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz \
          || wget -t 5 --retry-connrefused --waitretry=1 --read-timeout=20 --timeout=15 -O steamcmd_linux.tar.gz https://media.steampowered.com/installer/steamcmd_linux.tar.gz; \
          tar -xzvf steamcmd_linux.tar.gz; \
          rm steamcmd_linux.tar.gz; \
          chown -R ${STEAM_USER}:${STEAM_USER} ${STEAMCMD_DIR}; \
          chmod +x ${STEAMCMD_DIR}/steamcmd.sh; \
          su - ${STEAM_USER} -c "cd ${STEAMCMD_DIR} && ./steamcmd.sh +quit"; \
        fi) \
    # 创建steamclient.so符号链接
    && mkdir -p ${STEAM_HOME}/.steam/sdk32 ${STEAM_HOME}/.steam/sdk64 \
    && ln -sf ${STEAMCMD_DIR}/linux32/steamclient.so ${STEAM_HOME}/.steam/sdk32/steamclient.so \
    && ln -sf ${STEAMCMD_DIR}/linux64/steamclient.so ${STEAM_HOME}/.steam/sdk64/steamclient.so \
    # 创建额外的游戏常用目录链接    
    && mkdir -p ${STEAM_HOME}/.steam/sdk32/steamclient.so.dbg.sig ${STEAM_HOME}/.steam/sdk64/steamclient.so.dbg.sig \
    && mkdir -p ${STEAM_HOME}/.steam/steam \
    && ln -sf ${STEAMCMD_DIR}/linux32 ${STEAM_HOME}/.steam/steam/linux32 \
    && ln -sf ${STEAMCMD_DIR}/linux64 ${STEAM_HOME}/.steam/steam/linux64 \
    && ln -sf ${STEAMCMD_DIR}/steamcmd ${STEAM_HOME}/.steam/steam/steamcmd \
    && chown -R ${STEAM_USER}:${STEAM_USER} ${STEAM_HOME}/.steam


# 复制前端package.json并安装依赖
COPY --chown=steam:steam ./app/package.json ./app/package-lock.json* /home/steam/app/
WORKDIR /home/steam/app
RUN npm install --legacy-peer-deps --no-fund && \
    npm install react-router-dom @types/react @types/react-dom react-dom @monaco-editor/react monaco-editor js-cookie @types/js-cookie

# pip已经通过python3-pip包安装，无需额外配置

# 安装后端依赖
RUN python3 -m pip install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple flask flask-cors gunicorn requests psutil PyJWT rarfile zstandard docker configobj pyhocon ruamel.yaml toml

# 添加启动脚本
RUN echo '#!/bin/bash\n\
echo "启动游戏服务器部署Web界面..."\n\
echo "请访问 http://[服务器IP]:5000 使用Web界面"\n\
\n\
# 确保start_web.sh有执行权限\n\
chmod +x /home/steam/server/start_web.sh\n\
\n\
# 启动API服务器\n\
cd /home/steam/server\n\
./start_web.sh\n\
' > /home/steam/start_web.sh \
&& chmod +x /home/steam/start_web.sh

# 创建目录用于挂载游戏数据
VOLUME ["${GAMES_DIR}"]

# 暴露API服务端口 - 对外网开放
EXPOSE 5000
# 暴露常用游戏端口
EXPOSE 27015-27020/tcp
EXPOSE 27015-27020/udp

# 复制FRP文件
COPY --chown=steam:steam ./frp/LoCyanFrp /home/steam/FRP/LoCyanFrp
COPY --chown=steam:steam ./frp/frpc /home/steam/FRP/frpc
COPY --chown=steam:steam ./frp/mefrp /home/steam/FRP/mefrp
COPY --chown=steam:steam ./frp/Sakura /home/steam/FRP/Sakura
COPY --chown=steam:steam ./frp/npc /home/steam/FRP/npc
RUN chmod +x /home/steam/FRP/LoCyanFrp/frpc
RUN chmod +x /home/steam/FRP/frpc/frpc
RUN chmod +x /home/steam/FRP/mefrp/frpc
RUN chmod +x /home/steam/FRP/Sakura/frpc
RUN chmod +x /home/steam/FRP/npc/frpc

# 最后一步：复制前端代码并构建
COPY --chown=steam:steam ./app /home/steam/app
WORKDIR /home/steam/app
RUN npm run build && \
    echo "前端构建完成"

# 复制后端代码
COPY --chown=steam:steam ./server /home/steam/server
RUN chmod +x /home/steam/server/start_web.sh
RUN chmod +x /home/steam/server/signal_handler.sh


# 设置工作目录和启动命令
WORKDIR /home/steam
# 使用信号处理包装脚本确保能够正确处理Docker信号
ENTRYPOINT ["/home/steam/server/signal_handler.sh", "/home/steam/start_web.sh"]