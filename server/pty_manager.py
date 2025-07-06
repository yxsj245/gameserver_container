import os
import pty
import fcntl
import select
import time
import threading
import queue
import logging
import subprocess
import tempfile
import psutil
import re
import termios

# 配置日志
logger = logging.getLogger("pty_manager")

ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

class PTYProcess:
    """通用PTY进程管理类，用于处理各种需要交互式终端的进程"""
    
    def __init__(self, process_id, cmd, cwd=None, env=None, log_prefix=None):
        """
        初始化PTY进程
        
        Args:
            process_id: 进程唯一标识符
            cmd: 要执行的命令
            cwd: 工作目录
            env: 环境变量
            log_prefix: 日志文件前缀
        """
        self.process_id = process_id
        self.cmd = cmd
        self.cwd = cwd
        self.env = env or dict(os.environ, TERM="xterm")
        self.log_prefix = log_prefix or f"pty_{process_id}"
        
        # 进程状态
        self.process = None
        self.master_fd = None
        self.slave_fd = None
        self.started_at = None
        self.return_code = None
        self.running = False
        self.complete = False
        self.error = None
        
        # 输出相关
        self.output = []
        self.output_queue = queue.Queue()
        self.output_file = None
        self.output_thread = None
        
        # 输入相关
        self.input_event = threading.Event()
        self.input_value = None
        
        # 其他状态
        self.final_message = None
        self.sent_complete = False
    
    def start(self):
        """启动PTY进程"""
        try:
            logger.info(f"开始使用PTY运行进程: {self.process_id}")
            logger.info(f"执行命令: {self.cmd}, 工作目录: {self.cwd or '当前目录'}")
            
            # 创建PTY
            self.master_fd, self.slave_fd = pty.openpty()
            logger.info(f"创建PTY: master={self.master_fd}, slave={self.slave_fd}")
            
            # 关闭ECHO，避免输入被进程再次回显导致前端显示错乱
            try:
                attrs = termios.tcgetattr(self.slave_fd)
                attrs[3] = attrs[3] & ~termios.ECHO  # lflag
                termios.tcsetattr(self.slave_fd, termios.TCSANOW, attrs)
                logger.debug("已关闭PTY从端的ECHO标志")
            except Exception as e_echo:
                logger.warning(f"设置PTY从端ECHO标志失败: {e_echo}")
            
            # 启动进程，将输出连接到PTY从端
            self.process = subprocess.Popen(
                self.cmd,
                shell=True,
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                close_fds=True,
                cwd=self.cwd,
                env=self.env
            )
            
            # 关闭PTY从端，主进程只需要主端
            os.close(self.slave_fd)
            self.slave_fd = None
            
            # 更新状态
            self.started_at = time.time()
            self.running = True
            logger.info(f"进程已启动，PID: {self.process.pid}")
            
            # 创建一个单独的线程来读取PTY输出
            self.output_thread = threading.Thread(
                target=self._read_pty_output,
                daemon=True
            )
            self.output_thread.start()
            
            return True
        except Exception as e:
            logger.error(f"启动PTY进程时出错: {str(e)}")
            self.error = str(e)
            self.running = False
            self.complete = True
            self.output_queue.put({'complete': True, 'status': 'error', 'message': f'启动错误: {str(e)}'})
            return False
    
    def wait(self, timeout=None):
        """等待进程完成"""
        if not self.process:
            return None
        
        return_code = self.process.wait()
        
        # 确保读取线程有时间完成
        if self.output_thread:
            self.output_thread.join(timeout=timeout or 5)
        
        return return_code
    
    def send_input(self, value):
        """向进程发送输入"""
        if not self.running or not self.master_fd:
            logger.error(f"进程 {self.process_id} 未运行或无法获取PTY主端")
            return False
        
        try:
            send_str = value + '\n'
            os.write(self.master_fd, send_str.encode('utf-8'))
            logger.info(f"向进程 {self.process_id} 发送输入: {repr(send_str)}")
            return True
        except Exception as e:
            logger.error(f"向进程 {self.process_id} 发送输入失败: {str(e)}")
            return False
    
    def send_ctrl_c(self):
        """向进程发送Ctrl+C信号"""
        if not self.running or not self.master_fd:
            logger.error(f"进程 {self.process_id} 未运行或无法获取PTY主端")
            return False
        
        try:
            # Ctrl+C对应ASCII码为3
            os.write(self.master_fd, b'\x03')
            logger.info(f"向进程 {self.process_id} 发送Ctrl+C信号")
            return True
        except Exception as e:
            logger.error(f"向进程 {self.process_id} 发送Ctrl+C失败: {str(e)}")
            return False
    
    def terminate(self, force=False):
        """终止进程"""
        if not self.process:
            logger.warning(f"进程 {self.process_id} 不存在，无法终止")
            return False
        
        if self.process.poll() is not None:
            logger.info(f"进程 {self.process_id} 已经终止，返回码: {self.process.poll()}")
            self.running = False
            return True
        
        try:
            if force:
                # 强制模式：直接使用SIGKILL终止进程和所有子进程
                logger.info(f"强制终止进程 {self.process_id}")
                
                # 获取当前进程的PID
                pid = self.process.pid
                logger.info(f"进程PID: {pid}")
                
                try:
                    # 找到所有子进程
                    parent = psutil.Process(pid)
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
                except psutil.NoSuchProcess:
                    logger.warning(f"进程 {pid} 已不存在")
                except Exception as e:
                    logger.error(f"使用psutil杀死进程失败: {str(e)}")
                    # 如果上面失败，使用原始方法
                    self.process.kill()
            else:
                # 标准模式：先尝试发送Ctrl+C，然后等待一段时间，如果还未结束再使用terminate
                self.send_ctrl_c()
                
                # 等待进程响应Ctrl+C (增加等待时间和检查频率)
                max_wait = 20  # 增加到最多等待10秒
                for i in range(max_wait):
                    if self.process.poll() is not None:
                        break
                    # 每隔0.5秒检查一次进程状态
                    time.sleep(0.5)
                    # 每2秒额外再发送一次Ctrl+C
                    if i > 0 and i % 4 == 0:
                        logger.info(f"进程 {self.process_id} 未响应Ctrl+C，再次发送")
                        self.send_ctrl_c()
                
                # 如果进程仍在运行，使用terminate
                if self.process.poll() is None:
                    logger.info(f"进程 {self.process_id} 未响应Ctrl+C，使用terminate")
                    
                    # 尝试使用psutil查找并终止所有子进程
                    try:
                        parent = psutil.Process(self.process.pid)
                        children = parent.children(recursive=True)
                        
                        # 首先终止所有子进程
                        for child in children:
                            logger.info(f"终止子进程: {child.pid}")
                            try:
                                child.terminate()
                            except:
                                pass
                    except Exception as e:
                        logger.warning(f"终止子进程时出错: {str(e)}")
                    
                    # 然后终止主进程
                    self.process.terminate()
                    
                    # 再等待一段时间
                    for _ in range(10):  # 最多等待5秒
                        if self.process.poll() is not None:
                            break
                        time.sleep(0.5)
                    
                    # 如果进程仍在运行，使用kill
                    if self.process.poll() is None:
                        logger.info(f"进程 {self.process_id} 未响应terminate，使用kill")
                        
                        # 强制杀死所有相关进程
                        try:
                            parent = psutil.Process(self.process.pid)
                            children = parent.children(recursive=True)
                            
                            # 首先杀死所有子进程
                            for child in children:
                                logger.info(f"强制杀死子进程: {child.pid}")
                                try:
                                    child.kill()
                                except:
                                    pass
                            
                            # 然后杀死主进程
                            parent.kill()
                        except Exception as e:
                            logger.warning(f"强制杀死子进程时出错: {str(e)}")
                            # 如果上面失败，直接杀死主进程
                            self.process.kill()
            
            # 检查进程是否已终止
            return_code = self.process.poll()
            if return_code is not None:
                logger.info(f"进程 {self.process_id} 已终止，返回码: {return_code}")
                self.running = False
                self.return_code = return_code
                return True
            else:
                logger.warning(f"无法终止进程 {self.process_id}")
                return False
                
        except Exception as e:
            logger.error(f"终止进程 {self.process_id} 时出错: {str(e)}")
            return False
    
    def is_running(self):
        """检查进程是否在运行"""
        if not self.process:
            return False
        
        return self.process.poll() is None
    
    def get_status(self):
        """获取进程状态"""
        status = {
            'process_id': self.process_id,
            'cmd': self.cmd,
            'running': self.is_running(),
            'started_at': self.started_at,
            'complete': self.complete
        }
        
        if self.process:
            status['pid'] = self.process.pid
            status['return_code'] = self.process.poll()
            if self.started_at:
                status['uptime'] = time.time() - self.started_at
        
        if self.error:
            status['error'] = self.error
        
        if self.final_message:
            status['final_message'] = self.final_message
            
        if self.output_file:
            status['output_file'] = self.output_file
            
        return status
    
    def clean_up(self):
        """清理资源"""
        # 关闭PTY主端
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
            self.master_fd = None
        
        # 关闭PTY从端
        if self.slave_fd:
            try:
                os.close(self.slave_fd)
            except:
                pass
            self.slave_fd = None
        
        # 清理输出队列
        try:
            while not self.output_queue.empty():
                self.output_queue.get_nowait()
        except:
            pass
    
    def _read_pty_output(self):
        """从PTY主端读取输出并将其添加到队列中"""
        logger.info(f"启动进程 {self.process_id} 的PTY输出读取线程")
        
        # 创建临时日志文件
        output_log = tempfile.NamedTemporaryFile(mode='w+', delete=False, prefix=f"{self.log_prefix}_", suffix=".log")
        output_log_path = output_log.name
        logger.debug(f"日志将写入: {output_log_path}")
        self.output_file = output_log_path
        
        # 设置非阻塞模式
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        buffer = ""
        try:
            while True:
                try:
                    # 读取PTY输出
                    r, w, e = select.select([self.master_fd], [], [], 0.5)
                    if self.master_fd in r:
                        data = os.read(self.master_fd, 1024).decode('utf-8', errors='replace')
                        # 移除ANSI转义序列，避免前端出现异常字符
                        data = ANSI_ESCAPE_RE.sub('', data)
                        data = data.replace('\r', '\n')
                        if not data:  # EOF
                            break
                        
                        # 处理数据，按行分割
                        buffer += data
                        lines = buffer.split('\n')
                        buffer = lines.pop()  # 最后一个可能是不完整的行
                        
                        # 如果buffer以典型提示符结尾（如": ","> "），立即刷新输出
                        if buffer and (buffer.endswith(': ') or buffer.endswith('> ')):
                            lines.append(buffer)  # 将buffer视为完整行处理
                            buffer = ''
                        
                        for line in lines:
                            line = line.rstrip()
                            if line:
                                # 过滤掉多个连续的^C符号，只保留一个
                                if line.startswith('^C'):
                                    # 计算^C的数量
                                    control_c_count = 0
                                    for char in line:
                                        if char == '^' and control_c_count % 2 == 0:
                                            control_c_count += 1
                                        elif char == 'C' and control_c_count % 2 == 1:
                                            control_c_count += 1
                                    
                                    # 如果有多个^C，只保留一个并添加剩余内容
                                    if control_c_count > 2:  # 超过一个^C
                                        remaining_content = line.replace('^C', '')
                                        if remaining_content:
                                            line = "^C " + remaining_content
                                        else:
                                            line = "^C"
                                
                                # 写入日志文件
                                output_log.write(line + "\n")
                                output_log.flush()
                                
                                # 添加到内存中的输出历史
                                self.output.append(line)
                                
                                # 限制输出行数，最多保留500行
                                if len(self.output) > 500:
                                    # 移除最旧的输出，保持在500行以内
                                    self.output = self.output[-500:]
                                
                                # 添加到队列以供实时传输
                                self.output_queue.put(line)
                                

                    
                    # 检查进程是否结束
                    if self.process and self.process.poll() is not None:
                        # 处理剩余的buffer
                        if buffer:
                            # 同样过滤多个^C
                            if buffer.startswith('^C'):
                                control_c_count = 0
                                for char in buffer:
                                    if char == '^' and control_c_count % 2 == 0:
                                        control_c_count += 1
                                    elif char == 'C' and control_c_count % 2 == 1:
                                        control_c_count += 1
                                
                                if control_c_count > 2:  # 超过一个^C
                                    remaining_content = buffer.replace('^C', '')
                                    if remaining_content:
                                        buffer = "^C " + remaining_content
                                    else:
                                        buffer = "^C"
                            
                            output_log.write(buffer + "\n")
                            self.output.append(buffer)
                            
                            # 限制输出行数，最多保留500行
                            if len(self.output) > 500:
                                # 移除最旧的输出，保持在500行以内
                                self.output = self.output[-500:]
                            
                            self.output_queue.put(buffer)
                        break
                        
                except (IOError, OSError) as e:
                    if e.errno != 11:  # EAGAIN, 表示当前没有数据可读
                        logger.error(f"读取PTY输出时出错: {str(e)}")
                        break
                    time.sleep(0.1)
                    
            # 进程结束，检查返回码
            return_code = self.process.poll() if self.process else None
            logger.info(f"进程 {self.process_id} 已结束，返回码: {return_code}")
            
            if return_code is not None:
                self.return_code = return_code
                self.running = False
                self.complete = True
                
                # 发送完成消息
                status = 'success' if return_code == 0 else 'error'
                
                # 如果进程执行失败，添加最近的输出作为错误信息
                if return_code != 0:
                    # 收集最后的错误输出
                    last_outputs = self.output[-10:] if len(self.output) > 10 else self.output
                    error_output = "\n".join(last_outputs)
                    error_message = f"进程执行失败，返回码: {return_code}\n\n错误输出:\n{error_output}"
                    message = f'进程 {self.process_id} 失败，返回码: {return_code}，错误输出已记录'
                    logger.error(f"进程执行失败，返回码: {return_code}，错误输出: {error_output}")
                    self.error = error_message
                else:
                    message = f'进程 {self.process_id} 成功完成'
                
                self.final_message = message
                
                # 向队列添加完成消息
                if status == 'error':
                    # 针对错误情况，包含详细错误输出
                    self.output_queue.put({'complete': True, 'status': status, 'message': message, 'error_details': self.error})
                else:
                    self.output_queue.put({'complete': True, 'status': status, 'message': message})
                
        except Exception as e:
            logger.error(f"读取PTY输出线程出错: {str(e)}")
            
            # 向队列添加错误消息
            self.output_queue.put({'complete': True, 'status': 'error', 'message': f'读取输出错误: {str(e)}'})
            
            # 更新状态
            self.error = str(e)
            self.running = False
            self.complete = True
            
        finally:
            # 关闭PTY主端
            try:
                os.close(self.master_fd)
            except:
                pass
            self.master_fd = None
                
            # 关闭日志文件
            try:
                output_log.close()
            except:
                pass
                
            logger.info(f"进程 {self.process_id} 的PTY输出读取线程结束")


