#!/usr/bin/env python3
import os
import sys
import json
import time
import logging
import subprocess
import shlex
import shutil
import tempfile
import queue
import threading
import pty
import fcntl
import select
import re
import psutil
import uuid
import hashlib
import base64
import datetime
import zipfile
import tarfile
import gzip
import bz2
import rarfile
import lzma
import stat
import zstandard as zstd
import multiprocessing
from functools import wraps
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context, g, render_template_string, send_file, make_response
from werkzeug.utils import secure_filename
from flask_cors import CORS
from auth_middleware import auth_required, generate_token, verify_token, save_user, is_public_route, hash_password, verify_password
import jwt
import signal
import secrets
import socket
import requests

# 导入PTY管理器
from pty_manager import pty_manager
# 导入MC下载功能
from MCdownloads import get_server_list, get_server_info, get_builds, get_core_info, download_file
from sponsor_validator import SponsorValidator
# 导入Java安装器
from java_installer import install_java_worker
# 导入Docker管理器
from docker_manager import docker_manager
# 导入Minecraft整合包安装器
from minecraft_modpack_installer import MinecraftModpackInstaller

# 输出管理函数
def add_server_output(game_id, message, max_lines=500):
    """添加服务器输出并限制行数"""
    if game_id not in running_servers:
        return
    
    if 'output' not in running_servers[game_id]:
        running_servers[game_id]['output'] = []
    
    running_servers[game_id]['output'].append(message)
    
    # 限制输出行数，最多保留指定行数
    if len(running_servers[game_id]['output']) > max_lines:
        # 移除最旧的输出，保持在指定行数以内
        running_servers[game_id]['output'] = running_servers[game_id]['output'][-max_lines:]

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('api_server.log')
    ]
)
logger = logging.getLogger("api_server")

# FRP相关配置
FRP_DIR = "/home/steam/FRP"
FRP_CONFIG_FILE = os.path.join("/home/steam/games", "frp.json")
FRP_BINARY = os.path.join(FRP_DIR, "LoCyanFrp/frpc")
FRP_LOGS_DIR = os.path.join(FRP_DIR, "logs")
CUSTOM_FRP_DIR = os.path.join(FRP_DIR, "frpc")
CUSTOM_FRP_CONFIG_FILE = os.path.join(CUSTOM_FRP_DIR, "frpc.toml")
CUSTOM_FRP_BINARY = os.path.join(CUSTOM_FRP_DIR, "frpc")
# 添加mefrp相关配置
MEFRP_DIR = os.path.join(FRP_DIR, "mefrp")
MEFRP_BINARY = os.path.join(MEFRP_DIR, "frpc")
# Sakura内网穿透
SAKURA_DIR = os.path.join(FRP_DIR, "Sakura")
SAKURA_BINARY = os.path.join(SAKURA_DIR, "frpc")
# NPC内网穿透
NPC_DIR = os.path.join(FRP_DIR, "npc")
NPC_BINARY = os.path.join(NPC_DIR, "frpc")

# 确保FRP相关目录存在
os.makedirs(FRP_DIR, exist_ok=True)
os.makedirs(os.path.join(FRP_DIR, "LoCyanFrp"), exist_ok=True)
os.makedirs(FRP_LOGS_DIR, exist_ok=True)
os.makedirs(CUSTOM_FRP_DIR, exist_ok=True)
os.makedirs(os.path.join(FRP_DIR, "logs"), exist_ok=True)
os.makedirs(MEFRP_DIR, exist_ok=True)
os.makedirs(SAKURA_DIR, exist_ok=True)
os.makedirs(NPC_DIR, exist_ok=True)

# FRP进程字典
running_frp_processes = {}  # id: {'process': process, 'log_file': log_file_path}

# 添加一个全局变量来跟踪人工停止的服务器
manually_stopped_servers = set()  # 存储人工停止的服务器ID

# 添加一个全局变量来跟踪人工停止的内网穿透
manually_stopped_frps = set()  # 存储人工停止的内网穿透ID

app = Flask(__name__, static_folder='../app/dist')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # 禁用缓存，确保始终获取最新文件

# 允许跨域请求
CORS(app, resources={r"/*": {"origins": "*"}})  # 允许所有来源的跨域请求

# 在应用启动时加载备份配置（延迟加载，避免循环导入）
# 使用全局变量标记是否已初始化
_backup_config_loaded = False

def ensure_backup_config_loaded():
    global _backup_config_loaded
    if not _backup_config_loaded:
        load_backup_config()
        start_backup_scheduler()
        _backup_config_loaded = True

def ensure_auto_start_initialized():
    """确保自启动功能已初始化（用于Gunicorn启动）"""
    global _auto_start_initialized
    
    # 如果已经初始化过，直接返回，避免重复执行
    if _auto_start_initialized:
        logger.debug("自启动功能已初始化，跳过重复执行")
        return
        
    # 如果有服务器正在运行，说明已经初始化过了，避免重复执行
    if running_servers:
        logger.debug(f"检测到 {len(running_servers)} 个服务器正在运行，跳过自启动检查")
        _auto_start_initialized = True
        return
    
    try:
        auto_start_servers()
        # 打印当前运行的游戏服务器信息
        log_running_games()
        _auto_start_initialized = True
        logger.info("自启动功能初始化完成")
    except Exception as e:
        logger.error(f"初始化自启动功能时出错: {str(e)}")

# 导入JWT配置
from config import JWT_SECRET, JWT_EXPIRATION

# 生成JWT令牌
def generate_token(user):
    """生成JWT令牌"""
    payload = {
        'username': user.get('username'),
        'role': user.get('role', 'user'),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXPIRATION)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    return token

# 验证JWT令牌
def verify_token(token):
    """验证JWT令牌"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("令牌已过期")
        return None
    except jwt.InvalidTokenError:
        logger.warning("无效的令牌")
        return None

# 保存用户到auth_middleware
def save_user(user):
    """保存用户到auth_middleware"""
    try:
        # 这里简化处理，直接返回True
        return True
    except Exception as e:
        logger.error(f"保存用户失败: {str(e)}")
        return False

# 定义公共路由列表
def is_public_route(path):
    """检查路径是否为公共路由"""
    public_routes = [
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/check_first_use'
        # 注意：/api/terminate_install 需要认证，不应该出现在这个列表中
    ]
    return path in public_routes

# 代理配置应用函数
def apply_proxy_config(proxy_config):
    """应用系统级别的代理配置"""
    try:
        if proxy_config.get('enabled', False):
            host = proxy_config.get('host', '')
            port = proxy_config.get('port', 8080)
            username = proxy_config.get('username', '')
            password = proxy_config.get('password', '')
            proxy_type = proxy_config.get('type', 'http')
            no_proxy = proxy_config.get('no_proxy', '')
            
            # 构建代理URL
            if username and password:
                proxy_url = f"{proxy_type}://{username}:{password}@{host}:{port}"
            else:
                proxy_url = f"{proxy_type}://{host}:{port}"
            
            # 1. 设置环境变量（应用程序级别）
            os.environ['HTTP_PROXY'] = proxy_url
            os.environ['HTTPS_PROXY'] = proxy_url
            os.environ['http_proxy'] = proxy_url
            os.environ['https_proxy'] = proxy_url
            os.environ['ALL_PROXY'] = proxy_url
            os.environ['all_proxy'] = proxy_url
            
            if no_proxy:
                os.environ['NO_PROXY'] = no_proxy
                os.environ['no_proxy'] = no_proxy
            
            # 2. 配置系统级别代理
            _configure_system_proxy(proxy_config)
            
            # 3. 配置APT代理（如果是Debian/Ubuntu系统）
            _configure_apt_proxy(proxy_config)
            
            # 4. 写入全局环境配置文件
            _write_global_proxy_config(proxy_config)
            
            logger.info(f"已应用系统级别代理配置: {proxy_type}://{host}:{port}")
        else:
            # 清除所有代理配置
            _clear_all_proxy_config()
            logger.info("已清除所有代理配置")
            
    except Exception as e:
        logger.error(f"应用代理配置时出错: {str(e)}")

def _configure_system_proxy(proxy_config):
    """配置系统级别代理"""
    try:
        host = proxy_config.get('host', '')
        port = proxy_config.get('port', 8080)
        username = proxy_config.get('username', '')
        password = proxy_config.get('password', '')
        proxy_type = proxy_config.get('type', 'http')
        
        # 构建代理URL
        if username and password:
            proxy_url = f"{proxy_type}://{username}:{password}@{host}:{port}"
        else:
            proxy_url = f"{proxy_type}://{host}:{port}"
        
        # 配置系统代理（通过gsettings，适用于GNOME桌面环境）
        # 检查是否有桌面环境
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            try:
                if proxy_type.lower() in ['http', 'https']:
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.http', 'host', host], check=False, stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.http', 'port', str(port)], check=False, stderr=subprocess.DEVNULL)
                    if username and password:
                        subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.http', 'authentication-user', username], check=False, stderr=subprocess.DEVNULL)
                        subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.http', 'authentication-password', password], check=False, stderr=subprocess.DEVNULL)
                        subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.http', 'use-authentication', 'true'], check=False, stderr=subprocess.DEVNULL)
                    
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy', 'mode', 'manual'], check=False, stderr=subprocess.DEVNULL)
                elif proxy_type.lower() == 'socks5':
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.socks', 'host', host], check=False, stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy.socks', 'port', str(port)], check=False, stderr=subprocess.DEVNULL)
                    subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy', 'mode', 'manual'], check=False, stderr=subprocess.DEVNULL)
                logger.info("已配置GNOME系统代理")
            except Exception as e:
                logger.warning(f"配置GNOME系统代理失败: {str(e)}")
        else:
            logger.info("无桌面环境，跳过GNOME系统代理配置")
        
        # 配置iptables透明代理（需要root权限）
        try:
            if proxy_type.lower() == 'socks5':
                _configure_transparent_proxy(host, port)
        except Exception as e:
            logger.warning(f"配置透明代理失败: {str(e)}")
            
    except Exception as e:
        logger.error(f"配置系统代理时出错: {str(e)}")

def _configure_transparent_proxy(proxy_host, proxy_port):
    """配置透明代理（使用iptables和redsocks）"""
    try:
        # 检查是否有redsocks
        redsocks_config = f"""
base {{
    log_debug = off;
    log_info = on;
    log = "file:/tmp/redsocks.log";
    daemon = on;
    redirector = iptables;
}}

redsocks {{
    local_ip = 127.0.0.1;
    local_port = 12345;
    ip = {proxy_host};
    port = {proxy_port};
    type = socks5;
}}
"""
        
        # 写入redsocks配置
        with open('/tmp/redsocks.conf', 'w') as f:
            f.write(redsocks_config)
        
        # 启动redsocks（如果存在）
        try:
            subprocess.run(['pkill', 'redsocks'], check=False)
            subprocess.run(['redsocks', '-c', '/tmp/redsocks.conf'], check=False)
        except FileNotFoundError:
            logger.warning("redsocks未安装，跳过透明代理配置")
            return
        
        # 配置iptables规则
        iptables_rules = [
            # 创建新链
            ['iptables', '-t', 'nat', '-N', 'REDSOCKS'],
            # 忽略本地和代理服务器的流量
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-d', '127.0.0.0/8', '-j', 'RETURN'],
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-d', proxy_host, '-j', 'RETURN'],
            # 忽略局域网流量
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-d', '10.0.0.0/8', '-j', 'RETURN'],
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-d', '172.16.0.0/12', '-j', 'RETURN'],
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-d', '192.168.0.0/16', '-j', 'RETURN'],
            # 重定向其他流量到redsocks
            ['iptables', '-t', 'nat', '-A', 'REDSOCKS', '-p', 'tcp', '-j', 'REDIRECT', '--to-ports', '12345'],
            # 应用规则到OUTPUT链
            ['iptables', '-t', 'nat', '-A', 'OUTPUT', '-p', 'tcp', '-j', 'REDSOCKS']
        ]
        
        for rule in iptables_rules:
            try:
                subprocess.run(rule, check=False)
            except Exception as e:
                logger.warning(f"执行iptables规则失败: {' '.join(rule)}, 错误: {str(e)}")
                
    except Exception as e:
        logger.error(f"配置透明代理时出错: {str(e)}")

def _configure_apt_proxy(proxy_config):
    """配置APT代理"""
    try:
        host = proxy_config.get('host', '')
        port = proxy_config.get('port', 8080)
        username = proxy_config.get('username', '')
        password = proxy_config.get('password', '')
        proxy_type = proxy_config.get('type', 'http')
        
        if proxy_type.lower() in ['http', 'https']:
            # 构建代理URL
            if username and password:
                proxy_url = f"http://{username}:{password}@{host}:{port}"
            else:
                proxy_url = f"http://{host}:{port}"
            
            apt_proxy_config = f"""
Acquire::http::Proxy "{proxy_url}";
Acquire::https::Proxy "{proxy_url}";
"""
            
            # 写入APT代理配置
            os.makedirs('/etc/apt/apt.conf.d', exist_ok=True)
            with open('/etc/apt/apt.conf.d/95proxy', 'w') as f:
                f.write(apt_proxy_config)
            
            logger.info("已配置APT代理")
            
    except Exception as e:
        logger.warning(f"配置APT代理失败: {str(e)}")

def _configure_git_proxy(proxy_config):
    """配置Git代理"""
    try:
        host = proxy_config.get('host', '')
        port = proxy_config.get('port', 8080)
        username = proxy_config.get('username', '')
        password = proxy_config.get('password', '')
        proxy_type = proxy_config.get('type', 'http')
        
        # 构建代理URL
        if username and password:
            proxy_url = f"{proxy_type}://{username}:{password}@{host}:{port}"
        else:
            proxy_url = f"{proxy_type}://{host}:{port}"
        
        # 配置Git全局代理
        if proxy_type.lower() in ['http', 'https']:
            subprocess.run(['git', 'config', '--global', 'http.proxy', proxy_url], check=False)
            subprocess.run(['git', 'config', '--global', 'https.proxy', proxy_url], check=False)
        elif proxy_type.lower() == 'socks5':
            subprocess.run(['git', 'config', '--global', 'http.proxy', proxy_url], check=False)
            subprocess.run(['git', 'config', '--global', 'https.proxy', proxy_url], check=False)
        
        logger.info("已配置Git代理")
        
    except Exception as e:
        logger.warning(f"配置Git代理失败: {str(e)}")

def _write_global_proxy_config(proxy_config):
    """写入全局环境配置文件"""
    try:
        host = proxy_config.get('host', '')
        port = proxy_config.get('port', 8080)
        username = proxy_config.get('username', '')
        password = proxy_config.get('password', '')
        proxy_type = proxy_config.get('type', 'http')
        no_proxy = proxy_config.get('no_proxy', '')
        
        # 构建代理URL
        if username and password:
            proxy_url = f"{proxy_type}://{username}:{password}@{host}:{port}"
        else:
            proxy_url = f"{proxy_type}://{host}:{port}"
        
        # 写入/etc/environment
        env_config = f"""
# Proxy Configuration
export HTTP_PROXY="{proxy_url}"
export HTTPS_PROXY="{proxy_url}"
export http_proxy="{proxy_url}"
export https_proxy="{proxy_url}"
export ALL_PROXY="{proxy_url}"
export all_proxy="{proxy_url}"
"""
        
        if no_proxy:
            env_config += f"""
export NO_PROXY="{no_proxy}"
export no_proxy="{no_proxy}"
"""
        
        # 写入到/etc/environment（需要root权限）
        try:
            with open('/etc/environment', 'a') as f:
                f.write(env_config)
        except PermissionError:
            # 如果没有权限，写入到用户目录
            home_dir = os.path.expanduser('~')
            with open(os.path.join(home_dir, '.proxy_env'), 'w') as f:
                f.write(env_config)
            
            # 添加到.bashrc
            bashrc_path = os.path.join(home_dir, '.bashrc')
            if os.path.exists(bashrc_path):
                with open(bashrc_path, 'a') as f:
                    f.write(f"\n# Load proxy configuration\nsource ~/.proxy_env\n")
        
        logger.info("已写入全局代理配置")
        
    except Exception as e:
        logger.warning(f"写入全局代理配置失败: {str(e)}")

def _clear_all_proxy_config():
    """清除所有代理配置"""
    try:
        # 1. 清除环境变量
        proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                     'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy', 'FTP_PROXY', 'ftp_proxy']
        for var in proxy_vars:
            if var in os.environ:
                del os.environ[var]
        
        # 2. 清除系统代理设置（GNOME）
        if os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
            try:
                subprocess.run(['gsettings', 'set', 'org.gnome.system.proxy', 'mode', 'none'], 
                             check=False, stderr=subprocess.DEVNULL)
                subprocess.run(['gsettings', 'reset', 'org.gnome.system.proxy.http', 'host'], 
                             check=False, stderr=subprocess.DEVNULL)
                subprocess.run(['gsettings', 'reset', 'org.gnome.system.proxy.http', 'port'], 
                             check=False, stderr=subprocess.DEVNULL)
                subprocess.run(['gsettings', 'reset', 'org.gnome.system.proxy.socks', 'host'], 
                             check=False, stderr=subprocess.DEVNULL)
                subprocess.run(['gsettings', 'reset', 'org.gnome.system.proxy.socks', 'port'], 
                             check=False, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        
        # 3. 清除APT代理
        try:
            if os.path.exists('/etc/apt/apt.conf.d/95proxy'):
                os.remove('/etc/apt/apt.conf.d/95proxy')
        except Exception:
            pass
        
        # 4. 清除Git代理
        try:
            subprocess.run(['git', 'config', '--global', '--unset', 'http.proxy'], 
                         check=False, stderr=subprocess.DEVNULL)
            subprocess.run(['git', 'config', '--global', '--unset', 'https.proxy'], 
                         check=False, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        
        # 5. 清除透明代理和iptables规则
        try:
            # 停止redsocks服务
            subprocess.run(['pkill', '-f', 'redsocks'], check=False, stderr=subprocess.DEVNULL)
            
            # 清除iptables规则
            subprocess.run(['iptables', '-t', 'nat', '-F', 'REDSOCKS'], 
                         check=False, stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'nat', '-D', 'OUTPUT', '-p', 'tcp', '-j', 'REDSOCKS'], 
                         check=False, stderr=subprocess.DEVNULL)
            subprocess.run(['iptables', '-t', 'nat', '-X', 'REDSOCKS'], 
                         check=False, stderr=subprocess.DEVNULL)
            
            # 删除redsocks配置文件
            if os.path.exists('/tmp/redsocks.conf'):
                os.remove('/tmp/redsocks.conf')
        except Exception:
            pass
        
        # 6. 清除环境配置文件
        try:
            home_dir = os.path.expanduser('~')
            proxy_env_file = os.path.join(home_dir, '.proxy_env')
            if os.path.exists(proxy_env_file):
                os.remove(proxy_env_file)
            
            # 清除/etc/environment中的代理配置
            if os.path.exists('/etc/environment'):
                with open('/etc/environment', 'r') as f:
                    lines = f.readlines()
                
                # 过滤掉代理相关的行
                filtered_lines = []
                for line in lines:
                    if not any(proxy_var in line.upper() for proxy_var in 
                             ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'FTP_PROXY']):
                        filtered_lines.append(line)
                
                with open('/etc/environment', 'w') as f:
                    f.writelines(filtered_lines)
        except Exception:
            pass
        
        # 7. 清除shell配置文件中的代理设置
        try:
            home_dir = os.path.expanduser('~')
            shell_files = ['.bashrc', '.zshrc', '.profile', '.bash_profile']
            
            for shell_file in shell_files:
                file_path = os.path.join(home_dir, shell_file)
                if os.path.exists(file_path):
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    # 移除代理相关的行
                    lines = content.split('\n')
                    filtered_lines = []
                    skip_next = False
                    
                    for line in lines:
                        if skip_next and line.strip() == '':
                            skip_next = False
                            continue
                        
                        if ('proxy' in line.lower() and ('export' in line or 'source' in line)) or \
                           any(proxy_var in line.upper() for proxy_var in 
                               ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'FTP_PROXY']) or \
                           '.proxy_env' in line:
                            skip_next = True
                            continue
                        
                        filtered_lines.append(line)
                        skip_next = False
                    
                    with open(file_path, 'w') as f:
                        f.write('\n'.join(filtered_lines))
        except Exception:
            pass
        
        # 8. 重新加载shell环境（尝试）
        try:
            subprocess.run(['bash', '-c', 'source ~/.bashrc'], check=False, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        
        # 9. 清除Docker代理配置（如果存在）
        try:
            docker_config_dir = os.path.expanduser('~/.docker')
            docker_config_file = os.path.join(docker_config_dir, 'config.json')
            if os.path.exists(docker_config_file):
                import json
                with open(docker_config_file, 'r') as f:
                    config = json.load(f)
                
                # 移除代理配置
                if 'proxies' in config:
                    del config['proxies']
                
                with open(docker_config_file, 'w') as f:
                    json.dump(config, f, indent=2)
        except Exception:
            pass
        
        logger.info("已清除所有代理配置，包括环境变量、系统设置、配置文件等")
        
    except Exception as e:
        logger.error(f"清除代理配置时出错: {str(e)}")

# 在每个请求前检查认证
# 初始化代理配置（用于Gunicorn启动）
def init_proxy_config():
    """初始化代理配置"""
    try:
        from config import load_config
        config = load_config()
        proxy_config = config.get('proxy')
        if proxy_config:
            apply_proxy_config(proxy_config)
            logger.info("已加载代理配置")
    except Exception as e:
        logger.error(f"加载代理配置失败: {str(e)}")

# 在Gunicorn启动时初始化代理配置
init_proxy_config()

@app.before_request
def check_auth():
    # 环境管理相关的API路由，不触发自启动检查
    environment_api_paths = [
        '/api/environment/java/status',
        '/api/environment/java/install',
        '/api/environment/java/uninstall',
        '/api/environment/java/check',
        '/api/environment/status'
    ]
    
    # 只有非环境管理的API请求才触发自启动检查
    if request.path.startswith('/api/') and not any(request.path.startswith(path) for path in environment_api_paths):
        # 确保自启动功能已初始化（用于Gunicorn启动）
        ensure_auto_start_initialized()
    
    # 记录请求路径，帮助调试
    logger.debug(f"收到请求: {request.method} {request.path}, 参数: {request.args}, 头部: {request.headers}")
    
    # 前端资源路由不需要认证
    if request.path == '/' or not request.path.startswith('/api/') or is_public_route(request.path):
        # logger.debug(f"公共路由，无需认证: {request.path}")
        return None
        
    # 所有API路由需要认证，除了登录API
    if request.path.startswith('/api/'):
        # 登录路由不需要认证
        if request.path == '/api/auth/login' or request.path == '/api/auth/register' or request.path == '/api/auth/check_first_use':
            # logger.debug("登录/注册路由，无需认证")
            return None
            
        auth_header = request.headers.get('Authorization')
        token_param = request.args.get('token')
        
        # logger.debug(f"认证检查 - 路径: {request.path}, 认证头: {auth_header}, Token参数: {token_param}")
        
        # 检查是否有令牌
        if not auth_header and not token_param:
            logger.warning(f"API请求无认证令牌: {request.path}")
            return jsonify({
                'status': 'error',
                'message': '未授权的访问，请先登录'
            }), 401
            
        # 验证令牌
        token = None
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
                # logger.debug(f"从认证头部获取到token: {token[:10]}...")
                
        if not token and token_param:
            token = token_param
            # logger.debug(f"从URL参数获取到token: {token_param[:10]}...")
            
        if token:
            payload = verify_token(token)
            if not payload:
                logger.warning(f"无效令牌: {request.path}, token: {token[:10]}...")
                return jsonify({
                    'status': 'error',
                    'message': '令牌无效或已过期，请重新登录'
                }), 401
            # 令牌有效，保存用户信息到g对象
            g.user = payload
            # logger.debug(f"认证通过: {request.path}, 用户: {payload.get('username')}")
            return None

# 游戏安装脚本路径
INSTALLER_SCRIPT = os.path.join(os.path.dirname(__file__), "game_installer.py")
GAMES_CONFIG = os.path.join(os.path.dirname(__file__), "installgame.json")
GAMES_DIR = "/home/steam/games"
USER_CONFIG_PATH = os.path.join(GAMES_DIR, "config.json")

# 用于存储正在进行的安装进程和它们的输出
active_installations = {}

# 创建一个全局的输出队列字典，用于实时传输安装进度
output_queues = {}

# 新增：用于存储每个游戏的运行中服务器进程和输出
running_servers = {}  # game_id: {'process': process, 'output': [], 'master_fd': fd, 'started_at': time.time()}
server_output_queues = {}  # game_id: queue.Queue()

# 备份任务计数器
backup_task_counter = 0

# 备份任务字典
backup_tasks = {}

# 备份调度器运行状态
backup_scheduler_running = False

# 加载游戏配置
def load_games_config():
    with open(GAMES_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)

# 在单独线程中使用PTY运行安装任务
def run_installation(game_id, cmd):
    logger.info(f"开始使用PTY运行游戏 {game_id} 的安装进程")
    
    try:
        # 准备命令字符串
        logger.info(f"执行命令: {cmd}")
        
        # 生成进程ID
        process_id = f"install_{game_id}"
        logger.info(f"生成进程ID: {process_id}")
        
        # 创建并启动PTY进程
        process = pty_manager.create_process(
            process_id=process_id,
            cmd=cmd,
            log_prefix=f"game_install_{game_id}"
        )
        
        # 将进程对象和输出队列关联到安装数据
        if game_id in active_installations:
            active_installations[game_id]['pty_process'] = process
            active_installations[game_id]['process_id'] = process_id
            output_queues[game_id] = process.output_queue
            logger.debug(f"进程已创建，准备启动，process_id={process_id}")
        else:
            logger.error(f"找不到游戏 {game_id} 的安装数据")
            return
        
        # 启动进程
        if not process.start():
            logger.error(f"启动游戏 {game_id} 的安装进程失败")
            active_installations[game_id]['error'] = "启动进程失败"
            active_installations[game_id]['complete'] = True
            return
        
        # 主安装线程等待进程完成
        return_code = process.wait()
        logger.info(f"游戏 {game_id} 安装主进程已结束，返回码: {return_code}")
        
        # 确保安装状态已更新
        if game_id in active_installations:
            active_installations[game_id]['return_code'] = return_code
            active_installations[game_id]['complete'] = True
            active_installations[game_id]['output_file'] = process.output_file
            
    except Exception as e:
        logger.error(f"运行安装进程时出错: {str(e)}")
        if game_id in active_installations:
            active_installations[game_id]['error'] = str(e)
            active_installations[game_id]['complete'] = True
            
        # 向队列添加错误消息
        if game_id in output_queues:
            output_queues[game_id].put({'complete': True, 'status': 'error', 'message': f'安装错误: {str(e)}'})

# 在单独线程中使用PTY运行服务器
def run_game_server(game_id, cmd, cwd):
    """在单独线程中使用PTY运行服务器"""
    logger.info(f"开始使用PTY运行游戏服务器 {game_id}")
    
    try:
        # 准备命令字符串
        logger.info(f"执行命令: {cmd}, 工作目录: {cwd}")
        
        # 生成进程ID
        process_id = f"server_{game_id}"
        logger.info(f"生成进程ID: {process_id}")
        
        # 创建并启动PTY进程
        process = pty_manager.create_process(
            process_id=process_id,
            cmd=cmd,
            cwd=cwd,
            env=dict(os.environ, TERM="xterm"),
            log_prefix=f"game_server_{game_id}"
        )
        
        # 将进程对象和输出队列关联到服务器数据
        if game_id in running_servers:
            running_servers[game_id]['pty_process'] = process
            running_servers[game_id]['process_id'] = process_id
            running_servers[game_id]['running'] = True  # 确保设置运行状态为True
            
            # 创建一个自定义队列，用于保存历史输出
            class HistoryQueue(queue.Queue):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.history = []  # 用于存储历史输出
                    
                def put(self, item, *args, **kwargs):
                    # 保存历史记录
                    if isinstance(item, str):
                        self.history.append(item)
                    super().put(item, *args, **kwargs)
                    
                def get_history(self):
                    return self.history
            
            # 创建保存历史的队列
            history_queue = HistoryQueue()
            server_output_queues[game_id] = history_queue
            
            # 将PTY进程的输出队列转发到历史队列
            def output_forwarder():
                try:
                    logger.info(f"启动输出转发线程: game_id={game_id}")
                    
                    # 先添加一些初始输出，确保有内容显示
                    server_output_queues[game_id].put(f"正在启动 {game_id} 服务器...")
                    
                    add_server_output(game_id, f"正在启动 {game_id} 服务器...")
                    
                    # 添加脚本路径信息
                    script_path = os.path.join(cwd, "start.sh")
                    if os.path.exists(script_path):
                        try:
                            with open(script_path, 'r') as f:
                                script_content = f.read()
                                server_output_queues[game_id].put(f"启动脚本内容: \n{script_content}")
                                add_server_output(game_id, f"启动脚本内容: \n{script_content}")
                        except Exception as e:
                            logger.error(f"读取启动脚本失败: {str(e)}")
                    
                    # 添加一个计数器，用于记录处理的输出行数
                    output_count = 0
                    last_log_time = time.time()
                    
                    # 添加一个测试输出
                    test_message = "输出转发线程已启动，开始监听服务器输出..."
                    server_output_queues[game_id].put(test_message)
                    add_server_output(game_id, test_message)
                    
                    # 持续监听队列
                    while True:
                        try:
                            # 检查进程是否结束
                            if game_id not in running_servers:
                                logger.info(f"游戏服务器 {game_id} 已从running_servers中移除，退出输出转发线程")
                                break
                                
                            if not process.output_queue.empty():
                                item = process.output_queue.get(timeout=0.1)
                                
                                # 处理完成消息
                                if isinstance(item, dict) and item.get('complete'):
                                    status = item.get('status', 'unknown')
                                    message = item.get('message', '未知状态')
                                    
                                    # 进程正常结束
                                    if status == 'success':
                                        end_msg = f"游戏服务器 {game_id} 已正常退出: {message}"
                                        logger.info(end_msg)
                                        server_output_queues[game_id].put(end_msg)
                                        add_server_output(game_id, end_msg)
                                    
                                    # 进程出错
                                    elif status == 'error':
                                        error_details = item.get('error_details', '')
                                        if error_details:
                                            # 如果有详细错误信息，添加到输出
                                            error_msg = f"游戏服务器 {game_id} 启动出错: {message}\n\n详细错误信息:\n{error_details}"
                                        else:
                                            error_msg = f"游戏服务器 {game_id} 启动出错: {message}"
                                            
                                        logger.error(error_msg)
                                        server_output_queues[game_id].put(error_msg)
                                        add_server_output(game_id, error_msg)
                                        running_servers[game_id]['error'] = error_msg
                                    
                                    # 进程被终止
                                    elif status == 'terminated':
                                        stop_msg = f"游戏服务器 {game_id} 已被停止: {message}"
                                        logger.info(stop_msg)
                                        server_output_queues[game_id].put(stop_msg)
                                        add_server_output(game_id, stop_msg)
                                    
                                    # 通知前端进程已结束
                                    complete_message = {
                                        'complete': True, 
                                        'status': status, 
                                        'message': message
                                    }
                                    
                                    # 如果有错误详情，添加到完成消息中
                                    if status == 'error' and item.get('error_details'):
                                        complete_message['error_details'] = item.get('error_details')
                                        
                                    server_output_queues[game_id].put(complete_message)
                                    break
                                    
                                # 处理请求输入的消息
                                elif isinstance(item, dict) and item.get('prompt'):
                                    # 这里处理Steam Guard等需要用户输入的情况
                                    server_output_queues[game_id].put(item)  # 直接转发，前端会处理
                                    add_server_output(game_id, f"请求输入: {item.get('prompt')}")
                                    continue
                                    
                                # 处理常规输出
                                else:
                                    server_output_queues[game_id].put(item)
                                    if isinstance(item, str):
                                        add_server_output(game_id, item)
                                        output_count += 1
                                        
                                        # 定期记录输出状态
                                        current_time = time.time()
                                        if current_time - last_log_time > 60:  # 每分钟记录一次
                                            logger.debug(f"游戏服务器 {game_id} 输出转发线程仍在运行，已处理 {output_count} 行输出")
                                            last_log_time = current_time
                        
                        except queue.Empty:
                            # 队列为空，检查进程是否已结束
                            if hasattr(process, 'poll'):
                                # 如果有poll方法，使用poll方法检查
                                if process.poll() is not None:
                                    logger.info(f"进程已结束，退出输出转发线程: game_id={game_id}")
                                    break
                            elif hasattr(process, 'complete'):
                                # 如果有complete属性，检查complete属性
                                if process.complete:
                                    logger.info(f"进程已完成，退出输出转发线程: game_id={game_id}")
                                    break
                            elif hasattr(process, 'running'):
                                # 如果有running属性，检查running属性
                                if not process.running:
                                    logger.info(f"进程已停止运行，退出输出转发线程: game_id={game_id}")
                                    break
                            else:
                                # 如果都没有，检查process_id是否还在pty_manager中
                                if process_id not in pty_manager.processes:
                                    logger.info(f"进程ID不再存在于PTY管理器中，退出输出转发线程: game_id={game_id}")
                                    break
                        
                        except Exception as e:
                            logger.error(f"处理输出时出错: {str(e)}")
                            error_msg = f"处理输出时出错: {str(e)}"
                            server_output_queues[game_id].put(error_msg)
                            add_server_output(game_id, error_msg)
                
                except Exception as e:
                    logger.error(f"输出转发线程异常: {str(e)}")
                    
                # 添加结束消息
                end_msg = f"输出转发线程结束: game_id={game_id}, 总共处理 {output_count} 行输出"
                logger.info(end_msg)
                server_output_queues[game_id].put(end_msg)
                
                # 如果游戏ID还在running_servers中，添加到输出历史
                if game_id in running_servers:
                    add_server_output(game_id, end_msg)
                    # 标记服务器已停止
                    running_servers[game_id]['running'] = False
                    
                    # 如果不是用户手动停止的，记录自动停止信息
                    if not running_servers[game_id].get('stopped_by_user', False):
                        stop_msg = f"游戏服务器 {game_id} 已自动停止运行"
                        logger.info(stop_msg)
                        server_output_queues[game_id].put(stop_msg)
                        add_server_output(game_id, stop_msg)
                        
                        # 从运行中的服务器字典中移除该游戏服务器
                        logger.info(f"从运行中的服务器列表中移除游戏服务器: {game_id}")
                        del running_servers[game_id]
                        
                        # 确保从PTY管理器中删除进程
                        if pty_manager.get_process(process_id):
                            logger.info(f"从PTY管理器中删除进程: {process_id}")
                            pty_manager.remove_process(process_id)
                
                # 从输出队列字典中移除该游戏服务器（延迟60秒，确保客户端能收到最后的消息）
                def delayed_cleanup():
                    time.sleep(60)  # 延长到60秒
                    if game_id in server_output_queues:
                        logger.info(f"从输出队列列表中移除游戏服务器: {game_id}")
                        del server_output_queues[game_id]
                
                # 启动延迟清理线程
                cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
                cleanup_thread.start()
            
            # 启动输出转发线程
            forwarder_thread = threading.Thread(
                target=output_forwarder,
                daemon=True
            )
            forwarder_thread.start()
            
            logger.info(f"服务器进程已创建，准备启动，process_id={process_id}")
        else:
            logger.error(f"找不到游戏服务器 {game_id} 的运行数据")
            return
        
        # 启动进程
        if not process.start():
            logger.error(f"启动游戏服务器 {game_id} 失败")
            running_servers[game_id]['error'] = "启动进程失败"
            running_servers[game_id]['running'] = False
            return
        
        # 获取进程对象并保存
        try:
            # 获取底层进程并保存
            if hasattr(process, 'process') and process.process:
                running_servers[game_id]['process'] = process.process
                logger.info(f"已保存游戏服务器 {game_id} 的底层进程对象，PID={process.process.pid}")
        except Exception as e:
            logger.warning(f"无法获取游戏服务器 {game_id} 的底层进程对象: {str(e)}")
        
        # 记录进程状态
        logger.info(f"游戏服务器 {game_id} 启动成功，process_id={process_id}")
        
        # 主线程等待进程完成
        return_code = process.wait()
        logger.info(f"游戏服务器 {game_id} 主进程已结束，返回码: {return_code}")
         
        # 确保服务器状态已更新
        if game_id in running_servers:
            running_servers[game_id]['return_code'] = return_code
            running_servers[game_id]['running'] = False
            running_servers[game_id]['output_file'] = process.output_file
            
            # 检查是否有错误信息
            if return_code != 0:
                # 如果进程有错误信息，记录下来
                error_info = process.error if hasattr(process, 'error') and process.error else f"进程返回非零状态码: {return_code}"
                running_servers[game_id]['error'] = error_info
                logger.error(f"启动游戏服务器 {game_id} 时出错: {error_info}")
            
            # 检查是否是异常退出（非人工关闭）
            if game_id not in manually_stopped_servers:
                # 检查是否需要自动重启
                config = load_config()
                auto_restart_servers = config.get('auto_restart_servers', [])
                
                if game_id in auto_restart_servers:
                    if return_code == 0:
                        logger.info(f"游戏服务器 {game_id} 异常退出（非人工停止），自动重启中...")
                    else:
                        logger.info(f"游戏服务器 {game_id} 因错误退出，返回码: {return_code}，自动重启中...")
                    
                    # 在新线程中重启服务器
                    restart_thread = threading.Thread(
                        target=lambda: restart_server(game_id, cwd),
                        daemon=True
                    )
                    restart_thread.start()
                else:
                    if return_code != 0:
                        logger.info(f"游戏服务器 {game_id} 因错误退出，返回码: {return_code}，未配置自动重启")
                    else:
                        logger.info(f"游戏服务器 {game_id} 异常退出，但未配置自动重启")
            else:
                # 从人工停止集合中移除
                manually_stopped_servers.discard(game_id)
                logger.info(f"游戏服务器 {game_id} 人工停止，不进行自动重启，返回码: {return_code}")
            
    except Exception as e:
        logger.error(f"运行服务器进程时出错: {str(e)}")
        if game_id in running_servers:
            running_servers[game_id]['error'] = str(e)
            running_servers[game_id]['running'] = False
            
        # 向队列添加错误消息
        if game_id in server_output_queues:
            error_info = str(e)
            
            # 对于特殊的'MCSERVER'错误，提供更详细的解释
            if "'MCSERVER'" in error_info:
                detailed_error = """
