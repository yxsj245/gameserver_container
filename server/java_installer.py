# -*- coding: utf-8 -*-
"""
Java JDK 安装器模块
使用独立进程模式避免与游戏监控线程的GIL锁竞争
"""

import os
import sys
import shutil
import tempfile
import tarfile
import stat
import subprocess
import re
import logging
import requests
import multiprocessing
import queue
import time

# 获取logger实例
logger = logging.getLogger(__name__)

def install_java_worker(version, java_versions, java_url, is_sponsor, install_queue):
    """Java安装工作进程
    
    Args:
        version: Java版本标识
        java_versions: Java版本配置字典
        java_url: 下载链接
        is_sponsor: 是否为赞助者
        install_queue: 安装进度队列
    """
    temp_dir = None
    temp_file = None
    
    try:
        # 降低进程优先级（Windows系统）
        try:
            if os.name == 'nt':
                # Windows系统设置进程优先级
                import psutil
                current_process = psutil.Process()
                current_process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                logger.info(f"成功为JDK安装任务设置低优先级")
        except Exception as e:
            logger.warning(f"设置进程优先级时出错: {e}")

        java_dir = java_versions[version]["dir"]
        display_name = java_versions[version]["display_name"]
        
        # 阶段1: 验证赞助者身份
        install_queue.put({
            'progress': 2,
            'status': 'verifying_sponsor',
            'message': '正在验证赞助者身份...'
        })
        
        # 阶段2: 开始下载
        install_queue.put({
            'progress': 5,
            'status': 'downloading',
            'message': f'正在准备下载{display_name}...'
        })
        
        # 创建临时目录
        temp_dir = tempfile.mkdtemp()
        temp_file = os.path.join(temp_dir, f"{version}.tar.gz")
        
        download_source_text = "赞助者专用链接" if is_sponsor else "普通链接"
        logger.info(f"开始使用aria2下载{display_name}: {java_url}")
        
        # 检查aria2c是否存在
        aria2c_path = shutil.which('aria2c')
        if not aria2c_path:
            # 如果没有aria2c，回退到requests下载
            logger.warning("aria2c未安装，使用requests下载")
            
            install_queue.put({
                'progress': 5,
                'status': 'downloading',
                'message': f'正在下载{display_name}（普通模式）...'
            })
            
            response = requests.get(java_url, stream=True)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            previous_progress = 5
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = int(20 * downloaded / total_size) + 5
                            progress = max(progress, previous_progress)
                            current_progress = min(progress, 25)
                            
                            install_queue.put({
                                'progress': current_progress,
                                'status': 'downloading',
                                'message': f'正在下载{display_name}... {downloaded//1024//1024}MB/{total_size//1024//1024}MB'
                            })
                            previous_progress = progress
        else:
            # 使用aria2c高速下载
            install_queue.put({
                'progress': 5,
                'status': 'downloading',
                'message': f'正在初始化高速下载{display_name}...'
            })
            
            aria2_cmd = [
                aria2c_path,
                '--dir', temp_dir,
                '--out', f"{version}.tar.gz",
                '--split=8', '--max-connection-per-server=8', '--min-split-size=1M',
                '--continue=true', '--max-tries=0', '--retry-wait=5',
                '--user-agent=GSManager/1.0', '--allow-overwrite=true', '--log-level=info',
                '--summary-interval=1',
                java_url
            ]
            
            process = subprocess.Popen(
                aria2_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='ignore'
            )
            
            # 监控aria2下载进度
            progress_regex = re.compile(r'\[#\w+\s+([\d\.]+[KMG]i?B)/([\d\.]+[KMG]i?B)\s*\((\d+)%\)[^\]]*DL:\s*([^ \]]+)')
            
            for line in iter(process.stdout.readline, ''):
                match = progress_regex.search(line)
                if match:
                    downloaded_str, total_str, percent_str, speed_str = match.groups()
                    download_percent = int(percent_str)
                    
                    # 将下载进度(0-100%)映射到总进度(5-25%)
                    overall_progress = 5 + int(download_percent * 0.2)
                    if not speed_str.endswith('/s'):
                        speed_str += '/s'
                    
                    install_queue.put({
                        'progress': overall_progress,
                        'status': 'downloading',
                        'message': f'正在高速下载{display_name}... {downloaded_str}/{total_str} ({speed_str})'
                    })
            
            process.wait()
            
            if process.returncode != 0:
                stderr_output = process.stderr.read()
                error_msg = f"aria2下载失败，返回码: {process.returncode}"
                logger.error(error_msg)
                logger.error(f"Aria2c STDERR: {stderr_output}")
                raise Exception("下载失败，请检查网络连接或下载链接")
            
            # 检查文件是否存在且不为空
            if not os.path.exists(temp_file) or os.path.getsize(temp_file) == 0:
                raise Exception("下载完成但文件为空，请检查下载源或网络")
            
            logger.info(f"aria2下载成功: {java_url} -> {temp_file}")
        
        # 阶段3: 解压文件
        install_queue.put({
            'progress': 30,
            'status': 'extracting',
            'message': f'正在解压{display_name}...'
        })
        
        # 确保目标目录存在并为空
        if os.path.exists(java_dir):
            shutil.rmtree(java_dir)
        os.makedirs(java_dir, exist_ok=True)
        
        # 解压tar.gz文件
        logger.info(f"解压{display_name}到: {java_dir}")
        with tarfile.open(temp_file, "r:gz") as tar:
            # 获取根目录名称
            root_dir = tar.getnames()[0].split('/')[0]
            
            # 解压所有文件
            members = tar.getmembers()
            total_members = len(members)
            
            for i, member in enumerate(members):
                tar.extract(member, temp_dir)
                # 更新解压进度
                if i % 100 == 0 or i == total_members - 1:
                    progress = int(40 * i / total_members) + 30  # 30-70%
                    install_queue.put({
                        'progress': min(progress, 70),
                        'status': 'extracting',
                        'message': f'正在解压{display_name}... ({i+1}/{total_members})'
                    })
        
        # 阶段4: 移动文件到目标目录
        install_queue.put({
            'progress': 75,
            'status': 'installing',
            'message': f'正在安装{display_name}...'
        })
        
        # 源目录是解压后的根目录
        extracted_files = os.listdir(temp_dir)
        
        # 找到解压后的目录
        source_dir = None
        for item in extracted_files:
            if os.path.isdir(os.path.join(temp_dir, item)) and item != "__MACOSX":
                source_dir = os.path.join(temp_dir, item)
                break
        
        if not source_dir:
            raise Exception("无法找到解压后的Java目录")
        
        # 复制所有文件到目标目录
        for item in os.listdir(source_dir):
            s = os.path.join(source_dir, item)
            d = os.path.join(java_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        
        # 阶段5: 设置执行权限
        install_queue.put({
            'progress': 85,
            'status': 'setting_permissions',
            'message': f'正在设置{display_name}权限...'
        })
        
        # 设置bin目录中所有文件的执行权限
        bin_dir = os.path.join(java_dir, "bin")
        if os.path.exists(bin_dir):
            for file in os.listdir(bin_dir):
                file_path = os.path.join(bin_dir, file)
                if os.path.isfile(file_path):
                    st = os.stat(file_path)
                    os.chmod(file_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        # 阶段6: 验证安装
        install_queue.put({
            'progress': 90,
            'status': 'verifying',
            'message': f'正在验证{display_name}安装...'
        })
        
        # 检查java是否可执行
        java_executable = os.path.join(java_dir, "bin/java")
        if os.name == 'nt':
            java_executable += ".exe"
            
        result = subprocess.run([java_executable, "-version"], 
                               capture_output=True, 
                               text=True)
        
        if result.returncode == 0:
            # 获取版本信息
            version_output = result.stderr  # java -version输出到stderr
            version_match = re.search(r'version "([^"]+)"', version_output)
            java_version = version_match.group(1) if version_match else "Unknown"
            
            # 安装完成
            install_queue.put({
                'progress': 100,
                'status': 'completed',
                'message': f'{display_name} 安装成功！',
                'completed': True,
                'version': java_version,
                'path': java_executable,
                'usage_hint': f"使用方式: {java_executable} -version",
                'download_source': "sponsor" if is_sponsor else "public"
            })
            
            logger.info(f"{display_name} 安装成功！")
            logger.info(f"Java版本: {java_version}")
            logger.info(f"安装路径: {java_executable}")
            logger.info(f"下载方式: 通过{download_source_text}下载")
        else:
            raise Exception("Java安装后无法执行")
            
    except Exception as e:
        logger.error(f"安装Java时出错: {str(e)}")
        install_queue.put({
            'progress': install_queue.qsize() and list(install_queue.queue)[-1].get('progress', 0) or 0,
            'status': 'error',
            'message': f'安装失败: {str(e)}',
            'completed': True,
            'error': str(e)
        })
    
    finally:
        # 清理临时文件
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")
        
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"清理临时目录失败: {e}")