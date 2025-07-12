# 项目介绍
<div align="center">

# ![logo3](https://github.com/user-attachments/assets/8d1a37bd-5955-4dc2-b314-aecb04f985dc)

**让游戏服务器的部署、管理和维护变得简单高效**

[![GitHub Stars](https://badgen.net/github/stars/yxsj245/GameServerManager)](https://github.com/yxsj245/GameServerManager/stargazers)
[![GitHub Release](https://badgen.net/github/release/yxsj245/GameServerManager)](https://github.com/yxsj245/GameServerManager/releases)
[![Docker Pulls](https://badgen.net/docker/pulls/xiaozhu674/gameservermanager)](https://hub.docker.com/r/xiaozhu674/gameservermanager)
[![License](https://badgen.net/github/license/yxsj245/GameServerManager)](https://github.com/yxsj245/GameServerManager/blob/main/LICENSE)

[📖 文档站](http://blogpage.xiaozhuhouses.asia/html6/index.html#/) • [🌐 官方网站](http://blogpage.xiaozhuhouses.asia/html5/index.html) • [💬 QQ群](https://qm.qq.com/q/oNd4HvMj6M)

</div>

---

## 📋 项目简介

GameServerManager（简称GSManager）是一个基于 **Docker** 技术的现代化游戏服务器管理平台，专为简化游戏服务器的部署、管理和维护而设计。

# 重磅通知 GSManager3.0 进入内测阶段
<img width="1915" height="1004" alt="image" src="https://github.com/user-attachments/assets/baccf78e-e580-45bf-ad7b-f2dd106c02ce" />


### ✨ 核心特性

- 🐳 **Docker 容器化** - 完全基于Docker运行，环境隔离，兼容性极佳
- 🎯 **一键部署** - 支持多款热门游戏的快速部署
- 🌐 **Web 管理界面** - 现代化的React前端，直观易用
- 🔧 **实时终端** - 内置Web终端，支持实时命令执行
- 📊 **资源监控** - 实时监控服务器资源使用情况
- 🔐 **权限管理** - 完善的用户认证和权限控制系统
- 🎮 **多游戏支持** - 支持Steam平台多款热门游戏服务端
- 💾 **数据持久化** - 游戏数据和配置文件外部映射，安全可靠

![容器信息面板](http://images.server.xiaozhuhouses.asia:40061/i/2025/06/09/wbnc63.png)

---

## 🚀 快速开始

### 一键安装脚本

```bash
rm -f install.py && wget http://blogpage.xiaozhuhouses.asia/api/api1/install.py && python3 install.py
```
> debian(docker自行安装)和centos请使用手动安装，详见文档站

---

## 🎮 支持的游戏

| 游戏名称 | 中文名 | Steam ID | 匿名下载 | 状态 |
|---------|--------|----------|----------|------|
| **热门游戏** | | | | |
| Palworld | 幻兽帕鲁 | 2394010 | ✅ | 🟢 完全支持 |
| Rust | 腐蚀 | 258550 | ✅ | 🟢 完全支持 |
| Satisfactory | 幸福工厂 | 1690800 | ✅ | 🟢 完全支持 |
| Valheim | 英灵神殿 | 896660 | ✅ | 🟢 完全支持 |
| 7 Days to Die | 七日杀 | 294420 | ✅ | 🟢 完全支持 |
| Project Zomboid | 僵尸毁灭工程 | 380870 | ✅ | 🟢 完全支持 |
| ARK: Survival Evolved | 方舟：生存进化 | 376030 | ✅ | 🟢 完全支持 |
| **射击游戏** | | | | |
| Left 4 Dead 2 | 求生之路2 | 222860 | ❌ | 🟡 需要正版 |
| Team Fortress 2 | 军团要塞2 | 232250 | ✅ | 🟢 完全支持 |
| Squad | 战术小队 | 403240 | ✅ | 🟢 完全支持 |
| Insurgency: Sandstorm | 叛乱：沙漠风暴 | 581330 | ✅ | 🟢 完全支持 |
| Killing Floor 2 | 杀戮空间2 | 232130 | ✅ | 🟢 完全支持 |
| Insurgency (2014) | 叛乱2 | 237410 | ✅ | 🟢 完全支持 |
| MORDHAU | 雷霆一击 | 629800 | ✅ | 🟢 完全支持 |
| No More Room in Hell | 地狱已满 | 317670 | ✅ | 🟢 完全支持 |
| Fistful of Frags | Fistful of Frags | 295230 | ✅ | 🟢 完全支持 |
| Half-Life | 半条命 | 90 | ✅ | 🟢 完全支持 |
| Half-Life 2: Deathmatch | 半条命2 | 232370 | ✅ | 🟢 完全支持 |
| Operation: Harsh Doorstop | 行动代号：残酷之门 | 950900 | ✅ | 🟢 完全支持 |
| Vox Machinae | Vox Machinae | 944490 | ✅ | 🟡 需要配置 |
| **独立游戏** | | | | |
| Unturned | 未转变者 | 1110390 | ✅ | 🟢 完全支持 |
| Don't Starve Together | 饥荒联机版 | 343050 | ✅ | 🟡 需要配置 |
| Last Oasis | 最后的绿洲 | 920720 | ✅ | 🟢 完全支持 |
| Hurtworld | 伤害世界 | 405100 | ✅ | 🟢 完全支持 |
| Soulmask | 灵魂面甲 | 3017300 | ✅ | 🟢 完全支持 |
| **模拟游戏** | | | | |
| Euro Truck Simulator 2 | 欧洲卡车模拟2 | 1948160 | ✅ | 🟡 需要配置 |
| American Truck Simulator | 美国卡车模拟 | 2239530 | ✅ | 🟡 需要配置 |
| ECO | 生态生存 | 739590 | ✅ | 🟡 需要配置 |

> 更多游戏支持正在持续添加中...

---

## 🏗️ 技术架构

### 前端技术栈
- **React 18** - 现代化前端框架
- **Ant Design** - 企业级UI组件库
- **Monaco Editor** - 代码编辑器
- **Xterm.js** - Web终端模拟器
- **Vite** - 快速构建工具

### 后端技术栈
- **Python 3.13** - 主要开发语言
- **Flask** - Web框架
- **Gunicorn** - WSGI服务器
- **Docker** - 容器化技术
- **SteamCMD** - Steam命令行工具
- **Aria2** - 多协议下载器

---

## 📁 项目结构

```
GameServerManager/
├── app/                    # 前端应用
│   ├── src/               # React源码
│   ├── public/            # 静态资源
│   └── package.json       # 前端依赖
├── server/                # 后端服务
│   ├── api_server.py      # 主API服务器
│   ├── game_installer.py  # 游戏安装器
│   ├── pty_manager.py     # 终端管理器
│   ├── auth_middleware.py # 认证中间件
│   └── installgame.json   # 游戏配置文件
├── docker-compose.yml     # Docker编排文件
├── Dockerfile            # Docker镜像构建文件
└── README.md             # 项目说明文档
```

---

## 🔧 配置说明

### 端口配置
- **5000** - Web管理界面
- **27015-27020** - Steam游戏服务器端口范围

### 数据卷映射
- `./game_data` → `/home/steam/games` - 游戏数据目录
- `./game_file` → `/home/steam/.config` - 游戏配置目录
- `./game_file` → `/home/steam/.local` - 游戏存档目录

### 环境变量
- `TZ=Asia/Shanghai` - 时区设置
- `USE_GUNICORN=true` - 启用Gunicorn
- `GUNICORN_TIMEOUT=120` - 请求超时时间
- `GUNICORN_PORT=5000` - 服务端口

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

1. **Fork** 本项目
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开一个 **Pull Request**

---

## 📞 支持与反馈

- 🐛 **问题反馈**：[GitHub Issues](https://github.com/yxsj245/GameServerManager/issues)
- 💬 **QQ交流群**：1040201322
- 📖 **详细文档**：[查看文档](http://blogpage.xiaozhuhouses.asia/html6/index.html#/)

---

## 📄 开源协议

本项目采用 [AGPL-3.0 license](LICENSE) 开源协议。

---

## 👨‍💻 关于作者

此项目由 **又菜又爱玩的小朱** 独立开发维护。

如果这个项目对你有帮助，请给个 ⭐ Star 支持一下！

---

## 📈 项目统计

![Star History](https://api.star-history.com/svg?repos=yxsj245/GameServerManager&type=Date)

---

<div align="center">

**🎮 让游戏服务器管理变得简单有趣！**

</div>