启动游戏服务器失败:
可能的原因:
1. 服务器配置文件缺失或损坏
2. 服务器执行脚本中存在语法错误
3. 启动脚本中的环境变量未正确设置
4. 服务器执行权限不足

建议解决方案:
1. 检查启动脚本的内容，确保语法正确
2. 确认服务器目录下的配置文件是否完整
3. 手动执行启动脚本，查看详细错误信息
4. 检查服务器目录权限，确保steam用户有执行权限
"""
                error_msg = detailed_error
                server_output_queues[game_id].put(error_msg)
                error_details = "MCSERVER环境变量错误或启动脚本执行失败，请检查脚本内容和权限设置"
            else:
                error_msg = f"服务器错误: {error_info}"
                server_output_queues[game_id].put(error_msg)
                error_details = error_info
                
            # 添加完成消息，确保前端能收到详细错误信息
            server_output_queues[game_id].put({
                'complete': True, 
                'status': 'error', 
                'message': f'启动游戏服务器失败: {error_info}', 
                'error_details': error_details
            })
            
            # 也添加为普通消息，确保在输出流中可见
            server_output_queues[game_id].put(f"启动游戏服务器失败: {error_info}")
            
            # 如果是特殊错误，添加详细的故障排除步骤
            if "'MCSERVER'" in error_info:
                server_output_queues[game_id].put("请检查启动脚本内容，确保配置文件完整，并验证执行权限")
                
            # 确保保存到输出历史记录
            if game_id in running_servers and 'output' in running_servers[game_id]:
                add_server_output(game_id, error_msg)
                add_server_output(game_id, "请检查启动脚本内容，确保配置文件完整，并验证执行权限")

# 添加一个新函数来确保目录权限正确
def ensure_steam_permissions(directory):
    """确保目录和子目录的所有者为steam用户"""
    try:
        logger.info(f"正在检查并修复目录权限: {directory}")
        # 使用chown -R steam:steam递归修改目录所有权
        cmd = f"chown -R steam:steam {shlex.quote(directory)}"
        logger.info(f"执行权限修复命令: {cmd}")
        subprocess.run(cmd, shell=True, check=True)
        return True
    except Exception as e:
        logger.error(f"修复目录权限失败: {str(e)}")
        return False

# 简单的错误页面模板
ERROR_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>游戏服务器部署系统</title>
    <style>
        body { font-family: 'Microsoft YaHei', sans-serif; text-align: center; padding: 50px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #1677ff; }
        .error { color: #ff4d4f; margin: 20px 0; }
        .api-list { background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: left; }
    </style>
</head>
<body>
    <div class="container">
        <h1>游戏服务器部署系统</h1>
        <div class="error">
            <p>{{ error_message }}</p>
        </div>
        <div class="api-list">
            <h3>可用API接口：</h3>
            <ul>
                <li><a href="/api/games">/api/games</a> - 获取游戏列表</li>
                <li>/api/install - 安装游戏（POST）</li>
                <li>/api/check_installation?game_id=XXX - 检查安装状态</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    """首页路由"""
    try:
        return send_from_directory('../app/dist', 'index.html')
    except Exception as e:
        return render_template_string(ERROR_PAGE, error_message=f"前端页面未找到：{str(e)}"), 404

@app.route('/<path:path>')
def static_files(path):
    """静态文件路由"""
    try:
        # 如果请求的是API路径，不进行处理，让后续的路由处理
        if path.startswith('api/'):
            return None
            
        # 检查是否存在对应的静态文件
        file_path = os.path.join('../app/dist', path)
        if os.path.isfile(file_path):
            return send_from_directory('../app/dist', path)
        
        # 如果不是静态文件，返回index.html给前端路由处理
        return send_from_directory('../app/dist', 'index.html')
    except Exception as e:
        # 遇到错误也返回index.html，让前端路由处理
        return send_from_directory('../app/dist', 'index.html')

@app.route('/api/games', methods=['GET'])
def get_games():
    """获取所有可安装的游戏列表"""
    try:
        logger.debug("获取游戏列表")
        
        # 检查赞助者身份
        validator = get_sponsor_validator()
        cloud_error = None
        
        # 如果有赞助者密钥，尝试从云端获取游戏列表
        if validator.has_sponsor_key():
            try:
                # 设置5秒超时
                cloud_games = validator.fetch_cloud_games()
                if cloud_games:
                    logger.info(f"从云端获取到 {len(cloud_games)} 个游戏")
                    return jsonify({'status': 'success', 'games': cloud_games, 'source': 'cloud'})
            except Exception as cloud_err:
                logger.error(f"从云端获取游戏列表失败: {str(cloud_err)}")
                # 记录错误信息，但继续使用本地列表
                cloud_error = str(cloud_err)
        
        # 使用本地游戏列表
        games = load_games_config()
        game_list = []
        
        for game_id, game_info in games.items():
            game_list.append({
                'id': game_id,
                'name': game_info.get('game_nameCN', game_id),
                'appid': game_info.get('appid'),
                'anonymous': game_info.get('anonymous', True),
                'has_script': game_info.get('script', False),
                'tip': game_info.get('tip', ''),
                'image': game_info.get('image', ''),
                'url': game_info.get('url', '')
            })
        
        logger.info(f"从本地找到 {len(game_list)} 个游戏")
        response_data = {
            'status': 'success', 
            'games': game_list, 
            'source': 'local'
        }
        
        # 如果有云端错误，添加到响应中
        if cloud_error:
            response_data['cloud_error'] = cloud_error
            
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"获取游戏列表失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 导入赞助者验证模块
from sponsor_validator import get_sponsor_validator

def fetch_cloud_games(sponsor_key):
    """从云端获取游戏列表"""
    try:
        validator = get_sponsor_validator()
        return validator.fetch_cloud_games(sponsor_key)
    except Exception as e:
        logger.error(f"获取云端游戏列表失败: {str(e)}")
        raise

@app.route('/api/install', methods=['POST'])
def install_game():
    """安装游戏 - 只启动安装进程并返回，不等待完成"""
    try:
        data = request.json
        game_id = data.get('game_id')
        account = data.get('account')
        password = data.get('password')
        if not game_id:
            logger.error("缺少游戏ID")
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
        logger.info(f"请求安装游戏: {game_id}")
        
        # 获取游戏信息 - 首先尝试从云端获取
        validator = get_sponsor_validator()
        game_info = None
        script_name = None
        
        # 如果有赞助者凭证，尝试从云端获取游戏信息
        if validator.has_sponsor_key():
            try:
                cloud_games = validator.fetch_cloud_games()
                if cloud_games:
                    # 查找指定游戏
                    for game in cloud_games:
                        if game['id'] == game_id:
                            game_info = game
                            script_name = game.get('script_name')
                            logger.info(f"从云端获取到游戏 {game_id} 的信息")
                            break
            except Exception as cloud_err:
                logger.error(f"从云端获取游戏 {game_id} 信息失败: {str(cloud_err)}")
        
        # 如果没有从云端获取到，则从本地配置获取
        if not game_info:
            games = load_games_config()
            if game_id not in games:
                logger.error(f"游戏不存在: {game_id}")
                return jsonify({'status': 'error', 'message': f'游戏 {game_id} 不存在'}), 404
            game_info = games[game_id]
            script_name = game_info.get('script_name')
        
        # 如果已经有正在运行的安装进程，则返回
        if game_id in active_installations and active_installations[game_id].get('process') and active_installations[game_id]['process'].poll() is None:
            logger.info(f"游戏 {game_id} 已经在安装中")
            return jsonify({
                'status': 'success', 
                'message': f'游戏 {game_id} 已经在安装中'
            })
            
        # 清理任何旧的安装数据
        if game_id in active_installations:
            logger.info(f"清理游戏 {game_id} 的旧安装数据")
            old_process = active_installations[game_id].get('process')
            if old_process and old_process.poll() is None:
                try:
                    old_process.terminate()
                except:
                    pass
                    
        # 重置输出队列
        if game_id in output_queues:
            try:
                while not output_queues[game_id].empty():
                    output_queues[game_id].get_nowait()
            except:
                output_queues[game_id] = queue.Queue()
        else:
            output_queues[game_id] = queue.Queue()
            
        # 如果是从云端获取的游戏信息，需要将脚本内容保存到本地临时文件
        if script_name and game_info.get('has_script', False) and game_info.get('script', False):
            try:
                # 确保游戏目录存在
                game_dir = os.path.join(GAMES_DIR, game_id)
                os.makedirs(game_dir, exist_ok=True)
                
                # 保存脚本到临时文件
                script_path = os.path.join(game_dir, "cloud_script.sh")
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script_name)
                    
                # 设置可执行权限
                os.chmod(script_path, 0o755)
                logger.info(f"已保存云端脚本到 {script_path}")
            except Exception as script_err:
                logger.error(f"保存云端脚本失败: {str(script_err)}")
                
        # 构建安装命令 (确保以steam用户运行)
        cmd = f"su - steam -c 'python3 {INSTALLER_SCRIPT} {game_id}"
        if account:
            cmd += f" --account {shlex.quote(account)}"
        if password:
            cmd += f" --password {shlex.quote(password)}"
        cmd += " 2>&1'"
        logger.info(f"准备执行命令 (将使用PTY): {cmd}")
        
        # 初始化安装状态跟踪
        active_installations[game_id] = {
            'process': None,
            'output': [],
            'started_at': time.time(),
            'complete': False,
            'cmd': cmd
        }
        
        # 在单独的线程中启动安装进程
        install_thread = threading.Thread(
            target=run_installation,
            args=(game_id, cmd),
            daemon=True
        )
        install_thread.start()
        
        # 添加一个确保安装后权限正确的线程
        def check_and_fix_permissions():
            # 等待安装进程完成
            install_thread.join(timeout=3600)  # 最多等待1小时
            # 检查安装是否已完成
            if game_id in active_installations and active_installations[game_id].get('complete'):
                # 安装完成后，确保游戏目录权限正确
                game_dir = os.path.join(GAMES_DIR, game_id)
                if os.path.exists(game_dir):
                    logger.info(f"安装完成，修复游戏目录权限: {game_dir}")
                    ensure_steam_permissions(game_dir)
                    
        # 启动权限修复线程
        permission_thread = threading.Thread(
            target=check_and_fix_permissions,
            daemon=True
        )
        permission_thread.start()
        
        logger.info(f"游戏 {game_id} 安装进程已启动")
        
        return jsonify({
            'status': 'success', 
            'message': f'游戏 {game_id} 安装已开始'
        })
    except Exception as e:
        logger.error(f"启动安装进程失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/install_stream', methods=['GET', 'POST'])
def install_game_stream():
    """以流式方式获取安装进度"""
    try:
        # 尝试从POST请求体获取游戏ID
        if request.method == 'POST' and request.is_json:
            data = request.json
            game_id = data.get('game_id')
        else:
            # 尝试从GET参数获取游戏ID
            game_id = request.args.get('game_id')
        
        if not game_id:
            logger.error("流式获取安装进度时缺少游戏ID")
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
        
        logger.info(f"开始流式获取游戏 {game_id} 的安装进度")
        
        # 检查游戏是否存在于配置中，对于以app_开头的ID，不进行检查
        games = load_games_config()
        if not game_id.startswith('app_') and game_id not in games:
            logger.error(f"游戏不存在: {game_id}")
            return jsonify({'status': 'error', 'message': f'游戏 {game_id} 不存在'}), 404

        # 检查是否有正在进行的安装进程
        if game_id not in active_installations:
            logger.error(f"游戏 {game_id} 没有活跃的安装任务")
            return jsonify({'status': 'error', 'message': f'游戏 {game_id} 没有活跃的安装任务'}), 404
        
        # 确保有队列
        if game_id not in output_queues:
            output_queues[game_id] = queue.Queue()
            
            # 如果安装已完成，但没有队列，添加完成消息
            installation_data = active_installations[game_id]
            if installation_data.get('complete', False):
                status = 'success' if installation_data.get('return_code', 1) == 0 else 'error'
                message = installation_data.get('final_message', f'游戏 {game_id} 安装已完成')
                output_queues[game_id].put({'complete': True, 'status': status, 'message': message})
                
                # 同时把历史输出添加到队列
                for line in installation_data.get('output', []):
                    output_queues[game_id].put(line)
        
        # 使用队列传输数据
        def generate():
            installation_data = active_installations[game_id]
            output_queue = output_queues[game_id]
            
            # 发送所有已有的输出
            logger.info(f"准备发送游戏 {game_id} 的安装输出")
            
            # 马上发送一条测试消息，验证流正常工作
            yield f"data: {json.dumps({'line': '建立连接成功，开始接收实时安装进度...'})}\n\n"
            
            # 超时设置
            timeout_seconds = 300  # 5分钟无输出则超时
            last_output_time = time.time()
            heartbeat_interval = 10  # 每10秒发送一次心跳
            next_heartbeat = time.time() + heartbeat_interval
            
            # 持续监听队列
            while True:
                try:
                    # 尝试获取队列中的数据，最多等待1秒
                    try:
                        item = output_queue.get(timeout=1)
                        last_output_time = time.time()  # 重置超时时间
                        
                        # 处理完成消息
                        if isinstance(item, dict) and item.get('complete', False):
                            # logger.debug(f"发送安装完成消息: {item.get('message', '')}")
                            yield f"data: {json.dumps(item)}\n\n"
                            break
                        
                        # 处理 prompt 消息
                        if isinstance(item, dict) and item.get('prompt'):
                            # logger.debug(f"发送prompt消息: {item.get('prompt')}")
                            yield f"data: {json.dumps(item)}\n\n"
                            continue
                        
                        # 处理普通输出
                        if isinstance(item, str):
                            # logger.debug(f"发送输出: {item}")
                            yield f"data: {json.dumps({'line': item})}\n\n"
                        
                    except queue.Empty:
                        # 心跳检查
                        current_time = time.time()
                        if current_time >= next_heartbeat:
                            logger.debug(f"发送心跳包: game_id={game_id}")
                            yield f"data: {json.dumps({'heartbeat': True, 'timestamp': current_time})}\n\n"
                            next_heartbeat = current_time + heartbeat_interval
                        
                        # 检查是否超时
                        if time.time() - last_output_time > timeout_seconds:
                            logger.warning(f"游戏 {game_id} 的安装流超过 {timeout_seconds}秒 无输出，结束连接")
                            yield f"data: {json.dumps({'line': '安装流超时，请刷新页面查看最新状态'})}\n\n"
                            yield f"data: {json.dumps({'complete': True, 'status': 'warning', 'message': '安装流超时'})}\n\n"
                            break
                        
                        # 检查进程是否结束但未发送完成消息
                        process = installation_data.get('process')
                        if process and process.poll() is not None and installation_data.get('complete', False):
                            logger.warn(f"进程已结束但未发送完成消息，发送完成状态")
                            status = 'success' if installation_data.get('return_code', 1) == 0 else 'error'
                            message = installation_data.get('final_message', f'游戏 {game_id} 安装已完成')
                            yield f"data: {json.dumps({'complete': True, 'status': status, 'message': message})}\n\n"
                            break
                        
                        continue
                
                except Exception as e:
                    logger.error(f"生成流数据时出错: {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    break
        
        return Response(stream_with_context(generate()), 
                       mimetype='text/event-stream',
                       headers={
                           'Cache-Control': 'no-cache',
                           'X-Accel-Buffering': 'no'  # 禁用Nginx缓冲
                       })
            
    except Exception as e:
        logger.error(f"安装流处理错误: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/check_installation', methods=['GET'])
def check_installation():
    """检查游戏是否已安装"""
    game_id = request.args.get('game_id')
    if not game_id:
        return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
    
    logger.debug(f"检查游戏 {game_id} 是否已安装")
    
    games_dir = "/home/steam/games"
    game_dir = os.path.join(games_dir, game_id)
    
    if os.path.exists(game_dir) and os.path.isdir(game_dir):
        # 检查目录是否不为空
        if os.listdir(game_dir):
            logger.debug(f"游戏 {game_id} 已安装")
            return jsonify({'status': 'success', 'installed': True})
    
    logger.debug(f"游戏 {game_id} 未安装")
    return jsonify({'status': 'success', 'installed': False})

@app.route('/api/batch_check_installation', methods=['POST'])
def batch_check_installation():
    """批量检查多个游戏是否已安装"""
    try:
        data = request.json
        game_ids = data.get('game_ids', [])
        
        if not game_ids:
            return jsonify({'status': 'error', 'message': '缺少游戏ID列表'}), 400
        
        logger.debug(f"批量检查游戏安装状态: {game_ids}")
        
        games_dir = "/home/steam/games"
        result = {}
        
        for game_id in game_ids:
            game_dir = os.path.join(games_dir, game_id)
            
            if os.path.exists(game_dir) and os.path.isdir(game_dir):
                # 检查目录是否不为空
                if os.listdir(game_dir):
                    result[game_id] = True
                    continue
            
            result[game_id] = False
        
        return jsonify({'status': 'success', 'installations': result})
        
    except Exception as e:
        logger.error(f"批量检查游戏安装状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/installation_status', methods=['GET'])
def installation_status():
    """获取所有安装任务的状态"""
    try:
        game_id = request.args.get('game_id')
        
        if game_id:
            # 获取特定游戏的安装状态
            if game_id not in active_installations:
                return jsonify({'status': 'error', 'message': f'没有找到游戏 {game_id} 的安装任务'}), 404
            
            install_data = active_installations[game_id]
            return jsonify({
                'status': 'success',
                'installation': {
                    'game_id': game_id,
                    'started_at': install_data.get('started_at'),
                    'complete': install_data.get('complete', False),
                    'return_code': install_data.get('return_code'),
                    'output_length': len(install_data.get('output', [])),
                    'error': install_data.get('error')
                }
            })
        else:
            # 获取所有安装任务的状态
            installations = {}
            for game_id, install_data in active_installations.items():
                installations[game_id] = {
                    'started_at': install_data.get('started_at'),
                    'complete': install_data.get('complete', False),
                    'return_code': install_data.get('return_code'),
                    'output_length': len(install_data.get('output', [])),
                    'error': install_data.get('error')
                }
            
            return jsonify({
                'status': 'success',
                'installations': installations
            })
    
    except Exception as e:
        logger.error(f"获取安装状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/installed_games', methods=['GET'])
def get_installed_games():
    """检测 /home/steam/games 下的文件夹，返回所有已安装的游戏ID列表和外部游戏"""
    try:
        games_config = load_games_config()
        all_game_ids = set(games_config.keys())
        
        if not os.path.exists(GAMES_DIR):
            return jsonify({'status': 'success', 'installed': [], 'external': []})
            
        installed = []
        external = []
        
        for name in os.listdir(GAMES_DIR):
            path = os.path.join(GAMES_DIR, name)
            if os.path.isdir(path):
                if name in all_game_ids:
                    # 配置中已有的游戏
                    installed.append(name)
                else:
                    # 配置中没有的外部游戏
                    external.append({
                        'id': name,
                        'name': name,  # 使用文件夹名作为游戏名
                        'external': True
                    })
        
        return jsonify({
            'status': 'success', 
            'installed': installed,
            'external': external
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/uninstall', methods=['POST'])
def uninstall_game():
    """卸载游戏，删除/home/steam/games/游戏名目录"""
    try:
        data = request.json
        game_id = data.get('game_id')
        if not game_id:
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        # 不再要求游戏必须在配置中
        games_config = load_games_config()
        is_external = game_id not in games_config
        
        game_dir = os.path.join(GAMES_DIR, game_id)
        if not os.path.exists(game_dir):
            return jsonify({'status': 'error', 'message': '游戏目录不存在'}), 404
        
        # 如果游戏服务器正在运行，先停止它
        if game_id in running_servers:
            process = running_servers[game_id].get('process')
            if process and process.poll() is None:
                logger.info(f"游戏服务器 {game_id} 正在运行，先停止它")
                try:
                    # 发送终止信号
                    process.terminate()
                    # 等待进程终止，最多等待5秒
                    for _ in range(10):
                        if process.poll() is not None:
                            break
                        time.sleep(0.5)
                    # 如果仍未终止，强制终止
                    if process.poll() is None:
                        process.kill()
                except Exception as e:
                    logger.error(f"停止游戏服务器 {game_id} 时出错: {str(e)}")
                    
        # 直接删除游戏目录
        logger.info(f"直接删除游戏目录: {game_dir}")
        shutil.rmtree(game_dir)
            
        # 清理服务器状态
        if game_id in running_servers:
            running_servers.pop(game_id)
            
        # 清理输出队列
        if game_id in server_output_queues:
            server_output_queues.pop(game_id)
            
        return jsonify({
            'status': 'success', 
            'message': f'游戏{" (外部)" if is_external else ""} {game_id} 已卸载'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/send_input', methods=['POST'])
def send_input():
    data = request.json
    game_id = data.get('game_id')
    value = data.get('value')
    if not game_id or value is None:
        return jsonify({'status': 'error', 'message': '缺少参数'}), 400
    
    # 使用PTY管理器设置输入值
    process_id = f"install_{game_id}"
    if pty_manager.set_input_value(process_id, value):
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': '无等待输入的进程'}), 404

@app.route('/api/server/start', methods=['POST'])
def start_game_server():
    """启动游戏服务器"""
    try:
        data = request.json
        game_id = data.get('game_id')
        script_name = data.get('script_name')  # 用于指定要执行的脚本
        reconnect = data.get('reconnect', False)  # 新增参数，标识是否为重连
        
        if not game_id:
            logger.error("缺少游戏ID")
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        logger.info(f"请求启动游戏服务器: {game_id}" + (f", 指定脚本: {script_name}" if script_name else "") + (", 重连模式" if reconnect else ""))
        
        # 检查游戏是否存在于配置中
        games = load_games_config()
        is_external_game = False
        
        if game_id not in games:
            logger.warning(f"游戏 {game_id} 不在配置列表中，作为外部游戏处理")
            is_external_game = True
            
        # 检查游戏是否已安装
        game_dir = os.path.join(GAMES_DIR, game_id)
        if not os.path.exists(game_dir) or not os.path.isdir(game_dir):
            logger.error(f"游戏 {game_id} 未安装")
            return jsonify({'status': 'error', 'message': f'游戏 {game_id} 未安装'}), 400
        
        # 查找所有可执行的sh脚本
        available_scripts = []
        for file in os.listdir(game_dir):
            file_path = os.path.join(game_dir, file)
            if file.endswith('.sh') and os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                available_scripts.append(file)
        
        # 如果没有可执行脚本，返回错误
        if not available_scripts:
            logger.error(f"游戏 {game_id} 目录下没有可执行的sh脚本")
            return jsonify({'status': 'error', 'message': f'游戏 {game_id} 目录下没有可执行的sh脚本，请确保有至少一个.sh文件并具有执行权限'}), 400
        
        # 尝试获取上次使用的脚本名称
        last_script_path = os.path.join(game_dir, '.last_script')
        last_script = None
        if os.path.exists(last_script_path):
            try:
                with open(last_script_path, 'r') as f:
                    last_script = f.read().strip()
                    if last_script and last_script in available_scripts:
                        logger.info(f"找到上次使用的脚本: {last_script}")
                    else:
                        last_script = None
            except Exception as e:
                logger.warning(f"读取上次使用的脚本失败: {str(e)}")
                last_script = None
        
        # 确定要执行的脚本
        selected_script = None
        
        # 如果指定了脚本名称，优先使用
        if script_name and script_name in available_scripts:
            selected_script = script_name
            logger.info(f"使用指定的脚本: {selected_script}")
        # 否则，如果是重连模式且有上次使用的脚本，使用上次的脚本
        elif reconnect and last_script:
            selected_script = last_script
            logger.info(f"重连模式，使用上次的脚本: {selected_script}")
        # 如果只有一个脚本，直接使用
        elif len(available_scripts) == 1:
            selected_script = available_scripts[0]
            logger.info(f"只有一个脚本，直接使用: {selected_script}")
        # 否则，如果有上次使用的脚本，使用上次的脚本
        elif last_script:
            selected_script = last_script
            logger.info(f"使用上次的脚本: {selected_script}")
        # 如果有多个脚本但没有确定使用哪个，返回可选脚本列表
        elif len(available_scripts) > 1:
            logger.info(f"游戏 {game_id} 有多个可执行脚本: {available_scripts}，需要用户选择")
            return jsonify({
                'status': 'multiple_scripts',
                'message': f'游戏 {game_id} 有多个可执行脚本，请选择一个',
                'scripts': available_scripts,
                'reconnect': reconnect
            })
        
        # 如果没有确定脚本（理论上不会到这里）
        if not selected_script:
            logger.error(f"无法确定要执行的脚本")
            return jsonify({'status': 'error', 'message': f'无法确定要执行的脚本'}), 400
        
        # 保存选择的脚本名称，供下次使用
        try:
            with open(last_script_path, 'w') as f:
                f.write(selected_script)
            logger.info(f"已保存脚本选择: {selected_script}")
        except Exception as e:
            logger.warning(f"保存脚本选择失败: {str(e)}")
        
        # 确定要执行的脚本路径
        start_script = os.path.join(game_dir, selected_script)
        
        # 确保启动脚本有执行权限
        if not os.access(start_script, os.X_OK):
            logger.info(f"添加启动脚本执行权限: {start_script}")
            os.chmod(start_script, 0o755)
            
        # 确保游戏目录的所有者为steam用户
        ensure_steam_permissions(game_dir)
            
        # 检查是否有正在运行的服务器进程
        process_id = f"server_{game_id}"
        
        existing_pty_proc = pty_manager.get_process(process_id)
        server_running_in_rs = False
        rs_process_obj = None

        if game_id in running_servers:
            server_data_rs = running_servers[game_id]
            rs_process_obj = server_data_rs.get('process') # This is the subprocess.Popen object
            rs_pty_process_obj = server_data_rs.get('pty_process') # This is the PTYProcess object from pty_manager

            if rs_process_obj and rs_process_obj.poll() is None:
                server_running_in_rs = True
            
            # Consistency check: if running_servers has a pty_process, it should match existing_pty_proc
            if existing_pty_proc and rs_pty_process_obj and existing_pty_proc is not rs_pty_process_obj:
                logger.warning(f"Inconsistency: PTYManager has process {process_id}, running_servers has a DIFFERENT pty_process object for {game_id}. Will prioritize PTYManager's if it's running, or clean up.")
                # This scenario might require more specific handling if existing_pty_proc is also running.
                # For now, if existing_pty_proc is running, we might assume it's the more current one.

        if existing_pty_proc:
            logger.info(f"PTY管理器中已存在进程ID {process_id}的记录。")
            if existing_pty_proc.is_running():
                logger.info(f"PTY进程 {process_id} 报告正在运行。")
                # Now check if this matches what running_servers thinks
                if server_running_in_rs and rs_process_obj == existing_pty_proc.process and running_servers[game_id].get('pty_process') == existing_pty_proc:
                    logger.info(f"游戏服务器 {game_id} (PTY: {process_id}, Subprocess PID: {rs_process_obj.pid}) 确认已在运行中，且状态一致。")
                    return jsonify({
                        'status': 'success',
                        'message': f'游戏服务器 {game_id} 已经在运行中',
                        'already_running': True
                    })
                else:
                    # PTY manager has a running process, but running_servers either doesn't know,
                    # or has conflicting info, or its PTYProcess object is different.
                    # This is a problematic state. Safest is to stop the PTY process and restart.
                    logger.warning(f"状态不一致: PTY进程 {process_id} 在运行，但与running_servers记录不符或对象不同。将尝试终止并清理。")
                    pty_manager.terminate_process(process_id, force=True)
                    pty_manager.remove_process(process_id)
                    if game_id in running_servers:
                        del running_servers[game_id]
                    # Fall through to normal startup logic
            else:
                logger.info(f"PTY进程 {process_id} 存在但未运行。将移除此无效PTY记录。")
                pty_manager.remove_process(process_id)
                # Also clean from running_servers if it's there and refers to this dead PTY
                if game_id in running_servers and running_servers[game_id].get('pty_process') == existing_pty_proc:
                    logger.info(f"同时从running_servers中清理与此无效PTY进程相关的记录: {game_id}")
                    del running_servers[game_id]
                # Fall through to normal startup logic
        
        # If PTY manager didn't have it, or it was cleaned up, check running_servers independently
        if game_id in running_servers:
            server_data = running_servers[game_id]
            process = server_data.get('process') # Subprocess.Popen object
            # rs_pty_obj = server_data.get('pty_process') # PTYProcess object

            if process and process.poll() is None:
                # Process is running according to running_servers, but PTY manager either didn't know or its record was bad.
                # This is also an inconsistent state. The process is running外国 PTY manager control.
                logger.warning(f"状态不一致: running_servers中游戏 {game_id} (PID: {process.pid})在运行, 但PTY管理器无有效/活动记录.")
                logger.warning("这可能是一个失去PTY控制的进程。建议停止此进程并重新启动服务。")
                # For now, to prevent duplicate starts, we can still return 'already_running',
                # but commands to it will fail due to no PTY. User needs to stop/start via UI.
                # OR, we could try to kill it and restart cleanly.
                # Let's choose to kill it for better consistency.
                logger.info(f"尝试终止在running_servers中但无有效PTY的进程 PID: {process.pid}")
                try:
                    parent = psutil.Process(process.pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try: child.kill() 
                        except: pass
                    parent.kill()
                    logger.info(f"已终止进程 PID: {process.pid} 及其子进程。")
                except Exception as e_kill:
                    logger.error(f"终止进程 PID {process.pid} 失败: {e_kill}")
                
                del running_servers[game_id] # Clean up the stale entry
                # Fall through to normal startup logic to start fresh
            elif process and process.poll() is not None:
                # Process in running_servers is dead
                logger.info(f"清理游戏服务器 {game_id} 的旧已停止运行数据 (来自running_servers)。")
                del running_servers[game_id]
            # If no process in running_servers entry, or entry doesn't exist, that's fine, continue to start.

        # 检查系统中是否有同名进程在运行
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.cmdline()
                    script_name_to_check = os.path.basename(start_script)
                    if len(cmdline) > 1 and game_id in ' '.join(cmdline) and f'./{script_name_to_check}' in ' '.join(cmdline):
                        logger.warning(f"发现系统中可能有相关进程正在运行: PID={proc.pid}, CMD={' '.join(cmdline)}")
                        # 尝试终止这个进程
                        try:
                            proc.terminate()
                            logger.info(f"已终止可能相关的进程: PID={proc.pid}")
                        except:
                            logger.warning(f"无法终止可能相关的进程: PID={proc.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            logger.warning(f"检查系统进程时出错: {str(e)}")
            
        # 清理任何旧的服务器数据
        logger.info(f"清理游戏服务器 {game_id} 的旧运行数据")
        
        # 清理输出队列
        if game_id in server_output_queues:
            try:
                while not server_output_queues[game_id].empty():
                    server_output_queues[game_id].get_nowait()
            except:
                server_output_queues[game_id] = queue.Queue()
        else:
            server_output_queues[game_id] = queue.Queue()
            
        # 读取启动脚本内容
        try:
            with open(start_script, 'r') as f:
                script_content = f.read()
                logger.debug(f"启动脚本内容: \n{script_content}")
        except Exception as e:
            logger.warning(f"读取启动脚本失败: {str(e)}")
            
        # 构建启动命令，确保以steam用户运行
        script_name_to_run = os.path.basename(start_script)
        cmd = f"su - steam -c 'cd {game_dir} && ./{script_name_to_run}'"
        logger.debug(f"准备执行命令 (将使用PTY): {cmd}")
        
        # 初始化服务器状态跟踪
        running_servers[game_id] = {
            'process': None,
            'output': [],
            'started_at': time.time(),
            'running': True,
            'return_code': None,
            'cmd': cmd,
            'master_fd': None,
            'game_dir': game_dir,
            'external': is_external_game,  # 添加外部游戏标记
            'script_name': script_name_to_run  # 记录使用的脚本名称
        }
        
        # 在单独的线程中启动服务器
        server_thread = threading.Thread(
            target=run_game_server,
            args=(game_id, cmd, game_dir),
            daemon=True
        )
        server_thread.start()
        
        logger.info(f"游戏服务器 {game_id} 启动线程已启动，使用脚本: {script_name_to_run}")
        time.sleep(0.5)
        
        # 确保队列存在并放入初始消息
        if game_id not in server_output_queues:
            # 理论上队列应该由run_game_server或其内部的output_forwarder创建
            logger.warning(f"在start_game_server中发现游戏 {game_id} 的server_output_queue不存在，将创建一个新的。")
            server_output_queues[game_id] = queue.Queue()
            
        server_output_queues[game_id].put("服务器启动中...")
        server_output_queues[game_id].put(f"游戏目录: {game_dir}")
        server_output_queues[game_id].put(f"启动脚本: {script_name_to_run}")
        server_output_queues[game_id].put(f"启动命令: {cmd}")
        
        # 添加到输出历史 - 只有当服务器记录仍然存在时
        if game_id in running_servers:
            if 'output' not in running_servers[game_id]:
                running_servers[game_id]['output'] = []
            add_server_output(game_id, "服务器启动中...")
            add_server_output(game_id, f"游戏目录: {game_dir}")
            add_server_output(game_id, f"启动脚本: {script_name_to_run}")
            add_server_output(game_id, f"启动命令: {cmd}")
        else:
            logger.warning(f"游戏服务器 {game_id} 在尝试记录初始启动信息到running_servers时已不存在。可能已快速失败。")
        
        return jsonify({
            'status': 'success', 
            'message': f'游戏服务器 {game_id} 启动已开始',
            'script_name': script_name_to_run
        })
        
    except Exception as e:
        logger.error(f"启动游戏服务器失败: {str(e)}")
        
        # 保存临时错误信息，供服务器流API使用
        if not hasattr(app, 'temp_server_errors'):
            app.temp_server_errors = {}
        app.temp_server_errors[game_id] = {
            'message': f'启动游戏服务器失败: {str(e)}',
            'details': str(e),
            'timestamp': time.time()
        }
        
        # 如果游戏ID已经在running_servers中，添加错误信息
        if game_id in running_servers:
            running_servers[game_id]['error'] = str(e)
            running_servers[game_id]['running'] = False
            
            # 向队列添加错误消息
            if game_id in server_output_queues:
                error_msg = f'服务器启动错误: {str(e)}'
                server_output_queues[game_id].put(error_msg)
                server_output_queues[game_id].put({'complete': True, 'status': 'error', 'message': error_msg})
        
        # 返回200状态码但带有错误信息，避免前端收到500错误
        return jsonify({
            'status': 'error', 
            'message': f'启动游戏服务器失败: {str(e)}',
            'error_details': str(e)
        })

@app.route('/api/terminate_install', methods=['POST'])
def terminate_install():
    """终止游戏安装进程"""
    try:
        data = request.json
        game_id = data.get('game_id')
        
        if not game_id:
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        logger.info(f"请求终止游戏 {game_id} 的安装进程")
        
        # 检查游戏是否正在安装
        if game_id not in active_installations:
            # 游戏未在安装中，返回成功状态
            logger.info(f"游戏 {game_id} 未在安装中，但仍返回成功状态")
            return jsonify({'status': 'success', 'message': f'游戏 {game_id} 未在安装中'})
            
        installation_data = active_installations[game_id]
        
        # 如果已经完成，则直接返回
        if installation_data.get('complete', False):
            logger.info(f"游戏 {game_id} 安装已完成，无需终止")
            return jsonify({'status': 'success', 'message': f'游戏 {game_id} 安装已完成'})
            
        # 尝试获取PTY进程对象
        pty_process = installation_data.get('pty_process')
        process_id = f"install_{game_id}"
        
        # 记录详细的进程信息
        logger.info(f"进程信息: process_id={process_id}, pty_process存在={pty_process is not None}")
        if pty_process:
            logger.info(f"PTY进程状态: running={pty_process.running}, complete={pty_process.complete}")
        
        # 尝试使用PTY管理器终止进程
        logger.info(f"尝试使用PTY管理器终止进程: {process_id}")
        pty_result = False
        
        # 首先尝试通过进程ID终止
        if pty_manager.get_process(process_id):
            logger.info(f"在pty_manager中找到进程: {process_id}")
            pty_result = pty_manager.terminate_process(process_id, force=True)
        # 如果通过ID终止失败，但我们有进程对象，直接终止它
        elif pty_process:
            logger.info(f"直接终止PTY进程对象")
            pty_result = pty_process.terminate(force=True)
        
        if pty_result:
            logger.info(f"成功终止进程: {process_id}")
            # 更新安装状态
            installation_data['complete'] = True
            installation_data['terminated'] = True
            installation_data['error'] = "安装被用户终止"
            
            # 向队列添加终止消息
            if game_id in output_queues:
                output_queues[game_id].put({'complete': True, 'status': 'terminated', 'message': f'游戏 {game_id} 安装已被用户终止'})
                
            return jsonify({'status': 'success', 'message': f'游戏 {game_id} 安装已终止'})
        else:
            logger.warning(f"使用PTY管理器终止进程失败，尝试使用备选方案: {process_id}")
            
            # 尝试直接终止进程
            try:
                # 检查是否有进程对象
                process = installation_data.get('process')
                if process and process.poll() is None:
                    logger.info(f"尝试直接终止进程 PID: {process.pid}")
                    try:
                        # 找到所有子进程并终止
                        parent = psutil.Process(process.pid)
                        children = parent.children(recursive=True)
                        
                        # 首先杀死所有子进程
                        for child in children:
                            logger.info(f"杀死子进程: {child.pid}")
                            try:
                                child.kill()
                            except:
                                pass
                        
                        # 然后杀死主进程
                        parent.kill()
                        logger.info(f"已杀死进程及其子进程")
                        
                        # 更新安装状态
                        installation_data['complete'] = True
                        installation_data['terminated'] = True
                        installation_data['error'] = "安装被用户强制终止"
                        
                        # 向队列添加终止消息
                        if game_id in output_queues:
                            output_queues[game_id].put({'complete': True, 'status': 'terminated', 'message': f'游戏 {game_id} 安装已被用户强制终止'})
                        
                        return jsonify({'status': 'success', 'message': f'游戏 {game_id} 安装已强制终止'})
                    except Exception as e:
                        logger.error(f"直接终止进程失败: {str(e)}")
                else:
                    logger.warning(f"没有找到活动的进程对象")
                    
                # 即使无法终止进程，也标记为完成
                installation_data['complete'] = True
                installation_data['terminated'] = True
                installation_data['error'] = "尝试终止安装，但无法找到进程"
                
                # 向队列添加终止消息
                if game_id in output_queues:
                    output_queues[game_id].put({'complete': True, 'status': 'warning', 'message': f'游戏 {game_id} 安装标记为终止，但可能仍在后台运行'})
                
                return jsonify({'status': 'warning', 'message': f'游戏 {game_id} 安装标记为终止，但可能仍在后台运行'})
            except Exception as e:
                logger.error(f"备选终止方案失败: {str(e)}")
                return jsonify({'status': 'error', 'message': f'无法终止游戏 {game_id} 的安装进程: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"终止安装进程失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/server/stop', methods=['POST'])
def stop_game_server():
    """停止游戏服务器"""
    try:
        data = request.json
        game_id = data.get('game_id')
        force = data.get('force', False)  # 是否强制停止
        
        if not game_id:
            logger.error("缺少游戏ID")
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        logger.info(f"请求停止游戏服务器: {game_id}, 强制模式: {force}")
        
        # 将此服务器标记为人工停止
        manually_stopped_servers.add(game_id)
        logger.info(f"已将游戏服务器 {game_id} 标记为人工停止")
        
        # 检查游戏服务器是否在运行
        if game_id not in running_servers:
            logger.error(f"游戏服务器 {game_id} 未运行")
            return jsonify({'status': 'error', 'message': f'游戏服务器 {game_id} 未运行'}), 400
            
        # 尝试获取PTY进程对象
        server_data = running_servers[game_id]
        pty_process = server_data.get('pty_process')
        process_id = server_data.get('process_id') or f"server_{game_id}"
        
        # 记录详细的进程信息
        logger.info(f"进程信息: process_id={process_id}, pty_process存在={pty_process is not None}")
        if pty_process:
            logger.info(f"PTY进程状态: running={pty_process.running}, complete={pty_process.complete}")
        
        # 尝试使用PTY管理器终止进程
        logger.info(f"尝试使用PTY管理器终止进程: {process_id}")
        pty_result = False
        
        # 首先尝试通过进程ID终止
        if pty_manager.get_process(process_id):
            logger.info(f"在pty_manager中找到进程: {process_id}")
            pty_result = pty_manager.terminate_process(process_id, force=force)
        # 如果通过ID终止失败，但我们有进程对象，直接终止它
        elif pty_process:
            logger.info(f"直接终止PTY进程对象")
            pty_result = pty_process.terminate(force=force)
            
        # 进行额外的进程检查
        process = running_servers[game_id].get('process')
        process_still_running = False
        
        if process:
            # 检查进程是否仍在运行
            if process.poll() is None:
                process_still_running = True
                logger.warning(f"PTY管理器报告终止成功，但进程仍在运行，PID: {process.pid}")
                
                # 尝试使用psutil进行更深入的检查
                try:
                    # 检查进程是否真的存在
                    if psutil.pid_exists(process.pid):
                        p = psutil.Process(process.pid)
                        logger.warning(f"进程 {process.pid} 仍然存在，状态: {p.status()}")
                        
                        # 如果是强制模式或PTY终止失败，直接杀死进程
                        if force or not pty_result:
                            logger.info(f"强制杀死进程 {process.pid}")
                            p.kill()
                            
                            # 检查子进程并杀死
                            try:
                                children = p.children(recursive=True)
                                for child in children:
                                    logger.info(f"杀死子进程: {child.pid}")
                                    child.kill()
                            except:
                                pass
                    else:
                        logger.info(f"进程 {process.pid} 不存在于系统中，可能已经终止")
                        process_still_running = False
                except Exception as e:
                    logger.error(f"检查进程状态时出错: {str(e)}")
            else:
                logger.info(f"进程已终止，返回码: {process.poll()}")
                process_still_running = False
        
        # 如果PTY终止成功或进程确实不再运行
        if pty_result or not process_still_running:
            logger.info(f"成功终止进程: {process_id}")
            # 更新服务器状态
            running_servers[game_id]['running'] = False
            running_servers[game_id]['stopped_by_user'] = True
            
            # 清理终端日志
            clean_server_output(game_id)
            
            # 从运行中的服务器字典中移除该游戏服务器
            if game_id in running_servers:
                logger.info(f"从运行中的服务器列表中移除游戏服务器: {game_id}")
                del running_servers[game_id]
                
            # 从输出队列字典中移除该游戏服务器
            if game_id in server_output_queues:
                logger.info(f"从输出队列列表中移除游戏服务器: {game_id}")
                del server_output_queues[game_id]
                
            # 确保从PTY管理器中删除进程
            if pty_manager.get_process(process_id):
                logger.info(f"从PTY管理器中删除进程: {process_id}")
                pty_manager.remove_process(process_id)
            
            return jsonify({'status': 'success', 'message': f'游戏服务器 {game_id} 已停止'})
        else:
            logger.warning(f"使用PTY管理器终止进程失败，尝试使用备选方案: {process_id}")
            
            # 尝试直接终止进程
            try:
                # 检查是否有进程对象
                process = running_servers[game_id].get('process')
                if process and process.poll() is None:
                    logger.info(f"尝试直接终止进程 PID: {process.pid}")
                    try:
                        # 找到所有子进程并终止
                        parent = psutil.Process(process.pid)
                        children = parent.children(recursive=True)
                        
                        # 如果不是强制模式，先尝试正常终止
                        if not force:
                            logger.info("尝试正常终止进程")
                            parent.terminate()
                            # 等待一段时间
                            for _ in range(10):  # 最多等待5秒
                                if process.poll() is not None:
                                    break
                                time.sleep(0.5)
                        
                        # 如果仍在运行或强制模式，强制终止
                        if force or process.poll() is None:
                            # 首先杀死所有子进程
                            for child in children:
                                logger.info(f"杀死子进程: {child.pid}")
                                try:
                                    child.kill()
                                except:
                                    pass
                            
                            # 然后杀死主进程
                            parent.kill()
                            logger.info(f"已杀死进程及其子进程")
                        
                        # 更新服务器状态
                        running_servers[game_id]['running'] = False
                        running_servers[game_id]['stopped_by_user'] = True
                        
                        # 清理终端日志
                        clean_server_output(game_id)
                        
                        # 从运行中的服务器字典中移除该游戏服务器
                        if game_id in running_servers:
                            logger.info(f"从运行中的服务器列表中移除游戏服务器: {game_id}")
                            del running_servers[game_id]
                            
                        # 从输出队列字典中移除该游戏服务器
                        if game_id in server_output_queues:
                            logger.info(f"从输出队列列表中移除游戏服务器: {game_id}")
                            del server_output_queues[game_id]
                        
                        # 确保从PTY管理器中删除进程
                        if pty_manager.get_process(process_id):
                            logger.info(f"从PTY管理器中删除进程: {process_id}")
                            pty_manager.remove_process(process_id)
                        
                        return jsonify({'status': 'success', 'message': f'游戏服务器 {game_id} 已强制停止'})
                    except Exception as e:
                        logger.error(f"直接终止进程失败: {str(e)}")
                else:
                    logger.warning(f"没有找到活动的进程对象")
                
                # 即使无法终止进程，也标记为停止
                running_servers[game_id]['running'] = False
                running_servers[game_id]['stopped_by_user'] = True
                
                # 清理终端日志
                clean_server_output(game_id)
                
                # 从运行中的服务器字典中移除该游戏服务器
                if game_id in running_servers:
                    logger.info(f"从运行中的服务器列表中移除游戏服务器: {game_id}")
                    del running_servers[game_id]
                    
                # 从输出队列字典中移除该游戏服务器
                if game_id in server_output_queues:
                    logger.info(f"从输出队列列表中移除游戏服务器: {game_id}")
                    del server_output_queues[game_id]
                
                # 确保从PTY管理器中删除进程
                if pty_manager.get_process(process_id):
                    logger.info(f"从PTY管理器中删除进程: {process_id}")
                    pty_manager.remove_process(process_id)
                
                return jsonify({'status': 'warning', 'message': f'游戏服务器 {game_id} 标记为停止，但可能仍在后台运行'})
            except Exception as e:
                logger.error(f"备选终止方案失败: {str(e)}")
                return jsonify({'status': 'error', 'message': f'无法停止游戏服务器 {game_id}: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"停止游戏服务器失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加一个清理服务器输出的函数
def clean_server_output(game_id):
    """清理服务器终端日志"""
    try:
        logger.info(f"清理游戏服务器 {game_id} 的终端日志")
        
        # 清空服务器输出历史
        if game_id in running_servers:
            running_servers[game_id]['output'] = []
            logger.info(f"已清空游戏服务器 {game_id} 的输出历史")
        
        # 清空输出队列
        if game_id in server_output_queues:
            try:
                while not server_output_queues[game_id].empty():
                    server_output_queues[game_id].get_nowait()
                logger.info(f"已清空游戏服务器 {game_id} 的输出队列")
            except:
                pass
        
        return True
    except Exception as e:
        logger.error(f"清理游戏服务器 {game_id} 终端日志失败: {str(e)}")
        return False

@app.route('/api/server/send_input', methods=['POST'])
def server_send_input():
    """向游戏服务器发送输入"""
    try:
        data = request.json
        game_id = data.get('game_id')
        value = data.get('value')
        
        if not game_id or value is None:
            logger.error("缺少参数")
            return jsonify({'status': 'error', 'message': '缺少游戏ID或输入值'}), 400
            
        logger.info(f"向游戏服务器发送输入: game_id={game_id}, value={value}")
        
        # 检查服务器是否在运行
        if game_id not in running_servers:
            logger.error(f"游戏服务器 {game_id} 未运行")
            return jsonify({'status': 'error', 'message': '服务器未运行'}), 400
            
        # 使用PTY管理器发送输入
        process_id = f"server_{game_id}"
        
        # 检查进程是否存在
        pty_proc = pty_manager.get_process(process_id)
        if not pty_proc:
            logger.error(f"PTY进程不存在: {process_id}。这可能意味着服务器在API重启后仍在运行，或者PTY记录已丢失。将清理无效记录。")
            if game_id in running_servers:
                del running_servers[game_id]
                logger.info(f"已从running_servers中移除无效的游戏服务器记录: {game_id}")
            if game_id in server_output_queues:
                # 清理队列中的内容
                try:
                    while not server_output_queues[game_id].empty():
                        server_output_queues[game_id].get_nowait()
                except Exception as e_q:
                    logger.warning(f"清理server_output_queues[{game_id}]时出错: {e_q}")
                del server_output_queues[game_id]
                logger.info(f"已从server_output_queues中移除无效的游戏服务器队列: {game_id}")
            return jsonify({
                'status': 'error',
                'message': '服务器PTY进程不存在或已与管理器断开连接。请尝试重新启动该服务器。'
            }), 400
            
        # 再次确认 pty_proc 是否真的在运行 (以防 get_process 返回了一个已停止的实例)
        if not pty_proc.is_running():
            logger.error(f"PTY进程 {process_id} 存在但未运行。清理记录。")
            if game_id in running_servers:
                del running_servers[game_id]
                logger.info(f"已从running_servers中移除未运行的游戏服务器记录: {game_id}")
            if game_id in server_output_queues:
                try:
                    while not server_output_queues[game_id].empty():
                        server_output_queues[game_id].get_nowait()
                except Exception as e_q:
                    logger.warning(f"清理server_output_queues[{game_id}]时出错: {e_q}")
                del server_output_queues[game_id]
                logger.info(f"已从server_output_queues中移除未运行的游戏服务器队列: {game_id}")
            # 从PTY管理器也移除
            pty_manager.remove_process(process_id)
            logger.info(f"已从pty_manager中移除未运行的进程记录: {process_id}")
            return jsonify({
                'status': 'error',
                'message': '服务器PTY进程已停止。请尝试重新启动该服务器。'
            }), 400

        # 发送输入
        if pty_manager.send_input(process_id, value):
            logger.info(f"输入发送成功: game_id={game_id}")
            
            # 不再手动回显，以避免顺序错乱
            return jsonify({'status': 'success', 'message': '输入已发送'})
        else:
            logger.error(f"发送输入失败: game_id={game_id}")
            return jsonify({'status': 'error', 'message': '服务器未运行或无法发送输入'}), 400
        
    except Exception as e:
        logger.error(f"向游戏服务器发送输入失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加服务器状态缓存
server_status_cache = {}
server_status_timestamp = 0
server_status_lock = threading.Lock()

@app.route('/api/server/status', methods=['GET'])
def server_status():
    """获取指定游戏或所有游戏的服务器状态"""
    global server_status_cache, server_status_timestamp
    try:
        game_id = request.args.get('game_id')
        
        # 检查是否可以使用缓存（5秒内的缓存有效）
        current_time = time.time()
        use_cache = False
        
        with server_status_lock:
            if current_time - server_status_timestamp < 5 and server_status_cache:
                use_cache = True
                cached_response = server_status_cache
        
        if use_cache and not game_id:
            # 返回所有服务器的缓存状态
            logger.debug("使用缓存的服务器状态")
            return jsonify(cached_response)
        
        # 如果请求特定游戏的状态，或者缓存无效，则重新获取
        if game_id:
            # 获取特定游戏的服务器状态
            server_data = running_servers.get(game_id)
            if server_data:
                process = server_data.get('process')
                if process and process.poll() is None:
                    # 服务器正在运行
                    return jsonify({
                        'status': 'success',
                        'server_status': 'running',
                        'started_at': server_data.get('started_at'),
                        'uptime': time.time() - server_data.get('started_at', time.time())
                    })
                else:
                    # 服务器已停止
                    return jsonify({
                        'status': 'success',
                        'server_status': 'stopped'
                    })
            else:
                # 服务器未启动
                return jsonify({
                    'status': 'success',
                    'server_status': 'stopped'
                })
        else:
            # 获取所有服务器的状态
            servers = {}
            for server_id, server_data in running_servers.items():
                process = server_data.get('process')
                if process and process.poll() is None:
                    # 服务器正在运行
                    servers[server_id] = {
                        'status': 'running',
                        'started_at': server_data.get('started_at'),
                        'uptime': time.time() - server_data.get('started_at', time.time())
                    }
            
            response = {
                'status': 'success',
                'servers': servers
            }
            
            # 更新缓存
            with server_status_lock:
                server_status_cache = response
                server_status_timestamp = current_time
            
            return jsonify(response)
    except Exception as e:
        logger.error(f"获取服务器状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/server/stream', methods=['GET'])
def server_stream():
    """游戏服务器输出流"""
    try:
        game_id = request.args.get('game_id')
        token = request.args.get('token')
        include_history = request.args.get('include_history', 'true').lower() == 'true'
        is_restart = request.args.get('restart', 'false').lower() == 'true'
        
        if not game_id:
            return jsonify({'status': 'error', 'message': '缺少游戏ID参数'}), 400
            
        # 验证token (如果提供)
        if token:
            payload = verify_token(token)
            if not payload:
                return jsonify({'status': 'error', 'message': '无效的认证令牌'}), 401
        
        logger.info(f"请求游戏 {game_id} 的输出流, include_history={include_history}, is_restart={is_restart}")
            
        # 如果服务器不在运行中，但请求了流
        if game_id not in running_servers:
            logger.warning(f"游戏服务器 {game_id} 未运行，但请求了输出流")
            
            # 如果是重启请求，创建一个新的输出队列，不返回错误
            if is_restart:
                logger.info(f"检测到重启请求，为游戏 {game_id} 创建新的输出队列")
                server_output_queues[game_id] = queue.Queue()
                # 添加一条初始消息
                server_output_queues[game_id].put(f"正在准备重启游戏服务器 {game_id}...")
            else:
                # 尝试从该服务器的输出队列中获取已有的错误信息
                queued_error_message = None
                queued_error_details = None
                specific_error_found_in_queue = False

                if game_id in server_output_queues and not server_output_queues[game_id].empty():
                    logger.info(f"服务器 {game_id} 未运行，但其队列中存在消息，尝试读取错误信息")
                    temp_queue_holder = []
                    try:
                        while not server_output_queues[game_id].empty():
                            item = server_output_queues[game_id].get_nowait()
                            temp_queue_holder.append(item) # 保存起来，如果不是错误消息，后面可能还需要
                            if isinstance(item, dict) and item.get('complete') and item.get('status') == 'error':
                                logger.info(f"从队列中找到错误完成消息: {item}")
                                queued_error_message = item.get('message', '队列中发现错误')
                                queued_error_details = item.get('error_details')
                                specific_error_found_in_queue = True
                                break # 找到主要错误，跳出
                            elif isinstance(item, str) and ("错误" in item or "失败" in item or "error" in item.lower() or "fail" in item.lower()):
                                # 如果是字符串类型的错误提示
                                if not queued_error_message: # 优先使用字典类型的错误
                                    queued_error_message = item
                                if "MCSERVER" in item:
                                     queued_error_details = queued_error_details or "请检查MCSERVER相关配置和脚本。"
                                specific_error_found_in_queue = True 
                    except queue.Empty:
                        pass
                    except Exception as e_q_read:
                        logger.error(f"从队列读取先前错误信息时发生错误: {e_q_read}")
                    
                    # 如果没有从队列中找到明确的错误完成消息，但队列不为空，则把消息放回去，让后续的generate()处理
                    if not specific_error_found_in_queue and temp_queue_holder:
                        logger.info(f"未在队列 {game_id} 中找到特定错误完成消息，但队列非空。将重新填充队列内容供后续处理。")
                        for prev_item in temp_queue_holder:
                            server_output_queues[game_id].put(prev_item)
                        # 这种情况下，我们依赖后续的 generate() 逻辑来处理队列中的常规消息
                        # 或者，如果队列中只有非错误消息，最终也会走到下面的 temp_server_errors 逻辑

                error_message = None
                error_details = None
                
                if specific_error_found_in_queue:
                    error_message = queued_error_message
                    error_details = queued_error_details
                else:
                    # 检查是否有临时错误信息 (通常是 start_game_server 直接抛出的错误)
                    try:
                        temp_errors = getattr(app, 'temp_server_errors', {})
                        if game_id in temp_errors:
                            error_message = temp_errors[game_id].get('message', '未知错误')
                            error_details = temp_errors[game_id].get('details', None)
                            # 使用后删除临时错误
                            del temp_errors[game_id]
                    except Exception as e:
                        logger.error(f"获取临时错误信息失败: {str(e)}")
                
                # 返回SSE流，包含错误信息
                def generate_error():
                    if error_message:
                        yield f"data: {json.dumps({'line': f'游戏服务器 {game_id} 启动失败: {error_message}'})}\n\n"
                        if error_details:
                            yield f"data: {json.dumps({'line': f'错误详情: {error_details}'})}\n\n"
                            
                            # 对于特殊的'MCSERVER'错误，提供更详细的解释
                            if "'MCSERVER'" in error_details:
                                detailed_error = """
