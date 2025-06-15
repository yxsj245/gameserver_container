#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 整合包自动安装器
支持从 Modrinth 下载整合包并自动安装到 /home/steam/games
包含 Java 版本选择和启动脚本创建功能
"""

import os
import sys
import json
import shutil
import zipfile
import requests
import subprocess
from typing import List, Dict, Optional, Tuple
from minecraft_loader_cli import MinecraftLoaderCLI, MODRINTH_API_URL


class MinecraftModpackInstaller:
    """Minecraft整合包安装器"""
    
    def __init__(self):
        self.base_install_dir = "/home/steam/games"
        self.cli = MinecraftLoaderCLI()
        
        # Java版本配置（与api_server.py保持一致）
        self.java_versions = {
            "jdk8": {
                "name": "OpenJDK 8",
                "dir": "/home/steam/environment/java/jdk8",
                "url": "https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u392-b08/OpenJDK8U-jdk_x64_linux_hotspot_8u392b08.tar.gz"
            },
            "jdk11": {
                "name": "OpenJDK 11",
                "dir": "/home/steam/environment/java/jdk11",
                "url": "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.21%2B9/OpenJDK11U-jdk_x64_linux_hotspot_11.0.21_9.tar.gz"
            },
            "jdk12": {
                "name": "OpenJDK 12",
                "dir": "/home/steam/environment/java/jdk12",
                "url": "https://github.com/adoptium/temurin12-binaries/releases/download/jdk-12.0.2%2B10/OpenJDK12U-jdk_x64_linux_hotspot_12.0.2_10.tar.gz"
            },
            "jdk17": {
                "name": "OpenJDK 17",
                "dir": "/home/steam/environment/java/jdk17",
                "url": "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.9%2B9/OpenJDK17U-jdk_x64_linux_hotspot_17.0.9_9.tar.gz"
            },
            "jdk21": {
                "name": "OpenJDK 21",
                "dir": "/home/steam/environment/java/jdk21",
                "url": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.1%2B12/OpenJDK21U-jdk_x64_linux_hotspot_21.0.1_12.tar.gz"
            },
            "jdk24": {
                "name": "OpenJDK 24",
                "dir": "/home/steam/environment/java/jdk24",
                "url": "https://github.com/adoptium/temurin24-binaries/releases/download/jdk-24%2B36/OpenJDK24U-jdk_x64_linux_hotspot_24_36.tar.gz"
            }
        }
        
        # 确保基础安装目录存在
        os.makedirs(self.base_install_dir, exist_ok=True)
    
    def get_folder_name(self) -> str:
        """获取用户输入的文件夹名称"""
        while True:
            folder_name = input("\n请输入整合包安装文件夹名称: ").strip()
            
            if not folder_name:
                print("❌ 文件夹名称不能为空")
                continue
            
            # 检查文件夹名称是否合法
            if any(char in folder_name for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']):
                print("❌ 文件夹名称包含非法字符，请重新输入")
                continue
            
            # 检查文件夹是否已存在
            install_path = os.path.join(self.base_install_dir, folder_name)
            if os.path.exists(install_path):
                choice = input(f"⚠️  文件夹 '{folder_name}' 已存在，是否覆盖? (y/n): ").strip().lower()
                if choice not in ['y', 'yes', '是']:
                    continue
                else:
                    # 删除现有文件夹
                    shutil.rmtree(install_path)
                    print(f"已删除现有文件夹: {install_path}")
            
            return folder_name
    
    def check_java_installation(self, version: str) -> Tuple[bool, Optional[str]]:
        """检查Java版本是否已安装"""
        if version not in self.java_versions:
            return False, None
        
        java_dir = self.java_versions[version]["dir"]
        java_executable = os.path.join(java_dir, "bin/java")
        
        if os.path.exists(java_executable):
            try:
                # 获取Java版本信息
                result = subprocess.run(
                    [java_executable, "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    # 从stderr中提取版本信息（Java版本信息通常在stderr中）
                    version_output = result.stderr.split('\n')[0] if result.stderr else result.stdout.split('\n')[0]
                    return True, version_output.strip()
            except Exception:
                pass
        
        return False, None
    
    def get_installed_java_versions(self) -> List[Dict]:
        """获取已安装的Java版本列表"""
        installed_versions = []
        
        for version_id, version_info in self.java_versions.items():
            installed, version_output = self.check_java_installation(version_id)
            if installed:
                installed_versions.append({
                    "id": version_id,
                    "name": version_info["name"],
                    "version": version_output,
                    "path": os.path.join(version_info["dir"], "bin/java")
                })
        
        return installed_versions
    
    def select_java_version(self, game_versions: List[str]) -> Optional[str]:
        """选择Java版本"""
        installed_versions = self.get_installed_java_versions()
        
        if not installed_versions:
            print("❌ 未检测到已安装的Java版本")
            print("请先安装Java环境，或使用系统默认Java")
            choice = input("是否使用系统默认Java? (y/n): ").strip().lower()
            if choice in ['y', 'yes', '是']:
                return "system"
            else:
                return None
        
        print("\n检测到以下已安装的Java版本:")
        print("0. 系统默认Java")
        
        for i, version in enumerate(installed_versions, 1):
            print(f"{i}. {version['name']} - {version['version']}")
        
        # 根据游戏版本推荐Java版本
        if game_versions:
            latest_version = max(game_versions, key=lambda v: [int(x) for x in v.split('.')])
            major_version = int(latest_version.split('.')[1])
            
            if major_version >= 18:
                recommended = "建议使用 Java 17 或更高版本"
            elif major_version >= 17:
                recommended = "建议使用 Java 17"
            elif major_version >= 12:
                recommended = "建议使用 Java 11 或更高版本"
            else:
                recommended = "建议使用 Java 8"
            
            print(f"\n💡 根据游戏版本 {latest_version}，{recommended}")
        
        while True:
            try:
                choice = input(f"\n请选择Java版本 (0-{len(installed_versions)}): ").strip()
                
                if choice == '0':
                    return "system"
                
                index = int(choice) - 1
                if 0 <= index < len(installed_versions):
                    return installed_versions[index]['id']
                else:
                    print(f"❌ 请输入 0 到 {len(installed_versions)} 之间的数字")
                    
            except ValueError:
                print("❌ 请输入有效的数字")
    
    def create_start_script(self, install_dir: str, jar_file: str, java_version: str, 
                          server_name: str, memory_settings: Dict = None) -> bool:
        """创建启动脚本"""
        try:
            # 确定Java可执行文件路径
            if java_version == "system":
                java_executable = "java"
            else:
                java_executable = os.path.join(self.java_versions[java_version]["dir"], "bin/java")
            
            # 默认内存设置
            if memory_settings is None:
                memory_settings = {
                    "min_memory": "1G",
                    "max_memory": "4G"
                }
            
            # 创建启动脚本内容
            script_content = f"""#!/bin/bash
