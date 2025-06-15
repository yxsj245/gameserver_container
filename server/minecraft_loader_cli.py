#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 加载器下载命令行工具
支持 Fabric、Forge 和 Quilt 的交互式下载
支持整合包选择和一键打包功能
"""

import os
import sys
import re
import json
import shutil
import tempfile
import zipfile
import datetime
import requests
import threading
import concurrent.futures
import time
from typing import List, Dict, Optional, Tuple, Any
from minecraft_loader_api import MinecraftLoaderAPI, LoaderType


# Modrinth API常量
MODRINTH_API_URL = "https://api.modrinth.com/v2"
MODRINTH_BASE_URL = "https://modrinth.com/modpack"


class DownloadStatus:
    """下载状态追踪类"""
    def __init__(self):
        self.total = 0
        self.completed = 0
        self.success = 0
        self.failed = 0
        self.current_file = ""
        self.current_progress = 0
        self.lock = threading.Lock()
    
    def update(self, success=False, progress=100):
        """更新下载状态"""
        with self.lock:
            self.completed += 1
            if success:
                self.success += 1
            else:
                self.failed += 1
            self.current_progress = progress
    
    def set_current_file(self, filename):
        """设置当前下载文件名"""
        with self.lock:
            self.current_file = filename
    
    def get_progress(self):
        """获取当前进度"""
        with self.lock:
            if self.total == 0:
                return 0
            return (self.completed / self.total) * 100


class DownloadManager:
    """多线程下载管理器"""
    def __init__(self, max_workers=5):
        self.max_workers = max_workers
        self.status = DownloadStatus()
        self.stop_event = threading.Event()
        
        # 创建共享的 Session 以复用连接
        self.session = requests.Session()
        
        # 配置连接池适配器
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=max_workers,
            pool_maxsize=max_workers * 2,
            max_retries=requests.adapters.Retry(
                total=3,
                backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504]
            )
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # 设置默认超时
        self.session.timeout = 30
    
    def download_file(self, url, save_path, headers=None):
        """下载单个文件"""
        try:
            if headers is None:
                headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
            
            # 获取文件名
            filename = os.path.basename(save_path)
            self.status.set_current_file(filename)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # 使用共享的 session 发送请求
            response = self.session.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 下载文件
            with open(save_path, 'wb') as f:
                if total_size > 0:
                    downloaded = 0
                    # 使用更大的chunk_size提高效率
                    for chunk in response.iter_content(chunk_size=32768):
                        if self.stop_event.is_set():
                            response.close()
                            return False
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress = (downloaded / total_size) * 100
                            self.status.current_progress = progress
                else:
                    # 如果没有文件大小信息，直接写入
                    for chunk in response.iter_content(chunk_size=32768):
                        if self.stop_event.is_set():
                            response.close()
                            return False
                        if chunk:
                            f.write(chunk)
            
            response.close()
            self.status.update(success=True)
            return True
            
        except Exception as e:
            print(f"下载失败 {url}: {str(e)}")
            self.status.update(success=False)
            return False
    
    def download_files(self, files):
        """并行下载多个文件
        
        Args:
            files: [(url, save_path, headers), ...]
        """
        # 初始化状态
        self.status.total = len(files)
        self.status.completed = 0
        self.status.success = 0
        self.status.failed = 0
        
        # 启动进度显示线程
        progress_thread = threading.Thread(target=self._display_progress)
        progress_thread.daemon = True
        progress_thread.start()
        
        # 使用线程池并行下载
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for file_info in files:
                url, save_path = file_info[0], file_info[1]
                headers = file_info[2] if len(file_info) > 2 else None
                future = executor.submit(self.download_file, url, save_path, headers)
                futures.append(future)
            
            # 等待所有任务完成
            for future in concurrent.futures.as_completed(futures):
                pass
        
        # 停止进度显示
        self.stop_event.set()
        progress_thread.join()
        
        # 清屏并显示最终结果
        print(f"\n\n✅ 下载完成: 成功 {self.status.success}/{self.status.total}, 失败 {self.status.failed}")
        return self.status.failed == 0
    
    def close(self):
        """关闭下载管理器，清理资源"""
        if hasattr(self, 'session'):
            self.session.close()
        self.stop_event.set()
    
    def _display_progress(self):
        """显示下载进度"""
        while not self.stop_event.is_set():
            with self.status.lock:
                total = self.status.total
                completed = self.status.completed
                success = self.status.success
                failed = self.status.failed
                current_file = self.status.current_file
                progress = self.status.current_progress
            
            # 计算总体进度
            overall_progress = (completed / total) * 100 if total > 0 else 0
            
            # 构造进度条
            bar_length = 30
            filled_length = int(bar_length * overall_progress / 100)
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            # 显示进度
            sys.stdout.write(f"\r进度: [{bar}] {overall_progress:.1f}% | 完成: {completed}/{total} | 成功: {success} | 失败: {failed} | 当前: {current_file} ({progress:.1f}%)")
            sys.stdout.flush()
            
            time.sleep(0.1)
        
        # 清空最后一行
        sys.stdout.write('\r' + ' ' * 100 + '\r')
        sys.stdout.flush()


class MinecraftLoaderCLI:
    """Minecraft加载器命令行界面"""
    
    def __init__(self):
        self.api = MinecraftLoaderAPI()
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        self.modpack_dir = os.path.join(os.getcwd(), "modpacks")
        self.download_manager = DownloadManager(max_workers=6)  # 创建下载管理器，最多6个线程
        
        # 确保下载目录存在
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.modpack_dir, exist_ok=True)
    
    def __del__(self):
        """析构函数，清理资源"""
        if hasattr(self, 'download_manager'):
            self.download_manager.close()
        
    def print_banner(self):
        """打印程序横幅"""
        print("=" * 60)
        print("    Minecraft 加载器下载工具")
        print("    支持 Fabric、Forge 和 Quilt")
        print("    支持整合包选择和一键打包")
        print("=" * 60)
        print()
    
    def print_separator(self):
        """打印分隔线"""
        print("-" * 50)
    
    def validate_minecraft_version(self, version: str) -> bool:
        """验证Minecraft版本格式"""
        # 匹配格式如: 1.20.1, 1.19, 1.18.2 等
        pattern = r'^\d+\.\d+(\.\d+)?$'
        return bool(re.match(pattern, version))
    
    def get_minecraft_version(self) -> str:
        """获取用户输入的Minecraft版本"""
        while True:
            print("请输入Minecraft游戏版本号:")
            print("示例: 1.20.1, 1.19.4, 1.18.2")
            version = input("游戏版本: ").strip()
            
            if not version:
                print("❌ 版本号不能为空，请重新输入")
                continue
                
            if not self.validate_minecraft_version(version):
                print("❌ 版本号格式不正确，请输入正确的版本号 (如: 1.20.1)")
                continue
                
            return version
    
    def select_loader_type(self) -> str:
        """选择加载器类型"""
        loaders = {
            "1": "fabric",
            "2": "forge", 
            "3": "quilt"
        }
        
        while True:
            print("\n请选择加载器类型:")
            print("1. Fabric")
            print("2. Forge")
            print("3. Quilt")
            
            choice = input("请输入选项 (1-3): ").strip()
            
            if choice in loaders:
                return loaders[choice]
            else:
                print("❌ 无效选择，请输入 1、2 或 3")
    
    def display_compatible_versions(self, versions: List[Dict], loader_type: str) -> None:
        """显示兼容的加载器版本"""
        if not versions:
            print(f"❌ 未找到兼容的 {loader_type.title()} 版本")
            return
            
        print(f"\n找到 {len(versions)} 个兼容的 {loader_type.title()} 稳定版本:")
        self.print_separator()
        
        for i, version in enumerate(versions, 1):
            stable_text = "✅ 稳定版" if version.get("stable", False) else "⚠️  测试版"
            build_text = f" (构建 {version['build']})" if version.get("build") else ""
            print(f"{i:2d}. {version['version']}{build_text} - {stable_text}")
    
    def select_loader_version(self, versions: List[Dict]) -> Optional[Dict]:
        """选择加载器版本"""
        if not versions:
            return None
            
        while True:
            try:
                choice = input(f"\n请选择版本 (1-{len(versions)}) 或输入 'q' 退出: ").strip()
                
                if choice.lower() == 'q':
                    return None
                    
                index = int(choice) - 1
                if 0 <= index < len(versions):
                    return versions[index]
                else:
                    print(f"❌ 请输入 1 到 {len(versions)} 之间的数字")
                    
            except ValueError:
                print("❌ 请输入有效的数字")
    
    def confirm_download(self, loader_type: str, loader_version: str, game_version: str, modpack_name: str = None) -> bool:
        """确认下载"""
        print(f"\n📋 下载信息确认:")
        print(f"   加载器类型: {loader_type.title()}")
        print(f"   加载器版本: {loader_version}")
        print(f"   游戏版本: {game_version}")
        if modpack_name:
            print(f"   整合包: {modpack_name}")
        print(f"   保存目录: {self.download_dir}")
        
        while True:
            confirm = input("\n确认下载? (y/n): ").strip().lower()
            if confirm in ['y', 'yes', '是']:
                return True
            elif confirm in ['n', 'no', '否']:
                return False
            else:
                print("请输入 y 或 n")
    
    def download_loader_jar(self, loader_type: str, game_version: str, loader_version: str) -> Dict:
        """下载加载器JAR文件"""
        print(f"\n🔄 正在下载 {loader_type.title()} 加载器JAR文件...")
        
        try:
            if loader_type == "forge":
                # Forge需要指定MC版本
                result = self.api.download_loader(
                    loader_type, 
                    self.download_dir,
                    loader_version=loader_version,
                    mc_version=game_version
                )
            else:
                # Fabric和Quilt
                result = self.api.download_loader(
                    loader_type,
                    self.download_dir,
                    loader_version=loader_version
                )
            
            if result["success"]:
                data = result["data"]
                file_size_mb = data["file_size"] / (1024 * 1024)
                
                print("✅ 下载成功!")
                print(f"   文件名: {data['filename']}")
                print(f"   文件大小: {file_size_mb:.2f} MB")
                print(f"   保存路径: {data['file_path']}")
                return result["data"]
            else:
                print(f"❌ 下载失败: {result['message']}")
                return {}
                
        except Exception as e:
            print(f"❌ 下载过程中发生错误: {str(e)}")
            return {}
            
    # 整合包相关函数
    def search_modpacks(self, query="", game_versions=None, loaders=None, max_results=300) -> List[Dict]:
        """搜索Modrinth上的整合包"""
        print(f"\n🔍 搜索整合包: {query}")
        
        facets = [["project_type:modpack"]]
        
        # 添加游戏版本过滤
        if game_versions:
            if isinstance(game_versions, str):
                game_versions = [game_versions]
            versions_facet = [f"versions:{v}" for v in game_versions]
            facets.append(versions_facet)
        
        # 添加加载器过滤
        if loaders:
            if isinstance(loaders, str):
                loaders = [loaders]
            loaders_facet = [f"categories:{l}" for l in loaders]
            facets.append(loaders_facet)
        
        # 准备API参数
        payload = {
            "query": query,
            "facets": json.dumps(facets),
            "limit": max_results,
            "index": "relevance"
        }
        
        # 发送请求
        headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
        try:
            response = requests.get(f"{MODRINTH_API_URL}/search", params=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            # 验证响应数据格式
            if not isinstance(data, dict):
                print(f"❌ API响应格式错误: 期望字典，收到 {type(data)}")
                return []
            
            if 'hits' not in data:
                print(f"❌ API响应中缺少 'hits' 字段")
                return []
            
            hits = data['hits']
            if not isinstance(hits, list):
                print(f"❌ API响应中 'hits' 字段格式错误: 期望列表，收到 {type(hits)}")
                return []
            
            print(f"✅ 找到 {len(hits)} 个整合包")
            
            # 将 project_id 映射为 id 字段，以匹配前端期望的数据结构
            for hit in hits:
                if 'project_id' in hit:
                    hit['id'] = hit['project_id']
            
            return hits
            
        except requests.exceptions.RequestException as e:
            print(f"❌ 网络请求失败: {str(e)}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {str(e)}")
            return []
        except Exception as e:
            print(f"❌ 搜索整合包失败: {str(e)}")
            return []
    
    def display_modpacks(self, modpacks: List[Dict], page: int = 1, items_per_page: int = 10) -> int:
        """显示搜索到的整合包列表
        
        Args:
            modpacks: 整合包列表
            page: 当前页码（从1开始）
            items_per_page: 每页显示的数量
        
        Returns:
            总页数
        """
        if not modpacks:
            print("❌ 未找到整合包")
            return 0
        
        # 计算总页数
        total_pages = (len(modpacks) + items_per_page - 1) // items_per_page
        
        # 调整页码范围
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # 计算当前页显示的整合包范围
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, len(modpacks))
        
        print(f"\n找到以下整合包 (第 {page}/{total_pages} 页):")
        self.print_separator()
        
        for i, modpack in enumerate(modpacks[start_idx:end_idx], start_idx + 1):
            print(f"{i:2d}. {modpack['title']}")
            if 'description' in modpack:
                description = modpack['description'].strip()
                if len(description) > 60:
                    description = description[:57] + "..."
                print(f"    描述: {description}")
            
            # 显示支持的游戏版本
            versions = modpack.get('versions', [])
            if versions:
                print(f"    游戏版本: {', '.join(versions[:5])}")
                if len(versions) > 5:
                    print(f"              ...等 {len(versions)} 个版本")
            
            # 显示加载器类型
            categories = modpack.get('categories', [])
            loaders = [cat for cat in categories if cat in ['fabric', 'forge', 'quilt']]
            if loaders:
                print(f"    加载器类型: {', '.join(loaders)}")
            
            # 显示下载量
            downloads = modpack.get('downloads', 0)
            print(f"    下载量: {downloads:,}")
            
            print()
            
        # 显示分页提示
        print("\n导航:")
        if page > 1:
            print("  [p] - 上一页")
        if page < total_pages:
            print("  [n] - 下一页")
        print("  [q] - 退出搜索")
        
        return total_pages
    
    def select_modpack(self, modpacks: List[Dict]) -> Optional[Dict]:
        """用户选择整合包（支持分页）"""
        if not modpacks:
            return None
        
        current_page = 1
        items_per_page = 10  # 每页显示10个整合包
        
        while True:
            # 显示当前页的整合包
            total_pages = self.display_modpacks(modpacks, current_page, items_per_page)
            
            # 获取用户输入
            prompt = f"\n请选择整合包 (1-{len(modpacks)})，或输入 [p/n/q] 进行翻页/退出: "
            choice = input(prompt).strip().lower()
            
            # 处理导航命令
            if choice == 'q':
                return None
            elif choice == 'n' and current_page < total_pages:
                current_page += 1
                continue
            elif choice == 'p' and current_page > 1:
                current_page -= 1
                continue
            
            # 处理选择整合包
            try:
                index = int(choice) - 1
                if 0 <= index < len(modpacks):
                    return modpacks[index]
                else:
                    print(f"❌ 请输入 1 到 {len(modpacks)} 之间的数字")
            except ValueError:
                if choice not in ['p', 'n', 'q']:
                    print("❌ 请输入有效的数字或 p (上一页), n (下一页), q (退出)")
    
    def get_modpack_details(self, modpack_id: str) -> Dict:
        """获取整合包详细信息"""
        print(f"\n🔍 获取整合包详情...")
        
        headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
        try:
            response = requests.get(f"{MODRINTH_API_URL}/project/{modpack_id}", headers=headers)
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            print(f"❌ 获取整合包详情失败: {str(e)}")
            return {}
    
    def get_modpack_versions(self, modpack_id: str) -> List[Dict]:
        """获取整合包版本信息"""
        print(f"\n🔍 获取整合包版本信息...")
        
        headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
        try:
            response = requests.get(f"{MODRINTH_API_URL}/project/{modpack_id}/version", headers=headers)
            response.raise_for_status()
            versions = response.json()
            print(f"✅ 找到 {len(versions)} 个版本")
            return versions
            
        except Exception as e:
            print(f"❌ 获取整合包版本失败: {str(e)}")
            return []
    
    def display_modpack_versions(self, versions: List[Dict], page: int = 1, items_per_page: int = 10) -> int:
        """显示整合包版本列表
        
        Args:
            versions: 版本列表
            page: 当前页码（从1开始）
            items_per_page: 每页显示的数量
        
        Returns:
            总页数
        """
        if not versions:
            print("❌ 未找到版本信息")
            return 0
        
        # 计算总页数
        total_pages = (len(versions) + items_per_page - 1) // items_per_page
        
        # 调整页码范围
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        
        # 计算当前页显示的版本范围
        start_idx = (page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, len(versions))
            
        print(f"\n整合包版本 (第 {page}/{total_pages} 页):")
        self.print_separator()
        
        for i, version in enumerate(versions[start_idx:end_idx], start_idx + 1):
            status = "✅ 发行版" if version.get("version_type") == "release" else "⚠️ 测试版"
            game_versions = ", ".join(version.get("game_versions", []))
            loaders = ", ".join(version.get("loaders", []))
            print(f"{i:2d}. {version['name']} - {version['version_number']} {status}")
            print(f"    游戏版本: {game_versions}")
            print(f"    加载器: {loaders}")
            if 'date_published' in version:
                print(f"    发布日期: {version['date_published'].split('T')[0]}")
            print()
        
        # 显示分页提示
        if total_pages > 1:
            print("\n导航:")
            if page > 1:
                print("  [p] - 上一页")
            if page < total_pages:
                print("  [n] - 下一页")
            print("  [q] - 返回")
        
        return total_pages
    
    def select_modpack_version(self, versions: List[Dict]) -> Optional[Dict]:
        """选择整合包版本（支持分页）"""
        if not versions:
            return None
            
        # 默认选择第一个版本（最新版本）
        latest_version = versions[0]
        print(f"\n默认选择最新版本: {latest_version['name']} ({latest_version['version_number']})")
        
        choice = input("使用此版本? (y/n): ").strip().lower()
        if choice in ['y', 'yes', '是']:
            return latest_version
            
        # 如果用户不使用最新版，显示所有版本让用户选择
        current_page = 1
        items_per_page = 10  # 每页显示10个版本
        
        while True:
            # 显示当前页的版本
            total_pages = self.display_modpack_versions(versions, current_page, items_per_page)
            
            # 获取用户输入
            prompt = f"\n请选择版本 (1-{len(versions)})，或输入 [p/n/q] 进行翻页/退出: "
            choice = input(prompt).strip().lower()
            
            # 处理导航命令
            if choice == 'q':
                return None
            elif choice == 'n' and current_page < total_pages:
                current_page += 1
                continue
            elif choice == 'p' and current_page > 1:
                current_page -= 1
                continue
            
            # 处理选择版本
            try:
                index = int(choice) - 1
                if 0 <= index < len(versions):
                    return versions[index]
                else:
                    print(f"❌ 请输入 1 到 {len(versions)} 之间的数字")
                    
            except ValueError:
                if choice not in ['p', 'n', 'q']:
                    print("❌ 请输入有效的数字或 p (上一页), n (下一页), q (退出)")
    
    def create_modpack_zip(self, modpack_name: str, loader_jar_path: str, modpack_version: Dict) -> bool:
        """将加载器JAR和整合包信息打包为zip"""
        try:
            # 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix="mc_modpack_")
            
            # 设置最终zip路径
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            sanitized_name = re.sub(r'[^\w\-\. ]', '_', modpack_name)
            zip_filename = f"{sanitized_name}_{timestamp}.zip"
            zip_path = os.path.join(self.modpack_dir, zip_filename)
            
            # 复制加载器JAR到临时目录
            loader_jar_filename = os.path.basename(loader_jar_path)
            temp_jar_path = os.path.join(temp_dir, loader_jar_filename)
            shutil.copy2(loader_jar_path, temp_jar_path)
            
            # 创建modpack.json文件，包含整合包信息
            modpack_info = {
                "name": modpack_name,
                "version": modpack_version.get("version_number", "1.0"),
                "game_versions": modpack_version.get("game_versions", []),
                "loaders": modpack_version.get("loaders", []),
                "download_url": f"{MODRINTH_BASE_URL}/{modpack_version.get('project_id', '')}",
                "created_at": datetime.datetime.now().isoformat(),
            }
            
            with open(os.path.join(temp_dir, "modpack.json"), "w", encoding="utf-8") as f:
                json.dump(modpack_info, f, indent=2, ensure_ascii=False)
            
            # 创建README.txt，使用UTF-8 with BOM编码以防止中文乱码
            with open(os.path.join(temp_dir, "README.txt"), "wb") as f:
                content = f"Minecraft整合包: {modpack_name}\n"
                content += f"版本: {modpack_version.get('version_number', '1.0')}\n"
                content += f"游戏版本: {', '.join(modpack_version.get('game_versions', []))}\n"
                content += f"加载器: {', '.join(modpack_version.get('loaders', []))}\n\n"
                content += f"下载地址: {MODRINTH_BASE_URL}/{modpack_version.get('project_id', '')}\n\n"
                content += "使用说明:\n"
                content += "1. 解压此ZIP文件\n"
                content += "2. 运行加载器JAR文件安装Minecraft和对应加载器\n"
                content += "3. 前往整合包下载地址下载完整整合包内容\n"
                # 添加BOM头以正确显示中文
                f.write(b'\xef\xbb\xbf' + content.encode('utf-8'))
            
            # 创建ZIP文件
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)
            
            # 清理临时目录
            shutil.rmtree(temp_dir)
            
            print(f"\n✅ 整合包已创建: {zip_path}")
            return True
            
        except Exception as e:
            print(f"❌ 创建整合包失败: {str(e)}")
            return False
    
    def modpack_workflow(self):
        """整合包工作流程"""
        print("\n=== 整合包下载模式 ===\n")
        
        # 步骤1: 搜索整合包
        query = input("请输入要搜索的整合包名称 (留空显示热门整合包): ").strip()
        
        modpacks = self.search_modpacks(query)
        if not modpacks:
            print("❌ 未找到整合包，请尝试其他关键词")
            return
        
        # 步骤2: 选择整合包（内部已包含分页显示）
        selected_modpack = self.select_modpack(modpacks)
        
        if not selected_modpack:
            print("👋 已取消操作")
            return
        
        print(f"\n✅ 已选择整合包: {selected_modpack['title']}")
        
        # 步骤3: 获取整合包详情和版本列表
        modpack_details = self.get_modpack_details(selected_modpack["project_id"])
        modpack_versions = self.get_modpack_versions(selected_modpack["project_id"])
        
        if not modpack_versions:
            print("❌ 未找到此整合包的版本信息")
            return
        
        # 步骤4: 选择整合包版本
        selected_version = self.select_modpack_version(modpack_versions)
        
        if not selected_version:
            print("👋 已取消操作")
            return
        
        # 步骤5: 从整合包版本中获取游戏版本和加载器类型
        game_versions = selected_version.get("game_versions", [])
        loaders = selected_version.get("loaders", [])
        
        if not game_versions or not loaders:
            print("❌ 整合包版本信息不完整，缺少游戏版本或加载器信息")
            return
        
        # 使用整合包的第一个游戏版本和加载器
        game_version = game_versions[0]
        loader_type = loaders[0]
        
        print(f"\n✅ 游戏版本: {game_version}")
        print(f"✅ 加载器类型: {loader_type.title()}")
        
        # 步骤6: 获取与游戏版本兼容的加载器版本
        print(f"\n🔍 正在查找与 Minecraft {game_version} 兼容的 {loader_type.title()} 版本...")
        
        result = self.api.get_compatible_loader_versions(
            loader_type, 
            game_version, 
            stable_only=True,  # 只显示稳定版本
            limit=20  # 限制显示20个版本
        )
        
        if not result["success"]:
            print(f"❌ 获取版本信息失败: {result['message']}")
            return
        
        compatible_versions = result["data"]["compatible_versions"]
        
        # 步骤7: 显示并选择加载器版本
        self.display_compatible_versions(compatible_versions, loader_type)
        
        if not compatible_versions:
            print(f"\n💡 建议:")
            print(f"   1. 检查游戏版本 {game_version} 是否正确")
            print(f"   2. 尝试其他加载器类型")
            print(f"   3. 查看 {loader_type.title()} 官网了解支持的版本")
            return
        
        selected_loader_version = self.select_loader_version(compatible_versions)
        
        if not selected_loader_version:
            print("👋 已取消操作")
            return
        
        # 步骤8: 确认并下载
        if self.confirm_download(loader_type, selected_loader_version["version"], game_version, selected_modpack["title"]):
            download_result = self.download_loader_jar(loader_type, game_version, selected_loader_version["version"])
            
            if download_result:
                print(f"\n🎉 {loader_type.title()} 加载器JAR文件下载完成!")
                
                # 步骤9: 询问是否下载整个整合包
                choice = input("\n是否下载整个整合包（包括所有模组和配置）? (y/n): ").strip().lower()
                if choice in ['y', 'yes', '是']:
                    # 创建输出目录
                    output_dir = os.path.join(self.modpack_dir, re.sub(r'[^\w\-\. ]', '_', selected_modpack["title"]))
                    os.makedirs(output_dir, exist_ok=True)
                    
                    # 复制加载器JAR到输出目录
                    loader_jar_filename = os.path.basename(download_result["file_path"])
                    shutil.copy2(download_result["file_path"], os.path.join(output_dir, loader_jar_filename))
                    
                    # 下载并解析整合包
                    index_data = self.download_and_extract_mrpack(selected_version["id"], output_dir)
                    if index_data:
                        # 下载所有文件
                        if self.download_modpack_files(index_data, output_dir):
                            # 处理覆盖文件
                            self.process_modpack_overrides(output_dir)
                            
                            # 创建整合包zip
                            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                            sanitized_name = re.sub(r'[^\w\-\. ]', '_', selected_modpack["title"])
                            zip_filename = f"{sanitized_name}_full_{timestamp}.zip"
                            zip_path = os.path.join(self.modpack_dir, zip_filename)
                            
                            # 压缩整个目录
                            print(f"\n创建最终整合包ZIP文件...")
                            try:
                                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                                    for root, dirs, files in os.walk(output_dir):
                                        for file in files:
                                            file_path = os.path.join(root, file)
                                            arcname = os.path.relpath(file_path, output_dir)
                                            zipf.write(file_path, arcname)
                                
                                print(f"\n✅ 完整整合包已创建: {zip_path}")
                                
                                # 询问是否删除原始文件夹
                                choice = input("\n是否删除原始文件夹以节省空间? (y/n): ").strip().lower()
                                if choice in ['y', 'yes', '是']:
                                    shutil.rmtree(output_dir)
                                    print(f"已删除原始文件夹: {output_dir}")
                                
                            except Exception as e:
                                print(f"❌ 创建ZIP文件失败: {str(e)}")
                                print(f"整合包文件保存在: {output_dir}")
                else:
                    # 仅创建加载器ZIP
                    self.create_modpack_zip(
                        selected_modpack["title"], 
                        download_result["file_path"], 
                        selected_version
                    )
                    
                    print(f"\n📝 使用说明:")
                    print(f"   1. 解压下载的整合包")
                    print(f"   2. 运行JAR文件安装Minecraft和{loader_type.title()}加载器")
                    print(f"   3. 从Modrinth下载整合包内容: {MODRINTH_BASE_URL}/{selected_modpack['slug']}")
            else:
                print(f"\n❌ 下载失败，请稍后重试")
        else:
            print("👋 已取消下载")
    
    def run(self):
        """运行主程序"""
        try:
            self.print_banner()
            
            # 直接进入整合包模式，跳过选择
            self.modpack_workflow()
            return
                
            # 默认模式：直接下载加载器
            # 步骤1: 获取游戏版本
            game_version = self.get_minecraft_version()
            print(f"✅ 已选择游戏版本: {game_version}")
            
            # 步骤2: 选择加载器类型
            loader_type = self.select_loader_type()
            print(f"✅ 已选择加载器: {loader_type.title()}")
            
            # 步骤3: 获取兼容的加载器版本
            print(f"\n🔍 正在查找与 Minecraft {game_version} 兼容的 {loader_type.title()} 版本...")
            
            result = self.api.get_compatible_loader_versions(
                loader_type, 
                game_version, 
                stable_only=True,  # 只显示稳定版本
                limit=20  # 限制显示20个版本
            )
            
            if not result["success"]:
                print(f"❌ 获取版本信息失败: {result['message']}")
                return
            
            compatible_versions = result["data"]["compatible_versions"]
            
            # 步骤4: 显示并选择版本
            self.display_compatible_versions(compatible_versions, loader_type)
            
            if not compatible_versions:
                print(f"\n💡 建议:")
                print(f"   1. 检查游戏版本 {game_version} 是否正确")
                print(f"   2. 尝试其他加载器类型")
                print(f"   3. 查看 {loader_type.title()} 官网了解支持的版本")
                return
            
            selected_version = self.select_loader_version(compatible_versions)
            
            if not selected_version:
                print("👋 已取消操作")
                return
            
            # 步骤5: 确认并下载
            if self.confirm_download(loader_type, selected_version["version"], game_version):
                download_result = self.download_loader_jar(loader_type, game_version, selected_version["version"])
                
                if download_result:
                    print(f"\n🎉 {loader_type.title()} 加载器JAR文件下载完成!")
                    print(f"\n📝 使用说明:")
                    print(f"   1. 进入下载目录: {self.download_dir}")
                    print(f"   2. 将JAR文件放入Minecraft的mods文件夹或按需使用")
                    if loader_type == "fabric":
                        print(f"   3. Fabric加载器通常需要配合Fabric API使用")
                    elif loader_type == "forge":
                        print(f"   3. Forge加载器可以直接加载Forge模组")
                    elif loader_type == "quilt":
                        print(f"   3. Quilt加载器兼容Fabric模组并提供额外功能")
                else:
                    print(f"\n❌ 下载失败，请稍后重试")
            else:
                print("👋 已取消下载")
                
        except KeyboardInterrupt:
            print("\n\n👋 用户中断操作")
        except Exception as e:
            print(f"\n❌ 程序运行出错: {str(e)}")
        finally:
            # 清理资源
            self.api.cleanup()

    def download_and_extract_mrpack(self, version_id: str, output_dir: str) -> Dict:
        """下载并解析.mrpack文件
        
        Args:
            version_id: 整合包版本ID
            output_dir: 输出目录
        
        Returns:
            解析后的整合包索引数据
        """
        print(f"\n🔍 下载整合包文件...")
        
        # 创建临时目录
        temp_dir = os.path.join(output_dir, "temp")
        os.makedirs(temp_dir, exist_ok=True)
        
        # 获取下载链接
        headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
        try:
            # 获取版本数据
            version_url = f"{MODRINTH_API_URL}/version/{version_id}"
            response = requests.get(version_url, headers=headers)
            response.raise_for_status()
            version_data = response.json()
            
            # 找到.mrpack文件的下载链接
            mrpack_url = None
            for file in version_data.get("files", []):
                if file.get("filename", "").endswith(".mrpack"):
                    mrpack_url = file.get("url")
                    break
            
            if not mrpack_url:
                print("❌ 找不到整合包文件下载链接")
                return {}
            
            # 下载.mrpack文件
            mrpack_path = os.path.join(temp_dir, f"{version_id}.mrpack")
            print(f"正在下载整合包文件: {mrpack_url}")
            
            response = requests.get(mrpack_url, headers=headers, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(mrpack_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # 计算进度
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            sys.stdout.write(f"\r下载进度: {progress:.1f}% | {downloaded/(1024*1024):.1f} MB / {total_size/(1024*1024):.1f} MB")
                            sys.stdout.flush()
            
            # 清空进度行
            sys.stdout.write('\r' + ' ' * 100 + '\r')
            sys.stdout.flush()
            
            print(f"✅ 整合包文件下载完成")
            
            # 解压.mrpack文件（实际上是一个zip文件）
            extract_dir = os.path.join(output_dir, "mrpack")
            os.makedirs(extract_dir, exist_ok=True)
            
            print(f"正在解压整合包文件...")
            with zipfile.ZipFile(mrpack_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # 读取modrinth.index.json文件
            index_path = os.path.join(extract_dir, "modrinth.index.json")
            if not os.path.exists(index_path):
                print("❌ 整合包索引文件不存在")
                return {}
            
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            # 清理临时文件
            os.remove(mrpack_path)
            print(f"✅ 整合包解析完成")
            return index_data
            
        except Exception as e:
            print(f"❌ 下载或解析整合包文件失败: {str(e)}")
            return {}
    
    def download_modpack_files(self, index_data: Dict, output_dir: str, progress_callback=None) -> bool:
        """使用多线程下载整合包中的所有文件
        
        Args:
            index_data: 整合包索引数据
            output_dir: 输出目录
            progress_callback: 进度回调函数，接收(progress_percent, message)参数
        
        Returns:
            下载是否成功
        """
        if not index_data or "files" not in index_data:
            print("❌ 整合包索引数据无效")
            return False
        
        # 准备下载任务
        files_dir = os.path.join(output_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        
        files = index_data.get("files", [])
        total_files = len(files)
        
        if total_files == 0:
            print("❌ 整合包中没有文件")
            return False
        
        print(f"\n准备下载整合包中的 {total_files} 个文件...")
        headers = {"User-Agent": "MinecraftLoaderCLI/1.0.0"}
        
        # 准备下载任务列表
        download_tasks = []
        skipped_client_only = 0
        
        for file_info in files:
            # 获取文件路径和文件名
            file_path = file_info.get("path", "")
            if not file_path:
                continue
            
            # 检查环境配置，过滤仅客户端文件
            env_config = file_info.get("env", {})
            if env_config:
                server_support = env_config.get("server", "required")
                # 如果服务器端不支持此文件，跳过下载
                if server_support == "unsupported":
                    skipped_client_only += 1
                    continue
                
            # 创建保存路径
            save_path = os.path.join(files_dir, file_path)
            
            # 获取下载链接
            download_url = None
            for url in file_info.get("downloads", []):
                download_url = url
                break
            
            if download_url:
                download_tasks.append((download_url, save_path, headers))
        
        if skipped_client_only > 0:
            print(f"已跳过 {skipped_client_only} 个仅客户端文件")
        
        if not download_tasks:
            print("❌ 没有可下载的文件")
            return False
        
        # 开始多线程下载
        if progress_callback:
            progress_callback(0, f"开始下载 {len(download_tasks)} 个文件，使用 {self.download_manager.max_workers} 个线程...")
        else:
            print(f"开始下载 {len(download_tasks)} 个文件，使用 {self.download_manager.max_workers} 个线程...")
        
        # 创建带进度回调的下载管理器
        if progress_callback:
            # 重写下载管理器的进度显示方法
            original_display = self.download_manager._display_progress
            def custom_display():
                while not self.download_manager.stop_event.is_set():
                    with self.download_manager.status.lock:
                        total = self.download_manager.status.total
                        completed = self.download_manager.status.completed
                        current_file = self.download_manager.status.current_file
                        current_progress = self.download_manager.status.current_progress
                    
                    if total > 0:
                        overall_progress = (completed / total) * 100
                        progress_callback(overall_progress, f"下载进度: {completed}/{total} 文件，当前: {current_file}")
                    
                    time.sleep(0.5)
            
            self.download_manager._display_progress = custom_display
        
        # 重置下载管理器的停止事件
        self.download_manager.stop_event.clear()
        
        result = self.download_manager.download_files(download_tasks)
        
        if progress_callback:
            progress_callback(100, "文件下载完成")
        
        return result
    
    def process_modpack_overrides(self, output_dir: str) -> bool:
        """处理整合包的覆盖文件
        
        Args:
            output_dir: 输出目录
        
        Returns:
            处理是否成功
        """
        overrides_dir = os.path.join(output_dir, "mrpack", "overrides")
        files_dir = os.path.join(output_dir, "files")
        
        if not os.path.exists(overrides_dir):
            return True  # 没有覆盖文件，视为成功
        
        print("\n复制覆盖文件...")
        try:
            for root, dirs, files in os.walk(overrides_dir):
                for file in files:
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, overrides_dir)
                    dest_path = os.path.join(files_dir, rel_path)
                    
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    
                    # 复制文件
                    shutil.copy2(src_path, dest_path)
            
            print("✅ 覆盖文件复制完成")
            return True
            
        except Exception as e:
            print(f"❌ 复制覆盖文件失败: {str(e)}")
            return False


def main():
    """主函数"""
    cli = MinecraftLoaderCLI()
    cli.run()


if __name__ == "__main__":
    main()