启动游戏服务器失败: 'MCSERVER'
可能的原因:
1. 服务器配置文件缺失或损坏
2. 服务器执行脚本中存在语法错误
3. 启动脚本中的MCSERVER环境变量未正确设置
4. 服务器执行权限不足

建议解决方案:
1. 检查启动脚本的内容，确保语法正确
2. 确认服务器目录下的配置文件是否完整
3. 手动执行启动脚本，查看详细错误信息
4. 检查服务器目录权限，确保steam用户有执行权限
"""
                                yield f"data: {json.dumps({'line': detailed_error})}\n\n"
                    else:
                        yield f"data: {json.dumps({'line': f'游戏服务器 {game_id} 未运行或已停止'})}\n\n"
                    
                    # 发送完成消息
                    complete_msg = {
                        'complete': True, 
                        'status': 'error', 
                        'message': error_message or f'游戏服务器 {game_id} 未运行或已停止'
                    }
                    if error_details:
                        complete_msg['error_details'] = error_details
                    
                    yield f"data: {json.dumps(complete_msg)}\n\n"
                
                return Response(stream_with_context(generate_error()), 
                              mimetype='text/event-stream',
                              headers={
                                  'Cache-Control': 'no-cache',
                                  'X-Accel-Buffering': 'no'  # 禁用Nginx缓冲
                              })
            
        # 确保有队列
        if game_id not in server_output_queues:
            server_output_queues[game_id] = queue.Queue()
        
        # 获取服务器数据和历史输出
        output_history = []
        if game_id in running_servers:
            server_data = running_servers[game_id]
            output_history = server_data.get('output', [])
            
        # 添加历史记录到队列开头
        if include_history and output_history:
            logger.info(f"将 {len(output_history)} 行历史输出添加到流中: game_id={game_id}")
            for line in output_history:
                if isinstance(line, str) and not line.startswith('[历史记录]'):
                    server_output_queues[game_id].put(f"[历史记录] {line}")
                else:
                    server_output_queues[game_id].put(line)
        
        # 生成器函数
        def generate():
            output_queue = server_output_queues[game_id]
            
            # 发送一条连接成功消息
            yield f"data: {json.dumps({'line': '已连接到服务器输出流，等待服务器输出...'})}\n\n"
            
            # 检查进程是否已结束
            process_ended = False
            return_code = None
            
            if game_id in running_servers:
                process = running_servers[game_id].get('process')
                pty_process = running_servers[game_id].get('pty_process')
            else:
                process = None
                pty_process = None
                # 如果是重启请求，尝试从PTY管理器获取进程
                if is_restart:
                    process_id = f"server_{game_id}"
                    if pty_manager.get_process(process_id):
                        pty_process = pty_manager.get_process(process_id)
            
            if process and hasattr(process, 'poll'):
                return_code = process.poll()
                if return_code is not None:
                    process_ended = True
            elif pty_process:
                if hasattr(pty_process, 'complete') and pty_process.complete:
                    process_ended = True
                    return_code = pty_process.return_code if hasattr(pty_process, 'return_code') else 0
                elif hasattr(pty_process, 'running') and not pty_process.running:
                    process_ended = True
                    return_code = pty_process.return_code if hasattr(pty_process, 'return_code') else 0
            
            if process_ended:
                status = 'success' if return_code == 0 else 'error'
                message = f'游戏服务器 {game_id} ' + ('正常关闭' if return_code == 0 else f'异常退出，返回码: {return_code}')
                logger.info(f"服务器已停止，发送完成消息: game_id={game_id}, 状态={status}")
                yield f"data: {json.dumps({'complete': True, 'status': status, 'message': message})}\n\n"
                return
            
            # 超时设置
            timeout_seconds = 3600  # 1小时无输出则超时
            last_output_time = time.time()
            heartbeat_interval = 10  # 每10秒发送一次心跳
            next_heartbeat = time.time() + heartbeat_interval
            
            # 持续监听队列
            logger.info(f"开始监听实时输出队列: game_id={game_id}")
            
            # 发送一条实时输出测试消息
            test_message = f"服务器 {game_id} 已启动，等待输出..."
            yield f"data: {json.dumps({'line': test_message})}\n\n"
            
            # 添加一个计数器，用于记录处理的输出行数
            output_count = 0
            
            # 记录错误消息
            error_messages = []
            has_exit_message = False
            
            try:
                while True:
                    # 检查进程是否已结束
                    process_ended = False
                    if game_id in running_servers:
                        process = running_servers[game_id].get('process')
                        pty_process = running_servers[game_id].get('pty_process')
                        
                        if process and hasattr(process, 'poll'):
                            return_code = process.poll()
                            if return_code is not None:
                                process_ended = True
                        elif pty_process:
                            if hasattr(pty_process, 'complete') and pty_process.complete:
                                process_ended = True
                                return_code = pty_process.return_code if hasattr(pty_process, 'return_code') else 0
                            elif hasattr(pty_process, 'running') and not pty_process.running:
                                process_ended = True
                                return_code = pty_process.return_code if hasattr(pty_process, 'return_code') else 0
                    else:
                        # 进程已从running_servers中移除
                        process_ended = True
                        return_code = 0  # 假设成功完成
                        process = None
                        pty_process = None
                    
                    # 如果进程已结束且队列为空，发送完成消息并退出
                    if process_ended and output_queue.empty():
                        if not has_exit_message:
                            # 收集可能的错误消息
                            if error_messages:
                                error_summary = "; ".join(error_messages)
                                logger.warning(f"服务器 {game_id} 退出时有错误: {error_summary}")
                                yield f"data: {json.dumps({'line': f'服务器退出时有错误: {error_summary}'})}\n\n"
                            
                            # 发送完成消息
                            status = 'success' if return_code == 0 else 'error'
                            message = f'游戏服务器 {game_id} ' + ('正常关闭' if return_code == 0 else f'异常退出，返回码: {return_code}')
                            logger.info(f"服务器已停止，发送完成消息: game_id={game_id}, 状态={status}, 已处理 {output_count} 行输出")
                            yield f"data: {json.dumps({'complete': True, 'status': status, 'message': message})}\n\n"
                            has_exit_message = True
                        break
                    
                    # 检查是否有新输出
                    try:
                        line = output_queue.get(timeout=0.5)
                        output_count += 1
                        
                        # 如果是字典类型（特殊消息），直接发送
                        if isinstance(line, dict):
                            if 'complete' in line:  # 完成消息
                                logger.info(f"检测到完成消息: game_id={game_id}, 状态={line.get('status', 'unknown')}")
                                yield f"data: {json.dumps(line)}\n\n"
                                has_exit_message = True
                                break
                            else:  # 其他特殊消息
                                logger.debug(f"发送特殊消息 #{output_count}: {line}")
                                yield f"data: {json.dumps(line)}\n\n"
                        else:  # 普通文本行
                            # 检查是否包含错误信息
                            if isinstance(line, str) and any(err_keyword in line.lower() for err_keyword in ['error', 'exception', 'fail', '错误', '异常', '失败']):
                                # 保存错误消息
                                if len(error_messages) < 5:  # 最多保存5条错误消息
                                    error_messages.append(line)
                            
                            # 检查是否包含退出信息
                            if isinstance(line, str) and any(exit_keyword in line.lower() for exit_keyword in ['exit', 'shutdown', 'terminate', '退出', '关闭', '停止']):
                                logger.info(f"检测到退出消息: {line}")
                            
                            if output_count % 10 == 0:  # 每10行输出打印一次调试信息
                                logger.debug(f"已处理 {output_count} 行输出: game_id={game_id}")
                            
                            # 截断长输出
                            if isinstance(line, str) and len(line) > 10000:
                                logger.info(f"输出行过长，已截断: {len(line)} 字符")
                                line = line[:10000] + "... (输出过长，已截断)"
                            
                            logger.debug(f"发送服务器输出 #{output_count}: {line[:100]}...")
                            yield f"data: {json.dumps({'line': line})}\n\n"
                        
                        # 更新最后输出时间
                        last_output_time = time.time()
                        
                    except queue.Empty:
                        # 队列为空，检查是否需要发送心跳
                        current_time = time.time()
                        
                        # 检查是否超时
                        if current_time - last_output_time > timeout_seconds:
                            logger.warning(f"服务器 {game_id} 长时间无输出，超时")
                            yield f"data: {json.dumps({'line': '[心跳检查] 服务器长时间无输出，连接超时'})}\n\n"
                            yield f"data: {json.dumps({'complete': True, 'status': 'timeout', 'message': '服务器长时间无输出，连接超时'})}\n\n"
                            break
                        
                        # 发送心跳包
                        if current_time > next_heartbeat:
                            heartbeat_msg = f"[心跳检查] 连接正常，等待服务器输出... ({time.strftime('%H:%M:%S')})"
                            logger.debug(f"发送心跳包: game_id={game_id}, 已处理 {output_count} 行")
                            yield f"data: {json.dumps({'line': heartbeat_msg})}\n\n"
                            next_heartbeat = current_time + heartbeat_interval
                        
                        # 如果队列为空且进程仍在运行，等待片刻再继续
                        if not process_ended:
                            logger.debug(f"队列为空，等待输出: game_id={game_id}, 已处理 {output_count} 行")
                            time.sleep(1)
            except GeneratorExit:
                logger.info(f"客户端断开连接: game_id={game_id}, 已处理 {output_count} 行输出")
            except Exception as e:
                logger.error(f"生成输出流时出错: {str(e)}")
                yield f"data: {json.dumps({'line': f'处理输出流时出错: {str(e)}'})}\n\n"
                yield f"data: {json.dumps({'complete': True, 'status': 'error', 'message': f'处理输出流时出错: {str(e)}'})}\n\n"
            
            logger.info(f"输出转发线程结束: game_id={game_id}, 总共处理 {output_count} 行输出")
        
        # 返回流式响应
        return Response(stream_with_context(generate()), 
                       mimetype='text/event-stream',
                       headers={
                           'Cache-Control': 'no-cache',
                           'X-Accel-Buffering': 'no'  # 禁用Nginx缓冲
                       })
    
    except Exception as e:
        logger.error(f"创建服务器输出流失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/container_info', methods=['GET'])
def get_container_info():
    """获取容器信息，包括系统资源占用、已安装游戏和正在运行的游戏"""
    try:
        # 设置超时处理
        timeout_seconds = 5  # 5秒超时
        start_time = time.time()
        
        # 获取CPU型号信息
        cpu_model = "未知"
        try:
            if sys.platform == "linux" or sys.platform == "linux2":
                # Linux系统，从/proc/cpuinfo读取
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if line.startswith('model name'):
                            cpu_model = line.split(':', 1)[1].strip()
                            break
            elif sys.platform == "darwin":
                # macOS系统
                cpu_model = subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string']).decode().strip()
            elif sys.platform == "win32":
                # Windows系统
                import platform
                cpu_model = platform.processor()
        except Exception as e:
            logger.error(f"获取CPU型号时出错: {str(e)}")
            cpu_model = "获取失败"

        # 检查是否超时
        if time.time() - start_time > timeout_seconds:
            logger.warning("获取CPU型号超时")
            return jsonify({
                'status': 'success',
                'system_info': {
                    'cpu_usage': 0,
                    'cpu_per_core': [],
                    'cpu_model': '获取超时',
                    'cpu_cores': 0,
                    'cpu_logical_cores': 0,
                    'memory': {'total': 0, 'used': 0, 'percent': 0},
                    'disk': {'total': 0, 'used': 0, 'percent': 0}
                },
                'installed_games': [],
                'running_games': []
            })

        # 获取内存频率信息
        memory_freq = "未知"
        try:
            if sys.platform == "linux" or sys.platform == "linux2":
                # Linux系统，尝试从dmidecode获取
                try:
                    memory_info = subprocess.check_output(['dmidecode', '-t', 'memory'], stderr=subprocess.STDOUT, timeout=2).decode()
                    for line in memory_info.split('\n'):
                        if "Speed" in line and "MHz" in line and not "Unknown" in line:
                            memory_freq = line.split(':', 1)[1].strip()
                            break
                except subprocess.TimeoutExpired:
                    logger.warning("获取内存频率命令超时")
                    memory_freq = "获取超时"
                except:
                    # 尝试从/proc/meminfo获取，但通常不包含频率信息
                    memory_freq = "无法获取"
            elif sys.platform == "darwin":
                # macOS系统
                try:
                    memory_info = subprocess.check_output(['system_profiler', 'SPMemoryDataType'], timeout=2).decode()
                    for line in memory_info.split('\n'):
                        if "Speed" in line:
                            memory_freq = line.split(':', 1)[1].strip()
                            break
                except subprocess.TimeoutExpired:
                    logger.warning("获取内存频率命令超时")
                    memory_freq = "获取超时"
                except:
                    memory_freq = "无法获取"
            elif sys.platform == "win32":
                # Windows系统，尝试使用wmic
                try:
                    memory_info = subprocess.check_output(['wmic', 'memorychip', 'get', 'speed'], timeout=2).decode()
                    lines = memory_info.strip().split('\n')
                    if len(lines) > 1:
                        memory_freq = lines[1].strip() + " MHz"
                except subprocess.TimeoutExpired:
                    logger.warning("获取内存频率命令超时")
                    memory_freq = "获取超时"
                except:
                    memory_freq = "无法获取"
        except Exception as e:
            logger.error(f"获取内存频率时出错: {str(e)}")
            memory_freq = "获取失败"

        # 检查是否超时
        if time.time() - start_time > timeout_seconds:
            logger.warning("获取内存频率超时")
            return jsonify({
                'status': 'success',
                'system_info': {
                    'cpu_usage': 0,
                    'cpu_per_core': [],
                    'cpu_model': cpu_model,
                    'cpu_cores': 0,
                    'cpu_logical_cores': 0,
                    'memory': {'total': 0, 'used': 0, 'percent': 0, 'frequency': '获取超时'},
                    'disk': {'total': 0, 'used': 0, 'percent': 0}
                },
                'installed_games': [],
                'running_games': []
            })

        # 获取系统信息
        system_info = {
            'cpu_usage': psutil.cpu_percent(interval=None),  # 使用非阻塞方式获取CPU使用率
            'cpu_per_core': psutil.cpu_percent(interval=None, percpu=True),  # 每个核心的使用率
            'cpu_model': cpu_model,
            'cpu_cores': psutil.cpu_count(logical=False),  # 物理核心数
            'cpu_logical_cores': psutil.cpu_count(logical=True),  # 逻辑核心数
            'memory': {
                'total': psutil.virtual_memory().total / (1024 * 1024 * 1024),  # GB
                'used': psutil.virtual_memory().used / (1024 * 1024 * 1024),    # GB
                'percent': psutil.virtual_memory().percent,
                'frequency': memory_freq  # 添加内存频率信息
            },
            'disk': {
                'total': 0,
                'used': 0,
                'percent': 0
            }
        }
        
        # 获取游戏目录磁盘使用情况
        if os.path.exists(GAMES_DIR):
            try:
                disk_usage = shutil.disk_usage(GAMES_DIR)
                system_info['disk'] = {
                    'total': disk_usage.total / (1024 * 1024 * 1024),  # GB
                    'used': disk_usage.used / (1024 * 1024 * 1024),    # GB
                    'percent': disk_usage.used * 100 / disk_usage.total if disk_usage.total > 0 else 0
                }
            except Exception as e:
                logger.error(f"获取磁盘信息失败: {str(e)}")
                system_info['disk'] = {'total': 0, 'used': 0, 'percent': 0}
            
            # 检查是否超时
            if time.time() - start_time > timeout_seconds:
                logger.warning("获取磁盘信息超时")
                return jsonify({
                    'status': 'success',
                    'system_info': system_info,
                    'installed_games': [],
                    'running_games': []
                })
            
            # 计算各游戏占用空间，但限制处理时间
            games_space = {}
            remaining_time = timeout_seconds - (time.time() - start_time)
            
            # 检查是否有服务器正在运行
            has_running_servers = False
            for game_id, server_data in running_servers.items():
                process = server_data.get('process')
                if process and process.poll() is None:
                    has_running_servers = True
                    break
            
            # 如果有服务器正在运行，跳过详细的空间计算，使用估算值或缓存
            if has_running_servers:
                logger.debug("检测到有服务器正在运行，跳过详细的游戏空间计算")
                
                # 尝试从缓存加载游戏空间数据
                try:
                    cache_file = os.path.join(os.path.dirname(GAMES_DIR), 'games_space_cache.json')
                    if os.path.exists(cache_file) and (time.time() - os.path.getmtime(cache_file) < 3600):  # 1小时内的缓存有效
                        with open(cache_file, 'r') as f:
                            games_space = json.load(f)
                            logger.info(f"从缓存加载游戏空间数据: {len(games_space)} 个游戏")
                    else:
                        # 使用快速估算
                        for game_id in os.listdir(GAMES_DIR):
                            game_path = os.path.join(GAMES_DIR, game_id)
                            if os.path.isdir(game_path):
                                try:
                                    # 使用du命令快速估算
                                    try:
                                        du_output = subprocess.check_output(['du', '-sm', game_path], timeout=1).decode()
                                        size = float(du_output.split()[0]) * 1024 * 1024  # 转换为字节
                                    except:
                                        # 如果du命令失败，使用目录大小作为估算
                                        size = os.path.getsize(game_path)
                                    
                                    games_space[game_id] = size / (1024 * 1024)  # MB
                                except Exception as e:
                                    logger.error(f"估算游戏 {game_id} 空间占用时出错: {str(e)}")
                                    games_space[game_id] = 0
                        
                        # 保存到缓存
                        try:
                            with open(cache_file, 'w') as f:
                                json.dump(games_space, f)
                        except Exception as e:
                            logger.error(f"保存游戏空间缓存失败: {str(e)}")
                except Exception as e:
                    logger.error(f"处理游戏空间缓存时出错: {str(e)}")
            elif remaining_time > 0:
                # 没有服务器运行，可以进行详细计算
                game_dirs = os.listdir(GAMES_DIR)
                time_per_game = remaining_time / (len(game_dirs) or 1)
                
                for game_id in game_dirs:
                    game_start_time = time.time()
                    game_path = os.path.join(GAMES_DIR, game_id)
                    if os.path.isdir(game_path):
                        try:
                            size = 0
                            for dirpath, dirnames, filenames in os.walk(game_path):
                                # 检查是否超过每个游戏的时间限制
                                if time.time() - game_start_time > time_per_game:
                                    logger.debug(f"计算游戏 {game_id} 空间占用超时")
                                    size = -1  # 使用-1表示计算超时
                                    break
                                    
                                for f in filenames:
                                    fp = os.path.join(dirpath, f)
                                    if os.path.exists(fp):
                                        size += os.path.getsize(fp)
                            
                            # 如果超时，使用估算值
                            if size == -1:
                                # 尝试使用du命令快速估算
                                try:
                                    du_output = subprocess.check_output(['du', '-sm', game_path], timeout=1).decode()
                                    size = float(du_output.split()[0]) * 1024 * 1024  # 转换为字节
                                except:
                                    # 如果du命令失败，使用目录大小作为估算
                                    size = os.path.getsize(game_path)
                            
                            games_space[game_id] = size / (1024 * 1024)  # MB
                        except Exception as e:
                            logger.error(f"计算游戏 {game_id} 空间占用时出错: {str(e)}")
                            games_space[game_id] = 0
                
                # 保存到缓存
                try:
                    cache_file = os.path.join(os.path.dirname(GAMES_DIR), 'games_space_cache.json')
                    with open(cache_file, 'w') as f:
                        json.dump(games_space, f)
                except Exception as e:
                    logger.error(f"保存游戏空间缓存失败: {str(e)}")
            
            system_info['games_space'] = games_space
        
        # 检查是否超时
        if time.time() - start_time > timeout_seconds:
            logger.warning("计算游戏空间占用超时")
            return jsonify({
                'status': 'success',
                'system_info': system_info,
                'installed_games': [],
                'running_games': []
            })
        
        # 获取已安装游戏（仅包含在配置中的游戏）
        installed_games = []
        games_config = load_games_config()
        if os.path.exists(GAMES_DIR):
            for name in os.listdir(GAMES_DIR):
                path = os.path.join(GAMES_DIR, name)
                if os.path.isdir(path) and name in games_config:
                    game_info = {
                        'id': name,
                        'name': games_config[name].get('game_nameCN', name),
                        'size_mb': system_info['games_space'].get(name, 0) if 'games_space' in system_info else 0
                    }
                    installed_games.append(game_info)
        
        # 检查是否超时
        if time.time() - start_time > timeout_seconds:
            logger.warning("获取已安装游戏列表超时")
            return jsonify({
                'status': 'success',
                'system_info': system_info,
                'installed_games': installed_games,
                'running_games': []
            })
        
        # 获取正在运行的游戏
        running_games = []
        for game_id, server_data in running_servers.items():
            process = server_data.get('process')
            if process and process.poll() is None:
                game_name = game_id
                if game_id in games_config:
                    game_name = games_config[game_id].get('game_nameCN', game_id)
                game_info = {
                    'id': game_id,
                    'name': game_name,
                    'started_at': server_data.get('started_at'),
                    'uptime': time.time() - server_data.get('started_at', time.time()),
                    'external': game_id not in games_config  # 标记是否为外部游戏
                }
                running_games.append(game_info)
        
        return jsonify({
            'status': 'success',
            'system_info': system_info,
            'installed_games': installed_games,
            'running_games': running_games
        })
    except Exception as e:
        logger.error(f"获取容器信息失败: {str(e)}")
        return jsonify({
            'status': 'error', 
            'message': str(e),
            'system_info': {
                'cpu_usage': 0,
                'memory': {'total': 0, 'used': 0, 'percent': 0},
                'disk': {'total': 0, 'used': 0, 'percent': 0}
            },
            'installed_games': [],
            'running_games': []
        }), 500

# 添加一个清理安装输出的函数，类似于清理服务器输出的函数
def clean_installation_output(game_id):
    """清理安装终端日志"""
    try:
        logger.info(f"清理游戏 {game_id} 的安装终端日志")
        
        # 清空安装输出历史
        if game_id in active_installations:
            active_installations[game_id]['output'] = []
            logger.info(f"已清空游戏 {game_id} 的安装输出历史")
        
        # 清空输出队列
        if game_id in output_queues:
            try:
                while not output_queues[game_id].empty():
                    output_queues[game_id].get_nowait()
                logger.info(f"已清空游戏 {game_id} 的输出队列")
            except:
                pass
        
        return True
    except Exception as e:
        logger.error(f"清理游戏 {game_id} 安装终端日志失败: {str(e)}")
        return False

# 文件管理相关的API路由

@app.route('/api/files', methods=['GET'])
def list_files():
    """列出指定目录下的文件和子目录"""
    try:
        path = request.args.get('path', '/home/steam')
        
        # 安全检查：防止目录遍历攻击
        if '..' in path or not path.startswith('/'):
            # 返回默认目录内容而不是错误
            logger.warning(f"检测到无效路径: {path}，已自动切换到默认路径")
            path = '/home/steam'
        
        # 确保路径存在
        if not os.path.exists(path):
            # 尝试使用父目录
            parent_path = os.path.dirname(path)
            if parent_path == path:  # 如果已经是根目录
                parent_path = '/home/steam'
                
            logger.warning(f"路径不存在: {path}，尝试切换到父目录: {parent_path}")
            
            if os.path.exists(parent_path) and os.path.isdir(parent_path):
                path = parent_path
            else:
                # 如果父目录也不存在，使用默认目录
                path = '/home/steam'
                logger.warning(f"父目录也不存在，切换到默认目录: {path}")
            
        # 确保是目录
        if not os.path.isdir(path):
            # 如果不是目录，使用其所在的目录
            parent_path = os.path.dirname(path)
            logger.warning(f"路径不是目录: {path}，切换到其所在目录: {parent_path}")
            
            if os.path.exists(parent_path) and os.path.isdir(parent_path):
                path = parent_path
            else:
                # 如果父目录不是有效目录，使用默认目录
                path = '/home/steam'
                logger.warning(f"父目录不是有效目录，切换到默认目录: {path}")
            
        # 获取目录内容
        items = []
        for name in os.listdir(path):
            full_path = os.path.join(path, name)
            stat_result = os.stat(full_path)
            
            # 确定类型
            item_type = 'directory' if os.path.isdir(full_path) else 'file'
            
            # 获取修改时间
            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_result.st_mtime))
            
            # 获取文件大小（对于目录，大小为0）
            size = 0 if item_type == 'directory' else stat_result.st_size
            
            items.append({
                'name': name,
                'path': full_path,
                'type': item_type,
                'size': size,
                'modified': mtime
            })
            
        # 按照类型和名称排序，先显示目录，再显示文件
        items.sort(key=lambda x: (0 if x['type'] == 'directory' else 1, x['name']))
        
        return jsonify({'status': 'success', 'files': items, 'path': path})
        
    except Exception as e:
        logger.error(f"列出文件时出错: {str(e)}")
        # 发生错误时，尝试返回默认目录
        try:
            default_path = '/home/steam'
            default_items = []
            for name in os.listdir(default_path):
                full_path = os.path.join(default_path, name)
                stat_result = os.stat(full_path)
                
                item_type = 'directory' if os.path.isdir(full_path) else 'file'
                mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_result.st_mtime))
                size = 0 if item_type == 'directory' else stat_result.st_size
                
                default_items.append({
                    'name': name,
                    'path': full_path,
                    'type': item_type,
                    'size': size,
                    'modified': mtime
                })
                
            default_items.sort(key=lambda x: (0 if x['type'] == 'directory' else 1, x['name']))
            
            return jsonify({
                'status': 'success', 
                'files': default_items, 
                'path': default_path,
                'message': f'原路径出错，已切换到默认路径: {str(e)}'
            })
        except Exception as inner_e:
            logger.error(f"尝试使用默认路径也失败: {str(inner_e)}")
            return jsonify({'status': 'error', 'message': f'无法列出文件: {str(e)}'})

@app.route('/api/open_folder', methods=['GET'])
def open_folder():
    """在客户端打开指定的文件夹"""
    try:
        path = request.args.get('path', '/home/steam')
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件夹路径'})
            
        # 确保目录存在
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '文件夹不存在'})
            
        # 确保是目录
        if not os.path.isdir(path):
            return jsonify({'status': 'error', 'message': '路径不是文件夹'})
        
        # 在这里，我们只返回路径信息，因为在Web应用中无法直接打开客户端的文件夹
        # 实际的打开操作将在前端通过专门的功能（例如electron的shell.openPath）完成
        return jsonify({
            'status': 'success', 
            'path': path,
            'message': '请求打开文件夹'
        })
        
    except Exception as e:
        logger.error(f"请求打开文件夹时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'无法打开文件夹: {str(e)}'})

@app.route('/api/file_content', methods=['GET'])
def get_file_content():
    """获取文件内容"""
    try:
        path = request.args.get('path')
        encoding = request.args.get('encoding', 'utf-8')  # 默认使用UTF-8编码
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件路径'})
            
        # 确保文件存在且是文件
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '文件不存在'})
            
        if not os.path.isfile(path):
            return jsonify({'status': 'error', 'message': '路径不是文件'})
            
        # 检查文件大小，防止读取过大的文件
        if os.path.getsize(path) > 10 * 1024 * 1024:  # 10MB限制
            return jsonify({'status': 'error', 'message': '文件过大，无法读取'})
            
        # 验证编码格式
        supported_encodings = ['utf-8', 'gbk', 'gb2312', 'big5', 'ascii', 'latin1', 'utf-16', 'utf-32']
        if encoding not in supported_encodings:
            encoding = 'utf-8'  # 如果编码不支持，回退到UTF-8
            
        # 读取文件内容
        try:
            with open(path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 如果指定编码失败，尝试使用UTF-8
            logger.warning(f"使用编码 {encoding} 读取文件失败，尝试使用 UTF-8")
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            encoding = 'utf-8'  # 更新实际使用的编码
            
        return jsonify({
            'status': 'success', 
            'content': content,
            'encoding': encoding  # 返回实际使用的编码
        })
        
    except Exception as e:
        logger.error(f"读取文件内容时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'读取文件失败: {str(e)}'})

@app.route('/api/save_file', methods=['POST'])
def save_file_content():
    """保存文件内容"""
    try:
        data = request.json
        path = data.get('path')
        content = data.get('content', '')
        encoding = data.get('encoding', 'utf-8')  # 默认使用UTF-8编码
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件路径'})
            
        # 验证编码格式
        supported_encodings = ['utf-8', 'gbk', 'gb2312', 'big5', 'ascii', 'latin1', 'utf-16', 'utf-32']
        if encoding not in supported_encodings:
            encoding = 'utf-8'  # 如果编码不支持，回退到UTF-8
            
        # 确保目录存在
        dir_path = os.path.dirname(path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
            
        # 写入文件
        try:
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
        except UnicodeEncodeError:
            # 如果指定编码失败，尝试使用UTF-8
            logger.warning(f"使用编码 {encoding} 保存文件失败，尝试使用 UTF-8")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            encoding = 'utf-8'  # 更新实际使用的编码
            
        return jsonify({
            'status': 'success',
            'encoding': encoding  # 返回实际使用的编码
        })
        
    except Exception as e:
        logger.error(f"保存文件内容时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存文件失败: {str(e)}'})

@app.route('/api/copy', methods=['POST'])
def copy_item():
    """复制文件或目录"""
    try:
        data = request.json
        source_path = data.get('sourcePath')
        destination_path = data.get('destinationPath')
        
        # 安全检查
        if not source_path or not destination_path or '..' in source_path or '..' in destination_path:
            return jsonify({'status': 'error', 'message': '无效的路径'})
            
        if not source_path.startswith('/') or not destination_path.startswith('/'):
            return jsonify({'status': 'error', 'message': '路径必须是绝对路径'})
            
        # 确保源路径存在
        if not os.path.exists(source_path):
            return jsonify({'status': 'error', 'message': '源路径不存在'})
            
        # 如果目标路径已存在，先删除
        if os.path.exists(destination_path):
            if os.path.isdir(destination_path):
                shutil.rmtree(destination_path)
            else:
                os.remove(destination_path)
                
        # 复制文件或目录
        if os.path.isdir(source_path):
            shutil.copytree(source_path, destination_path)
        else:
            shutil.copy2(source_path, destination_path)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"复制文件/目录时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'复制失败: {str(e)}'})

@app.route('/api/move', methods=['POST'])
def move_item():
    """移动文件或目录"""
    try:
        data = request.json
        source_path = data.get('sourcePath')
        destination_path = data.get('destinationPath')
        
        # 安全检查
        if not source_path or not destination_path or '..' in source_path or '..' in destination_path:
            return jsonify({'status': 'error', 'message': '无效的路径'})
            
        if not source_path.startswith('/') or not destination_path.startswith('/'):
            return jsonify({'status': 'error', 'message': '路径必须是绝对路径'})
            
        # 确保源路径存在
        if not os.path.exists(source_path):
            return jsonify({'status': 'error', 'message': '源路径不存在'})
            
        # 如果目标路径已存在，先删除
        if os.path.exists(destination_path):
            if os.path.isdir(destination_path):
                shutil.rmtree(destination_path)
            else:
                os.remove(destination_path)
                
        # 移动文件或目录
        shutil.move(source_path, destination_path)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"移动文件/目录时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'移动失败: {str(e)}'})

@app.route('/api/delete', methods=['POST'])
def delete_item():
    """删除文件或目录"""
    try:
        data = request.json
        path = data.get('path')
        item_type = data.get('type')
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的路径'})
            
        # 确保路径存在
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '路径不存在'})
            
        # 删除文件或目录
        if item_type == 'directory' or os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"删除文件/目录时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'删除失败: {str(e)}'})

@app.route('/api/search', methods=['GET'])
def search_files():
    """搜索文件和文件夹"""
    try:
        search_path = request.args.get('path', '/home/steam')
        search_query = request.args.get('query', '')
        search_type = request.args.get('type', 'all')  # all, file, directory
        case_sensitive = request.args.get('case_sensitive', 'false').lower() == 'true'
        max_results = int(request.args.get('max_results', '100'))
        
        # 安全检查
        if '..' in search_path or not search_path.startswith('/'):
            logger.warning(f"检测到无效搜索路径: {search_path}，已自动切换到默认路径")
            search_path = '/home/steam'
            
        # 确保搜索路径存在
        if not os.path.exists(search_path):
            logger.warning(f"搜索路径不存在: {search_path}，切换到默认路径")
            search_path = '/home/steam'
            
        if not os.path.isdir(search_path):
            # 如果不是目录，使用其父目录
            search_path = os.path.dirname(search_path)
            
        # 如果搜索查询为空，返回错误
        if not search_query.strip():
            return jsonify({'status': 'error', 'message': '搜索关键词不能为空'})
            
        results = []
        search_count = 0
        
        # 递归搜索函数
        def search_recursive(current_path, query, search_type, case_sensitive):
            nonlocal search_count, max_results
            
            if search_count >= max_results:
                return
                
            try:
                # 遍历当前目录
                for item_name in os.listdir(current_path):
                    if search_count >= max_results:
                        break
                        
                    item_path = os.path.join(current_path, item_name)
                    
                    # 跳过隐藏文件和系统文件（可选）
                    if item_name.startswith('.'):
                        continue
                        
                    try:
                        # 获取文件信息
                        stat_result = os.stat(item_path)
                        is_directory = os.path.isdir(item_path)
                        
                        # 根据搜索类型过滤
                        if search_type == 'file' and is_directory:
                            # 如果只搜索文件，跳过目录，但仍需递归搜索目录内容
                            if is_directory:
                                search_recursive(item_path, query, search_type, case_sensitive)
                            continue
                        elif search_type == 'directory' and not is_directory:
                            continue
                            
                        # 执行搜索匹配
                        search_name = item_name if case_sensitive else item_name.lower()
                        search_query_processed = query if case_sensitive else query.lower()
                        
                        if search_query_processed in search_name:
                            # 获取文件大小和修改时间
                            size = 0 if is_directory else stat_result.st_size
                            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat_result.st_mtime))
                            
                            # 计算相对路径
                            relative_path = os.path.relpath(item_path, search_path)
                            if relative_path == '.':
                                relative_path = item_name
                                
                            results.append({
                                'name': item_name,
                                'path': item_path,
                                'relative_path': relative_path,
                                'type': 'directory' if is_directory else 'file',
                                'size': size,
                                'modified': mtime,
                                'parent_dir': current_path
                            })
                            search_count += 1
                            
                        # 如果是目录，递归搜索
                        if is_directory and search_count < max_results:
                            search_recursive(item_path, query, search_type, case_sensitive)
                            
                    except (OSError, PermissionError) as e:
                        # 跳过无法访问的文件/目录
                        logger.debug(f"跳过无法访问的项目 {item_path}: {str(e)}")
                        continue
                        
            except (OSError, PermissionError) as e:
                logger.debug(f"无法访问目录 {current_path}: {str(e)}")
                return
                
        # 开始搜索
        search_recursive(search_path, search_query, search_type, case_sensitive)
        
        # 按类型和名称排序
        results.sort(key=lambda x: (0 if x['type'] == 'directory' else 1, x['name']))
        
        return jsonify({
            'status': 'success',
            'results': results,
            'search_path': search_path,
            'search_query': search_query,
            'search_type': search_type,
            'case_sensitive': case_sensitive,
            'total_found': len(results),
            'max_results': max_results,
            'truncated': search_count >= max_results
        })
        
    except Exception as e:
        logger.error(f"搜索文件时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'搜索失败: {str(e)}'})

@app.route('/api/create_folder', methods=['POST'])
def create_folder():
    """创建文件夹"""
    try:
        data = request.json
        path = data.get('path')
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的路径'})
            
        # 如果目录已存在，返回错误
        if os.path.exists(path):
            return jsonify({'status': 'error', 'message': '目录已存在'})
            
        # 创建目录
        os.makedirs(path)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"创建文件夹时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'创建文件夹失败: {str(e)}'})

@app.route('/api/rename', methods=['POST'])
def rename_item():
    """重命名文件或目录"""
    try:
        data = request.json
        old_path = data.get('oldPath')
        new_path = data.get('newPath')
        
        # 安全检查
        if not old_path or not new_path or '..' in old_path or '..' in new_path:
            return jsonify({'status': 'error', 'message': '无效的路径'})
            
        if not old_path.startswith('/') or not new_path.startswith('/'):
            return jsonify({'status': 'error', 'message': '路径必须是绝对路径'})
            
        # 确保源路径存在
        if not os.path.exists(old_path):
            return jsonify({'status': 'error', 'message': '源路径不存在'})
            
        # 如果目标路径已存在，返回错误
        if os.path.exists(new_path):
            return jsonify({'status': 'error', 'message': '目标路径已存在'})
            
        # 重命名文件或目录
        os.rename(old_path, new_path)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"重命名文件/目录时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'重命名失败: {str(e)}'})

@app.route('/api/semi-auto-deploy', methods=['POST'])
@auth_required
def semi_auto_deploy():
    """半自动部署服务器"""
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': '没有文件'}), 400
            
        file = request.files['file']
        server_name = request.form.get('server_name', '').strip()
        server_type = request.form.get('server_type', '').strip()
        jdk_version = request.form.get('jdk_version', '').strip()
        
        # 验证参数
        if not server_name:
            return jsonify({'status': 'error', 'message': '服务器名称不能为空'}), 400
            
        if not server_type:
            return jsonify({'status': 'error', 'message': '请选择服务端类型'}), 400
            
        if file.filename == '':
            return jsonify({'status': 'error', 'message': '没有选择文件'}), 400
            
        # 安全处理文件名
        filename = secure_filename(file.filename)
        
        # 检查文件扩展名
        allowed_extensions = ['.zip', '.rar', '.tar.gz', '.tar', '.7z']
        if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
            return jsonify({'status': 'error', 'message': '不支持的文件格式，请上传 .zip, .rar, .tar.gz, .tar, .7z 格式的压缩包'}), 400
            
        # 创建游戏目录
        games_dir = "/home/steam/games"
        game_dir = os.path.join(games_dir, server_name)
        
        # 检查目录是否已存在
        if os.path.exists(game_dir):
            return jsonify({'status': 'error', 'message': f'服务器 {server_name} 已存在，请选择其他名称'}), 400
            
        # 确保games目录存在
        os.makedirs(games_dir, exist_ok=True)
        os.makedirs(game_dir, exist_ok=True)
        
        # 保存上传的文件到临时位置
        temp_file = os.path.join(game_dir, filename)
        file.save(temp_file)
        
        logger.info(f"文件已上传: {temp_file}, 用户: {g.user.get('username')}")
        
        # 解压文件
        try:
            if filename.lower().endswith('.zip'):
                with zipfile.ZipFile(temp_file, 'r') as zip_ref:
                    zip_ref.extractall(game_dir)
            elif filename.lower().endswith('.rar'):
                with rarfile.RarFile(temp_file, 'r') as rar_ref:
                    rar_ref.extractall(game_dir)
            elif filename.lower().endswith(('.tar.gz', '.tar')):
                with tarfile.open(temp_file, 'r:*') as tar_ref:
                    tar_ref.extractall(game_dir)
            elif filename.lower().endswith('.7z'):
                # 使用7z命令行工具
                result = subprocess.run(['7z', 'x', temp_file, f'-o{game_dir}'], 
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    raise Exception(f"7z解压失败: {result.stderr}")
            else:
                raise Exception("不支持的压缩格式")
                
            logger.info(f"文件解压成功: {game_dir}")
            
        except Exception as e:
            # 清理失败的目录
            if os.path.exists(game_dir):
                shutil.rmtree(game_dir)
            logger.error(f"解压文件失败: {str(e)}")
            return jsonify({'status': 'error', 'message': f'解压文件失败: {str(e)}'}), 500
            
        # 删除原始压缩包
        try:
            os.remove(temp_file)
        except:
            pass
            
        # 设置目录权限
        try:
            subprocess.run(['chown', '-R', 'steam:steam', game_dir], check=True)
        except:
            logger.warning(f"设置目录权限失败: {game_dir}")
            
        # 如果是Java类型，生成启动脚本
        start_script = None
        if server_type == 'java':
            start_script = generate_java_start_script(game_dir, server_name, jdk_version)
            
        return jsonify({
            'status': 'success',
            'message': '服务器部署成功',
            'data': {
                'server_name': server_name,
                'game_dir': game_dir,
                'server_type': server_type,
                'start_script': start_script
            }
        })
        
    except Exception as e:
        logger.error(f"半自动部署时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'部署失败: {str(e)}'}), 500

def generate_java_start_script(game_dir, server_name, jdk_version=None):
    """生成Java启动脚本"""
    try:
        # 查找jar文件
        jar_files = []
        for root, dirs, files in os.walk(game_dir):
            for file in files:
                if file.lower().endswith('.jar') and not file.lower().startswith('libraries'):
                    jar_files.append(os.path.relpath(os.path.join(root, file), game_dir))
                    
        if not jar_files:
            logger.warning(f"在 {game_dir} 中未找到jar文件")
            return None
            
        # 选择最可能的服务端jar文件
        server_jar = None
        for jar in jar_files:
            jar_name = os.path.basename(jar).lower()
            if any(keyword in jar_name for keyword in ['server', 'spigot', 'paper', 'bukkit', 'forge', 'fabric']):
                server_jar = jar
                break
                
        if not server_jar:
            # 如果没找到明显的服务端jar，使用第一个
            server_jar = jar_files[0]
            
        # 确定Java可执行文件路径
        java_executable = "java"
        if jdk_version and jdk_version in JAVA_VERSIONS:
            java_dir = JAVA_VERSIONS[jdk_version]["dir"]
            java_executable = os.path.join(java_dir, "bin/java")
            
        # 生成启动脚本内容
        script_content = f"""#!/bin/bash
