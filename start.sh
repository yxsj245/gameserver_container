#!/bin/bash

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 无颜色

# 输出创作声明
echo -e "${BLUE}=================================================${NC}"
echo -e "${BLUE}创作声明：本容器由${GREEN} 又菜又爱玩的小猪 ${BLUE}独立制作${NC}"
echo -e "${BLUE}项目完全开源，开源协议AGPL3.0${NC}"
echo -e "${BLUE}GitHub: https://github.com/yxsj245/GameServerManager/tree/container_Shell${NC}"
echo -e "${BLUE}Gitee: https://gitee.com/xiao-zhu245/gameserver_container/tree/container_Shell${NC}"
echo -e "${BLUE}允许商业用途但请勿倒卖！${NC}"
echo -e "${BLUE}=================================================${NC}"

# 显示欢迎信息
echo "========================================================="
echo "          欢迎使用星辰的游戏开服容器"
echo "========================================================="
echo ""
echo "正在启动SteamCMD..."
echo ""

# 配置SteamCMD默认安装目录
function configure_steam_default_dir() {
    # 创建或修改SteamCMD配置
    STEAM_CONFIG_DIR="/home/steam/Steam/config"
    mkdir -p "$STEAM_CONFIG_DIR"
    
    echo "\"InstallConfigStore\"
{
	\"Software\"
	{
		\"Valve\"
		{
			\"Steam\"
			{
				\"BaseInstallFolder_1\"\t\t\"/home/steam/games\"
				\"DownloadThrottleKB\"\t\t\"0\"
				\"AutoUpdateWindowEnabled\"\t\t\"0\"
			}
		}
	}
}" > "$STEAM_CONFIG_DIR/config.vdf"

    # 设置权限
    if [ -f "$STEAM_CONFIG_DIR/config.vdf" ]; then
        chown -R steam:steam "$STEAM_CONFIG_DIR"
        echo "已配置SteamCMD默认安装目录为: /home/steam/games"
    else
        echo "警告: 无法配置SteamCMD默认安装目录"
    fi
}

# 确保数据目录存在
mkdir -p /home/steam/games

# 设置权限
if [ "$(id -u)" = "0" ]; then
    # 确保目录存在
    mkdir -p /home/steam/games
    mkdir -p /home/steam/Steam
    mkdir -p /home/steam/Steam/steamapps/common
    
    # 设置递归权限，确保steam用户对所有目录有完全控制权
    chown -R steam:steam /home/steam/games
    chown -R steam:steam /home/steam/Steam
    chmod -R 755 /home/steam/games
    chmod -R 755 /home/steam/Steam
    
    echo "已设置目录权限"
    
    # 配置SteamCMD默认安装目录
    su - steam -c "mkdir -p /home/steam/Steam"
    configure_steam_default_dir
    chown -R steam:steam /home/steam/Steam
fi

echo "正在启动SteamCMD..."
echo ""

# 以steam用户身份启动SteamCMD
if [ "$(id -u)" = "0" ]; then
    exec su - steam -c "cd /home/steam/steamcmd && ./steamcmd.sh"
else
    exec /home/steam/steamcmd/steamcmd.sh
fi