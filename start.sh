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
echo -e "${BLUE}项目完全开源，开源协议Apache2.0${NC}"
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

# 检查是否设置了游戏目录和启动脚本环境变量
if [ -n "$GAME_DIR" ] && [ -n "$START_SCRIPT" ]; then
    echo -e "${BLUE}=================================================${NC}"
    echo -e "${BLUE}创作声明：本容器由${GREEN} 又菜又爱玩的小猪 ${BLUE}独立制作${NC}"
    echo -e "${BLUE}项目完全开源，开源协议Apache2.0${NC}"
    echo -e "${BLUE}GitHub: https://github.com/yxsj245/GameServerManager/tree/container_Shell${NC}"
    echo -e "${BLUE}Gitee: https://gitee.com/xiao-zhu245/gameserver_container/tree/container_Shell${NC}"
    echo -e "${BLUE}允许商业用途但请勿倒卖！${NC}"
    echo -e "${BLUE}=================================================${NC}"

    # 显示欢迎信息
    echo "========================================================="
    echo "          欢迎使用星辰的游戏开服容器"
    echo "========================================================="
    echo -e "${GREEN}检测到游戏目录和启动脚本环境变量${NC}"
    echo -e "${BLUE}游戏目录: $GAME_DIR${NC}"
    echo -e "${BLUE}启动脚本: $START_SCRIPT${NC}"
    echo ""
    
    # 检查游戏目录是否存在
    if [ -d "$GAME_DIR" ]; then
        echo -e "${GREEN}游戏目录存在，准备启动游戏服务器...${NC}"
        
        # 检查启动脚本是否存在
        if [ -f "$START_SCRIPT" ]; then
            echo -e "${GREEN}启动脚本存在，正在执行...${NC}"
            echo ""
            
            # 设置脚本执行权限
            chmod +x "$START_SCRIPT"
            
            # 切换到游戏目录并执行启动脚本
            cd "$GAME_DIR"
            
            # 以steam用户身份执行启动脚本
            if [ "$(id -u)" = "0" ]; then
                exec su - steam -c "cd '$GAME_DIR' && '$START_SCRIPT'"
            else
                exec "$START_SCRIPT"
            fi
        else
            echo -e "${RED}错误: 启动脚本 $START_SCRIPT 不存在${NC}"
            echo -e "${YELLOW}将使用默认的SteamCMD启动方式${NC}"
        fi
    else
        echo -e "${RED}错误: 游戏目录 $GAME_DIR 不存在${NC}"
        echo -e "${YELLOW}将使用默认的SteamCMD启动方式${NC}"
    fi
else
    echo -e "${YELLOW}未设置游戏目录或启动脚本环境变量，使用默认SteamCMD启动方式${NC}"
fi

echo "正在启动SteamCMD..."
echo ""

# 以steam用户身份启动SteamCMD
if [ "$(id -u)" = "0" ]; then
    exec su - steam -c "cd /home/steam/steamcmd && ./steamcmd.sh"
else
    exec /home/steam/steamcmd/steamcmd.sh
fi