FROM debian:bullseye-slim

ENV DEBIAN_FRONTEND=noninteractive \
    STEAM_USER=steam \
    STEAM_HOME=/home/steam \
    STEAMCMD_DIR=/home/steam/steamcmd \
    GAMES_DIR=/home/steam/games

# 将apt源改为中国镜像源（清华TUNA）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list \
    && sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list

# 安装SteamCMD和常见依赖（包括32位库）
RUN apt-get update && apt-get upgrade -y \
    && dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        locales \
        wget \
        curl \
        jq \
        xdg-user-dirs \
        libncurses5:i386 \
        libbz2-1.0:i386 \
        libicu67:i386 \
        libxml2:i386 \
        libstdc++6:i386 \
        lib32gcc-s1 \
        libc6-i386 \
        lib32stdc++6 \
        libcurl4-gnutls-dev:i386 \
        libcurl4-gnutls-dev \
        libgl1-mesa-glx:i386 \
        gcc-10-base:i386 \
        libssl1.1:i386 \
        libopenal1:i386 \
        libtinfo6:i386 \
        libtcmalloc-minimal4:i386 \
        # .NET和Mono相关依赖（ECO服务器等需要）
        libgdiplus \
        libc6-dev \
        libasound2 \
        libpulse0 \
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
        netcat \
        procps \
        python3 \
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

# 切换到root用户安装SteamCMD（确保有足够权限）
USER root

# 下载并安装SteamCMD
RUN mkdir -p ${STEAMCMD_DIR} \
    && cd ${STEAMCMD_DIR} \
    && (if curl -s --connect-timeout 3 http://192.168.10.23:7890 >/dev/null 2>&1 || wget -q --timeout=3 --tries=1 http://192.168.10.23:7890 -O /dev/null >/dev/null 2>&1; then \
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

# 复制菜单脚本和启动脚本
COPY --chown=steam:steam start.sh /home/steam/start.sh

# 创建目录用于挂载游戏数据
VOLUME ["${GAMES_DIR}"]

# 切回steam用户
USER ${STEAM_USER}
WORKDIR ${STEAM_HOME}

# 启动容器时运行start.sh
ENTRYPOINT ["/home/steam/start.sh"] 
