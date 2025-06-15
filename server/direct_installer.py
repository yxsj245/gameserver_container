#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import shlex
import stat
import argparse

# 确保使用与docker-compose.yml中挂载点一致的路径
GAMES_DIR = "/home/steam/games"
STEAMCMD_PATH = "/home/steam/steamcmd/steamcmd.sh"

# 彩色输出
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BLUE = '\033[0;34m'
NC = '\033[0m'

def check_dir_writable(directory):
    """检查目录是否存在且可写"""
    if not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"{GREEN}创建目录: {directory}{NC}")
        except Exception as e:
            print(f"{RED}错误: 无法创建目录 {directory}: {str(e)}{NC}")
            return False
    
    # 测试目录是否可写
    test_file = os.path.join(directory, ".write_test")
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        print(f"{GREEN}目录可写: {directory}{NC}")
        return True
    except Exception as e:
        print(f"{RED}错误: 目录不可写 {directory}: {str(e)}{NC}")
        # 显示权限信息
        try:
            mode = os.stat(directory).st_mode
            perms = stat.filemode(mode)
            print(f"{YELLOW}目录权限: {perms}{NC}")
            print(f"{YELLOW}建议使用 chmod 777 {directory} 或更改所有者{NC}")
        except:
            pass
        return False

def install_steam_game(app_id, game_id, use_custom_account=False, steam_account=None, steam_password=None):
    install_dir = os.path.join(GAMES_DIR, game_id)
    print(f"{BLUE}================ 预检查 ================={NC}")
    print(f"{YELLOW}检查安装目录是否可写: {install_dir}{NC}")
    
    # 确保游戏目录存在且可写
    if not check_dir_writable(GAMES_DIR):
        print(f"{RED}错误: 游戏主目录不可写，请检查挂载和权限{NC}")
        return False
    
    if not check_dir_writable(install_dir):
        print(f"{RED}错误: 游戏安装目录不可写，请检查挂载和权限{NC}")
        return False
    
    print(f"{GREEN}正在安装 AppID: {app_id} 到 {install_dir}...{NC}")
    print(f"{BLUE}================ 安装信息 ================={NC}")
    print(f"{YELLOW}• 安装目录是否已挂载: {'是' if os.path.ismount(GAMES_DIR) else '否 (警告：容器重启后数据可能丢失)'}{NC}")
    print(f"{YELLOW}• SteamCMD路径: {STEAMCMD_PATH}{NC}")
    print(f"{YELLOW}• 全路径: {os.path.abspath(install_dir)}{NC}")
    
    if use_custom_account:
        if steam_account:
            if steam_password:
                login_cmd = f"+login {steam_account} {steam_password}"
            else:
                login_cmd = f"+login {steam_account}"
        else:
            # 兼容老逻辑，交互式输入
            steam_account = input(f"{YELLOW}请输入Steam账户: {NC}")
            need_password = input(f"{YELLOW}是否需要输入密码？(y/n){NC}")
            if need_password.lower() == 'y':
                import getpass
                steam_password = getpass.getpass(f"{YELLOW}请输入密码 (密码不会显示): {NC}")
                login_cmd = f"+login {steam_account} {steam_password}"
            else:
                login_cmd = f"+login {steam_account}"
    else:
        login_cmd = "+login anonymous"

    if not os.path.exists(STEAMCMD_PATH):
        print(f"{RED}错误: 找不到SteamCMD可执行文件!{NC}")
        sys.exit(1)

    # 构建命令
    cmd = f"{STEAMCMD_PATH} {login_cmd} +force_install_dir \"{install_dir}\" +app_update {app_id} validate +quit"
    
    print(f"{YELLOW}开始下载安装，这可能需要一段时间，请耐心等待...{NC}")
    print(f"{BLUE}================ 安装进度 ================={NC}")
    
    # 使用实时输出方式执行命令
    process = subprocess.Popen(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1  # 行缓冲
    )
    
    success = True
    # 读取并输出实时进度
    for line in iter(process.stdout.readline, ''):
        line = line.strip()
        # 高亮显示重要信息
        if "Error" in line or "ERROR" in line:
            print(f"{RED}{line}{NC}")
            success = False
        elif "Update state" in line or "Download" in line or "Validating" in line:
            print(f"{BLUE}{line}{NC}")
        elif "Progress:" in line:
            print(f"{GREEN}{line}{NC}")
        else:
            print(line)
    
    # 等待进程结束并获取返回码
    return_code = process.wait()
    
    print(f"{BLUE}================ 安装完成 ================={NC}")
    
    # 检查安装目录中是否有文件
    try:
        files = os.listdir(install_dir)
        if not files:
            print(f"{RED}警告: 安装目录 {install_dir} 为空，游戏可能没有正确安装!{NC}")
            print(f"{YELLOW}请检查Docker挂载设置，确保 {GAMES_DIR} 正确挂载到宿主机{NC}")
            success = False
        else:
            print(f"{GREEN}安装目录中文件数: {len(files)}{NC}")
    except Exception as e:
        print(f"{RED}检查安装目录时出错: {str(e)}{NC}")
        success = False
    
    if return_code == 0 and success:
        print(f"{GREEN}AppID: {app_id} 安装成功!{NC}")
        with open(os.path.join(install_dir, "steam_appid.txt"), "w") as f:
            f.write(str(app_id))
        return True
    else:
        print(f"{RED}AppID: {app_id} 安装失败! 返回码: {return_code}{NC}")
        # 仅在真正需要调试时才显示调试信息
        # print(f"{YELLOW}调试信息:{NC}")
        # print(f"{YELLOW}• 确认 docker-compose.yml 中的挂载设置是否正确{NC}")
        # print(f"{YELLOW}• 确认宿主机上的 game_data 目录权限是否为 777{NC}")
        # print(f"{YELLOW}• 尝试添加 user: root 到 docker-compose.yml{NC}")
        return False