# {server_name} 整合包服务器启动脚本
# 自动生成于 {self.__class__.__name__}

cd "$(dirname "$0")"

# Java 可执行文件路径
JAVA_EXECUTABLE="{java_executable}"

# 内存设置
MIN_MEMORY="{memory_settings['min_memory']}"
MAX_MEMORY="{memory_settings['max_memory']}"

# 服务器JAR文件
SERVER_JAR="{jar_file}"

# JVM参数
JVM_ARGS="-Xms$MIN_MEMORY -Xmx$MAX_MEMORY"
JVM_ARGS="$JVM_ARGS -XX:+UseG1GC"
JVM_ARGS="$JVM_ARGS -XX:+ParallelRefProcEnabled"
JVM_ARGS="$JVM_ARGS -XX:MaxGCPauseMillis=200"
JVM_ARGS="$JVM_ARGS -XX:+UnlockExperimentalVMOptions"
JVM_ARGS="$JVM_ARGS -XX:+DisableExplicitGC"
JVM_ARGS="$JVM_ARGS -XX:+AlwaysPreTouch"
JVM_ARGS="$JVM_ARGS -XX:G1NewSizePercent=30"
JVM_ARGS="$JVM_ARGS -XX:G1MaxNewSizePercent=40"
JVM_ARGS="$JVM_ARGS -XX:G1HeapRegionSize=8M"
JVM_ARGS="$JVM_ARGS -XX:G1ReservePercent=20"
JVM_ARGS="$JVM_ARGS -XX:G1HeapWastePercent=5"
JVM_ARGS="$JVM_ARGS -XX:G1MixedGCCountTarget=4"
JVM_ARGS="$JVM_ARGS -XX:InitiatingHeapOccupancyPercent=15"
JVM_ARGS="$JVM_ARGS -XX:G1MixedGCLiveThresholdPercent=90"
JVM_ARGS="$JVM_ARGS -XX:G1RSetUpdatingPauseTimePercent=5"
JVM_ARGS="$JVM_ARGS -XX:SurvivorRatio=32"
JVM_ARGS="$JVM_ARGS -XX:+PerfDisableSharedMem"
JVM_ARGS="$JVM_ARGS -XX:MaxTenuringThreshold=1"

