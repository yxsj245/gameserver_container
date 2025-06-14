import os
import sys
import json
import subprocess
import shlex
import stat
import argparse

# 确保使用与docker-compose.yml中挂载点一致的路径
GAMES_DIR = "/home/steam/games"
GAME_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "installgame.json")
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

def load_config():
    try:
        if not os.path.exists(GAME_CONFIG_FILE):
            print(f"{RED}未找到配置文件: {GAME_CONFIG_FILE}{NC}")
            return {}
        with open(GAME_CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"{RED}加载配置文件失败: {str(e)}{NC}")
        return {}

def install_steam_game(app_id, game_name, use_custom_account=False, steam_account=None, steam_password=None, manifest=None):
    install_dir = os.path.join(GAMES_DIR, game_name)
    print(f"{BLUE}================ 预检查 ================={NC}")
    print(f"{YELLOW}检查安装目录是否可写: {install_dir}{NC}")
    
    # 确保游戏目录存在且可写
    if not check_dir_writable(GAMES_DIR):
        print(f"{RED}错误: 游戏主目录不可写，请检查挂载和权限{NC}")
        return False
    
    if not check_dir_writable(install_dir):
        print(f"{RED}错误: 游戏安装目录不可写，请检查挂载和权限{NC}")
        return False
    
    print(f"{GREEN}正在安装 {game_name} (AppID: {app_id}) 到 {install_dir}...{NC}")
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
    if manifest:
        cmd = f"{STEAMCMD_PATH} {login_cmd} +force_install_dir \"{install_dir}\" +app_update {app_id} -manifest {manifest} validate +quit"
    else:
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
        print(f"{GREEN}{game_name} 安装成功!{NC}")
        with open(os.path.join(install_dir, "steam_appid.txt"), "w") as f:
            f.write(str(app_id))
        return True
    else:
        print(f"{RED}{game_name} 安装失败! 返回码: {return_code}{NC}")
        # 显示调试信息
        print(f"{YELLOW}调试信息:{NC}")
        print(f"{YELLOW}• 确认 docker-compose.yml 中的挂载设置是否正确{NC}")
        print(f"{YELLOW}• 确认宿主机上的 game_data 目录权限是否为 777{NC}")
        print(f"{YELLOW}• 尝试添加 user: root 到 docker-compose.yml{NC}")
        return False

