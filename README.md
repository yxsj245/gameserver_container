# 项目导航
   [快速部署](https://github.com/yxsj245/gameserver_container/blob/main/%E5%BF%AB%E9%80%9F%E5%85%A5%E9%97%A8.md)
   [已确认兼容的游戏](https://github.com/yxsj245/gameserver_container/blob/main/已确认兼容的游戏.md)
   [文档站](http://blogpage.xiaozhuhouses.asia/html4/index.html#/)
   [赞助项目](https://github.com/yxsj245/gameserver_container/blob/main/%E8%B5%9E%E5%8A%A9%E9%A1%B9%E7%9B%AE.md)

### 此分支开源协议变更为Apache2.0

# 社交媒体平台
### [bilibili](https://www.bilibili.com/video/BV1YiLqz7EVX/)
### [抖音](https://v.douyin.com/XVMwsSjymZg/)
### [QQ群](https://qm.qq.com/q/iFTPvgcfDO)

# 使用教程
### [bilibili](https://www.bilibili.com/video/BV1CZLqzAEN7/)

# 已支持功能
- [x] 集成steamcmd
- [x] 对接[MCSManager](https://www.mcsmanager.com/)
- [x] 常用服务端快速部署，现已支持超过20款游戏
- [x] 支持一键从第三方直链中在线安装任意服务端
- [x] MCBE服务端
- [x] 所有脚本在线热更新
- [x] 启动服务端持续检测已申请开通的端口

# 项目介绍

这个项目是一个基于Docker且采用debian作为镜像底层的通用游戏服务器管理容器，具有非常高的兼容性和拓展性，专为运行各种Steam游戏服务器而设计。它提供了一套完整的内容，让游戏服务器的部署、管理和维护变得简单高效。

## 核心亮点

### 一站式游戏服务器部署平台
- 基于Debian Bullseye，较高的兼容性和拓展性 \
![](https://th.bing.com/th/id/OIP.GOEUYPz3zTEbVPuOsxc1gAHaEo?rs=1&pid=ImgDetMain)
- 预装SteamCMD及其所有依赖，支持32位和64位游戏服务器 \
![](https://th.bing.com/th/id/OIP.C52cJ46FbMs9L8otALrBRwHaEK?rs=1&pid=ImgDetMain)
- 交互式终端菜单界面，让服务器管理变得直观简单 \
![](https://pic1.imgdb.cn/item/6815830c58cb8da5c8d76bef.png)
- 开服端口侦听判断是否可以进服 \
![](https://pic1.imgdb.cn/item/680c3f9e58cb8da5c8ce14b5.png)
### 全面的游戏支持
- 内置多款热门游戏服务器的一键部署脚本 \
![](https://pic1.imgdb.cn/item/680c424658cb8da5c8ce1564.png)
> 温馨提示：内容将会通过热更新持续从云端拉取最新支持的快速部署游戏
- 支持包括：幻兽帕鲁、方舟生存进化、七日杀、腐蚀、求生之路2等多种一键部署 \
![](https://pic1.imgdb.cn/item/680c435458cb8da5c8ce15a1.png)
- 支持通过AppID安装任意Steam游戏服务器 \
![](https://pic1.imgdb.cn/item/680c43ff58cb8da5c8ce15cb.png) \
![](https://pic1.imgdb.cn/item/680c443058cb8da5c8ce15d5.png)
### 容器化技术优势
- 环境隔离，防止不同游戏服务器之间互相干扰 \
![](https://pic1.imgdb.cn/item/680c454258cb8da5c8ce161f.png)
- 统一的管理接口，简化多服务器管理
- 数据持久化设计，游戏数据安全存储在宿主机上
- 自动迁移功能，可轻松将游戏从临时目录转移到持久化存储

### 强大的系统架构
   - 模块化设计，各组件功能明确分离
   - 自动化脚本系统，减少人工操作
   - 完善的错误处理和日志记录

### [MCSManager](https://www.mcsmanager.com/)面板集成
![](https://www.mcsmanager.com/static/media/zh-console-page.04ad38056ab0c9a55c31.png)
   - 内置MCSManager API支持，可直接在容器内注册游戏实例
![](https://pic1.imgdb.cn/item/680c468258cb8da5c8ce167a.png)
   - 一键创建面板实例，无需手动配置
   - 自动设置适当的容器参数和端口映射

### 用户友好设计
   - 中文界面，降低使用门槛
   - 详细的安装后提示，指导用户进行后续配置
![](https://pic1.imgdb.cn/item/680c49cd58cb8da5c8ce179f.png)
   - 彩色命令行界面，提升用户体验
   - 周到的游戏特定配置提示

7. **丰富的管理功能**
   - 游戏服务器启动/停止/重启
   - 配置文件在线编辑
   - 启动脚本自定义
   - 系统资源监控
   - 游戏服务器自动更新

8. **兼容性和可扩展性**
   - 兼容多种游戏引擎（Unity、Unreal等）
   - 预装常见游戏所需的依赖库
   - 灵活的配置系统，可根据需求定制

### 技术实现亮点

1. **脚本系统设计**
   - `menu.sh`: 交互式菜单系统，提供用户友好的界面
   - `game_installers.sh`: 集成各种游戏的安装脚本，实现一键部署
   - `start.sh`: 容器启动入口，初始化环境并启动菜单
   - `update_scripts.sh`: 自动更新脚本，保持系统最新

2. **Dockerfile优化**
   - 多阶段构建，减小镜像体积
   - 精心选择的基础镜像，平衡大小和功能
   - 合理的层次结构，优化缓存利用
   - 专门为游戏服务器定制的依赖配置

3. **MCSM集成接口**
   - 封装REST API调用，简化面板交互
   - 配置文件持久化，方便多容器共享配置
   - 自动处理复杂的Docker参数转换

4. **安全性考虑**
   - 非root用户运行游戏服务，提高安全性
   - 权限控制，防止未授权访问
   - 安全的数据存储设计

### 典型使用场景

1. **小型游戏社区服务器**
   - 一键部署多种游戏，满足社区多样化需求
   - 中央化管理，降低运维成本

2. **个人游戏服务器**
   - 简化安装和配置流程，非专业用户也能轻松上手
   - 资源共享，在有限硬件上运行多个游戏服务器

3. **游戏服务器提供商**
   - 标准化部署流程，提高服务质量
   - 自动化管理，降低人工成本

### 未来发展方向

1. **更多游戏支持**
   - 不断扩充游戏库，支持更多热门游戏
   - 优化现有游戏的配置模板