echo "正在启动 {server_name} 服务器..."
echo "Java版本: $($JAVA_EXECUTABLE -version 2>&1 | head -n 1)"
echo "内存设置: $MIN_MEMORY - $MAX_MEMORY"
echo "服务器文件: $SERVER_JAR"
echo ""

# 检查服务器JAR文件是否存在
if [ ! -f "$SERVER_JAR" ]; then
    echo "错误: 找不到服务器JAR文件: $SERVER_JAR"
    exit 1
fi

# 检查Java是否可用
if ! command -v "$JAVA_EXECUTABLE" &> /dev/null; then
    echo "错误: Java可执行文件不存在: $JAVA_EXECUTABLE"
    exit 1
fi

# 启动服务器
exec "$JAVA_EXECUTABLE" $JVM_ARGS -jar "$SERVER_JAR" nogui
"""
            
            # 写入启动脚本
            script_path = os.path.join(install_dir, "start.sh")
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # 设置执行权限
            os.chmod(script_path, 0o755)
            
            print(f"✅ 启动脚本已创建: {script_path}")
            return True
            
        except Exception as e:
            print(f"❌ 创建启动脚本失败: {str(e)}")
            return False
    
    def create_eula_file(self, install_dir: str) -> bool:
        """创建EULA文件"""
        try:
            eula_path = os.path.join(install_dir, "eula.txt")
            with open(eula_path, 'w', encoding='utf-8') as f:
                f.write("# Minecraft EULA\n")
                f.write("# https://account.mojang.com/documents/minecraft_eula\n")
                f.write("eula=true\n")
            
            print(f"✅ EULA文件已创建: {eula_path}")
            return True
            
        except Exception as e:
            print(f"❌ 创建EULA文件失败: {str(e)}")
            return False
    
    def set_directory_permissions(self, install_dir: str) -> bool:
        """设置目录权限"""
        try:
            # 设置目录所有者为steam用户
            subprocess.run(['chown', '-R', 'steam:steam', install_dir], check=False)
            
            # 设置目录权限
            subprocess.run(['chmod', '-R', '755', install_dir], check=False)
            
            print(f"✅ 目录权限已设置: {install_dir}")
            return True
            
        except Exception as e:
            print(f"❌ 设置目录权限失败: {str(e)}")
            return False
    
    def install_modpack(self, modpack_data: Dict, version_data: Dict, 
                       folder_name: str, java_version: str, progress_callback=None) -> Dict:
        """安装整合包到指定目录"""
        install_dir = os.path.join(self.base_install_dir, folder_name)
        
        def update_progress(progress: int, message: str, status: str = 'installing'):
            """更新进度"""
            if progress_callback:
                progress_callback({
                    'progress': progress,
                    'message': message,
                    'status': status
                })
            else:
                print(f"[{progress}%] {message}")
        
        try:
            update_progress(0, f"开始安装整合包到: {install_dir}")
            
            # 创建安装目录
            os.makedirs(install_dir, exist_ok=True)
            update_progress(5, "安装目录已创建")
            
            # 下载并解析整合包
            update_progress(10, "正在下载整合包文件...")
            index_data = self.cli.download_and_extract_mrpack(version_data['id'], install_dir)
            
            if not index_data:
                return {
                    'success': False,
                    'message': '下载或解析整合包失败'
                }
            
            update_progress(30, "整合包文件下载完成")
            
            # 下载整合包中的所有文件
            update_progress(35, "正在下载整合包内容...")
            download_success = self.cli.download_modpack_files(index_data, install_dir, 
                lambda p, msg: update_progress(35 + int(p * 0.4), f"下载: {msg}"))
            
            if not download_success:
                return {
                    'success': False,
                    'message': '下载整合包文件失败'
                }
            
            update_progress(75, "整合包内容下载完成")
            
            # 处理覆盖文件
            update_progress(80, "正在处理配置文件...")
            self.cli.process_modpack_overrides(install_dir)
            
            # 直接下载服务器核心文件
            update_progress(85, "正在下载服务器核心文件...")
            game_versions = version_data.get('game_versions', [])
            server_jar = None
            
            if game_versions:
                minecraft_version = game_versions[0]  # 使用第一个支持的版本
                
                # 检查整合包依赖，确定加载器类型
                dependencies = index_data.get('dependencies', {})
                loader_type = None
                loader_version = None
                
                if 'fabric-loader' in dependencies:
                    loader_type = 'fabric'
                    loader_version = dependencies['fabric-loader']
                elif 'quilt-loader' in dependencies:
                    loader_type = 'quilt'
                    loader_version = dependencies['quilt-loader']
                elif 'forge' in dependencies:
                    loader_type = 'forge'
                    loader_version = dependencies['forge']
                elif 'neoforge' in dependencies:
                    loader_type = 'neoforge'
                    loader_version = dependencies['neoforge']
                
                if loader_type and loader_version:
                    # 下载对应的加载器JAR文件
                    print(f"正在下载 {loader_type} 服务器核心 (MC版本: {minecraft_version}, 加载器版本: {loader_version})")
                    download_result = self.cli.download_loader_jar(loader_type, minecraft_version, loader_version)
                    if download_result:
                        # 复制到安装目录根目录
                        server_jar_name = f"{loader_type}-server-{minecraft_version}-{loader_version}.jar"
                        server_jar_path = os.path.join(install_dir, server_jar_name)
                        shutil.copy2(download_result["file_path"], server_jar_path)
                        server_jar = server_jar_path
                        print(f"✅ 已下载 {loader_type} 服务器核心: {server_jar_name}")
                        update_progress(87, f"已下载 {loader_type} 服务器核心")
                    else:
                        print(f"❌ 下载 {loader_type} 服务器核心失败")
                
                if not server_jar:
                    # 如果没有加载器，直接下载原版服务器
                    print(f"正在下载原版Minecraft服务器 (版本: {minecraft_version})")
                    update_progress(88, "正在下载原版Minecraft服务器...")
                    try:
                        from MCdownloads import download_file
                        server_jar_name = f"minecraft-server-{minecraft_version}.jar"
                        server_jar_path = os.path.join(install_dir, server_jar_name)
                        
                        # 这里需要实现原版服务器下载逻辑
                        # 暂时创建一个提示文件
                        info_file_path = server_jar_path.replace('.jar', '_download_info.txt')
                        with open(info_file_path, 'w', encoding='utf-8') as f:
                            f.write(f"请手动下载 Minecraft {minecraft_version} 服务器JAR文件\n")
                            f.write(f"下载地址: https://www.minecraft.net/en-us/download/server\n")
                            f.write(f"将文件重命名为: {server_jar_name}\n")
                            f.write(f"并放置在: {install_dir}\n")
                        print(f"⚠️  已创建下载提示文件: {os.path.basename(info_file_path)}")
                        server_jar = info_file_path  # 设置为提示文件路径，表示已处理
                    except Exception as e:
                        print(f"❌ 创建提示文件失败: {str(e)}")
            
            if not server_jar:
                return {
                    'success': False,
                    'message': f'下载服务器核心文件失败。支持的游戏版本: {", ".join(game_versions) if game_versions else "未知"}'
                }
            
            # 如果下载的是提示文件，需要重新查找实际的JAR文件
            if server_jar.endswith('_download_info.txt'):
                actual_server_jar = self.find_server_jar(install_dir)
                if actual_server_jar:
                    server_jar = actual_server_jar
                else:
                    # 使用预期的JAR文件名
                    server_jar = server_jar.replace('_download_info.txt', '.jar')
            
            # 获取游戏版本信息
            game_versions = version_data.get('game_versions', [])
            
            # 创建启动脚本
            update_progress(90, "正在创建启动脚本...")
            script_success = self.create_start_script(
                install_dir, 
                os.path.basename(server_jar),
                java_version,
                modpack_data['title']
            )
            
            if not script_success:
                update_progress(90, "启动脚本创建失败，但整合包安装成功")
            
            # 创建EULA文件
            update_progress(95, "正在创建EULA文件...")
            self.create_eula_file(install_dir)
            
            # 将files文件夹内容移动到根目录
            update_progress(92, "正在整理文件结构...")
            files_dir = os.path.join(install_dir, "files")
            if os.path.exists(files_dir):
                print("正在将files文件夹内容移动到根目录...")
                # 移动files文件夹中的所有内容到根目录
                for item in os.listdir(files_dir):
                    src_path = os.path.join(files_dir, item)
                    dst_path = os.path.join(install_dir, item)
                    
                    # 如果目标已存在，先删除
                    if os.path.exists(dst_path):
                        if os.path.isdir(dst_path):
                            shutil.rmtree(dst_path)
                        else:
                            os.remove(dst_path)
                    
                    # 移动文件或文件夹
                    shutil.move(src_path, dst_path)
                    print(f"已移动: {item}")
                
                # 删除空的files文件夹
                if os.path.exists(files_dir) and not os.listdir(files_dir):
                    os.rmdir(files_dir)
                    print("已删除空的files文件夹")
                
                # 更新server_jar路径
                if server_jar and "files" in server_jar:
                    server_jar = server_jar.replace(os.path.join(install_dir, "files"), install_dir)
                    server_jar = server_jar.replace("files/", "")
                    server_jar = server_jar.replace("files\\", "")
            
            # 设置目录权限
            update_progress(97, "正在设置目录权限...")
            self.set_directory_permissions(install_dir)
            
            # 清理临时文件
            update_progress(99, "正在清理临时文件...")
            temp_dir = os.path.join(install_dir, "temp")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            
            mrpack_dir = os.path.join(install_dir, "mrpack")
            if os.path.exists(mrpack_dir):
                shutil.rmtree(mrpack_dir)
            
            update_progress(100, "整合包安装完成!", "completed")
            
            return {
                'success': True,
                'message': '整合包安装成功',
                'data': {
                    'install_dir': install_dir,
                    'server_jar': os.path.basename(server_jar),
                    'java_version': java_version,
                    'start_script': 'start.sh',
                    'modpack_name': modpack_data['title'],
                    'modpack_version': version_data['version_number'],
                    'game_versions': game_versions
                }
            }
            
        except Exception as e:
            print(f"❌ 安装整合包失败: {str(e)}")
            return {
                'success': False,
                'message': f'安装失败: {str(e)}'
            }
    
    def find_server_jar(self, install_dir: str) -> Optional[str]:
        """查找服务器JAR文件"""
        # 常见的服务器JAR文件名模式
        server_patterns = [
            'server.jar',
            'minecraft_server.jar',
            'minecraft-server',
            'forge-',
            'fabric-',
            'quilt-',
            'neoforge-'
        ]
        
        # 首先在根目录查找
        print(f"正在根目录查找服务器JAR文件: {install_dir}")
        for file in os.listdir(install_dir):
            if file.endswith('.jar'):
                file_lower = file.lower()
                if any(pattern in file_lower for pattern in server_patterns):
                    jar_path = os.path.join(install_dir, file)
                    print(f"✅ 在根目录找到服务器JAR: {file}")
                    return jar_path
        
        # 然后在files目录查找（如果存在）
        files_dir = os.path.join(install_dir, "files")
        if os.path.exists(files_dir):
            print(f"正在files目录查找服务器JAR文件: {files_dir}")
            for root, dirs, files in os.walk(files_dir):
                for file in files:
                    if file.endswith('.jar'):
                        file_lower = file.lower()
                        if any(pattern in file_lower for pattern in server_patterns):
                            jar_path = os.path.join(root, file)
                            print(f"✅ 在files目录找到服务器JAR: {file}")
                            return jar_path
        
        # 如果没找到特定的服务器JAR，返回根目录第一个JAR文件
        for file in os.listdir(install_dir):
            if file.endswith('.jar'):
                jar_path = os.path.join(install_dir, file)
                print(f"✅ 找到JAR文件: {file}")
                return jar_path
        
        # 最后在files目录找任意JAR文件
        if os.path.exists(files_dir):
            for root, dirs, files in os.walk(files_dir):
                for file in files:
                    if file.endswith('.jar'):
                        jar_path = os.path.join(root, file)
                        print(f"✅ 在files目录找到JAR文件: {file}")
                        return jar_path
        
        print("❌ 未找到任何JAR文件")
        return None
    
    def run_interactive_install(self):
        """运行交互式安装流程"""
        try:
            print("=" * 60)
            print("    Minecraft 整合包自动安装器")
            print("    支持从 Modrinth 下载并自动安装")
            print("=" * 60)
            
            # 步骤1: 搜索整合包
            query = input("\n请输入要搜索的整合包名称 (留空显示热门整合包): ").strip()
            
            print(f"\n🔍 搜索整合包...")
            modpacks = self.cli.search_modpacks(query, max_results=50)
            
            if not modpacks:
                print("❌ 未找到整合包")
                return
            
            # 步骤2: 选择整合包
            selected_modpack = self.cli.select_modpack(modpacks)
            if not selected_modpack:
                print("👋 已取消操作")
                return
            
            print(f"\n✅ 已选择整合包: {selected_modpack['title']}")
            
            # 步骤3: 获取整合包版本
            versions = self.cli.get_modpack_versions(selected_modpack['id'])
            if not versions:
                print("❌ 获取整合包版本失败")
                return
            
            # 步骤4: 选择版本
            selected_version = self.cli.select_modpack_version(versions)
            if not selected_version:
                print("👋 已取消操作")
                return
            
            print(f"✅ 已选择版本: {selected_version['name']} ({selected_version['version_number']})")
            
            # 步骤5: 获取文件夹名称
            folder_name = self.get_folder_name()
            print(f"✅ 安装文件夹: {folder_name}")
            
            # 步骤6: 选择Java版本
            game_versions = selected_version.get('game_versions', [])
            java_version = self.select_java_version(game_versions)
            if not java_version:
                print("👋 已取消操作")
                return
            
            java_name = self.java_versions.get(java_version, {}).get('name', '系统默认Java')
            print(f"✅ 已选择Java版本: {java_name}")
            
            # 步骤7: 确认安装
            print(f"\n📋 安装信息确认:")
            print(f"   整合包: {selected_modpack['title']}")
            print(f"   版本: {selected_version['name']} ({selected_version['version_number']})")
            print(f"   游戏版本: {', '.join(game_versions)}")
            print(f"   安装目录: {os.path.join(self.base_install_dir, folder_name)}")
            print(f"   Java版本: {java_name}")
            
            confirm = input("\n确认安装? (y/n): ").strip().lower()
            if confirm not in ['y', 'yes', '是']:
                print("👋 已取消安装")
                return
            
            # 步骤8: 执行安装
            result = self.install_modpack(
                selected_modpack,
                selected_version,
                folder_name,
                java_version
            )
            
            if result['success']:
                print(f"\n🎉 安装成功!")
                print(f"\n📝 使用说明:")
                print(f"   1. 进入安装目录: cd {result['data']['install_dir']}")
                print(f"   2. 运行启动脚本: ./start.sh")
                print(f"   3. 首次启动可能需要较长时间来生成世界")
                print(f"   4. 服务器启动后可通过 localhost:25565 连接")
            else:
                print(f"\n❌ 安装失败: {result['message']}")
                
        except KeyboardInterrupt:
            print("\n\n👋 用户中断操作")
        except Exception as e:
            print(f"\n❌ 程序运行出错: {str(e)}")


def main():
    """主函数"""
    installer = MinecraftModpackInstaller()
    installer.run_interactive_install()


if __name__ == "__main__":
    main()