# {server_name} 服务器启动脚本
# 自动生成于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

cd "$(dirname "$0")"

# Java可执行文件路径
JAVA_EXEC="{java_executable}"

# 服务端jar文件
SERVER_JAR="{server_jar}"

# JVM参数
JVM_ARGS="-Xmx2G -Xms1G -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1"

# 启动服务器
echo "正在启动 {server_name} 服务器..."
echo "Java: $JAVA_EXEC"
echo "服务端: $SERVER_JAR"
echo "JVM参数: $JVM_ARGS"
echo ""

"$JAVA_EXEC" $JVM_ARGS -jar "$SERVER_JAR" nogui
"""
        
        # 写入启动脚本
        script_path = os.path.join(game_dir, "start.sh")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
            
        # 设置执行权限
        os.chmod(script_path, 0o755)
        
        logger.info(f"Java启动脚本已生成: {script_path}")
        return "start.sh"
        
    except Exception as e:
        logger.error(f"生成Java启动脚本失败: {str(e)}")
        return None

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传文件"""
    try:
        # 获取目标目录
        path = request.args.get('path', '/home/steam')
        
        # 获取认证令牌
        token_param = request.args.get('token')
        auth_header = request.headers.get('Authorization')
        
        # 检查认证
        token = None
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
                
        if not token and token_param:
            token = token_param
            
        if not token:
            logger.warning(f"上传文件请求缺少认证令牌: {path}")
            return jsonify({'status': 'error', 'message': '未授权的访问，请先登录'}), 401
            
        # 验证令牌
        payload = verify_token(token)
        if not payload:
            logger.warning(f"上传文件请求的令牌无效: {path}")
            return jsonify({'status': 'error', 'message': '令牌无效或已过期，请重新登录'}), 401
            
        # 认证通过，将用户信息保存到g对象
        g.user = payload
            
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的目标路径'}), 400
            
        # 确保目录存在
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '目标目录不存在'}), 400
            
        if not os.path.isdir(path):
            return jsonify({'status': 'error', 'message': '目标路径不是目录'}), 400
            
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': '没有文件'}), 400
            
        file = request.files['file']
        
        # 如果用户没有选择文件
        if file.filename == '':
            return jsonify({'status': 'error', 'message': '没有选择文件'}), 400
            
        # 安全处理文件名
        filename = secure_filename(file.filename)
        
        # 保存文件
        file_path = os.path.join(path, filename)
        file.save(file_path)
        
        logger.info(f"文件已上传: {file_path}, 用户: {payload.get('username')}")
        
        return jsonify({'status': 'success', 'message': '文件上传成功'})
        
    except Exception as e:
        logger.error(f"上传文件时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'上传文件失败: {str(e)}'}), 500

@app.route('/api/download', methods=['GET'])
def download_file():
    """下载文件"""
    try:
        # 从参数中获取文件路径和预览选项
        path = request.args.get('path')
        preview = request.args.get('preview', 'false').lower() == 'true'
        
        # logger.debug(f"下载文件请求: path={path}, preview={preview}, token={request.args.get('token', '')[:5]}...")
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
            
        # 确保文件存在
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '文件不存在'}), 404
            
        if not os.path.isfile(path):
            return jsonify({'status': 'error', 'message': '路径不是文件'}), 400
            
        # 获取文件名
        filename = os.path.basename(path)
        
        # 检查是否为图片预览
        if preview:
            # 获取文件MIME类型
            file_ext = os.path.splitext(path)[1].lower()
            mime_type = None
            
            # 设置常见图片文件的MIME类型
            if file_ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif file_ext == '.png':
                mime_type = 'image/png'
            elif file_ext == '.gif':
                mime_type = 'image/gif'
            elif file_ext == '.bmp':
                mime_type = 'image/bmp'
            elif file_ext == '.webp':
                mime_type = 'image/webp'
            elif file_ext == '.svg':
                mime_type = 'image/svg+xml'
            
            # 对于图片文件，如果是预览模式，设置合适的Content-Type
            if preview and mime_type.startswith('image/'):
                # logger.debug(f"预览图片: {path}, MIME类型: {mime_type}")
                return send_file(path, mimetype=mime_type)
            else:
                # logger.debug(f"下载文件: {path}, 文件名: {filename}")
                return send_file(path, as_attachment=True, download_name=filename, mimetype=mime_type)
        
        # 发送文件作为附件下载
        # logger.debug(f"下载文件: {path}, 文件名: {filename}")
        return send_file(path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        logger.error(f"下载文件时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'下载文件失败: {str(e)}'}), 500

@app.route('/api/compress', methods=['POST'])
def compress_files():
    """压缩文件，支持多种格式"""
    try:
        data = request.json
        paths = data.get('paths', [])
        current_path = data.get('currentPath', '')
        format = data.get('format', 'zip')  # 默认使用zip格式
        level = data.get('level', 6)  # 默认压缩级别
        
        # 创建临时目录用于存放压缩文件
        temp_dir = tempfile.mkdtemp()
        
        # 根据格式选择文件扩展名
        if format == 'zip':
            ext = '.zip'
        elif format == 'tar':
            ext = '.tar'
        elif format == 'tgz':
            ext = '.tar.gz'
        elif format == 'tbz2':
            ext = '.tar.bz2'
        elif format == 'txz':
            ext = '.tar.xz'
        elif format == 'tzst':
            ext = '.tar.zst'
        else:
            ext = '.zip'
            
        # 生成临时文件名
        temp_file = os.path.join(temp_dir, f'archive_{int(time.time())}{ext}')
        
        # 检查所有路径是否合法
        for path in paths:
            if not path.startswith('/') or '..' in path:
                return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
            if not os.path.exists(path):
                return jsonify({'status': 'error', 'message': f'文件不存在: {path}'}), 404
                
        # 获取所有文件的共同父目录
        common_path = os.path.commonpath([os.path.abspath(p) for p in paths])
        
        if format == 'zip':
            # 使用ZIP格式压缩
            with zipfile.ZipFile(temp_file, 'w', zipfile.ZIP_DEFLATED, compresslevel=level) as zipf:
                for path in paths:
                    if os.path.isfile(path):
                        # 添加文件
                        arcname = os.path.relpath(path, common_path)
                        zipf.write(path, arcname)
                    elif os.path.isdir(path):
                        # 添加目录及其内容
                        for root, dirs, files in os.walk(path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, common_path)
                                zipf.write(file_path, arcname)
                                
        elif format in ['tar', 'tgz', 'tbz2', 'txz']:
            # 使用TAR格式压缩
            mode = 'w:'
            if format == 'tgz':
                mode = 'w:gz'
            elif format == 'tbz2':
                mode = 'w:bz2'
            elif format == 'txz':
                mode = 'w:xz'
                
            with tarfile.open(temp_file, mode) as tarf:
                for path in paths:
                    # 添加文件或目录
                    arcname = os.path.relpath(path, common_path)
                    tarf.add(path, arcname=arcname)
                    
        elif format == 'tzst':
            # 使用TAR+ZSTD格式压缩
            # 首先创建tar文件
            tar_temp = os.path.join(temp_dir, 'temp.tar')
            with tarfile.open(tar_temp, 'w') as tarf:
                for path in paths:
                    arcname = os.path.relpath(path, common_path)
                    tarf.add(path, arcname=arcname)
            
            # 然后用zstd压缩tar文件
            cctx = zstd.ZstdCompressor(level=level)
            with open(tar_temp, 'rb') as tar_data:
                with open(temp_file, 'wb') as compressed:
                    cctx.copy_stream(tar_data, compressed)
            
            # 删除临时tar文件
            os.unlink(tar_temp)
            
        return jsonify({
            'status': 'success',
            'message': '文件已压缩',
            'zipPath': temp_file
        })
        
    except Exception as e:
        logger.error(f"压缩文件时出错: {str(e)}")
        # 清理临时文件
        if 'temp_file' in locals() and os.path.exists(temp_file):
            os.unlink(temp_file)
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'status': 'error', 'message': f'压缩文件失败: {str(e)}'}), 500