def create_startup_script(install_dir, script_content):
    script_path = os.path.join(install_dir, "start.sh")
    try:
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
    parser.add_argument('game_name', help='游戏英文名')
    parser.add_argument('--account', type=str, default=None, help='Steam账号')
    parser.add_argument('--password', type=str, default=None, help='Steam密码')
    parser.add_argument('--manifest', type=str, default=None, help='版本号 (Manifest ID)')
    args = parser.parse_args()
    game_name = args.game_name
    steam_account = args.account
    steam_password = args.password
    manifest = args.manifest
    
    # 首先检查游戏目录中是否存在cloud_script.sh，这表明可能是云端游戏
    install_dir = os.path.join(GAMES_DIR, game_name)
    cloud_script_path = os.path.join(install_dir, "cloud_script.sh")
    
    config = load_config()
    
    # 如果游戏不在本地配置中，但存在云端脚本，则可能是从云端获取的游戏
    if game_name not in config and os.path.exists(cloud_script_path):
        print(f"{YELLOW}游戏 {game_name} 不在本地配置中，但检测到云端脚本，可能是赞助者专属游戏{NC}")
        
        # 尝试从文件名中提取AppID
        appid = None
        
        # 检查云端脚本内容，尝试获取一些基本信息
        try:
            with open(cloud_script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
                
            # 查找类似 appid 的信息
            import re
            appid_match = re.search(r'appid[=:]?\s*["\'"]?(\d+)', script_content, re.IGNORECASE)
            if appid_match:
                appid = appid_match.group(1)
                print(f"{GREEN}从脚本中提取到AppID: {appid}{NC}")
        except Exception as e:
            print(f"{RED}读取云端脚本失败: {str(e)}{NC}")
        
        # 如果没有从脚本中找到AppID，检查游戏目录下是否有appid.txt文件
        if not appid and os.path.exists(os.path.join(install_dir, "appid.txt")):
            try:
                with open(os.path.join(install_dir, "appid.txt"), "r") as f:
                    appid = f.read().strip()
                print(f"{GREEN}从appid.txt中读取到AppID: {appid}{NC}")
            except Exception as e:
                print(f"{RED}读取appid.txt失败: {str(e)}{NC}")
                
        # 如果仍然没有找到AppID，尝试从游戏名称推断
        if not appid:
            if game_name.lower().startswith("app_"):
                appid = game_name[4:]  # 去掉"app_"前缀
                print(f"{YELLOW}尝试从游戏ID推断AppID: {appid}{NC}")
                
        # 如果找到了AppID，可以继续安装
        if appid:
            print(f"{GREEN}准备安装云端游戏 {game_name} (AppID: {appid}){NC}")
            use_custom_account = False  # 假设默认匿名登录
            
            # 如果提供了账户信息，则使用账户登录
            if steam_account:
                use_custom_account = True
                
            success = install_steam_game(appid, game_name, use_custom_account, steam_account, steam_password, manifest)
            if not success:
                sys.exit(1)
                
            # 处理云端脚本
            print(f"{GREEN}检测到云端脚本文件，将使用云端脚本{NC}")
            try:
                with open(cloud_script_path, "r", encoding="utf-8") as f:
                    cloud_script_content = f.read()
                    
                # 创建启动脚本
                script_path = os.path.join(install_dir, "start.sh")
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(cloud_script_content)
                    
                # 设置执行权限
                os.chmod(script_path, 0o755)
                print(f"{GREEN}使用云端脚本创建启动脚本成功!{NC}")
                
                # 完成后删除临时云端脚本
                os.remove(cloud_script_path)
                print(f"{GREEN}临时云端脚本已清理{NC}")
            except Exception as e:
                print(f"{RED}处理云端脚本失败: {str(e)}{NC}")
                
            print(f"{GREEN}云端游戏 {game_name} 服务端安装完成!{NC}")
            print(f"{YELLOW}游戏安装位置: {install_dir}{NC}")
            print(f"{YELLOW}如需手动启动: cd {install_dir} && ./start.sh{NC}")
            print(f"{GREEN}========================================{NC}")
            sys.exit(0)
        else:
            print(f"{RED}无法确定游戏的AppID，安装失败{NC}")
            sys.exit(1)
    
    # 常规安装流程
    if game_name not in config:
        print(f"{RED}未找到游戏: {game_name}{NC}")
        sys.exit(1)
        
    info = config[game_name]
    game_nameCN = info.get("game_nameCN", game_name)
    appid = info.get("appid")
    anonymous = info.get("anonymous", True)
    script = info.get("script", False)
    script_name = info.get("script_name", "")
    tip = info.get("tip", "")
    
    if not appid:
        print(f"{RED}配置缺少AppID，无法安装{NC}")
        sys.exit(1)
        
    use_custom_account = not anonymous
    success = install_steam_game(appid, game_name, use_custom_account, steam_account, steam_password, manifest)
    if not success:
        sys.exit(1)
    
    # 检查是否存在云端脚本文件
    if os.path.exists(cloud_script_path):
        print(f"{GREEN}检测到云端脚本文件，将使用云端脚本{NC}")
        # 读取云端脚本内容
        try:
            with open(cloud_script_path, "r", encoding="utf-8") as f:
                cloud_script_content = f.read()
                
            # 创建启动脚本
            script_path = os.path.join(install_dir, "start.sh")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(cloud_script_content)
                
            # 设置执行权限
            os.chmod(script_path, 0o755)
            print(f"{GREEN}使用云端脚本创建启动脚本成功!{NC}")
            
            # 完成后删除临时云端脚本
            os.remove(cloud_script_path)
            print(f"{GREEN}临时云端脚本已清理{NC}")
        except Exception as e:
            print(f"{RED}处理云端脚本失败: {str(e)}{NC}")
    elif script and script_name and script_name != "echo=none":
        create_startup_script(install_dir, script_name)
        
    print(f"{GREEN}{game_nameCN} 服务端安装完成!{NC}")
    print(f"{YELLOW}安装提示: {tip}{NC}")
    print(f"{YELLOW}游戏安装位置: {install_dir}{NC}")
    print(f"{YELLOW}如需手动启动: cd {install_dir} && ./start.sh{NC}")
    print(f"{GREEN}========================================{NC}")
    print(f"{GREEN}提示: 如果游戏文件没有正确写入到宿主机上的game_data目录，请尝试:{NC}")
    print(f"{YELLOW}1. 检查宿主机上目录权限: chmod -R 777 ./game_data{NC}")
    print(f"{YELLOW}2. 确认 docker-compose.yml 中挂载设置: ./game_data:/home/steam/games{NC}")
    print(f"{YELLOW}3. 重启容器并使用 root 用户: user: root{NC}")

if __name__ == "__main__":
    main()