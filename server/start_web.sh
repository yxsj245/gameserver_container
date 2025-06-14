#!/bin/bash

echo "==== 启动游戏服务器网页部署界面 ===="

# 信号处理函数
cleanup() {
    echo "收到退出信号，正在优雅关闭Gunicorn..."
    if [ ! -z "$GUNICORN_PID" ]; then
        # 发送SIGTERM信号给gunicorn主进程
        kill -TERM $GUNICORN_PID 2>/dev/null
        # 等待进程结束，最多等待30秒
        for i in {1..30}; do
            if ! kill -0 $GUNICORN_PID 2>/dev/null; then
                echo "Gunicorn已优雅关闭"
                break
            fi
            sleep 1
        done
        # 如果进程仍然存在，强制杀死
        if kill -0 $GUNICORN_PID 2>/dev/null; then
            echo "强制关闭Gunicorn进程"
            kill -KILL $GUNICORN_PID 2>/dev/null
        fi
    fi
    exit 0
}

# 捕获SIGTERM和SIGINT信号
trap cleanup SIGTERM SIGINT

# 确认前端已构建
if [ ! -d "/home/steam/app/dist" ]; then
  echo "错误: 前端未构建，请检查Dockerfile"
  exit 1
fi

echo "前端已构建，dist目录存在"

# 从环境变量读取配置，如果没有则使用默认值
WORKERS=1
TIMEOUT=${GUNICORN_TIMEOUT:-120}
PORT=${GUNICORN_PORT:-5000}
USE_GUNICORN=${USE_GUNICORN:-true}

# 检查是否安装了Gunicorn
if ! command -v gunicorn &> /dev/null; then
  echo "安装Gunicorn..."
  pip3 install gunicorn
fi

# 如果指定不使用Gunicorn，则警告并退出
if [ "$USE_GUNICORN" != "true" ]; then
  echo "警告: 不推荐直接使用Flask开发服务器"
  echo "设置环境变量 USE_GUNICORN=true 可启用Gunicorn"
  cd /home/steam/server
  # 启动Flask开发服务器并记录PID
  python3 api_server.py &
  FLASK_PID=$!
  echo "Flask开发服务器已启动，PID: $FLASK_PID"
  
  # 重新定义cleanup函数用于Flask
  cleanup() {
      echo "收到退出信号，正在关闭Flask服务器..."
      if [ ! -z "$FLASK_PID" ]; then
          kill -TERM $FLASK_PID 2>/dev/null
          wait $FLASK_PID 2>/dev/null
          echo "Flask服务器已关闭"
      fi
      exit 0
  }
  
  # 等待Flask进程结束
  wait $FLASK_PID
  exit 0
fi

# 启动API服务器(使用Gunicorn)
echo "使用Gunicorn启动API服务器..."
echo "工作进程数: $WORKERS, 超时时间: $TIMEOUT 秒, 监听端口: $PORT"
cd /home/steam/server

# Gunicorn配置参数:
# -w $WORKERS: 使用环境变量指定的工作进程数
# -b 0.0.0.0:$PORT: 绑定到所有网络接口的指定端口
# --timeout $TIMEOUT: 设置超时时间
# --preload: 预加载应用程序代码，减少每个工作进程的启动时间
# --max-requests 1000: 每个工作进程处理1000个请求后自动重启，防止内存泄漏
# --max-requests-jitter 50: 为重启添加随机抖动，避免所有工作进程同时重启
# --worker-class gthread: 使用线程工作模式，适合I/O密集型应用
# --threads 4: 每个工作进程4个线程，增加并发能力
# --log-level info: 设置日志级别为info
# --access-logfile -: 访问日志输出到标准输出
# --error-logfile -: 错误日志输出到标准输出

# 启动gunicorn并记录PID
gunicorn -w $WORKERS \
  -b 0.0.0.0:$PORT \
  --timeout $TIMEOUT \
  --preload \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --worker-class gthread \
  --threads 4 \
  --log-level info \
  --access-logfile - \
  --error-logfile - \
  api_server:app &

# 记录gunicorn主进程PID
GUNICORN_PID=$!
echo "Gunicorn已启动，PID: $GUNICORN_PID"

# 等待gunicorn进程结束
wait $GUNICORN_PID