@app.route('/api/install_by_appid', methods=['POST'])
def install_by_appid():
    """通过AppID安装游戏"""
    try:
        data = request.json
        app_id = data.get('appid')
        game_name = data.get('name')
        anonymous = data.get('anonymous', True)
        account = data.get('account')
        password = data.get('password')
        
        if not app_id or not game_name:
            logger.error("缺少AppID或游戏名称")
            return jsonify({'status': 'error', 'message': '缺少AppID或游戏名称'}), 400
            
        logger.info(f"请求通过AppID安装游戏: AppID={app_id}, 名称={game_name}, 匿名={anonymous}")
        
        # 创建一个唯一的游戏ID
        game_id = f"app_{app_id}"
        
        # 检查是否已经有正在运行的安装进程
        if game_id in active_installations and active_installations[game_id].get('process') and active_installations[game_id]['process'].poll() is None:
            logger.info(f"游戏 {game_id} 已经在安装中")
            return jsonify({
                'status': 'success', 
                'message': f'游戏 {game_id} 已经在安装中'
            })
            
        # 清理任何旧的安装数据
        if game_id in active_installations:
            logger.info(f"清理游戏 {game_id} 的旧安装数据")
            old_process = active_installations[game_id].get('process')
            if old_process and old_process.poll() is None:
                try:
                    old_process.terminate()
                except:
                    pass
                    
        # 重置输出队列
        if game_id in output_queues:
            try:
                while not output_queues[game_id].empty():
                    output_queues[game_id].get_nowait()
            except:
                output_queues[game_id] = queue.Queue()
        else:
            output_queues[game_id] = queue.Queue()
            
        # 构建安装命令
        cmd = f"su - steam -c 'python3 {os.path.dirname(__file__)}/direct_installer.py {app_id} {game_id}"
        
        if not anonymous and account:
            cmd += f" --account {shlex.quote(account)}"
            if password:
                cmd += f" --password {shlex.quote(password)}"
        
        cmd += " 2>&1'"
        
        logger.info(f"准备执行命令 (将使用PTY): {cmd}")
        
        # 初始化安装状态跟踪
        active_installations[game_id] = {
            'process': None,
            'output': [],
            'started_at': time.time(),
            'complete': False,
            'cmd': cmd
        }
        
        # 在单独的线程中启动安装进程
        install_thread = threading.Thread(
            target=run_installation,
            args=(game_id, cmd),
            daemon=True
        )
        install_thread.start()
        
        # 添加一个确保安装后权限正确的线程
        def check_and_fix_permissions():
            # 等待安装进程完成
            install_thread.join(timeout=3600)  # 最多等待1小时
            # 检查安装是否已完成
            if game_id in active_installations and active_installations[game_id].get('complete'):
                # 安装完成后，确保游戏目录权限正确
                game_dir = os.path.join(GAMES_DIR, game_id)
                if os.path.exists(game_dir):
                    logger.info(f"安装完成，修复游戏目录权限: {game_dir}")
                    ensure_steam_permissions(game_dir)
                    
        # 启动权限修复线程
        permission_thread = threading.Thread(
            target=check_and_fix_permissions,
            daemon=True
        )
        permission_thread.start()
        
        logger.info(f"游戏 {game_id} 安装进程已启动")
        
        return jsonify({
            'status': 'success', 
            'message': f'游戏 {game_id} 安装已开始'
        })
    except Exception as e:
        logger.error(f"启动通过AppID安装进程失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加检查首次使用和注册的API
@app.route('/api/auth/check_first_use', methods=['GET'])
def check_first_use():
    """检查是否为首次使用，是否需要注册"""
    try:
        # 确保游戏目录存在
        if not os.path.exists(GAMES_DIR):
            try:
                os.makedirs(GAMES_DIR, exist_ok=True)
                logger.info(f"已创建游戏目录: {GAMES_DIR}")
                # 设置目录权限
                os.chmod(GAMES_DIR, 0o755)
                # 设置为steam用户所有
                subprocess.run(['chown', '-R', 'steam:steam', GAMES_DIR])
            except Exception as e:
                logger.error(f"创建游戏目录失败: {str(e)}")
                return jsonify({'status': 'error', 'message': f'创建游戏目录失败: {str(e)}'}), 500
        
        logger.info(f"检查是否首次使用，配置文件路径: {USER_CONFIG_PATH}")
        
        # 检查config.json是否存在
        if not os.path.exists(USER_CONFIG_PATH):
            logger.info(f"配置文件不存在，创建新文件: {USER_CONFIG_PATH}")
            # 创建一个空的config.json文件
            with open(USER_CONFIG_PATH, 'w') as f:
                json.dump({"first_use": True, "users": []}, f, indent=4)
            
            # 设置文件权限
            os.chmod(USER_CONFIG_PATH, 0o644)
            # 设置为steam用户所有
            subprocess.run(['chown', 'steam:steam', USER_CONFIG_PATH])
            
            logger.debug("返回首次使用状态: True (文件不存在)")
            return jsonify({
                'status': 'success',
                'first_use': True,
                'message': '首次使用，需要注册账号'
            })
        
        # 读取config.json
        with open(USER_CONFIG_PATH, 'r') as f:
            config = json.load(f)
            logger.info(f"配置文件内容: {config}")
        
        # 检查是否有用户注册
        if not config.get('users') or len(config.get('users', [])) == 0:
            logger.debug("返回首次使用状态: True (无用户)")
            return jsonify({
                'status': 'success',
                'first_use': True,
                'message': '首次使用，需要注册账号'
            })
        
        logger.debug("返回首次使用状态: False (已有用户)")
        return jsonify({
            'status': 'success',
            'first_use': False,
            'message': '系统已完成初始设置'
        })
        
    except Exception as e:
        logger.error(f"检查首次使用状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加注册路由
@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册路由"""
    try:
        data = request.json
        logger.info(f"收到注册请求: {data}")
        
        if not data:
            logger.warning("注册请求无效: 缺少请求数据")
            return jsonify({
                'status': 'error',
                'message': '无效的请求'
            }), 400
            
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            logger.warning("注册请求无效: 用户名或密码为空")
            return jsonify({
                'status': 'error',
                'message': '用户名和密码不能为空'
            }), 400
            
        # 确保游戏目录存在
        if not os.path.exists(GAMES_DIR):
            try:
                os.makedirs(GAMES_DIR, exist_ok=True)
                logger.info(f"已创建游戏目录: {GAMES_DIR}")
                # 设置目录权限
                os.chmod(GAMES_DIR, 0o755)
                # 设置为steam用户所有
                subprocess.run(['chown', '-R', 'steam:steam', GAMES_DIR])
            except Exception as e:
                logger.error(f"创建游戏目录失败: {str(e)}")
                return jsonify({'status': 'error', 'message': f'创建游戏目录失败: {str(e)}'}), 500
            
        # 检查config.json是否存在，不存在则创建
        if not os.path.exists(USER_CONFIG_PATH):
            logger.info(f"配置文件不存在，创建新文件: {USER_CONFIG_PATH}")
            with open(USER_CONFIG_PATH, 'w') as f:
                json.dump({"first_use": True, "users": []}, f, indent=4)
            # 设置文件权限
            os.chmod(USER_CONFIG_PATH, 0o644)
            # 设置为steam用户所有
            subprocess.run(['chown', 'steam:steam', USER_CONFIG_PATH])
        
        # 读取现有配置
        try:
            with open(USER_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                logger.info(f"读取配置文件成功，内容: {config}")
        except Exception as e:
            logger.warning(f"读取配置文件失败，创建新配置: {str(e)}")
            config = {"first_use": True, "users": []}
        
        # 检查是否已有用户注册，如果有则拒绝新的注册
        users = config.get('users', [])
        if len(users) > 0:
            logger.warning(f"已有用户注册，拒绝新用户注册请求: {username}")
            return jsonify({
                'status': 'error',
                'message': '系统仅允许一个用户注册，已有用户存在'
            }), 403
            
        # 检查用户名是否已存在
        for user in users:
            if user.get('username') == username:
                logger.warning(f"用户名已存在: {username}")
                return jsonify({
                    'status': 'error',
                    'message': '用户名已存在'
                }), 400
        
        # 对密码进行哈希处理
        password_hash, salt = hash_password(password)
        
        # 添加新用户，存储哈希密码和盐值
        new_user = {
            'username': username,
            'password_hash': password_hash,  # 存储哈希后的密码
            'salt': salt,  # 存储盐值
            'role': 'admin' if not users else 'user',  # 第一个注册的用户为管理员
            'created_at': time.time()
        }
        
        logger.info(f"创建新用户: {username}, 角色: {new_user['role']}")
        
        users.append(new_user)
        config['users'] = users
        config['first_use'] = False
        
        # 保存配置
        with open(USER_CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=4)
            logger.info(f"成功保存配置文件，用户数: {len(users)}")
        
        # 设置文件权限
        os.chmod(USER_CONFIG_PATH, 0o644)
        # 设置为steam用户所有
        subprocess.run(['chown', 'steam:steam', USER_CONFIG_PATH])
        
        # 同时也更新用户到auth_middleware中的users.json
        if save_user(new_user):
            logger.info(f"成功保存用户到auth_middleware: {username}")
        else:
            logger.warning(f"保存用户到auth_middleware失败: {username}")
        
        # 生成令牌
        token = generate_token(new_user)
        logger.info(f"生成令牌成功: {username}")
        
        return jsonify({
            'status': 'success',
            'message': '注册成功',
            'token': token,
            'username': username,
            'role': new_user.get('role', 'user')
        })
        
    except Exception as e:
        logger.error(f"注册失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 修改登录路由，从config.json中验证
@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录路由"""
    try:
        data = request.json
        if not data:
            return jsonify({
                'status': 'error',
                'message': '无效的请求'
            }), 400
            
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({
                'status': 'error',
                'message': '用户名和密码不能为空'
            }), 400
            
        # 确保游戏目录存在
        if not os.path.exists(GAMES_DIR):
            try:
                os.makedirs(GAMES_DIR, exist_ok=True)
                logger.info(f"已创建游戏目录: {GAMES_DIR}")
                # 设置目录权限
                os.chmod(GAMES_DIR, 0o755)
                # 设置为steam用户所有
                subprocess.run(['chown', '-R', 'steam:steam', GAMES_DIR])
            except Exception as e:
                logger.error(f"创建游戏目录失败: {str(e)}")
                # 目录创建失败不阻止登录流程
                
        # 检查config.json是否存在，不存在则创建
        is_first_use = False
        if not os.path.exists(USER_CONFIG_PATH):
            with open(USER_CONFIG_PATH, 'w') as f:
                json.dump({"first_use": True, "users": []}, f, indent=4)
            # 设置文件权限
            os.chmod(USER_CONFIG_PATH, 0o644)
            # 设置为steam用户所有
            subprocess.run(['chown', 'steam:steam', USER_CONFIG_PATH])
            is_first_use = True
            
        # 从config.json验证用户
        user = None
        if os.path.exists(USER_CONFIG_PATH):
            try:
                with open(USER_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
                
                # 如果是首次使用，直接返回需要注册的提示
                if is_first_use or not config.get('users'):
                    return jsonify({
                        'status': 'error',
                        'message': '首次使用，请先注册账号',
                        'first_use': True
                    }), 401
                
                users = config.get('users', [])
                for u in users:
                    # 兼容旧版本纯文本密码存储
                    if u.get('username') == username:
                        if 'password_hash' in u and 'salt' in u:
                            # 使用新的哈希验证
                            if verify_password(password, u.get('password_hash'), u.get('salt')):
                                user = u
                                break
                        elif 'password' in u:
                            # 兼容旧的明文密码验证
                            if u.get('password') == password:
                                # 自动升级到哈希存储
                                password_hash, salt = hash_password(password)
                                u['password_hash'] = password_hash
                                u['salt'] = salt
                                del u['password']  # 删除明文密码
                                
                                # 保存更新后的配置
                                with open(USER_CONFIG_PATH, 'w') as fw:
                                    json.dump(config, fw, indent=4)
                                logger.info(f"已升级用户 {username} 的密码存储到哈希格式")
                                
                                user = u
                                break
            except Exception as e:
                logger.error(f"从config.json验证用户失败: {str(e)}")
        
        # 如果没有找到用户或密码不匹配，返回错误
        if not user:
            logger.warning(f"用户名或密码错误: {username}")
            return jsonify({
                'status': 'error',
                'message': '用户名或密码错误'
            }), 401
            
        # 生成令牌
        token = generate_token(user)
        logger.info(f"用户 {username} 登录成功")
        
        return jsonify({
            'status': 'success',
            'token': token,
            'username': username,
            'role': user.get('role', 'user')
        })
    except Exception as e:
        logger.error(f"登录失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/open_game_folder', methods=['GET', 'POST'])
def open_game_folder():
    """在客户端打开指定的文件夹"""
    try:
        # 处理GET请求
        if request.method == 'GET':
            path = request.args.get('path', '/home/steam')
        # 处理POST请求
        else:
            data = request.json
            game_id = data.get('game_id')
            if game_id:
                path = os.path.join(GAMES_DIR, game_id)
            else:
                path = data.get('path', '/home/steam')
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件夹路径'})
            
        # 确保目录存在
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '文件夹不存在'})
            
        # 确保是目录
        if not os.path.isdir(path):
            return jsonify({'status': 'error', 'message': '路径不是文件夹'})
        
        # 在这里，我们只返回路径信息，因为在Web应用中无法直接打开客户端的文件夹
        # 实际的打开操作将在前端通过专门的功能（例如electron的shell.openPath）完成
        return jsonify({
            'status': 'success', 
            'path': path,
            'message': '请求打开文件夹'
        })
        
    except Exception as e:
        logger.error(f"请求打开文件夹时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'无法打开文件夹: {str(e)}'})

# FRP相关API

# 加载FRP配置
def load_frp_configs():
    """加载FRP配置"""
    if not os.path.exists(FRP_CONFIG_FILE):
        return []
    
    try:
        with open(FRP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载FRP配置失败: {str(e)}")
        return []

# 保存FRP配置
def save_frp_configs(configs):
    """保存FRP配置"""
    try:
        with open(FRP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存FRP配置失败: {str(e)}")
        return False

# 获取FRP状态
def get_frp_status(frp_id):
    """获取FRP状态"""
    if frp_id in running_frp_processes:
        process = running_frp_processes[frp_id]['process']
        if process.poll() is None:  # 进程仍在运行
            return 'running'
    return 'stopped'

# 更新所有FRP状态
def update_all_frp_status():
    """更新所有FRP状态"""
    configs = load_frp_configs()
    updated_configs = []
    
    for config in configs:
        config['status'] = get_frp_status(config['id'])
        updated_configs.append(config)
    
    return updated_configs

# 获取FRP列表
@app.route('/api/frp/list', methods=['GET'])
def list_frp():
    try:
        configs = update_all_frp_status()
        return jsonify({
            'status': 'success',
            'configs': configs
        })
    except Exception as e:
        logger.error(f"获取FRP列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取FRP列表失败: {str(e)}"
        }), 500

# 创建FRP配置
@app.route('/api/frp/create', methods=['POST'])
def create_frp():
    try:
        data = request.json
        name = data.get('name')
        frp_type = data.get('type', 'general')
        command = data.get('command')
        
        if not name or not command:
            return jsonify({
                'status': 'error',
                'message': '配置名称和命令不能为空'
            }), 400
        
        # 生成唯一ID
        frp_id = str(uuid.uuid4())
        
        # 创建新配置
        new_config = {
            'id': frp_id,
            'name': name,
            'type': frp_type,
            'command': command,
            'status': 'stopped',
            'created_at': time.time()
        }
        
        # 加载现有配置并添加新配置
        configs = load_frp_configs()
        configs.append(new_config)
        
        # 保存配置
        if save_frp_configs(configs):
            return jsonify({
                'status': 'success',
                'message': 'FRP配置创建成功',
                'config': new_config
            })
        else:
            return jsonify({
                'status': 'error',
                'message': '保存FRP配置失败'
            }), 500
    except Exception as e:
        logger.error(f"创建FRP配置失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"创建FRP配置失败: {str(e)}"
        }), 500

# 启动FRP
@app.route('/api/frp/start', methods=['POST'])
def start_frp():
    try:
        data = request.json
        frp_id = data.get('id')
        
        if not frp_id:
            return jsonify({
                'status': 'error',
                'message': 'FRP ID不能为空'
            }), 400
        
        # 加载配置
        configs = load_frp_configs()
        target_config = None
        
        for config in configs:
            if config['id'] == frp_id:
                target_config = config
                break
        
        if not target_config:
            return jsonify({
                'status': 'error',
                'message': '未找到指定的FRP配置'
            }), 404
        
        # 检查FRP是否已经在运行
        if frp_id in running_frp_processes:
            process = running_frp_processes[frp_id]['process']
            if process.poll() is None:  # 进程仍在运行
                return jsonify({
                    'status': 'success',
                    'message': 'FRP已经在运行中'
                })
        
        # 根据FRP类型选择不同的二进制文件和目录
        frp_binary = FRP_BINARY
        frp_dir = os.path.join(FRP_DIR, "LoCyanFrp")
        
        if target_config['type'] == 'custom':
            frp_binary = CUSTOM_FRP_BINARY
            frp_dir = CUSTOM_FRP_DIR
        elif target_config['type'] == 'mefrp':
            frp_binary = MEFRP_BINARY
            frp_dir = MEFRP_DIR
        elif target_config['type'] == 'sakura':
            frp_binary = SAKURA_BINARY
            frp_dir = SAKURA_DIR
        elif target_config['type'] == 'npc':
            frp_binary = NPC_BINARY
            frp_dir = NPC_DIR
        
        # 确保FRP可执行
        if not os.path.exists(frp_binary):
            return jsonify({
                'status': 'error',
                'message': f'{target_config["type"]}客户端程序不存在'
            }), 500
        
        # 设置可执行权限
        os.chmod(frp_binary, 0o755)
        
        # 创建日志文件
        log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
        log_file = open(log_file_path, 'w')
        
        # 构建命令
        command = f"{frp_binary} {target_config['command']}"
        
        # 启动FRP进程
        process = subprocess.Popen(
            shlex.split(command),
            stdout=log_file,
            stderr=log_file,
            cwd=frp_dir
        )
        
        # 保存进程信息
        running_frp_processes[frp_id] = {
            'process': process,
            'log_file': log_file_path,
            'started_at': time.time()
        }
        
        # 更新配置状态
        for config in configs:
            if config['id'] == frp_id:
                config['status'] = 'running'
                break
        
        save_frp_configs(configs)
        
        return jsonify({
            'status': 'success',
            'message': 'FRP已启动'
        })
    except Exception as e:
        logger.error(f"启动FRP失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"启动FRP失败: {str(e)}"
        }), 500

# 停止FRP
@app.route('/api/frp/stop', methods=['POST'])
def stop_frp():
    try:
        data = request.json
        frp_id = data.get('id')
        
        if not frp_id:
            return jsonify({
                'status': 'error',
                'message': 'FRP ID不能为空'
            }), 400
        
        # 将此FRP标记为人工停止
        manually_stopped_frps.add(frp_id)
        logger.info(f"已将FRP {frp_id} 标记为人工停止")
        
        # 检查FRP是否在运行
        if frp_id not in running_frp_processes:
            return jsonify({
                'status': 'success',
                'message': 'FRP未在运行'
            })
        
        # 获取进程信息
        process_info = running_frp_processes[frp_id]
        process = process_info['process']
        
        # 尝试终止进程
        if process.poll() is None:  # 进程仍在运行
            process.terminate()
            try:
                process.wait(timeout=5)  # 等待进程终止
            except subprocess.TimeoutExpired:
                process.kill()  # 如果超时，强制终止
        
        # 关闭日志文件
        log_file_path = process_info['log_file']
        
        # 从运行列表中移除
        del running_frp_processes[frp_id]
        
        # 更新配置状态
        configs = load_frp_configs()
        for config in configs:
            if config['id'] == frp_id:
                config['status'] = 'stopped'
                break
        
        save_frp_configs(configs)
        
        return jsonify({
            'status': 'success',
            'message': 'FRP已停止'
        })
    except Exception as e:
        logger.error(f"停止FRP失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"停止FRP失败: {str(e)}"
        }), 500

# 删除FRP配置
@app.route('/api/frp/delete', methods=['POST'])
def delete_frp():
    try:
        data = request.json
        frp_id = data.get('id')
        
        if not frp_id:
            return jsonify({
                'status': 'error',
                'message': 'FRP ID不能为空'
            }), 400
        
        # 如果FRP正在运行，先停止它
        if frp_id in running_frp_processes:
            process_info = running_frp_processes[frp_id]
            process = process_info['process']
            
            if process.poll() is None:  # 进程仍在运行
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            
            # 从运行列表中移除
            del running_frp_processes[frp_id]
        
        # 删除日志文件
        log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
        
        # 更新配置
        configs = load_frp_configs()
        configs = [config for config in configs if config['id'] != frp_id]
        save_frp_configs(configs)
        
        return jsonify({
            'status': 'success',
            'message': 'FRP配置已删除'
        })
    except Exception as e:
        logger.error(f"删除FRP配置失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"删除FRP配置失败: {str(e)}"
        }), 500

# 获取FRP日志
@app.route('/api/frp/log', methods=['GET'])
def get_frp_log():
    try:
        frp_id = request.args.get('id')
        
        if not frp_id:
            return jsonify({
                'status': 'error',
                'message': 'FRP ID不能为空'
            }), 400
        
        # 获取日志文件路径
        if frp_id in running_frp_processes:
            # 如果FRP正在运行，使用当前日志文件
            log_file_path = running_frp_processes[frp_id]['log_file']
        else:
            # 如果FRP未运行，尝试读取历史日志文件
            log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
        
        # 检查日志文件是否存在
        if not os.path.exists(log_file_path):
            return jsonify({
                'status': 'success',
                'log': '暂无日志记录'
            })
        
        # 读取日志内容
        with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
            
        return jsonify({
            'status': 'success',
            'log': log_content
        })
    except Exception as e:
        logger.error(f"获取FRP日志失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取FRP日志失败: {str(e)}"
        }), 500

# 获取自建FRP配置
@app.route('/api/frp/custom/config', methods=['GET'])
def get_custom_frp_config():
    try:
        if not os.path.exists(CUSTOM_FRP_CONFIG_FILE):
            # 如果配置文件不存在，返回默认配置
            default_config = {
                'serverAddr': '127.0.0.1',
                'serverPort': 7000,
                'token': '',
                'proxies': []
            }
            return jsonify({
                'status': 'success',
                'config': default_config
            })
        
        # 读取配置文件
        with open(CUSTOM_FRP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析TOML配置
        config = {
            'serverAddr': '',
            'serverPort': 7000,
            'token': '',
            'proxies': []
        }
        
        # 简单解析TOML文件
        lines = content.split('\n')
        current_proxy = None
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if line.startswith('serverAddr'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    config['serverAddr'] = parts[1].strip().strip('"\'')
            elif line.startswith('serverPort'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    try:
                        config['serverPort'] = int(parts[1].strip())
                    except ValueError:
                        pass
            elif line.startswith('token') or line.startswith('auth.token'):
                parts = line.split('=', 1)
                if len(parts) == 2:
                    config['token'] = parts[1].strip().strip('"\'')
            elif line.startswith('[[proxies]]'):
                current_proxy = {}
                config['proxies'].append(current_proxy)
            elif current_proxy is not None and '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().strip('"\'')
                    if key == 'localPort' or key == 'remotePort':
                        try:
                            current_proxy[key] = int(value)
                        except ValueError:
                            current_proxy[key] = value
                    else:
                        current_proxy[key] = value
        
        return jsonify({
            'status': 'success',
            'config': config
        })
    except Exception as e:
        logger.error(f"获取自建FRP配置失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取自建FRP配置失败: {str(e)}"
        }), 500

# 保存自建FRP配置
@app.route('/api/frp/custom/config', methods=['POST'])
def save_custom_frp_config():
    try:
        data = request.json
        server_addr = data.get('serverAddr')
        server_port = data.get('serverPort')
        token = data.get('token', '')
        proxies = data.get('proxies', [])
        
        if not server_addr:
            return jsonify({
                'status': 'error',
                'message': '服务器地址不能为空'
            }), 400
        
        # 生成TOML配置
        config_content = f'serverAddr = "{server_addr}"\n'
        config_content += f'serverPort = {server_port}\n'
        
        if token:
            config_content += f'auth.token = "{token}"\n'
        
        # 添加代理配置
        for proxy in proxies:
            config_content += '\n[[proxies]]\n'
            for key, value in proxy.items():
                if isinstance(value, str):
                    config_content += f'{key} = "{value}"\n'
                else:
                    config_content += f'{key} = {value}\n'
        
        # 保存配置文件
        with open(CUSTOM_FRP_CONFIG_FILE, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        return jsonify({
            'status': 'success',
            'message': '自建FRP配置保存成功'
        })
    except Exception as e:
        logger.error(f"保存自建FRP配置失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"保存自建FRP配置失败: {str(e)}"
        }), 500

# 启动自建FRP
@app.route('/api/frp/custom/start', methods=['POST'])
def start_custom_frp():
    try:
        # 生成唯一ID
        frp_id = 'custom_frp'
        
        # 检查FRP是否已经在运行
        if frp_id in running_frp_processes:
            process = running_frp_processes[frp_id]['process']
            if process.poll() is None:  # 进程仍在运行
                return jsonify({
                    'status': 'success',
                    'message': '自建FRP已经在运行中'
                })
        
        # 确保FRP可执行
        if not os.path.exists(CUSTOM_FRP_BINARY):
            return jsonify({
                'status': 'error',
                'message': '自建FRP客户端程序不存在'
            }), 500
        
        # 设置可执行权限
        os.chmod(CUSTOM_FRP_BINARY, 0o755)
        
        # 创建日志文件
        log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
        log_file = open(log_file_path, 'w')
        
        # 构建命令
        command = f"{CUSTOM_FRP_BINARY} -c {CUSTOM_FRP_CONFIG_FILE}"
        
        # 启动FRP进程
        process = subprocess.Popen(
            shlex.split(command),
            stdout=log_file,
            stderr=log_file,
            cwd=CUSTOM_FRP_DIR
        )
        
        # 保存进程信息
        running_frp_processes[frp_id] = {
            'process': process,
            'log_file': log_file_path,
            'started_at': time.time()
        }
        
        # 更新配置状态
        configs = load_frp_configs()
        for config in configs:
            if config['id'] == frp_id:
                config['status'] = 'running'
                break
        
        save_frp_configs(configs)
        
        return jsonify({
            'status': 'success',
            'message': '自建FRP已启动'
        })
    except Exception as e:
        logger.error(f"启动自建FRP失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"启动自建FRP失败: {str(e)}"
        }), 500

# 停止自建FRP
@app.route('/api/frp/custom/stop', methods=['POST'])
def stop_custom_frp():
    try:
        frp_id = 'custom_frp'
        
        # 将自建FRP标记为人工停止
        manually_stopped_frps.add(frp_id)
        logger.info(f"已将自建FRP {frp_id} 标记为人工停止")
        
        # 检查FRP是否在运行
        if frp_id not in running_frp_processes:
            return jsonify({
                'status': 'success',
                'message': '自建FRP未在运行'
            })
        
        # 获取进程信息
        process_info = running_frp_processes[frp_id]
        process = process_info['process']
        
        # 尝试终止进程
        if process.poll() is None:  # 进程仍在运行
            process.terminate()
            try:
                process.wait(timeout=5)  # 等待进程终止
            except subprocess.TimeoutExpired:
                process.kill()  # 如果超时，强制终止
        
        # 从运行列表中移除
        del running_frp_processes[frp_id]
        
        return jsonify({
            'status': 'success',
            'message': '自建FRP已停止'
        })
    except Exception as e:
        logger.error(f"停止自建FRP失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"停止自建FRP失败: {str(e)}"
        }), 500

# 获取自建FRP状态
@app.route('/api/frp/custom/status', methods=['GET'])
def get_custom_frp_status():
    try:
        frp_id = 'custom_frp'
        status = get_frp_status(frp_id)
        
        return jsonify({
            'status': 'success',
            'frp_status': status
        })
    except Exception as e:
        logger.error(f"获取自建FRP状态失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取自建FRP状态失败: {str(e)}"
        }), 500