class PTYManager:
    """PTY进程管理器，用于管理多个PTY进程"""
    
    def __init__(self):
        self.processes = {}  # process_id -> PTYProcess
    
    def create_process(self, process_id, cmd, cwd=None, env=None, log_prefix=None):
        """创建一个新的PTY进程"""
        if process_id in self.processes:
            logger.warning(f"进程ID {process_id} 已存在，将替换旧进程")
            self.terminate_process(process_id)
        
        process = PTYProcess(process_id, cmd, cwd, env, log_prefix)
        self.processes[process_id] = process
        return process
    
    def start_process(self, process_id):
        """启动指定的PTY进程"""
        if process_id not in self.processes:
            logger.error(f"进程ID {process_id} 不存在")
            return False
        
        return self.processes[process_id].start()
    
    def get_process(self, process_id):
        """获取指定的PTY进程"""
        return self.processes.get(process_id)
    
    def send_input(self, process_id, value):
        """向指定的PTY进程发送输入"""
        if process_id not in self.processes:
            logger.error(f"进程ID {process_id} 不存在")
            return False
        
        return self.processes[process_id].send_input(value)
    
    def set_input_value(self, process_id, value):
        """设置输入值并触发输入事件"""
        if process_id not in self.processes:
            logger.error(f"进程ID {process_id} 不存在")
            return False
        
        process = self.processes[process_id]
        process.input_value = value
        process.input_event.set()
        return True
    
    def terminate_process(self, process_id, force=False):
        """终止指定的PTY进程"""
        if process_id not in self.processes:
            logger.error(f"进程ID {process_id} 不存在")
            return False
        
        process = self.processes[process_id]
        result = process.terminate(force)
        if result:
            # 清理资源
            process.clean_up()
            # 从管理器中移除进程引用，防止内存泄漏
            self.remove_process(process_id)
        return result
    
    def get_status(self, process_id=None):
        """获取进程状态"""
        if process_id:
            if process_id not in self.processes:
                return None
            return self.processes[process_id].get_status()
        else:
            return {pid: process.get_status() for pid, process in self.processes.items()}
    
    def clean_up(self, process_id=None):
        """清理资源"""
        if process_id:
            if process_id in self.processes:
                self.processes[process_id].clean_up()
                del self.processes[process_id]
        else:
            for process in self.processes.values():
                process.clean_up()
            self.processes.clear()
    
    def remove_process(self, process_id):
        """从进程字典中移除进程，但不进行清理操作"""
        if process_id in self.processes:
            logger.info(f"从进程字典中移除进程: {process_id}")
            del self.processes[process_id]
            return True
        else:
            logger.warning(f"进程ID {process_id} 不存在，无法移除")
            return False
    
    def is_running(self, process_id):
        """检查进程是否在运行"""
        if process_id not in self.processes:
            return False
        
        return self.processes[process_id].is_running()
    
    def get_all_processes(self):
        """获取所有进程"""
        return self.processes


# 创建全局PTY管理器实例
pty_manager = PTYManager()