def create_simple_startup_script(install_dir, app_id):
    """创建一个简单的启动脚本"""
    script_path = os.path.join(install_dir, "start.sh")
    try:
        script_content = f"""#!/bin/bash
exec > >(tee -a /tmp/start_sh_{app_id}.log) 2>&1
set -x

echo "--- start.sh for app_{app_id} ---"
echo "Timestamp: $(date)"
echo "Current directory: $(pwd)"
echo "Script arguments: \$1=\'$1\' \$2=\'$2\'"
cd "$(dirname "$0")"
echo "Changed directory to: $(pwd)"
echo "正在启动AppID: {app_id}的服务器..."

echo "Listing files in current directory:"
ls -la

if [ -f "./srcds_run" ]; then
    echo "Found ./srcds_run"
    ./srcds_run -console -game "$1" +ip 0.0.0.0 +port 27015 +map "$2"
    exit_code=$?
    echo "./srcds_run exited with code: $exit_code"
    exit $exit_code
elif [ -f "./srcds_linux" ]; then
    echo "Found ./srcds_linux"
    ./srcds_linux -console -game "$1" +ip 0.0.0.0 +port 27015 +map "$2"
    exit_code=$?
    echo "./srcds_linux exited with code: $exit_code"
    exit $exit_code
else
    echo "srcds_run and srcds_linux not found. Searching for other executables..."
    SERVER_EXE=$(find . -maxdepth 1 -name "*server*" -type f -executable | head -1)
    echo "Find command result: '$SERVER_EXE'"
    if [ ! -z "$SERVER_EXE" ]; then
        echo "找到可能的服务器可执行文件: $SERVER_EXE"
        "$SERVER_EXE"
        exit_code=$?
        echo "$SERVER_EXE exited with code: $exit_code"
        exit $exit_code
    else
        echo "未找到服务器可执行文件，请手动配置启动命令"
        exit 1
    fi
fi
echo "--- end of start.sh ---"
"""
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        os.chmod(script_path, 0o755)
        print(f"{GREEN}启动脚本创建成功!{NC}")
        return True
    except Exception as e:
        print(f"{RED}创建启动脚本失败: {str(e)}{NC}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('appid', help='Steam AppID')
    parser.add_argument('game_id', help='游戏ID (用于目录名)')
    parser.add_argument('--account', type=str, default=None, help='Steam账号')
    parser.add_argument('--password', type=str, default=None, help='Steam密码')
    args = parser.parse_args()
    
    app_id = args.appid
    game_id = args.game_id
    steam_account = args.account
    steam_password = args.password
    
    use_custom_account = bool(steam_account)
    success = install_steam_game(app_id, game_id, use_custom_account, steam_account, steam_password)
    
    if success:
        # 尝试创建一个简单的启动脚本
        create_simple_startup_script(os.path.join(GAMES_DIR, game_id), app_id)
        print(f"{GREEN}通过AppID {app_id} 安装游戏成功!{NC}")
        print(f"{YELLOW}游戏安装位置: {os.path.join(GAMES_DIR, game_id)}{NC}")
        print(f"{YELLOW}如需手动启动: cd {os.path.join(GAMES_DIR, game_id)} && ./start.sh{NC}")
        print(f"{GREEN}========================================{NC}")
        sys.exit(0)
    else:
        print(f"{RED}通过AppID {app_id} 安装游戏失败!{NC}")
        sys.exit(1)

if __name__ == "__main__":
    main() 