@app.route('/api/extract', methods=['POST'])
def extract_archive():
    """解压缩文件，支持多种格式"""
    try:
        data = request.json
        file_path = data.get('path')
        target_dir = data.get('targetDir')
        
        # 安全检查
        if not file_path or '..' in file_path or not file_path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
            
        if not target_dir or '..' in target_dir or not target_dir.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的目标目录'}), 400
            
        # 确保文件存在
        if not os.path.exists(file_path):
            return jsonify({'status': 'error', 'message': '文件不存在'}), 404
            
        if not os.path.isfile(file_path):
            return jsonify({'status': 'error', 'message': '路径不是文件'}), 400
            
        # 确保目标目录存在
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        elif not os.path.isdir(target_dir):
            return jsonify({'status': 'error', 'message': '目标路径不是目录'}), 400
            
        # 获取文件扩展名
        file_ext = os.path.splitext(file_path)[1].lower()
        file_name = os.path.basename(file_path)
        
        # 特别处理.tar.gz、.tar.xz和.tar.zst格式
        if file_path.endswith('.tar.gz') or file_path.endswith('.tar.xz') or file_path.endswith('.tar.zst'):
            if file_path.endswith('.tar.gz'):
                mode = 'r:gz'
            elif file_path.endswith('.tar.xz'):
                mode = 'r:xz'
            elif file_path.endswith('.tar.zst'):
                # 对于tar.zst，我们需要先解压zst，然后再解压tar
                with open(file_path, 'rb') as compressed:
                    dctx = zstd.ZstdDecompressor()
                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        dctx.copy_stream(compressed, tmp)
                        tmp_path = tmp.name
                
                try:
                    with tarfile.open(tmp_path, 'r:') as tarf:
                        tarf.extractall(target_dir)
                finally:
                    os.unlink(tmp_path)
                return jsonify({
                    'status': 'success',
                    'message': '文件已解压',
                    'targetDir': target_dir
                })
                
            with tarfile.open(file_path, mode) as tarf:
                tarf.extractall(target_dir)
            return jsonify({
                'status': 'success',
                'message': '文件已解压',
                'targetDir': target_dir
            })
            
        # 根据文件扩展名选择解压方法
        if file_ext in ['.zip', '.jar', '.apk']:
            # 处理ZIP文件
            with zipfile.ZipFile(file_path, 'r') as zipf:
                zipf.extractall(target_dir)
                
        elif file_ext in ['.tar']:
            # 处理TAR文件
            with tarfile.open(file_path, 'r') as tarf:
                tarf.extractall(target_dir)
                
        elif file_ext in ['.gz', '.tgz']:
            # 处理TAR.GZ文件
            if file_ext == '.tgz' or file_path.endswith('.tar.gz'):
                with tarfile.open(file_path, 'r:gz') as tarf:
                    tarf.extractall(target_dir)
            else:
                # 处理单个gzip文件
                with gzip.open(file_path, 'rb') as f_in:
                    # 提取不带.gz扩展名的原始文件名
                    output_file = os.path.join(target_dir, os.path.splitext(file_name)[0])
                    with open(output_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
        elif file_ext in ['.bz2']:
            # 处理TAR.BZ2或单个BZ2文件
            if file_path.endswith('.tar.bz2'):
                with tarfile.open(file_path, 'r:bz2') as tarf:
                    tarf.extractall(target_dir)
            else:
                # 处理单个bzip2文件
                with bz2.open(file_path, 'rb') as f_in:
                    # 提取不带.bz2扩展名的原始文件名
                    output_file = os.path.join(target_dir, os.path.splitext(file_name)[0])
                    with open(output_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
        elif file_ext in ['.xz']:
            # 处理.xz文件
            if file_path.endswith('.tar.xz'):
                with tarfile.open(file_path, 'r:xz') as tarf:
                    tarf.extractall(target_dir)
            else:
                # 处理单个xz文件
                with lzma.open(file_path, 'rb') as f_in:
                    # 提取不带.xz扩展名的原始文件名
                    output_file = os.path.join(target_dir, os.path.splitext(file_name)[0])
                    with open(output_file, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                        
        elif file_ext in ['.zst']:
            # 处理.zst文件
            with open(file_path, 'rb') as compressed:
                dctx = zstd.ZstdDecompressor()
                # 提取不带.zst扩展名的原始文件名
                output_file = os.path.join(target_dir, os.path.splitext(file_name)[0])
                with open(output_file, 'wb') as f_out:
                    dctx.copy_stream(compressed, f_out)
                        
        elif file_ext in ['.rar']:
            # 处理RAR文件，需要安装python-rarfile库
            try:
                with rarfile.RarFile(file_path) as rf:
                    rf.extractall(target_dir)
            except ImportError:
                # 如果没有安装rarfile库，尝试使用unrar命令
                try:
                    subprocess.run(['unrar', 'x', file_path, target_dir], check=True)
                except (subprocess.SubprocessError, FileNotFoundError):
                    return jsonify({
                        'status': 'error', 
                        'message': '解压RAR文件失败，系统未安装rarfile模块或unrar命令'
                    }), 500
                    
        elif file_ext in ['.7z']:
            # 处理7z文件，需要系统安装p7zip
            try:
                subprocess.run(['7z', 'x', file_path, '-o' + target_dir], check=True)
            except (subprocess.SubprocessError, FileNotFoundError):
                return jsonify({
                    'status': 'error', 
                    'message': '解压7Z文件失败，系统未安装7z命令'
                }), 500
                
        else:
            return jsonify({
                'status': 'error', 
                'message': f'不支持的文件格式: {file_ext}'
            }), 400
            
        logger.info(f"文件已解压: {file_path} -> {target_dir}")
        
        return jsonify({
            'status': 'success',
            'message': '文件已解压',
            'targetDir': target_dir
        })
        
    except Exception as e:
        logger.error(f"解压文件时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'解压文件失败: {str(e)}'}), 500

@app.route('/api/chmod', methods=['POST'])
def change_permissions():
    """修改文件或目录的权限"""
    try:
        data = request.json
        path = data.get('path')
        mode = data.get('mode')  # 数字形式的权限，如：0o755
        recursive = data.get('recursive', False)  # 是否递归修改子目录和文件
        
        # 安全检查
        if not path or '..' in path or not path.startswith('/'):
            return jsonify({'status': 'error', 'message': '无效的文件路径'}), 400
            
        if not os.path.exists(path):
            return jsonify({'status': 'error', 'message': '文件或目录不存在'}), 404
            
        if not isinstance(mode, int):
            try:
                # 如果传入的是字符串，尝试转换为整数
                mode = int(str(mode), 8)
            except ValueError:
                return jsonify({'status': 'error', 'message': '无效的权限值'}), 400

        if recursive and os.path.isdir(path):
            # 递归修改目录及其内容的权限
            for root, dirs, files in os.walk(path):
                # 修改目录权限
                os.chmod(root, mode)
                # 修改文件权限
                for file in files:
                    os.chmod(os.path.join(root, file), mode)
        else:
            # 仅修改当前文件或目录的权限
            os.chmod(path, mode)
            
        # 获取更新后的权限
        current_mode = stat.S_IMODE(os.stat(path).st_mode)
        
        return jsonify({
            'status': 'success',
            'message': '权限修改成功',
            'path': path,
            'mode': oct(current_mode)
        })
        
    except Exception as e:
        logger.error(f"修改权限失败: {str(e)}")
        return jsonify({'status': 'error', 'message': f'修改权限失败: {str(e)}'}), 500

@app.route('/api/server/start_steamcmd', methods=['POST'])
def start_steamcmd():
    """启动SteamCMD"""
    try:
        logger.info("请求启动SteamCMD")
        
        # SteamCMD目录
        steamcmd_dir = "/home/steam/steamcmd"
        steamcmd_path = os.path.join(steamcmd_dir, "steamcmd.sh")
        
        # 检查steamcmd.sh是否存在
        if not os.path.exists(steamcmd_path):
            logger.error(f"SteamCMD不存在: {steamcmd_path}")
            return jsonify({'status': 'error', 'message': f'SteamCMD不存在，请确保系统中已安装SteamCMD'}), 400
            
        # 确保steamcmd.sh有执行权限
        if not os.access(steamcmd_path, os.X_OK):
            logger.info(f"添加SteamCMD执行权限: {steamcmd_path}")
            os.chmod(steamcmd_path, 0o755)
        
        # 固定的游戏ID用于steamcmd
        game_id = "steamcmd"
        process_id = f"server_{game_id}"
        
        # 首先检查PTY管理器中是否存在该进程ID
        if pty_manager.get_process(process_id):
            logger.info(f"PTY管理器中存在进程ID {process_id}，但可能是残留的记录")
            # 移除PTY管理器中的进程记录
            pty_manager.remove_process(process_id)
            logger.info(f"已从PTY管理器中移除可能残留的进程记录: {process_id}")
        
        # 检查running_servers字典中是否存在steamcmd
        if game_id in running_servers:
            server_data = running_servers[game_id]
            process = server_data.get('process')
            
            # 检查进程是否仍在运行
            if process and process.poll() is None:
                logger.info(f"SteamCMD已经在运行中")
                return jsonify({
                    'status': 'success', 
                    'message': 'SteamCMD已经在运行中',
                    'already_running': True
                })
            else:
                # 进程已结束，但字典中仍有记录，清理旧数据
                logger.info(f"清理SteamCMD的旧运行数据")
                
                # 尝试终止任何可能仍在运行的进程
                try:
                    if process and process.poll() is None:
                        process.terminate()
                        time.sleep(0.5)
                        if process.poll() is None:
                            process.kill()
                except Exception as e:
                    logger.warning(f"终止旧进程时出错: {str(e)}")
                
                # 从字典中移除
                del running_servers[game_id]
        
        # 清理输出队列
        if game_id in server_output_queues:
            try:
                while not server_output_queues[game_id].empty():
                    server_output_queues[game_id].get_nowait()
            except:
                server_output_queues[game_id] = queue.Queue()
        else:
            server_output_queues[game_id] = queue.Queue()
            
        # 构建启动命令，确保以steam用户运行
        cmd = f"su - steam -c 'cd {steamcmd_dir} && ./steamcmd.sh'"
        logger.debug(f"准备执行命令 (将使用PTY): {cmd}")
        
        # 初始化服务器状态跟踪
        running_servers[game_id] = {
            'process': None,
            'output': [],
            'started_at': time.time(),
            'running': True,
            'return_code': None,
            'cmd': cmd,
            'master_fd': None,
            'game_dir': steamcmd_dir,
            'external': False
        }
        
        # 在单独的线程中启动服务器
        server_thread = threading.Thread(
            target=run_game_server,
            args=(game_id, cmd, steamcmd_dir),
            daemon=True
        )
        server_thread.start()
        
        logger.info(f"SteamCMD启动线程已启动")
        time.sleep(0.5)
        server_output_queues[game_id].put("SteamCMD启动中...")
        server_output_queues[game_id].put(f"SteamCMD目录: {steamcmd_dir}")
        server_output_queues[game_id].put(f"启动命令: {cmd}")
        
        # 添加到输出历史
        if 'output' not in running_servers[game_id]:
            running_servers[game_id]['output'] = []
        add_server_output(game_id, "SteamCMD启动中...")
        add_server_output(game_id, f"SteamCMD目录: {steamcmd_dir}")
        add_server_output(game_id, f"启动命令: {cmd}")
        
        return jsonify({
            'status': 'success', 
            'message': 'SteamCMD启动已开始'
        })
        
    except Exception as e:
        logger.error(f"启动SteamCMD失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 密码哈希功能从auth_middleware.py导入

@app.route('/api/network_info', methods=['GET'])
def get_network_info():
    """获取网络状态和公网IP信息"""
    try:
        # 获取网络接口信息
        network_interfaces = {}
        for interface, addrs in psutil.net_if_addrs().items():
            # 过滤掉lo接口
            if interface == 'lo':
                continue
                
            network_interfaces[interface] = {
                'addresses': [],
                'status': 'down'  # 默认为down
            }
            
            # 获取地址信息
            for addr in addrs:
                if addr.family == socket.AF_INET:  # IPv4
                    network_interfaces[interface]['addresses'].append({
                        'type': 'ipv4',
                        'address': addr.address,
                        'netmask': addr.netmask
                    })
                elif addr.family == socket.AF_INET6:  # IPv6
                    network_interfaces[interface]['addresses'].append({
                        'type': 'ipv6',
                        'address': addr.address,
                        'netmask': addr.netmask
                    })
        
        # 获取接口状态
        for interface, stats in psutil.net_if_stats().items():
            if interface in network_interfaces:
                network_interfaces[interface]['status'] = 'up' if stats.isup else 'down'
                network_interfaces[interface]['speed'] = stats.speed  # Mbps
                network_interfaces[interface]['duplex'] = stats.duplex
                network_interfaces[interface]['mtu'] = stats.mtu
        
        # 获取网络流量统计
        net_io = psutil.net_io_counters(pernic=True)
        io_stats = {}
        
        for interface, stats in net_io.items():
            if interface in network_interfaces:
                io_stats[interface] = {
                    'bytes_sent': stats.bytes_sent,
                    'bytes_recv': stats.bytes_recv,
                    'packets_sent': stats.packets_sent,
                    'packets_recv': stats.packets_recv,
                    'errin': stats.errin,
                    'errout': stats.errout,
                    'dropin': stats.dropin,
                    'dropout': stats.dropout
                }
        
        # 创建一个后台线程来异步获取公网IP，不阻塞主请求
        def fetch_public_ip():
            public_ip = {
                'ipv4': None,
                'ipv6': None
            }
            
            try:
                # 获取公网IPv4
                ipv4_response = requests.get('https://ipv4.ip.mir6.com', timeout=5)
                if ipv4_response.status_code == 200:
                    public_ip['ipv4'] = ipv4_response.text
            except Exception as e:
                logger.warning(f"获取公网IPv4失败: {str(e)}")
                
            try:
                # 获取公网IPv6
                ipv6_response = requests.get('https://ipv6.ip.mir6.com', timeout=5)
                if ipv6_response.status_code == 200:
                    public_ip['ipv6'] = ipv6_response.text
            except Exception as e:
                logger.warning(f"获取公网IPv6失败: {str(e)}")
                
            # 更新缓存
            with public_ip_lock:
                global cached_public_ip, public_ip_timestamp
                cached_public_ip = public_ip
                public_ip_timestamp = time.time()
        
        # 使用缓存的公网IP或启动异步更新
        public_ip = {
            'ipv4': None,
            'ipv6': None
        }
        
        with public_ip_lock:
            current_time = time.time()
            # 如果缓存存在且未过期（5分钟有效期）
            if cached_public_ip and current_time - public_ip_timestamp < 300:
                public_ip = cached_public_ip
            else:
                # 如果缓存不存在或已过期，启动后台线程更新
                threading.Thread(target=fetch_public_ip, daemon=True).start()
        
        return jsonify({
            'status': 'success',
            'network_interfaces': network_interfaces,
            'public_ip': public_ip,
            'io_stats': io_stats
        })
        
    except Exception as e:
        logger.error(f"获取网络信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/system_processes', methods=['GET'])
@auth_required
def get_system_processes():
    """获取当前运行的所有进程信息"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'create_time', 'cmdline']):
            try:
                proc_info = proc.info
                # 过滤掉一些系统进程和权限不足的进程
                if proc_info['name'] and proc_info['pid'] > 1:
                    # 获取命令行参数，限制长度
                    cmdline = ' '.join(proc_info['cmdline'] or [])[:100]
                    if len(cmdline) > 100:
                        cmdline += '...'
                    
                    processes.append({
                        'pid': proc_info['pid'],
                        'name': proc_info['name'],
                        'username': proc_info['username'] or 'unknown',
                        'cpu_percent': round(proc_info['cpu_percent'] or 0, 2),
                        'memory_percent': round(proc_info['memory_percent'] or 0, 2),
                        'create_time': proc_info['create_time'],
                        'cmdline': cmdline
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        # 按CPU使用率排序
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        
        return jsonify({
            'status': 'success',
            'processes': processes
        })
        
    except Exception as e:
        logger.error(f"获取进程信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/system_ports', methods=['GET'])
@auth_required
def get_system_ports():
    """获取当前活跃的端口和对应的进程信息"""
    try:
        ports = []
        port_set = set()  # 用于去重
        
        # 获取所有网络连接（包括IPv4和IPv6）
        try:
            connections = psutil.net_connections(kind='inet')
        except psutil.AccessDenied:
            # 如果权限不足，尝试只获取当前进程的连接
            connections = psutil.net_connections(kind='inet', perproc=False)
        
        for conn in connections:
            try:
                port_info = None
                
                # 处理监听端口（服务器端口）
                if conn.status == psutil.CONN_LISTEN and conn.laddr:
                    port_key = (conn.laddr.port, conn.laddr.ip, 'LISTEN')
                    if port_key not in port_set:
                        port_set.add(port_key)
                        port_info = {
                            'port': conn.laddr.port,
                            'address': conn.laddr.ip,
                            'family': 'IPv4' if conn.family == socket.AF_INET else 'IPv6',
                            'type': 'TCP' if conn.type == socket.SOCK_STREAM else 'UDP',
                            'status': 'LISTEN',
                            'pid': conn.pid,
                            'process_name': None,
                            'process_cmdline': None
                        }
                
                # 处理已建立的连接（显示本地端口）
                elif conn.status == psutil.CONN_ESTABLISHED and conn.laddr:
                    port_key = (conn.laddr.port, conn.laddr.ip, 'ESTABLISHED')
                    if port_key not in port_set:
                        port_set.add(port_key)
                        remote_info = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "Unknown"
                        port_info = {
                            'port': conn.laddr.port,
                            'address': conn.laddr.ip,
                            'family': 'IPv4' if conn.family == socket.AF_INET else 'IPv6',
                            'type': 'TCP' if conn.type == socket.SOCK_STREAM else 'UDP',
                            'status': f'ESTABLISHED -> {remote_info}',
                            'pid': conn.pid,
                            'process_name': None,
                            'process_cmdline': None
                        }
                
                # 处理UDP连接（通常没有状态）
                elif conn.type == socket.SOCK_DGRAM and conn.laddr:
                    port_key = (conn.laddr.port, conn.laddr.ip, 'UDP')
                    if port_key not in port_set:
                        port_set.add(port_key)
                        port_info = {
                            'port': conn.laddr.port,
                            'address': conn.laddr.ip,
                            'family': 'IPv4' if conn.family == socket.AF_INET else 'IPv6',
                            'type': 'UDP',
                            'status': 'ACTIVE',
                            'pid': conn.pid,
                            'process_name': None,
                            'process_cmdline': None
                        }
                
                # 获取进程信息
                if port_info and conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        port_info['process_name'] = proc.name()
                        cmdline = ' '.join(proc.cmdline()[:3])  # 只取前3个参数
                        if len(cmdline) > 80:
                            cmdline = cmdline[:80] + '...'
                        port_info['process_cmdline'] = cmdline
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        port_info['process_name'] = 'Unknown'
                        port_info['process_cmdline'] = 'Access Denied'
                
                if port_info:
                    ports.append(port_info)
                    
            except Exception:
                continue
        
        # 按端口号排序
        ports.sort(key=lambda x: x['port'])
        
        return jsonify({
            'status': 'success',
            'ports': ports
        })
        
    except Exception as e:
        logger.error(f"获取端口信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/kill_process', methods=['POST'])
@auth_required
def kill_process():
    """结束指定的进程"""
    try:
        data = request.get_json()
        if not data or 'pid' not in data:
            return jsonify({
                'status': 'error',
                'message': '缺少进程ID参数'
            }), 400
        
        pid = data['pid']
        force = data.get('force', False)
        
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            
            # 安全检查：不允许杀死重要的系统进程
            critical_processes = ['systemd', 'kernel', 'init', 'kthreadd', 'ssh', 'sshd']
            if proc_name.lower() in critical_processes:
                return jsonify({
                    'status': 'error',
                    'message': f'不允许结束关键系统进程: {proc_name}'
                }), 403
            
            if force:
                proc.kill()  # SIGKILL
                action = '强制结束'
            else:
                proc.terminate()  # SIGTERM
                action = '正常结束'
            
            logger.info(f"{action}进程: PID={pid}, Name={proc_name}")
            
            return jsonify({
                'status': 'success',
                'message': f'已{action}进程 {proc_name} (PID: {pid})'
            })
            
        except psutil.NoSuchProcess:
            return jsonify({
                'status': 'error',
                'message': '进程不存在或已结束'
            }), 404
        except psutil.AccessDenied:
            return jsonify({
                'status': 'error',
                'message': '权限不足，无法结束该进程'
            }), 403
            
    except Exception as e:
        logger.error(f"结束进程失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# 添加公网IP缓存相关变量
cached_public_ip = None
public_ip_timestamp = 0
public_ip_lock = threading.Lock()

@app.route('/api/settings/sponsor-key', methods=['POST'])
def save_sponsor_key():
    """保存赞助者凭证到配置文件"""
    try:
        data = request.json
        sponsor_key = data.get('sponsorKey')
        
        if not sponsor_key:
            return jsonify({'status': 'error', 'message': '赞助者凭证不能为空'}), 400
            
        # 使用赞助者验证模块保存密钥
        validator = get_sponsor_validator()
        if validator.save_sponsor_key(sponsor_key):
            return jsonify({'status': 'success', 'message': '赞助者凭证已保存'})
        else:
            return jsonify({'status': 'error', 'message': '保存赞助者凭证失败'}), 500
        
    except Exception as e:
        logger.error(f"保存赞助者凭证时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存赞助者凭证失败: {str(e)}'}), 500

@app.route('/api/settings/sponsor-key', methods=['GET'])
def get_sponsor_key():
    """获取当前赞助者凭证"""
    try:
        # 使用赞助者验证模块获取密钥信息
        validator = get_sponsor_validator()
        
        if validator.has_sponsor_key():
            masked_key = validator.get_masked_sponsor_key()
            return jsonify({
                'status': 'success', 
                'has_sponsor_key': True,
                'masked_sponsor_key': masked_key
            })
        else:
            return jsonify({'status': 'success', 'has_sponsor_key': False})
            
    except Exception as e:
        logger.error(f"获取赞助者凭证时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'获取赞助者凭证失败: {str(e)}'}), 500

@app.route('/api/settings/sponsor-key', methods=['DELETE'])
def delete_sponsor_key():
    """删除赞助者凭证"""
    try:
        # 使用赞助者验证模块删除密钥
        validator = get_sponsor_validator()
        
        if validator.remove_sponsor_key():
            return jsonify({'status': 'success', 'message': '赞助者凭证已删除'})
        else:
            return jsonify({'status': 'error', 'message': '删除赞助者凭证失败'}), 500
            
    except Exception as e:
        logger.error(f"删除赞助者凭证时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'删除赞助者凭证失败: {str(e)}'}), 500

@app.route('/api/sponsor', methods=['GET'])
def get_gold_sponsors():
    """获取金牌赞助商信息（代理请求解决CORS问题）"""
    try:
        # 代理请求到外部API
        response = requests.get('http://82.156.35.55:5001/sponsor', timeout=10)
        
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            logger.error(f"获取金牌赞助商数据失败，状态码: {response.status_code}")
            return jsonify({'status': 'error', 'message': '获取金牌赞助商数据失败'}), response.status_code
            
    except requests.exceptions.Timeout:
        logger.error("获取金牌赞助商数据超时")
        return jsonify({'status': 'error', 'message': '请求超时，请稍后重试'}), 408
    except requests.exceptions.ConnectionError:
        logger.error("无法连接到金牌赞助商服务器")
        return jsonify({'status': 'error', 'message': '无法连接到服务器'}), 503
    except Exception as e:
        logger.error(f"获取金牌赞助商数据时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'获取数据失败: {str(e)}'}), 500

@app.route('/api/sponsor/validate', methods=['GET'])
@auth_required
def validate_sponsor():
    """验证赞助者身份"""
    try:
        # 使用赞助者验证模块验证身份
        validator = get_sponsor_validator()
        
        # 检查是否有赞助者密钥
        if not validator.has_sponsor_key():
            return jsonify({
                'status': 'success',
                'valid': False,
                'message': '未配置赞助者密钥'
            })
        
        # 验证赞助者密钥
        is_valid = validator.validate_sponsor_key()
        
        if is_valid:
            return jsonify({
                'status': 'success',
                'valid': True,
                'message': '赞助者身份验证成功'
            })
        else:
            return jsonify({
                'status': 'success',
                'valid': False,
                'message': '赞助者身份验证失败'
            })
            
    except Exception as e:
        logger.error(f"验证赞助者身份时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'valid': False,
            'message': f'验证失败: {str(e)}'
        }), 500

@app.route('/api/online-games', methods=['GET'])
@auth_required
def get_online_games():
    """获取在线游戏列表"""
    try:
        validator = get_sponsor_validator()
        
        # 验证赞助者身份
        if not validator.has_sponsor_key() or not validator.validate_sponsor_key():
            return jsonify({
                'status': 'error',
                'message': '需要赞助者权限'
            }), 403
        
        # 获取赞助者密钥
        sponsor_key = validator.get_sponsor_key()
        if not sponsor_key:
            return jsonify({
                'status': 'error',
                'message': '未找到赞助者密钥'
            }), 403
        
        # 请求在线游戏列表
        import requests
        headers = {'key': sponsor_key}
        response = requests.get('http://82.156.35.55:5001/OnlineInstall', headers=headers, timeout=10)
        
        if response.status_code == 200:
            games_data = response.json()
            return jsonify({
                'status': 'success',
                'games': games_data
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'message': f'获取在线游戏列表失败: HTTP {response.status_code}'
            }), 500
            
    except requests.exceptions.RequestException as e:
        logger.error(f"请求在线游戏列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'网络请求失败: {str(e)}'
        }), 500
    except Exception as e:
        logger.error(f"获取在线游戏列表时发生错误: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取游戏列表时发生错误: {str(e)}'
        }), 500

# 在线部署相关的全局变量 (使用multiprocessing.Manager)
manager = multiprocessing.Manager()
active_online_deployments = manager.dict()  # game_id -> deployment_data (manager.dict)
online_deploy_queues = manager.dict()  # game_id -> queue (manager.Queue)

@app.route('/api/online-deploy', methods=['POST'])
@auth_required
def deploy_online_game():
    """启动在线游戏部署"""
    try:
        validator = get_sponsor_validator()
        
        # 验证赞助者身份
        if not validator.has_sponsor_key() or not validator.validate_sponsor_key():
            return jsonify({
                'status': 'error',
                'message': '需要赞助者权限'
            }), 403
        
        data = request.get_json()
        game_id = data.get('gameId')
        game_name = data.get('gameName')
        download_url = data.get('downloadUrl')
        script_content = data.get('script')
        
        if not all([game_id, game_name, download_url, script_content]):
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数'
            }), 400
        
        # 检查是否已有部署在进行
        if game_id in active_online_deployments:
            return jsonify({
                'status': 'error',
                'message': f'游戏 {game_name} 正在部署中，请等待完成'
            }), 409
        
        # 初始化部署状态 (使用Manager)
        deployment_data = manager.dict()
        deployment_data['game_name'] = game_name
        deployment_data['download_url'] = download_url
        deployment_data['script_content'] = script_content
        deployment_data['status'] = 'starting'
        deployment_data['progress'] = 0
        deployment_data['message'] = '正在准备部署...'
        deployment_data['complete'] = False
        deployment_data['start_time'] = time.time()
        active_online_deployments[game_id] = deployment_data
        
        deploy_queue = manager.Queue()
        online_deploy_queues[game_id] = deploy_queue
        
        # 启动部署进程
        deploy_process = multiprocessing.Process(
            target=_deploy_online_game_worker,
            args=(game_id, game_name, download_url, script_content, deployment_data, deploy_queue),
            daemon=True
        )
        deploy_process.start()
        
        return jsonify({
            'status': 'success',
            'message': f'开始部署游戏 {game_name}',
            'game_id': game_id
        }), 200
        
    except Exception as e:
        logger.error(f"启动在线游戏部署时发生错误: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'启动部署时发生错误: {str(e)}'
        }), 500

def _deploy_online_game_worker(game_id, game_name, download_url, script_content, deployment_data, deploy_queue):
    """在线游戏部署工作线程 - 调用aria2下载器模块"""
    from aria2_downloader import deploy_online_game_worker
    
    # 直接调用aria2下载器模块中的函数
    deploy_online_game_worker(game_id, game_name, download_url, script_content, deployment_data, deploy_queue)

@app.route('/api/online-deploy/stream', methods=['GET'])
@auth_required
def online_deploy_stream():
    """获取在线部署的实时进度"""
    try:
        game_id = request.args.get('game_id')
        
        if not game_id:
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
        
        validator = get_sponsor_validator()
        
        # 验证赞助者身份
        if not validator.has_sponsor_key() or not validator.validate_sponsor_key():
            return jsonify({
                'status': 'error',
                'message': '需要赞助者权限'
            }), 403
        
        # 检查部署是否存在
        if game_id not in active_online_deployments:
            return jsonify({
                'status': 'error',
                'message': f'游戏 {game_id} 没有活跃的部署任务'
            }), 404
        
        # 确保有队列
        if game_id not in online_deploy_queues:
            online_deploy_queues[game_id] = manager.Queue()
            
            # 如果部署已完成，添加完成消息
            deployment_data = active_online_deployments[game_id]
            if deployment_data.get('complete', False):
                online_deploy_queues[game_id].put({
                    'progress': deployment_data.get('progress', 100),
                    'status': deployment_data.get('status', 'completed'),
                    'message': deployment_data.get('message', '部署已完成'),
                    'complete': True,
                    'game_dir': deployment_data.get('game_dir')
                })
        
        def generate():
            deployment_data = active_online_deployments[game_id]
            deploy_queue = online_deploy_queues[game_id]
            
            # 发送连接成功消息
            yield f"data: {json.dumps({'message': '连接成功，开始接收部署进度...', 'progress': deployment_data.get('progress', 0), 'status': deployment_data.get('status', 'starting')})}\n\n"
            
            # 超时设置
            timeout_seconds = 600  # 10分钟超时
            last_output_time = time.time()
            heartbeat_interval = 10  # 每10秒发送一次心跳
            next_heartbeat = time.time() + heartbeat_interval
            
            while True:
                try:
                    # 尝试获取队列中的数据
                    try:
                        item = deploy_queue.get(timeout=1)
                        last_output_time = time.time()
                        
                        # 发送进度更新
                        yield f"data: {json.dumps(item)}\n\n"
                        
                        # 如果部署完成，结束流
                        if item.get('complete', False):
                            break
                            
                    except queue.Empty:
                        # 心跳检查
                        current_time = time.time()
                        if current_time >= next_heartbeat:
                            yield f"data: {json.dumps({'heartbeat': True, 'timestamp': current_time})}\n\n"
                            next_heartbeat = current_time + heartbeat_interval
                        
                        # 检查是否超时
                        if time.time() - last_output_time > timeout_seconds:
                            logger.warning(f"游戏 {game_id} 的部署流超时")
                            yield f"data: {json.dumps({'message': '部署流超时，请刷新页面查看最新状态', 'status': 'timeout', 'complete': True})}\n\n"
                            break
                        
                        # 检查部署是否已完成但未发送完成消息
                        if deployment_data.get('complete', False):
                            final_data = {
                                'progress': deployment_data.get('progress', 100),
                                'status': deployment_data.get('status', 'completed'),
                                'message': deployment_data.get('message', '部署已完成'),
                                'complete': True
                            }
                            if deployment_data.get('game_dir'):
                                final_data['game_dir'] = deployment_data['game_dir']
                            yield f"data: {json.dumps(final_data)}\n\n"
                            break
                        
                        continue
                        
                except Exception as e:
                    logger.error(f"生成部署流数据时出错: {str(e)}")
                    yield f"data: {json.dumps({'error': str(e), 'complete': True})}\n\n"
                    break
        
        return Response(stream_with_context(generate()),
                       mimetype='text/event-stream',
                       headers={
                           'Cache-Control': 'no-cache',
                           'X-Accel-Buffering': 'no'
                       })
                       
    except Exception as e:
        logger.error(f"在线部署流处理错误: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/settings/proxy', methods=['POST'])
@auth_required
def save_proxy_config():
    """保存代理配置"""
    try:
        data = request.json
        
        # 验证必要字段
        if data.get('enabled', False):
            if not data.get('host'):
                return jsonify({'status': 'error', 'message': '代理服务器地址不能为空'}), 400
            if not data.get('port'):
                return jsonify({'status': 'error', 'message': '端口号不能为空'}), 400
        
        # 加载现有配置
        from config import load_config, save_config
        config = load_config()
        
        # 更新代理配置
        config['proxy'] = {
            'enabled': data.get('enabled', False),
            'type': data.get('type', 'http'),
            'host': data.get('host', ''),
            'port': data.get('port', 8080),
            'username': data.get('username', ''),
            'password': data.get('password', ''),
            'no_proxy': data.get('no_proxy', '')
        }
        
        # 保存配置
        if save_config(config):
            # 应用代理配置到环境变量
            apply_proxy_config(config['proxy'])
            return jsonify({'status': 'success', 'message': '代理配置保存成功'})
        else:
            return jsonify({'status': 'error', 'message': '保存代理配置失败'}), 500
            
    except Exception as e:
        logger.error(f"保存代理配置时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'保存代理配置失败: {str(e)}'}), 500

@app.route('/api/settings/proxy', methods=['GET'])
@auth_required
def get_proxy_config():
    """获取代理配置"""
    try:
        from config import load_config
        config = load_config()
        
        # 获取代理配置，如果不存在则返回默认配置
        proxy_config = config.get('proxy', {
            'enabled': False,
            'type': 'http',
            'host': '',
            'port': 8080,
            'username': '',
            'password': '',
            'no_proxy': ''
        })
        
        return jsonify({
            'status': 'success',
            'config': proxy_config
        })
        
    except Exception as e:
        logger.error(f"获取代理配置时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f'获取代理配置失败: {str(e)}'}), 500

@app.route('/api/settings/test-network', methods=['POST'])
@auth_required
def test_network_connectivity():
    """测试网络连通性（谷歌连接测试）"""
    try:
        import time
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # 获取超时设置
        data = request.get_json() or {}
        timeout = data.get('timeout', 10)
        
        # 创建会话并配置重试策略
        session = requests.Session()
        retry_strategy = Retry(
            total=1,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 测试目标列表（按优先级排序）
        test_targets = [
            {'url': 'https://www.google.com', 'name': 'Google'},
            {'url': 'https://www.googleapis.com', 'name': 'Google APIs'},
            {'url': 'https://dns.google', 'name': 'Google DNS'},
        ]
        
        start_time = time.time()
        
        for target in test_targets:
            try:
                response = session.get(
                    target['url'],
                    timeout=timeout/1000,  # 转换为秒
                    allow_redirects=True,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                
                end_time = time.time()
                latency_ms = int((end_time - start_time) * 1000)
                
                if response.status_code == 200:
                    return jsonify({
                        'status': 'success',
                        'message': f'成功连接到 {target["name"]}',
                        'latency': latency_ms,
                        'target': target['name'],
                        'url': target['url']
                    })
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"连接 {target['name']} 失败: {str(e)}")
                continue
        
        # 所有目标都失败
        return jsonify({
            'status': 'error',
            'message': '无法连接到任何谷歌服务，请检查网络连接或代理设置',
            'latency': None
        }), 400
        
    except Exception as e:
        logger.error(f"网络连通性测试时出错: {str(e)}")
        return jsonify({
            'status': 'error', 
            'message': f'网络测试失败: {str(e)}',
            'latency': None
        }), 500

@app.route('/api/version/check', methods=['GET'])
@auth_required
def check_version_update():
    """检查版本更新"""
    try:
        # 使用赞助者验证模块检查版本更新
        validator = get_sponsor_validator()
        
        # 检查是否有赞助者密钥
        if not validator.has_sponsor_key():
            return jsonify({
                'status': 'skip', 
                'message': '未配置赞助者密钥，跳过版本检查'
            }), 200
        
        # 获取版本信息
        version_info = validator.check_version_update()
        
        if version_info:
            return jsonify({
                'status': 'success',
                'version': version_info.get('version'),
                'description': version_info.get('description', {})
            })
        else:
            return jsonify({
                'status': 'error',
                'message': '获取版本信息失败，请检查网络连接或赞助者凭证'
            }), 500
            
    except Exception as e:
        logger.error(f"检查版本更新时出错: {str(e)}")
        return jsonify({
                'status': 'error', 
                'message': f'检查版本更新失败: {str(e)}'
            }), 500

@app.route('/api/version/download-image', methods=['POST'])
@auth_required
def download_docker_image():
    """下载并导入Docker镜像"""
    try:
        # 验证赞助者身份
        validator = get_sponsor_validator()
        if not validator.has_sponsor_key() or not validator.validate_sponsor_key():
            return jsonify({
                'status': 'error',
                'message': '此功能仅限赞助者使用，请先配置有效的赞助者凭证'
            }), 403
        
        # 下载和导入Docker镜像
        download_url = "http://langlangy.server.xiaozhuhouses.asia:8082/disk1/Docker/GSM%e9%9d%a2%e6%9d%bf/gameservermanager.tar.xz"
        result = docker_manager.download_and_import_image(download_url, "gameservermanager:latest")
        
        if result['status'] != 'success':
            logger.error(f"下载或导入镜像失败: {result['message']}")
            return jsonify({
                'status': 'error',
                'message': f'下载或导入镜像失败: {result["message"]}'
            }), 500
        
        logger.info("镜像下载和导入成功，开始获取容器配置")
        
        # 获取当前容器配置
        container_info = docker_manager.get_container_info('GSManager')
        
        if container_info:
             logger.info(f"获取到容器信息:")
             logger.info(f"  - 容器名称: {container_info.get('name')}")
             logger.info(f"  - 镜像: {container_info.get('image')}")
             logger.info(f"  - 网络模式: {container_info.get('network_mode')}")
             logger.info(f"  - 端口映射: {container_info.get('ports')}")
             logger.info(f"  - 挂载点: {container_info.get('mounts')}")
             logger.info(f"  - 环境变量数量: {len(container_info.get('environment', []))}")
             logger.info(f"  - 重启策略: {container_info.get('restart_policy')}")
             
             # 更新镜像名称为最新版本
             container_info['image'] = 'gameservermanager:latest'
             
             # 生成完整的启动命令
             docker_command = docker_manager.generate_docker_command(container_info)
             
             if docker_command:
                 logger.info(f"生成的Docker命令: {docker_command}")
                 return jsonify({
                     'status': 'success',
                     'message': '已生成基于当前容器配置的启动命令',
                     'docker_command': docker_command,
                     'container_config': container_info
                 })
             else:
                 logger.error("生成Docker命令失败")
                 return jsonify({
                     'status': 'error',
                     'message': '生成Docker命令失败'
                 }), 500
        else:
            logger.warning("未找到GSManager容器，尝试查找其他可能的容器名称")
            
            # 尝试查找可能的容器名称变体
            possible_names = ['GSManager', 'gameservermanager', 'gsm', 'game-server-manager', 'GameServerManager']
            found_container = None
            
            for name in possible_names:
                container_info = docker_manager.get_container_info(name)
                if container_info:
                    found_container = container_info
                    logger.info(f"找到容器: {name}")
                    break
            
            if found_container:
                # 更新容器名称和镜像
                found_container['name'] = 'GSManager'
                found_container['image'] = 'gameservermanager:latest'
                
                docker_command = docker_manager.generate_docker_command(found_container)
                
                return jsonify({
                    'status': 'success',
                    'message': '已基于现有容器配置生成启动命令',
                    'docker_command': docker_command,
                    'container_config': found_container
                })
            else:
                logger.error("未找到任何相关容器，无法生成完整的启动命令")
                return jsonify({
                    'status': 'error',
                    'message': '未找到GSManager容器，无法生成完整的启动命令。请确保容器正在运行。'
                }), 404
            
    except Exception as e:
        logger.error(f"下载Docker镜像时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'下载Docker镜像失败: {str(e)}'
        }), 500

@app.route('/api/server/list_scripts', methods=['GET'])
def list_server_scripts():
    """获取服务器目录下所有可执行的sh脚本"""
    try:
        game_id = request.args.get('game_id')
        
        if not game_id:
            logger.error("缺少游戏ID")
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        logger.info(f"请求获取游戏 {game_id} 的可执行脚本列表")
        
        # 检查游戏是否已安装
        game_dir = os.path.join(GAMES_DIR, game_id)
        if not os.path.exists(game_dir) or not os.path.isdir(game_dir):
            logger.error(f"游戏 {game_id} 未安装")
            return jsonify({'status': 'error', 'message': f'游戏 {game_id} 未安装'}), 400
        
        # 查找所有.sh文件
        scripts = []
        for file in os.listdir(game_dir):
            file_path = os.path.join(game_dir, file)
            if file.endswith('.sh') and os.path.isfile(file_path) and os.access(file_path, os.X_OK):
                # 检查文件是否有执行权限
                scripts.append({
                    'name': file,
                    'path': file_path,
                    'size': os.path.getsize(file_path),
                    'mtime': os.path.getmtime(file_path)
                })
        
        logger.info(f"找到 {len(scripts)} 个可执行脚本: {[script['name'] for script in scripts]}")
        
        return jsonify({
            'status': 'success',
            'scripts': scripts
        })
        
    except Exception as e:
        logger.error(f"获取可执行脚本列表失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 定期清理临时错误信息
def clean_temp_errors():
    """定期清理超过5分钟的临时错误信息"""
    while True:
        try:
            if hasattr(app, 'temp_server_errors'):
                now = time.time()
                expired_keys = []
                for game_id, error_info in app.temp_server_errors.items():
                    if now - error_info.get('timestamp', 0) > 300:  # 5分钟
                        expired_keys.append(game_id)
                
                for game_id in expired_keys:
                    del app.temp_server_errors[game_id]
                    logger.debug(f"已清理游戏 {game_id} 的临时错误信息")
        except Exception as e:
            logger.error(f"清理临时错误信息时出错: {str(e)}")
        
        # 每分钟检查一次
        time.sleep(60)

# 启动清理线程
error_cleaner_thread = threading.Thread(target=clean_temp_errors, daemon=True)
error_cleaner_thread.start()
logger.info("临时错误信息清理线程已启动")

# 添加自启动相关的常量和函数
CONFIG_FILE = "/home/steam/games/config.json"

# 自启动功能初始化标志
_auto_start_initialized = False

def log_running_games():
    """使用logger打印当前正在运行的游戏服务器信息"""
    try:
        if not running_servers:
            logger.info("当前没有正在运行的游戏服务器")
            return
        
        logger.info("=== 当前正在运行的游戏服务器 ===")
        running_count = 0
        
        for game_id, server_data in running_servers.items():
            process = server_data.get('process')
            pty_process = server_data.get('pty_process')
            started_at = server_data.get('started_at')
            
            # 检查进程是否真的在运行
            is_running = False
            pid = None
            
            if process and hasattr(process, 'poll') and process.poll() is None:
                is_running = True
                pid = process.pid
            elif pty_process and hasattr(pty_process, 'process') and pty_process.process:
                if hasattr(pty_process.process, 'poll') and pty_process.process.poll() is None:
                    is_running = True
                    pid = pty_process.process.pid
            
            if is_running:
                running_count += 1
                uptime = time.time() - started_at if started_at else 0
                uptime_str = f"{int(uptime // 3600)}小时{int((uptime % 3600) // 60)}分钟" if uptime > 0 else "未知"
                
                logger.info(f"  游戏ID: {game_id}")
                logger.info(f"    进程PID: {pid}")
                logger.info(f"    运行时长: {uptime_str}")
                logger.info(f"    启动时间: {datetime.datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S') if started_at else '未知'}")
                logger.info(f"    是否有PTY: {'是' if pty_process else '否'}")
            else:
                logger.warning(f"  游戏ID: {game_id} - 进程已停止但仍在running_servers中")
        
        logger.info(f"=== 总计: {running_count} 个游戏服务器正在运行 ===")
        
    except Exception as e:
        logger.error(f"打印运行中游戏服务器信息时出错: {str(e)}")

def auto_start_servers():
    """在应用启动时自动启动配置的服务器"""
    global _auto_start_initialized
    
    if _auto_start_initialized:
        return
        
    _auto_start_initialized = True
    
    try:
        logger.info("开始检查自启动服务器配置...")
        
        # 加载配置
        config = load_config()
        auto_restart_servers = config.get('auto_restart_servers', [])
        auto_restart_frps = config.get('auto_restart_frps', [])
        
        if not auto_restart_servers and not auto_restart_frps:
            logger.info("没有配置自启动的服务器或内网穿透")
            return
            
        # 延迟启动，确保应用完全初始化
        def delayed_auto_start():
            time.sleep(5)  # 等待5秒确保应用完全启动
            
            # 自动启动服务器
            if auto_restart_servers:
                logger.info(f"发现 {len(auto_restart_servers)} 个自启动服务器: {auto_restart_servers}")
                
                for game_id in auto_restart_servers:
                    try:
                        # 检查游戏目录是否存在
                        game_dir = os.path.join(GAMES_DIR, game_id)
                        if not os.path.exists(game_dir):
                            logger.warning(f"游戏目录不存在，跳过自启动: {game_dir}")
                            continue
                            
                        # 检查是否已经在运行
                        if game_id in running_servers and running_servers[game_id].get('running', False):
                            logger.info(f"游戏服务器 {game_id} 已在运行，跳过自启动")
                            continue
                            
                        logger.info(f"自动启动游戏服务器: {game_id}")
                        
                        # 查找启动脚本
                        script_name = "start.sh"
                        script_path = os.path.join(game_dir, script_name)
                        
                        # 尝试从.last_script文件读取上次使用的脚本
                        last_script_path = os.path.join(game_dir, '.last_script')
                        if os.path.exists(last_script_path):
                            try:
                                with open(last_script_path, 'r') as f:
                                    saved_script = f.read().strip()
                                    if saved_script and os.path.exists(os.path.join(game_dir, saved_script)):
                                        script_name = saved_script
                                        script_path = os.path.join(game_dir, script_name)
                                        logger.info(f"使用上次保存的启动脚本: {script_name}")
                            except Exception as e:
                                logger.warning(f"读取.last_script文件失败: {str(e)}")
                        
                        if not os.path.exists(script_path):
                            logger.warning(f"启动脚本不存在，跳过自启动: {script_path}")
                            continue
                            
                        # 确保脚本有执行权限
                        if not os.access(script_path, os.X_OK):
                            logger.info(f"添加脚本执行权限: {script_path}")
                            os.chmod(script_path, 0o755)
                        
                        # 构建启动命令
                        cmd = f"su - steam -c 'cd {game_dir} && ./{script_name}'"
                        
                        # 初始化服务器状态跟踪
                        running_servers[game_id] = {
                            'process': None,
                            'output': [],
                            'started_at': time.time(),
                            'running': True,
                            'return_code': None,
                            'cmd': cmd,
                            'master_fd': None,
                            'game_dir': game_dir,
                            'external': False,
                            'script_name': script_name,
                            'auto_started': True  # 标记为自动启动
                        }
                        
                        # 创建输出队列
                        if game_id not in server_output_queues:
                            server_output_queues[game_id] = queue.Queue()
                        
                        # 在单独的线程中启动服务器
                        server_thread = threading.Thread(
                            target=run_game_server,
                            args=(game_id, cmd, game_dir),
                            daemon=True
                        )
                        server_thread.start()
                        
                        logger.info(f"游戏服务器 {game_id} 自启动线程已启动")
                        
                        # 间隔启动，避免同时启动太多服务器
                        time.sleep(2)
                        
                    except Exception as e:
                        logger.error(f"自动启动游戏服务器 {game_id} 失败: {str(e)}")
            
            # 自动启动内网穿透
            if auto_restart_frps:
                logger.info(f"发现 {len(auto_restart_frps)} 个自启动内网穿透: {auto_restart_frps}")
                
                for frp_id in auto_restart_frps:
                    try:
                        # 检查是否已经在运行
                        if frp_id in running_frp_processes:
                            logger.info(f"内网穿透 {frp_id} 已在运行，跳过自启动")
                            continue
                            
                        logger.info(f"自动启动内网穿透: {frp_id}")
                        
                        # 加载FRP配置
                        configs = load_frp_configs()
                        target_config = None
                        
                        for config in configs:
                            if config['id'] == frp_id:
                                target_config = config
                                break
                        
                        if not target_config:
                            logger.warning(f"未找到内网穿透 {frp_id} 的配置，跳过自启动")
                            continue
                        
                        # 启动内网穿透
                        # 根据FRP类型选择不同的二进制文件和目录
                        frp_binary = FRP_BINARY
                        frp_dir = os.path.join(FRP_DIR, "LoCyanFrp")
                        
                        if target_config['type'] == 'custom':
                            frp_binary = CUSTOM_FRP_BINARY
                            frp_dir = CUSTOM_FRP_DIR
                        elif target_config['type'] == 'mefrp':
                            frp_binary = MEFRP_BINARY
                            frp_dir = MEFRP_DIR
                        elif target_config['type'] == 'sakura':
                            frp_binary = SAKURA_BINARY
                            frp_dir = SAKURA_DIR
                        
                        # 确保FRP可执行
                        if not os.path.exists(frp_binary):
                            logger.warning(f"{target_config['type']}客户端程序不存在，跳过自启动: {frp_binary}")
                            continue
                        
                        # 设置可执行权限
                        os.chmod(frp_binary, 0o755)
                        
                        # 创建日志文件
                        log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
                        log_file = open(log_file_path, 'w')
                        
                        # 构建命令
                        command = f"{frp_binary} {target_config['command']}"
                        
                        # 启动FRP进程
                        process = subprocess.Popen(
                            shlex.split(command),
                            stdout=log_file,
                            stderr=log_file,
                            cwd=frp_dir
                        )
                        
                        # 保存进程信息
                        running_frp_processes[frp_id] = {
                            'process': process,
                            'log_file': log_file_path,
                            'started_at': time.time(),
                            'auto_started': True  # 标记为自动启动
                        }
                        
                        # 更新配置状态
                        configs = load_frp_configs()
                        for config in configs:
                            if config['id'] == frp_id:
                                config['status'] = 'running'
                                break
                        save_frp_configs(configs)
                        
                        logger.info(f"内网穿透 {frp_id} 自启动成功")
                        
                        # 间隔启动
                        time.sleep(1)
                        
                    except Exception as e:
                        logger.error(f"自动启动内网穿透 {frp_id} 失败: {str(e)}")
                        
            logger.info("自启动功能执行完成")
        
        # 在后台线程中执行延迟启动
        auto_start_thread = threading.Thread(target=delayed_auto_start, daemon=True)
        auto_start_thread.start()
        
        logger.info("自启动功能已初始化，将在5秒后开始执行")
        
    except Exception as e:
        logger.error(f"初始化自启动功能失败: {str(e)}")

def load_config():
    """加载配置文件"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"加载配置文件失败: {str(e)}")
        return {}

def save_config(config):
    """保存配置文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"保存配置文件失败: {str(e)}")
        return False

@app.route('/api/server/auto_restart', methods=['GET'])
def get_auto_restart_servers():
    """获取自启动服务器列表"""
    try:
        config = load_config()
        auto_restart_servers = config.get('auto_restart_servers', [])
        
        return jsonify({
            'status': 'success',
            'auto_restart_servers': auto_restart_servers
        })
    except Exception as e:
        logger.error(f"获取自启动服务器列表失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/server/set_auto_restart', methods=['POST'])
def set_auto_restart():
    """设置服务器自启动状态"""
    try:
        data = request.json
        game_id = data.get('game_id')
        auto_restart = data.get('auto_restart', False)
        
        if not game_id:
            return jsonify({'status': 'error', 'message': '缺少游戏ID'}), 400
            
        # 加载配置
        config = load_config()
        auto_restart_servers = config.get('auto_restart_servers', [])
        
        if auto_restart:
            # 添加到自启动列表
            if game_id not in auto_restart_servers:
                auto_restart_servers.append(game_id)
                logger.info(f"添加游戏服务器 {game_id} 到自启动列表")
        else:
            # 从自启动列表移除
            if game_id in auto_restart_servers:
                auto_restart_servers.remove(game_id)
                logger.info(f"从自启动列表移除游戏服务器 {game_id}")
        
        # 更新配置
        config['auto_restart_servers'] = auto_restart_servers
        save_config(config)
        
        return jsonify({
            'status': 'success',
            'message': f"已{'开启' if auto_restart else '关闭'}服务端自启动",
            'auto_restart_servers': auto_restart_servers
        })
    except Exception as e:
        logger.error(f"设置自启动状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加重启服务器的函数
def restart_server(game_id, cwd):
    """重启游戏服务器"""
    try:
        logger.info(f"准备重启游戏服务器 {game_id}")
        
        # 确保服务器不在人工停止列表中
        if game_id in manually_stopped_servers:
            manually_stopped_servers.discard(game_id)
            logger.info(f"从人工停止列表中移除游戏服务器 {game_id}")
        
        # 等待一小段时间再重启
        time.sleep(3)
        
        # 获取上次使用的脚本名称
        script_name = "start.sh"  # 默认脚本名
        
        # 首先检查运行中的服务器记录
        if game_id in running_servers and 'script_name' in running_servers[game_id]:
            script_name = running_servers[game_id]['script_name']
            logger.info(f"从运行记录中获取脚本名: {script_name}")
        else:
            # 尝试从.last_script文件读取
            last_script_path = os.path.join(cwd, '.last_script')
            if os.path.exists(last_script_path):
                try:
                    with open(last_script_path, 'r') as f:
                        saved_script = f.read().strip()
                        if saved_script and os.path.exists(os.path.join(cwd, saved_script)):
                            script_name = saved_script
                            logger.info(f"从.last_script文件读取脚本名: {script_name}")
                except Exception as e:
                    logger.warning(f"读取.last_script文件失败: {str(e)}")
        
        # 检查脚本是否存在
        script_path = os.path.join(cwd, script_name)
        if not os.path.exists(script_path):
            logger.warning(f"脚本 {script_name} 不存在，尝试使用默认的start.sh")
            script_name = "start.sh"
            script_path = os.path.join(cwd, script_name)
            if not os.path.exists(script_path):
                logger.error(f"默认脚本 start.sh 也不存在，无法重启服务器")
                return False
        
        # 确保脚本有执行权限
        if not os.access(script_path, os.X_OK):
            logger.info(f"添加脚本执行权限: {script_path}")
            os.chmod(script_path, 0o755)
        
        # 构建启动命令
        cmd = f"su - steam -c 'cd {cwd} && ./{script_name}'"
        
        # 初始化服务器状态跟踪
        running_servers[game_id] = {
            'process': None,
            'output': [],
            'started_at': time.time(),
            'running': True,
            'return_code': None,
            'cmd': cmd,
            'master_fd': None,
            'game_dir': cwd,
            'external': running_servers[game_id].get('external', False) if game_id in running_servers else False,
            'script_name': script_name
        }
        
        # 在单独的线程中启动服务器
        server_thread = threading.Thread(
            target=run_game_server,
            args=(game_id, cmd, cwd),
            daemon=True
        )
        server_thread.start()
        
        logger.info(f"游戏服务器 {game_id} 重启线程已启动，使用脚本: {script_name}")
        
        # 添加到输出队列
        if game_id in server_output_queues:
            server_output_queues[game_id].put("服务器自动重启中...")
            server_output_queues[game_id].put(f"游戏目录: {cwd}")
            server_output_queues[game_id].put(f"启动脚本: {script_name}")
            server_output_queues[game_id].put(f"启动命令: {cmd}")
            
        # 记录日志
        logger.info(f"游戏服务器 {game_id} 重启流程已完成")
        return True
    except Exception as e:
        logger.error(f"重启游戏服务器 {game_id} 失败: {str(e)}")
        return False

# 获取FRP自启动列表
@app.route('/api/frp/auto_restart', methods=['GET'])
def get_auto_restart_frps():
    """获取自启动内网穿透列表"""
    try:
        config = load_config()
        auto_restart_frps = config.get('auto_restart_frps', [])
        
        return jsonify({
            'status': 'success',
            'auto_restart_frps': auto_restart_frps
        })
    except Exception as e:
        logger.error(f"获取自启动内网穿透列表失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 设置FRP自启动状态
@app.route('/api/frp/set_auto_restart', methods=['POST'])
def set_frp_auto_restart():
    """设置内网穿透自启动状态"""
    try:
        data = request.json
        frp_id = data.get('frp_id')
        auto_restart = data.get('auto_restart', False)
        
        if not frp_id:
            return jsonify({'status': 'error', 'message': '缺少FRP ID'}), 400
            
        # 加载配置
        config = load_config()
        auto_restart_frps = config.get('auto_restart_frps', [])
        
        if auto_restart:
            # 添加到自启动列表
            if frp_id not in auto_restart_frps:
                auto_restart_frps.append(frp_id)
                logger.info(f"添加内网穿透 {frp_id} 到自启动列表")
        else:
            # 从自启动列表移除
            if frp_id in auto_restart_frps:
                auto_restart_frps.remove(frp_id)
                logger.info(f"从自启动列表移除内网穿透 {frp_id}")
        
        # 更新配置
        config['auto_restart_frps'] = auto_restart_frps
        save_config(config)
        
        return jsonify({
            'status': 'success',
            'message': f"已{'开启' if auto_restart else '关闭'}内网穿透自启动",
            'auto_restart_frps': auto_restart_frps
        })
    except Exception as e:
        logger.error(f"设置内网穿透自启动状态失败: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# 添加FRP自动重启函数
def restart_frp(frp_id):
    """重启内网穿透"""
    try:
        logger.info(f"准备重启内网穿透 {frp_id}")
        
        # 确保FRP不在人工停止列表中
        if frp_id in manually_stopped_frps:
            manually_stopped_frps.discard(frp_id)
            logger.info(f"从人工停止列表中移除内网穿透 {frp_id}")
        
        # 等待一小段时间再重启
        time.sleep(3)
        
        # 加载配置
        configs = load_frp_configs()
        target_config = None
        
        for config in configs:
            if config['id'] == frp_id:
                target_config = config
                break
        
        if not target_config:
            logger.error(f"未找到内网穿透 {frp_id} 的配置")
            return
        
        # 根据FRP类型选择不同的二进制文件和目录
        frp_binary = FRP_BINARY
        frp_dir = os.path.join(FRP_DIR, "LoCyanFrp")
        
        if target_config['type'] == 'custom':
            frp_binary = CUSTOM_FRP_BINARY
            frp_dir = CUSTOM_FRP_DIR
        elif target_config['type'] == 'mefrp':
            frp_binary = MEFRP_BINARY
            frp_dir = MEFRP_DIR
        elif target_config['type'] == 'sakura':
            frp_binary = SAKURA_BINARY
            frp_dir = SAKURA_DIR
        elif target_config['type'] == 'npc':
            frp_binary = NPC_BINARY
            frp_dir = NPC_DIR
        
        # 确保FRP可执行
        if not os.path.exists(frp_binary):
            logger.error(f"{target_config['type']}客户端程序不存在")
            return
        
        # 设置可执行权限
        os.chmod(frp_binary, 0o755)
        
        # 创建日志文件
        log_file_path = os.path.join(FRP_LOGS_DIR, f"{frp_id}.log")
        log_file = open(log_file_path, 'w')
        
        # 构建命令
        command = f"{frp_binary} {target_config['command']}"
        
        # 启动FRP进程
        process = subprocess.Popen(
            shlex.split(command),
            stdout=log_file,
            stderr=log_file,
            cwd=frp_dir
        )
        
        # 保存进程信息
        running_frp_processes[frp_id] = {
            'process': process,
            'log_file': log_file_path,
            'started_at': time.time()
        }
        
        # 更新配置状态
        for config in configs:
            if config['id'] == frp_id:
                config['status'] = 'running'
                break
        
        save_frp_configs(configs)
        
        logger.info(f"内网穿透 {frp_id} 重启成功")
        
    except Exception as e:
        logger.error(f"重启内网穿透 {frp_id} 失败: {str(e)}")

# 添加FRP进程监控线程
def monitor_frp_processes():
    """监控内网穿透进程，自动重启异常退出的进程"""
    while True:
        try:
            # 加载配置
            config = load_config()
            auto_restart_frps = config.get('auto_restart_frps', [])
            
            # 检查所有运行中的FRP进程
            for frp_id, process_info in list(running_frp_processes.items()):
                process = process_info['process']
                
                # 检查进程是否仍在运行
                if process.poll() is not None:  # 进程已退出
                    logger.info(f"检测到内网穿透 {frp_id} 已退出，返回码: {process.returncode}")
                    
                    # 如果不是人工停止且配置了自启动，则重启
                    if frp_id not in manually_stopped_frps and frp_id in auto_restart_frps:
                        logger.info(f"内网穿透 {frp_id} 异常退出（非人工停止），自动重启中...")
                        restart_frp(frp_id)
                    else:
                        # 如果是人工停止，从列表中移除
                        if frp_id in manually_stopped_frps:
                            manually_stopped_frps.discard(frp_id)
                            logger.info(f"内网穿透 {frp_id} 人工停止，不进行自动重启")
                        
                        # 从运行列表中移除
                        del running_frp_processes[frp_id]
                        
                        # 更新配置状态
                        configs = load_frp_configs()
                        for config in configs:
                            if config['id'] == frp_id:
                                config['status'] = 'stopped'
                                break
                        save_frp_configs(configs)
            
            # 每5秒检查一次
            time.sleep(5)
        except Exception as e:
            logger.error(f"监控内网穿透进程时出错: {str(e)}")
            time.sleep(10)  # 出错时等待更长时间

# 启动FRP监控线程
frp_monitor_thread = threading.Thread(target=monitor_frp_processes, daemon=True)
frp_monitor_thread.start()

# 环境安装相关配置
ENVIRONMENT_DIR = "/home/steam/environment"
JAVA_DIR = os.path.join(ENVIRONMENT_DIR, "java")
JAVA_JDK8_DIR = os.path.join(JAVA_DIR, "jdk8")
JAVA_JDK12_DIR = os.path.join(JAVA_DIR, "jdk12")
JAVA_JDK17_DIR = os.path.join(JAVA_DIR, "jdk17")
JAVA_JDK21_DIR = os.path.join(JAVA_DIR, "jdk21")
JAVA_JDK24_DIR = os.path.join(JAVA_DIR, "jdk24")

# JDK下载URL
JAVA_JDK8_URL = "https://download.java.net/openjdk/jdk8u44/ri/openjdk-8u44-linux-x64.tar.gz"
JAVA_JDK12_URL = "https://download.java.net/openjdk/jdk12/ri/openjdk-12+32_linux-x64_bin.tar.gz"
JAVA_JDK17_URL = "https://download.java.net/openjdk/jdk17.0.0.1/ri/openjdk-17.0.0.1+2_linux-x64_bin.tar.gz"
JAVA_JDK21_URL = "https://download.java.net/openjdk/jdk21/ri/openjdk-21+35_linux-x64_bin.tar.gz"
JAVA_JDK24_URL = "https://download.java.net/openjdk/jdk24/ri/openjdk-24+36_linux-x64_bin.tar.gz"

# JDK版本映射
JAVA_VERSIONS = {
    "jdk8": {
        "dir": JAVA_JDK8_DIR,
        "url": JAVA_JDK8_URL,
        "sponsor_url": "http://download.server.xiaozhuhouses.asia:8082/disk1/jdk/Linux/openjdk-8u44-linux-x64.tar.gz",
        "display_name": "JDK 8"
    },
    "jdk12": {
        "dir": JAVA_JDK12_DIR,
        "url": JAVA_JDK12_URL,
        "sponsor_url": "http://download.server.xiaozhuhouses.asia:8082/disk1/jdk/Linux/openjdk-12+32_linux-x64_bin.tar.gz",
        "display_name": "JDK 12"
    },
    "jdk17": {
        "dir": JAVA_JDK17_DIR,
        "url": JAVA_JDK17_URL,
        "sponsor_url": "http://download.server.xiaozhuhouses.asia:8082/disk1/jdk/Linux/openjdk-17.0.0.1+2_linux-x64_bin.tar.gz",
        "display_name": "JDK 17"
    },
    "jdk21": {
        "dir": JAVA_JDK21_DIR,
        "url": JAVA_JDK21_URL,
        "sponsor_url": "http://download.server.xiaozhuhouses.asia:8082/disk1/jdk/Linux/openjdk-21+35_linux-x64_bin.tar.gz",
        "display_name": "JDK 21"
    },
    "jdk24": {
        "dir": JAVA_JDK24_DIR,
        "url": JAVA_JDK24_URL,
        "sponsor_url": "http://download.server.xiaozhuhouses.asia:8082/disk1/jdk/Linux/openjdk-24+36_linux-x64_bin.tar.gz",
        "display_name": "JDK 24"
    }
}

# 确保环境目录存在
os.makedirs(ENVIRONMENT_DIR, exist_ok=True)
os.makedirs(JAVA_DIR, exist_ok=True)

# 环境安装进度跟踪 - 使用共享字典解决多进程状态同步问题
# 创建专门用于Java安装的multiprocessing.Manager
java_manager = multiprocessing.Manager()
java_install_progress = java_manager.dict()  # 专门用于Java安装进度的共享字典
environment_install_progress = {}  # 保留原有字典用于其他环境安装

# Java下载并发控制
java_download_lock = threading.Lock()
current_java_download = None
java_download_cancelled = {}  # 存储取消下载的标志 {version: True/False}

# 初始化赞助者验证器
sponsor_validator = SponsorValidator()

def verify_sponsor_for_java() -> tuple[bool, str]:
    """验证赞助者身份用于Java下载
    
    Returns:
        tuple: (是否为赞助者, 验证信息)
    """
    try:
        # 从配置文件中读取sponsor_key
        config_path = "/home/steam/games/config.json"
        sponsor_key = None
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    sponsor_key = config.get('sponsor_key')
            except Exception as e:
                logger.warning(f"读取配置文件失败: {str(e)}")
        
        if not sponsor_key:
            logger.info("未找到赞助者密钥，将使用普通下载链接")
            return False, "未找到赞助者密钥"
        
        # 验证赞助者密钥
        url = "http://82.156.35.55:5001/verify"
        headers = {
            'key': sponsor_key,
            'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
            'Accept': '*/*',
            'Host': '82.156.35.55:5001',
            'Connection': 'keep-alive'
        }
        
        logger.debug(f"开始验证赞助者身份")
        logger.debug(f"验证接口: {url}")
        logger.debug(f"使用密钥: {sponsor_key[:8]}...{sponsor_key[-4:] if len(sponsor_key) > 12 else sponsor_key}")
        
        response = requests.get(url, headers=headers, timeout=10)
        
        logger.debug(f"验证接口响应状态码: {response.status_code}")
        logger.debug(f"验证接口返回内容: {response.text.strip()}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                is_sponsor = result.get('is_sponsor', False)
                if is_sponsor:
                    logger.debug("赞助者验证成功，将使用专用下载链接")
                    return True, "赞助者验证成功"
                else:
                    logger.debug("非赞助者用户，将使用普通下载链接")
                    return False, "非赞助者用户"
            except json.JSONDecodeError:
                # 如果不是JSON格式，回退到原来的文本检查方式
                result = response.text.strip()
                if "success" in result.lower() or "valid" in result.lower():
                    return True, "赞助者验证成功"
                else:
                    return False, "非赞助者用户"
        else:
            logger.warning(f"⚠️ 赞助者验证失败，状态码: {response.status_code}，将使用普通下载链接")
            return False, f"验证服务器返回状态码: {response.status_code}"
            
    except Exception as e:
        logger.warning(f"赞助者验证出错: {str(e)}，将使用普通下载链接")
        return False, f"验证出错: {str(e)}"

# 检查Java是否已安装
def check_java_installation(version="jdk8"):
    """检查Java是否已安装"""
    if version not in JAVA_VERSIONS:
        return False, ""
    
    java_dir = JAVA_VERSIONS[version]["dir"]
    
    if not os.path.exists(java_dir):
        return False, ""
    
    # 检查java可执行文件是否存在
    java_executable = os.path.join(java_dir, "bin/java")
    if not os.path.exists(java_executable):
        return False, ""
    
    try:
        # 尝试执行java -version命令
        result = subprocess.run([java_executable, "-version"], 
                                capture_output=True, 
                                text=True, 
                                check=True)
        version_output = result.stderr  # java -version输出到stderr
        # 提取版本信息
        version_match = re.search(r'version "([^"]+)"', version_output)
        if version_match:
            return True, version_match.group(1)
        return True, "Unknown"
    except Exception as e:
        logger.error(f"检查Java版本时出错: {str(e)}")
        return True, "Unknown"  # 文件存在但无法获取版本

# 安装Java的函数
def install_java(version="jdk8"):
    """安装指定版本的Java"""
    global current_java_download
    
    if version not in JAVA_VERSIONS:
        return False, f"不支持的Java版本: {version}，支持的版本有: {', '.join(JAVA_VERSIONS.keys())}"
    
    # 检查是否有其他Java正在下载
    with java_download_lock:
        if current_java_download is not None:
            current_downloading = JAVA_VERSIONS.get(current_java_download, {}).get('display_name', current_java_download)
            return False, f"当前正在下载 {current_downloading}，请等待完成后再下载其他版本"
        
        # 设置当前下载的版本
        current_java_download = version
    
    # 初始化进度和取消标志 - 使用共享字典
    java_install_progress[version] = java_manager.dict({
        "progress": 0,
        "status": "downloading",
        "completed": False,
        "error": None
    })
    java_download_cancelled[version] = False
    
    # 使用独立进程执行安装，避免GIL锁竞争
    from java_installer import install_java_worker
    
    # 验证赞助者身份
    is_sponsor, verify_msg = verify_sponsor_for_java()
    
    # 根据赞助者身份选择下载链接
    if is_sponsor and "sponsor_url" in JAVA_VERSIONS[version]:
        java_url = JAVA_VERSIONS[version]["sponsor_url"]
    else:
        java_url = JAVA_VERSIONS[version]["url"]
    
    # 创建进程间通信队列
    install_queue = multiprocessing.Queue()
    
    # 启动独立进程进行安装
    process = multiprocessing.Process(
        target=install_java_worker,
        args=(version, JAVA_VERSIONS, java_url, is_sponsor, install_queue)
    )
    process.daemon = True
    process.start()
    
    # 在新线程中监控进程进度
    thread = threading.Thread(target=_monitor_java_install_process, args=(version, process, install_queue))
    thread.daemon = True
    thread.start()
    
    return True, f"{JAVA_VERSIONS[version]['display_name']}安装已启动"

def _monitor_java_install_process(version, process, install_queue):
    """监控Java安装进程的进度"""
    global current_java_download
    
    try:
        while process.is_alive() or not install_queue.empty():
            try:
                # 从队列中获取进度更新
                progress_data = install_queue.get(timeout=1)
                
                # 检查是否被用户取消
                if java_download_cancelled.get(version, False):
                    logger.info(f"{JAVA_VERSIONS[version]['display_name']} 安装已被用户取消")
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                    
                    java_install_progress[version]["status"] = "cancelled"
                    java_install_progress[version]["error"] = "安装已被用户取消"
                    java_install_progress[version]["completed"] = True
                    break
                
                # 更新进度数据
                java_install_progress[version].update(progress_data)
                
                # 如果安装完成或出错，退出循环
                if progress_data.get('completed', False):
                    break
                    
            except queue.Empty:
                # 队列为空，继续等待
                continue
            except Exception as e:
                logger.error(f"监控Java安装进程时出错: {e}")
                break
        
        # 等待进程结束
        process.join(timeout=5)
        
        # 如果进程仍在运行，强制终止
        if process.is_alive():
            logger.warning(f"Java安装进程超时，强制终止")
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
            
            # 设置错误状态
            java_install_progress[version]["status"] = "error"
            java_install_progress[version]["error"] = "安装进程超时"
            java_install_progress[version]["completed"] = True
    except Exception as e:
        logger.error(f"监控Java安装进程时出错: {str(e)}")
        java_install_progress[version]["status"] = "error"
        java_install_progress[version]["error"] = str(e)
        java_install_progress[version]["completed"] = True
    finally:
        # 重置当前下载状态
        with java_download_lock:
            current_java_download = None
        # 清理取消标志
        java_download_cancelled.pop(version, None)

# Java环境API路由
@app.route('/api/environment/java/status', methods=['GET'])
@auth_required
def get_java_status():
    """获取Java安装状态"""
    try:
        version = request.args.get('version', 'jdk8')
        installed, java_version = check_java_installation(version)
        
        # 获取安装进度 - 使用共享字典
        progress_info_proxy = java_install_progress.get(version, java_manager.dict({
            "progress": 0,
            "status": "not_started",
            "completed": False
        }))
        # 将共享字典代理对象转换为普通字典，确保jsonify能正常工作
        progress_info = dict(progress_info_proxy)
        
        # 如果已安装但进度信息不完整，补充信息
        if installed and not progress_info.get("completed"):
            java_dir = JAVA_VERSIONS[version]["dir"]
            java_executable = os.path.join(java_dir, "bin/java")
            progress_info = {
                "progress": 100,
                "status": "completed",
                "completed": True,
                "version": java_version,
                "path": java_executable,
                "usage_hint": f"使用方式: {java_executable} -version"
            }
        
        return jsonify({
            "status": "success",
            "installed": installed,
            "version": java_version if installed else None,
            "progress": progress_info
        })
    except Exception as e:
        logger.error(f"获取Java状态时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/environment/java/install', methods=['POST'])
@auth_required
def install_java_route():
    """安装Java"""
    try:
        data = request.get_json()
        version = data.get('version', 'jdk8')
        
        # 检查是否已安装
        installed, _ = check_java_installation(version)
        if installed:
            return jsonify({
                "status": "success",
                "message": f"{JAVA_VERSIONS[version]['display_name']}已安装"
            })
        
        # 开始安装
        success, message = install_java(version)
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
    except Exception as e:
        logger.error(f"安装Java时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/environment/java/versions', methods=['GET'])
@auth_required
def get_java_versions():
    """获取可用的Java版本"""
    try:
        versions = []
        for version_id, info in JAVA_VERSIONS.items():
            installed, java_version = check_java_installation(version_id)
            versions.append({
                "id": version_id,
                "name": info["display_name"],
                "installed": installed,
                "version": java_version if installed else None
            })
        
        return jsonify({
            "status": "success",
            "versions": versions
        })
    except Exception as e:
        logger.error(f"获取Java版本列表时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/environment/java/uninstall', methods=['POST'])
@auth_required
def uninstall_java_route():
    """卸载Java"""
    try:
        data = request.get_json()
        version = data.get('version', 'jdk8')
        
        if version not in JAVA_VERSIONS:
            return jsonify({
                "status": "error",
                "message": f"不支持的Java版本: {version}"
            }), 400
        
        # 检查是否已安装
        installed, _ = check_java_installation(version)
        if not installed:
            return jsonify({
                "status": "success",
                "message": f"{JAVA_VERSIONS[version]['display_name']}未安装"
            })
        
        # 检查是否正在安装中
        if current_java_download == version:
            return jsonify({
                "status": "error",
                "message": f"{JAVA_VERSIONS[version]['display_name']}正在安装中，无法卸载"
            }), 400
        
        # 执行卸载
        java_dir = JAVA_VERSIONS[version]["dir"]
        if os.path.exists(java_dir):
            shutil.rmtree(java_dir)
            logger.info(f"已卸载{JAVA_VERSIONS[version]['display_name']}: {java_dir}")
        
        # 清理进度信息
        java_install_progress.pop(version, None)
        
        return jsonify({
            "status": "success",
            "message": f"{JAVA_VERSIONS[version]['display_name']}卸载成功"
        })
    except Exception as e:
        logger.error(f"卸载Java时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/environment/java/cancel', methods=['POST'])
@auth_required
def cancel_java_download_route():
    """取消Java下载"""
    try:
        data = request.get_json()
        version = data.get('version', 'jdk8')
        
        if version not in JAVA_VERSIONS:
            return jsonify({
                "status": "error",
                "message": f"不支持的Java版本: {version}"
            }), 400
        
        # 检查是否正在下载
        if current_java_download != version:
            return jsonify({
                "status": "error",
                "message": f"{JAVA_VERSIONS[version]['display_name']}未在下载中"
            }), 400
        
        # 设置取消标志
        java_download_cancelled[version] = True
        logger.info(f"用户请求取消{JAVA_VERSIONS[version]['display_name']}下载")
        
        return jsonify({
            "status": "success",
            "message": f"已请求取消{JAVA_VERSIONS[version]['display_name']}下载"
        })
    except Exception as e:
        logger.error(f"取消Java下载时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks', methods=['GET'])
@auth_required
def get_backup_tasks():
    """获取备份任务列表"""
    try:
        ensure_backup_config_loaded()
        # 将backup_tasks对象转换为数组格式
        tasks_list = []
        for task_id, task_data in backup_tasks.items():
            task_info = task_data.copy()
            task_info['id'] = task_id
            tasks_list.append(task_info)
        
        return jsonify({
            "status": "success",
            "tasks": tasks_list
        })
    except Exception as e:
        logger.error(f"获取备份任务列表时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks', methods=['POST'])
@auth_required
def create_backup_task():
    """创建备份任务"""
    try:
        global backup_task_counter
        data = request.get_json()
        
        # 验证必需字段
        required_fields = ['name', 'directory', 'interval', 'keepCount']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "status": "error",
                    "message": f"缺少必需字段: {field}"
                }), 400
        
        # 验证目录是否存在
        if not os.path.exists(data['directory']):
            return jsonify({
                "status": "error",
                "message": "指定的备份目录不存在"
            }), 400
        
        backup_task_counter += 1
        task_id = str(backup_task_counter)
        
        # 计算下次备份时间
        import datetime
        interval_hours = float(data['interval'])
        next_backup = datetime.datetime.now() + datetime.timedelta(hours=interval_hours)
        
        task = {
            "id": task_id,
            "name": data['name'],
            "directory": data['directory'],
            "interval": interval_hours,
            "intervalValue": data.get('intervalValue'),
            "intervalUnit": data.get('intervalUnit'),
            "keepCount": int(data['keepCount']),
            "enabled": True,
            "nextBackup": next_backup.strftime('%Y-%m-%d %H:%M:%S'),
            "lastBackup": None,
            "status": "等待中",
            "linkedServerId": data.get('linkedServerId'),  # 关联的服务端ID
            "autoControl": data.get('autoControl', False)  # 是否自动控制（服务端开启时启用备份，关闭时停用）
        }
        
        backup_tasks[task_id] = task
        save_backup_config()
        
        logger.info(f"创建备份任务: {data['name']}")
        return jsonify({
            "status": "success",
            "task": task
        })
    except Exception as e:
        logger.error(f"创建备份任务时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks/<task_id>', methods=['PUT'])
@auth_required
def update_backup_task(task_id):
    """更新备份任务"""
    try:
        if task_id not in backup_tasks:
            return jsonify({
                "status": "error",
                "message": "备份任务不存在"
            }), 404
        
        data = request.get_json()
        task = backup_tasks[task_id]
        
        # 更新任务信息
        if 'name' in data:
            task['name'] = data['name']
        if 'directory' in data:
            if not os.path.exists(data['directory']):
                return jsonify({
                    "status": "error",
                    "message": "指定的备份目录不存在"
                }), 400
            task['directory'] = data['directory']
        if 'interval' in data:
            task['interval'] = float(data['interval'])
            # 重新计算下次备份时间
            import datetime
            next_backup = datetime.datetime.now() + datetime.timedelta(hours=task['interval'])
            task['nextBackup'] = next_backup.strftime('%Y-%m-%d %H:%M:%S')
        if 'intervalValue' in data:
            task['intervalValue'] = data['intervalValue']
        if 'intervalUnit' in data:
            task['intervalUnit'] = data['intervalUnit']
        if 'keepCount' in data:
            task['keepCount'] = int(data['keepCount'])
        if 'linkedServerId' in data:
            task['linkedServerId'] = data['linkedServerId']
        if 'autoControl' in data:
            task['autoControl'] = data['autoControl']
        
        save_backup_config()
        logger.info(f"更新备份任务: {task['name']}")
        return jsonify({
            "status": "success",
            "task": task
        })
    except Exception as e:
        logger.error(f"更新备份任务时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks/<task_id>', methods=['DELETE'])
@auth_required
def delete_backup_task(task_id):
    """删除备份任务"""
    try:
        if task_id not in backup_tasks:
            return jsonify({
                "status": "error",
                "message": "备份任务不存在"
            }), 404
        
        task_name = backup_tasks[task_id]['name']
        del backup_tasks[task_id]
        save_backup_config()
        
        logger.info(f"删除备份任务: {task_name}")
        return jsonify({
            "status": "success",
            "message": "备份任务已删除"
        })
    except Exception as e:
        logger.error(f"删除备份任务时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks/<task_id>/toggle', methods=['POST'])
@auth_required
def toggle_backup_task(task_id):
    """启用/禁用备份任务"""
    try:
        if task_id not in backup_tasks:
            return jsonify({
                "status": "error",
                "message": "备份任务不存在"
            }), 404
        
        task = backup_tasks[task_id]
        task['enabled'] = not task['enabled']
        save_backup_config()
        
        status = "启用" if task['enabled'] else "禁用"
        logger.info(f"{status}备份任务: {task['name']}")
        
        return jsonify({
            "status": "success",
            "task": task
        })
    except Exception as e:
        logger.error(f"切换备份任务状态时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/backup/tasks/<task_id>/run', methods=['POST'])
@auth_required
def run_backup_now(task_id):
    """立即执行备份"""
    try:
        if task_id not in backup_tasks:
            return jsonify({
                "status": "error",
                "message": "备份任务不存在"
            }), 404
        
        task = backup_tasks[task_id]
        
        # 创建备份目录
        backup_base_dir = "/home/steam/backup"
        task_backup_dir = os.path.join(backup_base_dir, task['name'])
        os.makedirs(task_backup_dir, exist_ok=True)
        
        # 生成备份文件名
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{task['name']}_{timestamp}.tar"
        backup_filepath = os.path.join(task_backup_dir, backup_filename)
        
        # 执行tar备份命令
        tar_cmd = [
            'tar', '-cf', backup_filepath,
            '-C', os.path.dirname(task['directory']),
            os.path.basename(task['directory'])
        ]
        
        result = subprocess.run(tar_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # 备份成功，更新任务状态
            task['lastBackup'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            task['status'] = '备份成功'
            
            # 清理旧备份文件
            cleanup_old_backups(task_backup_dir, task['keepCount'])
            
            # 计算下次备份时间
            next_backup = datetime.datetime.now() + datetime.timedelta(hours=task['interval'])
            task['nextBackup'] = next_backup.strftime('%Y-%m-%d %H:%M:%S')
            
            logger.info(f"备份任务执行成功: {task['name']}")
            return jsonify({
                "status": "success",
                "message": "备份执行成功",
                "task": task
            })
        else:
            task['status'] = '备份失败'
            logger.error(f"备份任务执行失败: {task['name']}, 错误: {result.stderr}")
            return jsonify({
                "status": "error",
                "message": f"备份执行失败: {result.stderr}"
            }), 500
            
    except Exception as e:
        logger.error(f"执行备份任务时出错: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def cleanup_old_backups(backup_dir, keep_count):
    """清理旧的备份文件，只保留指定数量的最新备份"""
    try:
        if not os.path.exists(backup_dir):
            return
        
        # 获取所有tar文件
        backup_files = []
        for file in os.listdir(backup_dir):
            if file.endswith('.tar'):
                filepath = os.path.join(backup_dir, file)
                backup_files.append((filepath, os.path.getmtime(filepath)))
        
        # 按修改时间排序，最新的在前
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # 删除超出保留数量的文件
        if len(backup_files) > keep_count:
            for filepath, _ in backup_files[keep_count:]:
                os.remove(filepath)
                logger.info(f"删除旧备份文件: {filepath}")
                
    except Exception as e:
        logger.error(f"清理旧备份文件时出错: {str(e)}")

def backup_scheduler():
    """备份任务调度器，定期检查并执行到期的备份任务"""
    global backup_scheduler_running
    backup_scheduler_running = True
    
    while backup_scheduler_running:
        try:
            current_time = datetime.datetime.now()
            
            for task_id, task in backup_tasks.items():
                # 检查是否启用了自动控制功能
                if task.get('autoControl', False) and task.get('linkedServerId'):
                    linked_server_id = task['linkedServerId']
                    server_running = is_server_running(linked_server_id)
                    
                    # 根据服务端状态自动控制备份任务
                    if server_running and not task.get('enabled', False):
                        # 服务端运行中但备份任务未启用，自动启用
                        task['enabled'] = True
                        task['status'] = '已启用（自动）'
                        logger.info(f"服务端 {linked_server_id} 运行中，自动启用备份任务: {task['name']}")
                        save_backup_config()
                    elif not server_running and task.get('enabled', False):
                        # 服务端已停止但备份任务仍启用，自动停用
                        task['enabled'] = False
                        task['status'] = '已停用（自动）'
                        logger.info(f"服务端 {linked_server_id} 已停止，自动停用备份任务: {task['name']}")
                        save_backup_config()
                
                # 只有启用的任务才执行备份
                if not task.get('enabled', False):
                    continue
                    
                next_backup_str = task.get('nextBackup')
                if not next_backup_str:
                    continue
                    
                try:
                    next_backup_time = datetime.datetime.strptime(next_backup_str, '%Y-%m-%d %H:%M:%S')
                    
                    # 检查是否到了备份时间
                    if current_time >= next_backup_time:
                        # 如果关联了服务端且启用了自动控制，只有在服务端运行时才执行备份
                        if task.get('autoControl', False) and task.get('linkedServerId'):
                            if not is_server_running(task['linkedServerId']):
                                logger.info(f"跳过备份任务 {task['name']}：关联的服务端 {task['linkedServerId']} 未运行")
                                continue
                        
                        logger.info(f"开始执行定时备份任务: {task['name']}")
                        execute_backup_task(task_id, task)
                        
                except ValueError as e:
                    logger.error(f"解析备份时间失败: {next_backup_str}, 错误: {str(e)}")
                    
        except Exception as e:
            logger.error(f"备份调度器运行出错: {str(e)}")
            
        # 每分钟检查一次
        time.sleep(60)
        
def execute_backup_task(task_id, task):
    """执行备份任务的核心逻辑"""
    try:
        # 创建备份目录
        backup_base_dir = "/home/steam/backup"
        task_backup_dir = os.path.join(backup_base_dir, task['name'])
        os.makedirs(task_backup_dir, exist_ok=True)
        
        # 生成备份文件名
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{task['name']}_{timestamp}.tar"
        backup_filepath = os.path.join(task_backup_dir, backup_filename)
        
        # 执行tar备份命令
        tar_cmd = [
            'tar', '-cf', backup_filepath,
            '-C', os.path.dirname(task['directory']),
            os.path.basename(task['directory'])
        ]
        
        result = subprocess.run(tar_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            # 备份成功，更新任务状态
            task['lastBackup'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            task['status'] = '备份成功'
            
            # 清理旧备份文件
            cleanup_old_backups(task_backup_dir, task['keepCount'])
            
            # 计算下次备份时间
            next_backup = datetime.datetime.now() + datetime.timedelta(hours=task['interval'])
            task['nextBackup'] = next_backup.strftime('%Y-%m-%d %H:%M:%S')
            
            # 保存配置
            save_backup_config()
            
            logger.info(f"定时备份任务执行成功: {task['name']}")
        else:
            task['status'] = '备份失败'
            logger.error(f"定时备份任务执行失败: {task['name']}, 错误: {result.stderr}")
            
    except Exception as e:
        task['status'] = '备份失败'
        logger.error(f"执行定时备份任务时出错: {task['name']}, 错误: {str(e)}")

def is_server_running(server_id):
    """检查指定服务端是否正在运行"""
    try:
        if server_id in running_servers:
            server_data = running_servers[server_id]
            process = server_data.get('process')
            if process and process.poll() is None:
                return True
        return False
    except Exception as e:
        logger.error(f"检查服务端 {server_id} 运行状态时出错: {str(e)}")
        return False

def start_backup_scheduler():
    """启动备份调度器"""
    global backup_scheduler_running
    if not backup_scheduler_running:
        scheduler_thread = threading.Thread(target=backup_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("备份调度器已启动")

def stop_backup_scheduler():
    """停止备份调度器"""
    global backup_scheduler_running
    backup_scheduler_running = False
    logger.info("备份调度器已停止")

def load_backup_config():
    """加载备份配置"""
    global backup_tasks, backup_task_counter
    try:
        backup_config_file = '/home/steam/games/backup_config.json'
        if os.path.exists(backup_config_file):
            with open(backup_config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                backup_tasks = config.get('tasks', {})
                backup_task_counter = config.get('counter', 0)
                logger.info(f"已加载 {len(backup_tasks)} 个备份任务")
        else:
            backup_tasks = {}
            backup_task_counter = 0
            logger.info("备份配置文件不存在，使用默认配置")
    except Exception as e:
        logger.error(f"加载备份配置失败: {str(e)}")
        backup_tasks = {}
        backup_task_counter = 0

def save_backup_config():
    """保存备份配置"""
    try:
        backup_config_file = '/home/steam/games/backup_config.json'
        os.makedirs(os.path.dirname(backup_config_file), exist_ok=True)
        config = {
            'tasks': backup_tasks,
            'counter': backup_task_counter
        }
        with open(backup_config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        logger.debug("备份配置已保存")
    except Exception as e:
        logger.error(f"保存备份配置失败: {str(e)}")

# Minecraft部署相关API
@app.route('/api/minecraft/servers', methods=['GET'])
@auth_required
def get_minecraft_servers():
    """获取支持的Minecraft服务端列表"""
    try:
        servers = get_server_list()
        return jsonify({
            'status': 'success',
            'data': servers
        })
    except Exception as e:
        logger.error(f"获取Minecraft服务端列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取服务端列表失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/server/<server_name>', methods=['GET'])
@auth_required
def get_minecraft_server_info(server_name):
    """获取指定Minecraft服务端信息"""
    try:
        server_info = get_server_info(server_name)
        if not server_info:
            return jsonify({
                'status': 'error',
                'message': f'未找到服务端 {server_name} 的信息'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': server_info
        })
    except Exception as e:
        logger.error(f"获取Minecraft服务端信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取服务端信息失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/builds/<server_name>/<mc_version>', methods=['GET'])
@auth_required
def get_minecraft_builds(server_name, mc_version):
    """获取指定服务端和MC版本的构建列表"""
    try:
        builds_data = get_builds(server_name, mc_version)
        if not builds_data:
            return jsonify({
                'status': 'error',
                'message': f'未找到 {server_name} {mc_version} 的构建版本'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': builds_data
        })
    except Exception as e:
        logger.error(f"获取Minecraft构建列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取构建列表失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/installed-jdks', methods=['GET'])
@auth_required
def get_installed_jdks():
    """获取已安装的JDK列表"""
    try:
        installed_jdks = []
        for version_id, info in JAVA_VERSIONS.items():
            installed, java_version = check_java_installation(version_id)
            if installed:
                java_executable = os.path.join(info["dir"], "bin/java")
                installed_jdks.append({
                    'id': version_id,
                    'name': info["display_name"],
                    'version': java_version,
                    'path': java_executable
                })
        
        return jsonify({
            'status': 'success',
            'jdks': installed_jdks
        })
        
    except Exception as e:
        logger.error(f"获取已安装JDK列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取JDK列表失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/deploy', methods=['POST'])
@auth_required
def deploy_minecraft_server():
    """部署Minecraft服务器"""
    try:
        data = request.get_json()
        server_name = data.get('server_name')
        mc_version = data.get('mc_version')
        core_version = data.get('core_version')
        custom_name = data.get('custom_name', server_name)
        selected_jdk = data.get('selected_jdk')  # 新增JDK选择参数
        deploy_mode = data.get('deploy_mode', 'new')  # 新增部署模式参数，默认为新建
        
        if not all([server_name, mc_version, core_version]):
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: server_name, mc_version, core_version'
            }), 400
        
        # 确定Java可执行文件路径（仅在新建模式下需要）
        java_executable = 'java'  # 默认使用系统Java
        if deploy_mode == 'new' and selected_jdk:
            if selected_jdk in JAVA_VERSIONS:
                installed, _ = check_java_installation(selected_jdk)
                if installed:
                    java_executable = os.path.join(JAVA_VERSIONS[selected_jdk]["dir"], "bin/java")
                else:
                    return jsonify({
                        'status': 'error',
                        'message': f'选择的JDK {selected_jdk} 未安装'
                    }), 400
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'不支持的JDK版本: {selected_jdk}'
                }), 400
        
        # 创建游戏目录
        game_dir = os.path.join('/home/steam/games', custom_name)
        os.makedirs(game_dir, exist_ok=True)
        
        # 获取核心信息
        core_info = get_core_info(server_name, mc_version, core_version)
        if not core_info:
            return jsonify({
                'status': 'error',
                'message': '获取核心信息失败'
            }), 500
        
        filename = core_info.get('filename', f'{server_name}-{mc_version}-{core_version}.jar')
        
        # 下载文件到指定目录
        import requests
        download_url = f"https://download.fastmirror.net/download/{server_name}/{mc_version}/{core_version}"
        
        logger.info(f"开始下载Minecraft服务端: {filename}")
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        file_path = os.path.join(game_dir, filename)
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        # 只有在新建模式下才创建启动脚本和配置文件
        if deploy_mode == 'new':
            # 创建启动脚本，使用选择的JDK
            start_script_content = f"""#!/bin/bash
cd "$(dirname "$0")"
{java_executable} -Xmx2G -Xms1G -jar {filename} nogui
"""
            
            start_script_path = os.path.join(game_dir, 'start.sh')
            with open(start_script_path, 'w') as f:
                f.write(start_script_content)
            
            # 设置执行权限
            os.chmod(start_script_path, 0o755)
            
            # 创建eula.txt文件
            eula_path = os.path.join(game_dir, 'eula.txt')
            with open(eula_path, 'w') as f:
                f.write('eula=true\n')
        
        # 设置目录权限
        subprocess.run(['chown', '-R', 'steam:steam', game_dir], check=False)
        
        if deploy_mode == 'new':
            logger.info(f"Minecraft服务端部署完成: {game_dir}，使用JDK: {java_executable}")
            message_text = 'Minecraft服务端部署成功'
        else:
            logger.info(f"Minecraft服务端核心文件下载完成: {game_dir}")
            message_text = 'Minecraft服务端核心文件下载成功'
        
        response_data = {
            'game_dir': game_dir,
            'filename': filename,
            'server_name': server_name,
            'mc_version': mc_version,
            'core_version': core_version,
            'deploy_mode': deploy_mode
        }
        
        # 只有在新建模式下才返回JDK相关信息
        if deploy_mode == 'new':
            response_data['java_executable'] = java_executable
            response_data['selected_jdk'] = selected_jdk
        
        return jsonify({
            'status': 'success',
            'message': message_text,
            'data': response_data
        })
        
    except Exception as e:
        logger.error(f"部署Minecraft服务端失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'部署失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/modpack/search', methods=['GET'])
@auth_required
def search_modpacks():
    """搜索Minecraft整合包"""
    try:
        query = request.args.get('query', '')
        max_results = int(request.args.get('max_results', 20))
        
        installer = MinecraftModpackInstaller()
        modpacks = installer.cli.search_modpacks(query=query, max_results=max_results)
        
        # 验证返回数据格式
        if not isinstance(modpacks, list):
            logger.error(f"搜索整合包返回数据格式错误: 期望列表，收到 {type(modpacks)}")
            return jsonify({
                'status': 'error',
                'message': '搜索结果格式错误'
            }), 500
        
        return jsonify({
            'status': 'success',
            'data': modpacks
        })
        
    except Exception as e:
        logger.error(f"搜索整合包失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'搜索失败: {str(e)}'
        }), 500

@app.route('/api/minecraft/modpack/<modpack_id>/versions', methods=['GET'])
@auth_required
def get_modpack_versions(modpack_id):
    """获取整合包版本列表"""
    try:
        installer = MinecraftModpackInstaller()
        versions = installer.cli.get_modpack_versions(modpack_id)
        
        return jsonify({
            'status': 'success',
            'data': versions
        })
        
    except Exception as e:
        logger.error(f"获取整合包版本失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取版本失败: {str(e)}'
        }), 500

# Minecraft整合包部署相关的全局变量
active_modpack_deployments = manager.dict()  # deployment_id -> deployment_data
modpack_deploy_queues = manager.dict()  # deployment_id -> queue

@app.route('/api/minecraft/modpack/deploy', methods=['POST'])
@auth_required
def deploy_minecraft_modpack():
    """启动Minecraft整合包部署"""
    try:
        data = request.get_json()
        modpack_id = data.get('modpack_id')
        version_id = data.get('version_id')
        folder_name = data.get('folder_name')
        java_version = data.get('java_version', 'system')
        
        if not all([modpack_id, version_id, folder_name]):
            return jsonify({
                'status': 'error',
                'message': '缺少必要参数: modpack_id, version_id, folder_name'
            }), 400
        
        # 验证文件夹名称
        if any(char in folder_name for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
            return jsonify({
                'status': 'error',
                'message': '文件夹名称包含非法字符'
            }), 400
        
        # 检查文件夹是否已存在
        install_path = os.path.join('/home/steam/games', folder_name)
        if os.path.exists(install_path):
            return jsonify({
                'status': 'error',
                'message': f'文件夹 {folder_name} 已存在'
            }), 400
        
        # 验证Java版本
        installer = MinecraftModpackInstaller()
        if java_version != 'system' and java_version not in installer.java_versions:
            return jsonify({
                'status': 'error',
                'message': f'不支持的Java版本: {java_version}'
            }), 400
        
        if java_version != 'system':
            installed, _ = installer.check_java_installation(java_version)
            if not installed:
                return jsonify({
                    'status': 'error',
                    'message': f'Java版本 {java_version} 未安装，请先安装对应的Java版本后再进行操作'
                }), 400
        
        # 获取整合包信息
        modpack_data = installer.cli.get_modpack_details(modpack_id)
        if not modpack_data:
            return jsonify({
                'status': 'error',
                'message': '获取整合包信息失败'
            }), 500
        
        # 获取版本信息
        versions = installer.cli.get_modpack_versions(modpack_id)
        version_data = None
        for version in versions:
            if version['id'] == version_id:
                version_data = version
                break
        
        if not version_data:
            return jsonify({
                'status': 'error',
                'message': '找不到指定的版本'
            }), 400
        
        # 生成部署ID
        deployment_id = f"modpack_{int(time.time())}_{folder_name}"
        
        # 检查是否已有部署在进行
        if deployment_id in active_modpack_deployments:
            return jsonify({
                'status': 'error',
                'message': f'整合包 {folder_name} 正在部署中，请等待完成'
            }), 400
        
        # 初始化部署状态
        deployment_data = manager.dict()
        deployment_data['modpack_name'] = modpack_data['title']
        deployment_data['folder_name'] = folder_name
        deployment_data['status'] = 'starting'
        deployment_data['progress'] = 0
        deployment_data['message'] = '正在准备部署...'
        deployment_data['complete'] = False
        deployment_data['start_time'] = time.time()
        active_modpack_deployments[deployment_id] = deployment_data
        
        deploy_queue = manager.Queue()
        modpack_deploy_queues[deployment_id] = deploy_queue
        
        # 启动部署进程
        deploy_process = multiprocessing.Process(
            target=_deploy_modpack_worker,
            args=(deployment_id, modpack_data, version_data, folder_name, java_version, deployment_data, deploy_queue),
            daemon=True
        )
        deploy_process.start()
        
        logger.info(f"开始部署整合包: {modpack_data['title']} v{version_data['version_number']} 到 {folder_name}")
        
        return jsonify({
            'status': 'success',
            'message': f'开始部署整合包 {modpack_data["title"]}',
            'deployment_id': deployment_id
        })
        
    except Exception as e:
        logger.error(f"启动整合包部署时发生错误: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'启动部署时发生错误: {str(e)}'
        }), 500

def _deploy_modpack_worker(deployment_id, modpack_data, version_data, folder_name, java_version, deployment_data, deploy_queue):
    """整合包部署工作进程"""
    try:
        installer = MinecraftModpackInstaller()
        
        def progress_callback(progress_data):
            """进度回调函数"""
            deployment_data['progress'] = progress_data['progress']
            deployment_data['message'] = progress_data['message']
            deployment_data['status'] = progress_data.get('status', 'installing')
            deploy_queue.put(progress_data)
        
        # 执行安装
        result = installer.install_modpack(
            modpack_data,
            version_data,
            folder_name,
            java_version,
            progress_callback
        )
        
        if result['success']:
            deployment_data['status'] = 'completed'
            deployment_data['progress'] = 100
            deployment_data['message'] = '整合包部署成功'
            deployment_data['complete'] = True
            deployment_data['data'] = result['data']
            
            deploy_queue.put({
                'progress': 100,
                'status': 'completed',
                'message': '整合包部署成功',
                'complete': True,
                'data': result['data']
            })
            
            logger.info(f"整合包部署成功: {folder_name}")
        else:
            error_msg = f'部署失败: {result["message"]}'
            deployment_data['status'] = 'error'
            deployment_data['message'] = error_msg
            deployment_data['complete'] = True
            
            deploy_queue.put({
                'progress': deployment_data['progress'],
                'status': 'error',
                'message': error_msg,
                'complete': True
            })
            
            logger.error(f"整合包部署失败: {result['message']}")
            
    except Exception as e:
        error_msg = f'部署时发生错误: {str(e)}'
        logger.error(f"整合包部署时发生错误: {str(e)}", exc_info=True)
        deployment_data['status'] = 'error'
        deployment_data['message'] = error_msg
        deployment_data['complete'] = True
        deploy_queue.put({
            'progress': deployment_data.get('progress', 0),
            'status': 'error',
            'message': error_msg,
            'complete': True
        })

@app.route('/api/minecraft/modpack/deploy/stream', methods=['GET'])
@auth_required
def modpack_deploy_stream():
    """获取整合包部署的实时进度"""
    # 在请求上下文中获取参数
    deployment_id = request.args.get('deployment_id')
    if not deployment_id:
        return jsonify({'error': '缺少deployment_id参数'}), 400
    
    def generate(deployment_id):
        try:
            
            # 检查部署是否存在
            if deployment_id not in active_modpack_deployments:
                yield f"data: {json.dumps({'error': f'部署任务 {deployment_id} 不存在'})}\n\n"
                return
            
            if deployment_id not in modpack_deploy_queues:
                modpack_deploy_queues[deployment_id] = manager.Queue()
            
            # 如果部署已完成，添加完成消息
            deployment_data = active_modpack_deployments[deployment_id]
            if deployment_data.get('complete', False):
                modpack_deploy_queues[deployment_id].put({
                    'progress': deployment_data.get('progress', 100),
                    'status': deployment_data.get('status', 'completed'),
                    'message': deployment_data.get('message', '部署已完成'),
                    'complete': True,
                    'data': deployment_data.get('data')
                })
            
            deployment_data = active_modpack_deployments[deployment_id]
            deploy_queue = modpack_deploy_queues[deployment_id]
            
            # 发送初始连接消息
            yield f"data: {json.dumps({'message': '连接成功，开始接收部署进度...', 'progress': deployment_data.get('progress', 0), 'status': deployment_data.get('status', 'starting')})}\n\n"
            
            # 持续监听进度更新
            timeout_count = 0
            max_timeout = 300  # 5分钟超时
            
            while timeout_count < max_timeout:
                try:
                    # 尝试从队列获取进度更新
                    item = deploy_queue.get(timeout=1)
                    timeout_count = 0  # 重置超时计数
                    
                    # 发送进度更新
                    yield f"data: {json.dumps(item)}\n\n"
                    
                    # 如果部署完成，结束流
                    if item.get('complete', False):
                        break
                        
                except:
                    timeout_count += 1
                    continue
            
            if timeout_count >= max_timeout:
                logger.warning(f"整合包部署 {deployment_id} 的流超时")
                yield f"data: {json.dumps({'message': '部署流超时，请刷新页面查看最新状态', 'status': 'timeout', 'complete': True})}\n\n"
            
            # 检查部署是否已完成但未发送完成消息
            if deployment_data.get('complete', False):
                final_data = {
                    'progress': deployment_data.get('progress', 100),
                    'status': deployment_data.get('status', 'completed'),
                    'message': deployment_data.get('message', '部署已完成'),
                    'complete': True
                }
                if deployment_data.get('data'):
                    final_data['data'] = deployment_data['data']
                
                yield f"data: {json.dumps(final_data)}\n\n"
            
        except Exception as e:
            logger.error(f"生成整合包部署流数据时出错: {str(e)}")
            yield f"data: {json.dumps({'error': f'生成流数据时出错: {str(e)}'})}\n\n"
        finally:
            # 清理资源
            try:
                if deployment_id in active_modpack_deployments:
                    if active_modpack_deployments[deployment_id].get('complete', False):
                        active_modpack_deployments.pop(deployment_id, None)
                        modpack_deploy_queues.pop(deployment_id, None)
            except:
                pass
    
    try:
        return Response(generate(deployment_id), mimetype='text/event-stream')
    except Exception as e:
        logger.error(f"整合包部署流处理错误: {str(e)}")
        return jsonify({'error': f'流处理错误: {str(e)}'}), 500



# 日志管理API
@app.route('/api/logs/api-server', methods=['GET'])
@auth_required
def get_api_server_log():
    """获取API服务器日志内容"""
    try:
        log_file_path = '/home/steam/server/api_server.log'
        
        # 检查日志文件是否存在
        if not os.path.exists(log_file_path):
            return jsonify({
                'status': 'success',
                'content': '日志文件不存在或尚未生成'
            })
        
        # 读取日志文件内容
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # 如果UTF-8解码失败，尝试其他编码
            with open(log_file_path, 'r', encoding='latin-1') as f:
                content = f.read()
        
        # 限制返回的内容大小（最后10000行）
        lines = content.split('\n')
        if len(lines) > 10000:
            lines = lines[-10000:]
            content = '\n'.join(lines)
            content = '[日志内容过长，仅显示最后10000行]\n\n' + content
        
        return jsonify({
            'status': 'success',
            'content': content
        })
        
    except Exception as e:
        logger.error(f"获取API服务器日志失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取日志失败: {str(e)}'
        }), 500

@app.route('/api/logs/api-server/export', methods=['GET'])
@auth_required
def export_api_server_log():
    """导出API服务器日志文件"""
    try:
        log_file_path = '/home/steam/server/api_server.log'
        
        # 检查日志文件是否存在
        if not os.path.exists(log_file_path):
            # 创建一个临时文件包含错误信息
            temp_content = '日志文件不存在或尚未生成'
            response = make_response(temp_content)
            response.headers['Content-Type'] = 'text/plain; charset=utf-8'
            response.headers['Content-Disposition'] = 'attachment; filename=api_server_empty.log'
            return response
        
        # 直接发送文件
        return send_file(
            log_file_path,
            as_attachment=True,
            download_name=f'api_server_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
            mimetype='text/plain'
        )
        
    except Exception as e:
        logger.error(f"导出API服务器日志失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'导出日志失败: {str(e)}'
        }), 500

# Docker管理API
@app.route('/api/docker/containers', methods=['GET'])
@auth_required
def list_docker_containers():
    """获取所有Docker容器列表"""
    try:
        containers = docker_manager.list_containers(all_containers=True)
        return jsonify({
            'status': 'success',
            'containers': containers
        })
    except Exception as e:
        logger.error(f"获取容器列表失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取容器列表失败: {str(e)}'
        }), 500

@app.route('/api/docker/container/<container_name>', methods=['GET'])
@auth_required
def get_docker_container_info(container_name):
    """获取指定容器的详细信息"""
    try:
        if not docker_manager.is_connected():
            return jsonify({
                'status': 'error',
                'message': 'Docker服务未连接，请检查Docker是否正常运行'
            }), 500
        
        container_info = docker_manager.get_container_info(container_name)
        if not container_info:
            return jsonify({
                'status': 'error',
                'message': f'容器 {container_name} 不存在'
            }), 404
        
        return jsonify({
            'status': 'success',
            'container': container_info
        })
    except Exception as e:
        logger.error(f"获取容器信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'获取容器信息失败: {str(e)}'
        }), 500

@app.route('/api/docker/container/<container_name>/stop', methods=['POST'])
@auth_required
def stop_container(container_name):
    """停止指定容器"""
    try:
        result = docker_manager.stop_container(container_name)
        if result['status'] == 'error':
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        logger.error(f"停止容器失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'停止容器失败: {str(e)}'
        }), 500

@app.route('/api/docker/container/<container_name>/restart', methods=['POST'])
@auth_required
def restart_container(container_name):
    """重启指定容器"""
    try:
        result = docker_manager.restart_container(container_name)
        if result['status'] == 'error':
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        logger.error(f"重启容器失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'重启容器失败: {str(e)}'
        }), 500

@app.route('/api/docker/generate-command', methods=['POST'])
@auth_required
def generate_docker_command():
    """根据配置生成Docker运行命令"""
    try:
        config = request.get_json()
        if not config:
            return jsonify({
                'status': 'error',
                'message': '请提供容器配置信息'
            }), 400
        
        command = docker_manager.generate_docker_command(config)
        if not command:
            return jsonify({
                'status': 'error',
                'message': '生成Docker命令失败'
            }), 500
        
        return jsonify({
            'status': 'success',
            'command': command
        })
    except Exception as e:
        logger.error(f"生成Docker命令失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'生成Docker命令失败: {str(e)}'
        }), 500

if __name__ == '__main__':
    logger.warning("检测到直接运行api_server.py")
    logger.warning("======================================================")
    logger.warning("警告: 不建议直接运行此文件。请使用Gunicorn启动服务器:")
    logger.warning("gunicorn -w 4 -b 0.0.0.0:5000 api_server:app")
    logger.warning("或者使用start_web.sh脚本")
    logger.warning("======================================================")
    
    # 判断是否真的想直接运行
    should_continue = input("是否仍要使用Flask开发服务器启动? (y/N): ")
    if should_continue.lower() != 'y':
        logger.error("退出程序，请使用Gunicorn启动")
        sys.exit(0)
    
    # 确保游戏目录存在
    if not os.path.exists(GAMES_DIR):
        try:
            os.makedirs(GAMES_DIR, exist_ok=True)
            logger.info(f"已创建游戏目录: {GAMES_DIR}")
            # 设置目录权限
            os.chmod(GAMES_DIR, 0o755)
            # 设置为steam用户所有
            subprocess.run(['chown', '-R', 'steam:steam', GAMES_DIR])
        except Exception as e:
            logger.error(f"创建游戏目录失败: {str(e)}")
    
    # 加载备份配置
    load_backup_config()
    start_backup_scheduler()
    
    # 加载代理配置
    try:
        from config import load_config
        config = load_config()
        proxy_config = config.get('proxy')
        if proxy_config:
            apply_proxy_config(proxy_config)
            logger.info("已加载代理配置")
    except Exception as e:
        logger.error(f"加载代理配置失败: {str(e)}")
    
    # 启动自启动功能
    auto_start_servers()
    
    # 打印当前运行的游戏服务器信息
    log_running_games()
    
    # 直接运行时使用Flask内置服务器，而不是通过Gunicorn导入时
    # 从环境变量读取端口配置，默认为5000
    port = int(os.environ.get('GUNICORN_PORT', 5000))
    logger.warning(f"使用Flask开发服务器启动 - 不推荐用于生产环境，监听端口: {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)