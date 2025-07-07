import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Layout, Typography, Row, Col, Card, Button, Spin, message, Tooltip, Modal, Tabs, Form, Input, Menu, Tag, Dropdown, Radio, Drawer, Switch, List, Select, Checkbox, Upload } from 'antd';
import { CloudServerOutlined, DashboardOutlined, AppstoreOutlined, PlayCircleOutlined, ReloadOutlined, DownOutlined, InfoCircleOutlined, FolderOutlined, UserOutlined, LogoutOutlined, LockOutlined, GlobalOutlined, MenuOutlined, SettingOutlined, ToolOutlined, BookOutlined, RocketOutlined, HistoryOutlined } from '@ant-design/icons';
import axios from 'axios';
// 导入antd样式
import 'antd/dist/antd.css';
import './App.css';

// 配置message为右上角通知样式，3秒自动消失
message.config({
  top: 24,
  duration: 3,
  maxCount: 5,
  rtl: false,
  prefixCls: 'ant-message',
  getContainer: () => document.body,
});
import Terminal from './components/Terminal';
import SimpleServerTerminal from './components/SimpleServerTerminal';
import ContainerInfo from './components/ContainerInfo';
import FileManager from './components/FileManager';
import GameConfigManager from './components/GameConfigManager'; // 导入游戏配置文件管理组件
import DirectoryPicker from './components/DirectoryPicker';
import Register from './components/Register'; // 导入注册组件
import GlobalMusicPlayer from './components/GlobalMusicPlayer'; // 导入全局音乐播放器
import FrpManager from './components/FrpManager'; // 导入内网穿透组件
import FrpDocModal from './components/FrpDocModal'; // 导入内网穿透文档弹窗组件
import OnlineDeploy from './components/OnlineDeploy'; // 导入在线部署组件
import About from './pages/About'; // 导入关于项目页面
import Settings from './pages/Settings'; // 导入设置页面
import Environment from './pages/Environment'; // 导入环境安装页面
import ServerGuide from './pages/ServerGuide'; // 导入开服指南页面
import PanelManager from './components/PanelManager'; // 导入面板管理组件
import MinecraftModpackDeploy from './components/MinecraftModpackDeploy'; // 导入Minecraft整合包部署组件
import { fetchGames, installGame, terminateInstall, installByAppId, openGameFolder, checkVersionUpdate, downloadDockerImage } from './api';
import { GameInfo } from './types';
import terminalService from './services/terminalService';
import { useAuth } from './context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useIsMobile } from './hooks/useIsMobile'; // 导入移动设备检测钩子
import Cookies from 'js-cookie'; // 导入js-cookie库

const { Header, Content, Footer, Sider } = Layout;
const { Title, Paragraph } = Typography;
const { TabPane } = Tabs;
const { Option } = Select;

// 扩展window对象类型
declare global {
  interface Window {
    currentProgressHide?: () => void;
  }
}

// 定义一个类型化的错误处理函数
const handleError = (err: any): void => {
  // console.error('Error:', err);
  message.error(err?.message || '发生未知错误');
};

interface InstallOutput {
  output: (string | { prompt?: string; line?: string })[];
  complete: boolean;
  installing: boolean;
}

// 新增API函数
const startServer = async (gameId: string, callback?: (line: any) => void, onComplete?: () => void, onError?: (error: any) => void, includeHistory: boolean = true, restart: boolean = false, scriptName?: string) => {
  try {
    // console.log(`正在启动服务器 ${gameId}...`);
    
    // 发送启动服务器请求
    const response = await axios.post('/api/server/start', { 
      game_id: gameId,
      script_name: scriptName,
      reconnect: restart  // 传递重连标识，帮助服务端决定是否使用上次的脚本
    });
    // console.log('启动服务器响应:', response.data);
    
    // 如果服务器返回多个脚本选择，返回脚本列表让调用者处理
    if (response.data.status === 'multiple_scripts') {
      return { 
        multipleScripts: true, 
        scripts: response.data.scripts,
        message: response.data.message,
        reconnect: response.data.reconnect || restart
      };
    }
    
    if (response.data.status !== 'success') {
      const errorMsg = response.data.message || '启动失败';
      // console.error(`启动服务器失败: ${errorMsg}`);
      if (onError) onError(new Error(errorMsg));
      throw new Error(errorMsg);
    }
    
    // 使用EventSource获取实时输出
    const token = localStorage.getItem('auth_token');
    const eventSource = new EventSource(`/api/server/stream?game_id=${gameId}${token ? `&token=${token}` : ''}&include_history=${includeHistory}${restart ? '&restart=true' : ''}`);
    // console.log(`已建立到 ${gameId} 服务器的SSE连接${restart ? ' (重启模式)' : ''}`);
    
    // 添加一个变量来跟踪上次输出时间，用于实时性检测
    let lastOutputTime = Date.now();
    
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // 更新最后输出时间
        lastOutputTime = Date.now();
        
        // 处理完成消息
        if (data.complete) {
          console.log(`服务器输出完成，关闭SSE连接`);
          eventSource.close();
          
          // 检查是否有错误状态
          if (data.status === 'error') {
            const errorMessage = data.message || '未知错误';
            const errorDetails = data.error_details || '';
            console.error(`服务器完成但有错误: ${errorMessage}${errorDetails ? ', 详情: ' + errorDetails : ''}`);
            
            // 如果有错误详情，添加到输出
            if (callback) {
              if (errorDetails) {
                callback(`错误详情: ${errorDetails}`);
                if (errorDetails.includes('启动失败') || errorMessage.includes('启动失败')) {
                  callback("---");
                  callback("检测到 '启动失败' 错误。这通常与启动脚本、环境变量或服务器配置文件有关。");
                  callback("请检查以下几点：");
                  callback("1. 游戏目录下的启动脚本 (例如 start.sh) 内容是否正确，语法是否有误。");
                  callback("---");
                }
              } else if (errorMessage.includes('启动失败')) {
                //即使没有errorDetails，但errorMessage包含启动失败，也显示提示
                callback("---");
                callback("检测到 '启动失败' 错误。这通常与启动脚本、环境变量或服务器配置文件有关。");
                callback("请检查以下几点：");
                callback("1. 游戏目录下的启动脚本 (例如 start.sh) 内容是否正确，语法是否有误。");
                callback("---");
              }
            }
            
            if (onError) onError(new Error(errorMessage));
            return;
          }
          
          if (onComplete) onComplete();
          return;
        }
        
        // 处理心跳包
        if (data.heartbeat) {
          // console.log(`收到心跳包: ${new Date(data.timestamp * 1000).toLocaleTimeString()}`);
          return;
        }
        
        // 处理超时消息
        if (data.timeout) {
          console.log(`服务器连接超时`);
          eventSource.close();
          if (onError) onError(new Error(data.message || '连接超时'));
          return;
        }
        
        // 处理错误消息
        if (data.error) {
          console.error(`服务器返回错误: ${data.error}`);
          eventSource.close();
          if (onError) onError(new Error(data.error));
          return;
        }
        
        // 处理普通输出行
        if (data.line && callback) {
          // 如果是历史输出，添加history标记
          if (data.history) {
            callback(data.line);
          } else {
            callback(data.line);
            
            // 只有非历史输出才滚动到底部
            setTimeout(() => {
              const terminalEndRef = document.querySelector('.terminal-end-ref');
              if (terminalEndRef && terminalEndRef.parentElement) {
                terminalEndRef.parentElement.scrollTop = terminalEndRef.parentElement.scrollHeight;
              }
            }, 10);
          }
        }
      } catch (err) {
        console.error('解析服务器输出失败:', err, event.data);
        if (onError) onError(new Error(`解析服务器输出失败: ${err}`));
      }
    };
    
    eventSource.onerror = (error) => {
      console.error('SSE连接错误:', error);
      eventSource.close();
      if (onError) onError(error || new Error('服务器连接错误'));
    };
    
    return eventSource;
  } catch (error) {
    // console.error('启动服务器函数出错:', error);
    
    let errorMsg;
    
    // 处理axios错误响应，特别是400状态码的错误
    if (error.response && error.response.status === 400 && error.response.data) {
      errorMsg = error.response.data.message || '启动失败';
      console.error(`启动服务器失败 (400): ${errorMsg}`);
    }
    // 处理其他axios错误
    else if (error.response && error.response.data && error.response.data.message) {
      errorMsg = error.response.data.message;
      console.error(`启动服务器失败: ${errorMsg}`);
    }
    // 处理网络错误或其他错误
    else {
      errorMsg = error.message || '启动服务器时发生未知错误';
    }
    
    // 创建统一的错误对象
    const finalError = new Error(errorMsg);
    
    // 只调用onError回调，不再抛出错误，避免重复处理
    if (onError) {
      onError(finalError);
    } else {
      // 如果没有onError回调，才抛出错误
      throw finalError;
    }
  }
};

const stopServer = async (gameId: string, force: boolean = false) => {
  try {
    // 显示加载消息
    const loadingKey = `stopping_${gameId}`;
    message.loading({ content: `正在${force ? '强制' : ''}停止服务器...`, key: loadingKey, duration: 0 });
    
    // 使用terminalService的terminate方法
    const success = await terminalService.terminateProcess('server', gameId, force);
    
    if (!success) {
      message.error({ content: '停止服务器失败', key: loadingKey });
      return { status: 'error', message: '停止服务器失败' };
    }
    
    // 模拟原来的响应格式
    const response = { data: { status: 'success' } };
    
    // 如果成功或警告，验证服务器是否真的停止了
    if (response.data.status === 'success' || response.data.status === 'warning') {
      message.success({ content: `服务器已${force ? '强制' : '标准'}停止`, key: loadingKey });
      
      // 等待一小段时间，让服务器有时间完全停止
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      try {
        // 验证服务器是否真的停止了
        const statusResponse = await axios.get(`/api/server/status?game_id=${gameId}`);
        if (statusResponse.data.server_status === 'running') {
          console.warn('服务器报告已停止，但状态检查显示仍在运行');
          
          // 如果不是强制模式，记录警告但不改变返回状态
          if (!force) {
            response.data._serverStillRunning = true;
          }
        }
      } catch (error) {
        console.error('验证服务器状态失败:', error);
        // 确保即使状态检查失败，也关闭加载消息
        message.error({ content: `服务器状态验证失败，但操作已完成`, key: loadingKey });
      }
    } else {
      message.error({ content: `停止服务器失败: ${response.data.message || '未知错误'}`, key: loadingKey });
    }
    
    return response.data;
  } catch (error) {
    // 确保在发生错误时关闭加载消息
    const loadingKey = `stopping_${gameId}`;
    message.error({ content: `停止服务器时发生错误: ${error.message || '未知错误'}`, key: loadingKey });
    throw error;
  }
};

const sendServerInput = async (gameId: string, value: string) => {
  try {
    // 发送命令
    const response = await axios.post('/api/server/send_input', {
      game_id: gameId,
      value
    });
    return response.data;
  } catch (error: any) {
    if (error.response && error.response.status === 400) {
      return {
        status: 'error',
        message: error.response.data.message || '服务器未运行或已停止，请重新启动服务器',
        server_status: 'stopped'
      };
    }
    // 对于其他类型的错误 (例如网络错误)，直接抛出或返回一个包含错误信息的标准对象
     return {
        status: 'error',
        message: error.message || '发送命令时发生未知网络或服务器错误',
        server_status: 'unknown' 
     };
  }
};

const checkServerStatus = async (gameId: string) => {
  try {
    const response = await axios.get(`/api/server/status?game_id=${gameId}`);
    return response.data;
  } catch (error) {
    throw error;
  }
};

// Minecraft部署组件
const MinecraftDeploy: React.FC = () => {
  const [mcServers, setMcServers] = useState<any[]>([]);
  const [selectedServer, setSelectedServer] = useState<string>('');
  const [mcVersions, setMcVersions] = useState<string[]>([]);
  const [selectedMcVersion, setSelectedMcVersion] = useState<string>('');
  const [builds, setBuilds] = useState<any[]>([]);
  const [selectedBuild, setSelectedBuild] = useState<string>('');
  const [customName, setCustomName] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [deploying, setDeploying] = useState<boolean>(false);
  const [installedJdks, setInstalledJdks] = useState<any[]>([]);
  const [selectedJdk, setSelectedJdk] = useState<string>('');
  const [deployMode, setDeployMode] = useState<string>('new'); // 新增部署模式状态
  const [installedGames, setInstalledGames] = useState<any[]>([]); // 已安装游戏列表
  const [selectedExistingServer, setSelectedExistingServer] = useState<string>(''); // 选择的现有服务端

  // 获取MC服务端列表
  const fetchMcServers = async () => {
    try {
      setLoading(true);
      const response = await axios.get('/api/minecraft/servers');
      if (response.data.status === 'success') {
        setMcServers(response.data.data || []);
      } else {
        message.error(response.data.message || '获取服务端列表失败');
      }
    } catch (error: any) {
      message.error('获取服务端列表失败: ' + (error.response?.data?.message || error.message));
    } finally {
      setLoading(false);
    }
  };

  // 获取服务端信息
  const fetchServerInfo = async (serverName: string) => {
    try {
      setLoading(true);
      const response = await axios.get(`/api/minecraft/server/${serverName}`);
      if (response.data.status === 'success') {
        const serverInfo = response.data.data;
        setMcVersions(serverInfo.mc_versions || []);
        setSelectedMcVersion('');
        setBuilds([]);
        setSelectedBuild('');
      } else {
        message.error(response.data.message || '获取服务端信息失败');
      }
    } catch (error: any) {
      message.error('获取服务端信息失败: ' + (error.response?.data?.message || error.message));
    } finally {
      setLoading(false);
    }
  };

  // 获取构建列表
  const fetchBuilds = async (serverName: string, mcVersion: string) => {
    try {
      setLoading(true);
      const response = await axios.get(`/api/minecraft/builds/${serverName}/${mcVersion}`);
      if (response.data.status === 'success') {
        const buildsData = response.data.data;
        setBuilds(buildsData.builds || []);
        setSelectedBuild('');
      } else {
        message.error(response.data.message || '获取构建列表失败');
      }
    } catch (error: any) {
      message.error('获取构建列表失败: ' + (error.response?.data?.message || error.message));
    } finally {
      setLoading(false);
    }
  };

  // 获取已安装的JDK列表
  const fetchInstalledJdks = async () => {
    try {
      const response = await axios.get('/api/minecraft/installed-jdks');
      if (response.data.status === 'success') {
        setInstalledJdks(response.data.jdks || []);
      } else {
        message.error(response.data.message || '获取JDK列表失败');
      }
    } catch (error: any) {
      message.error('获取JDK列表失败: ' + (error.response?.data?.message || error.message));
    }
  };

  // 获取已安装游戏列表
  const fetchInstalledGames = async () => {
    try {
      const response = await axios.get('/api/installed_games');
      if (response.data.status === 'success') {
        // 合并已安装游戏和外部游戏
        const allGames = [...(response.data.installed || []), ...(response.data.external || [])];
        setInstalledGames(allGames);
      } else {
        message.error(response.data.message || '获取已安装游戏列表失败');
      }
    } catch (error: any) {
      message.error('获取已安装游戏列表失败: ' + (error.response?.data?.message || error.message));
    }
  };

  // 部署服务器
  const deployServer = async () => {
    if (!selectedServer || !selectedMcVersion || !selectedBuild) {
      message.error('请完成所有选择');
      return;
    }

    // 根据部署模式验证服务器名称
    const serverName = deployMode === 'existing' ? selectedExistingServer : customName;
    if (!serverName || !serverName.trim()) {
      message.error(deployMode === 'existing' ? '请选择现有服务端' : '请输入服务器名称');
      return;
    }

    try {
      setDeploying(true);
      const deployData: any = {
        server_name: selectedServer,
        mc_version: selectedMcVersion,
        core_version: selectedBuild,
        custom_name: serverName.trim(),
        deploy_mode: deployMode
      };
      
      // 只有在新建服务端模式下才传递JDK参数
      if (deployMode === 'new') {
        deployData.selected_jdk = selectedJdk;
      }
      
      const response = await axios.post('/api/minecraft/deploy', deployData);

      if (response.data.status === 'success') {
        message.success('Minecraft服务器部署成功!');
        Modal.success({
          title: '部署成功',
          content: (
            <div>
              <p>服务器已成功部署到: {response.data.data.game_dir}</p>
              <p>服务端文件: {response.data.data.filename}</p>
              <p>您可以在"服务端管理"页面启动服务器</p>
            </div>
          )
        });
        // 重置表单
        setSelectedServer('');
        setSelectedMcVersion('');
        setSelectedBuild('');
        setCustomName('');
        setSelectedExistingServer('');
        setMcVersions([]);
        setBuilds([]);
      } else {
        message.error(response.data.message || '部署失败');
      }
    } catch (error: any) {
      message.error('部署失败: ' + (error.response?.data?.message || error.message));
    } finally {
      setDeploying(false);
    }
  };

  // 处理服务端选择
  const handleServerChange = (value: string) => {
    setSelectedServer(value);
    setCustomName(value); // 默认使用服务端名称
    fetchServerInfo(value);
  };

  // 处理MC版本选择
  const handleMcVersionChange = (value: string) => {
    setSelectedMcVersion(value);
    if (selectedServer) {
      fetchBuilds(selectedServer, value);
    }
  };

  // 组件挂载时获取服务端列表、JDK列表和已安装游戏列表
  React.useEffect(() => {
    fetchMcServers();
    fetchInstalledJdks();
    fetchInstalledGames();
  }, []);

  // 当部署模式改变时，重置相关状态
  React.useEffect(() => {
    if (deployMode === 'existing') {
      setCustomName('');
    } else {
      setSelectedExistingServer('');
    }
  }, [deployMode]);

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Title level={4}>部署模式</Title>
          <Select
            style={{ width: '100%' }}
            placeholder="请选择部署模式"
            value={deployMode}
            onChange={setDeployMode}
          >
            <Option value="new">新建服务端</Option>
            <Option value="existing">部署到现有服务端中</Option>
          </Select>
          <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
            {deployMode === 'new' ? '创建新的服务端实例，包含完整的启动配置' : '仅下载服务端核心文件到现有目录，不生成启动脚本'}
          </div>
        </Col>
        
        <Col span={24}>
          <Title level={4}>选择服务端类型</Title>
          <Select
            style={{ width: '100%' }}
            placeholder="请选择Minecraft服务端类型"
            value={selectedServer}
            onChange={handleServerChange}
            loading={loading}
          >
            {mcServers.map(server => (
              <Option key={server.name} value={server.name}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>{server.name}</span>
                  <div>
                    <Tag color={server.tag === 'official' ? 'blue' : 'green'}>{server.tag}</Tag>
                    {server.recommend && <Tag color="gold">推荐</Tag>}
                  </div>
                </div>
              </Option>
            ))}
          </Select>
        </Col>

        {selectedServer && (
          <Col span={24}>
            <Title level={4}>选择Minecraft版本</Title>
            <Select
              style={{ width: '100%' }}
              placeholder="请选择Minecraft版本"
              value={selectedMcVersion}
              onChange={handleMcVersionChange}
              loading={loading}
            >
              {mcVersions.map(version => (
                <Option key={version} value={version}>
                  {version}
                </Option>
              ))}
            </Select>
          </Col>
        )}

        {selectedMcVersion && (
          <Col span={24}>
            <Title level={4}>选择构建版本</Title>
            <Select
              style={{ width: '100%' }}
              placeholder="请选择构建版本"
              value={selectedBuild}
              onChange={setSelectedBuild}
              loading={loading}
            >
              {builds.map(build => (
                <Option key={build.core_version} value={build.core_version}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{build.core_version}</span>
                    <span style={{ color: '#666', fontSize: '12px' }}>
                      {new Date(build.update_time).toLocaleDateString()}
                    </span>
                  </div>
                </Option>
              ))}
            </Select>
          </Col>
        )}

        {selectedBuild && (
          <Col span={24}>
            {deployMode === 'new' ? (
              <>
                <Title level={4}>服务器名称</Title>
                <Input
                  placeholder="请输入服务器名称（将作为目录名）"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                />
                <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
                  服务器将部署到: /home/steam/games/{customName || '服务器名称'}
                </div>
              </>
            ) : (
              <>
                <Title level={4}>选择现有服务端</Title>
                <Select
                  style={{ width: '100%' }}
                  placeholder="请选择要部署到的现有服务端"
                  value={selectedExistingServer}
                  onChange={setSelectedExistingServer}
                  loading={loading}
                >
                  {installedGames.map(game => (
                    <Option key={game.id || game} value={game.id || game}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>{game.name || game}</span>
                        {game.external && <Tag color="orange">外部游戏</Tag>}
                      </div>
                    </Option>
                  ))}
                </Select>
                <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
                  核心文件将下载到: /home/steam/games/{selectedExistingServer || '选择的服务端'}
                </div>
              </>
            )}
          </Col>
        )}

        {deployMode === 'new' && customName && (
          <Col span={24}>
            <Title level={4}>Java环境选择</Title>
            <Select
              style={{ width: '100%' }}
              placeholder="请选择Java版本（可选，留空使用系统默认Java）"
              value={selectedJdk}
              onChange={setSelectedJdk}
              allowClear
            >
              {installedJdks.map(jdk => (
                <Option key={jdk.id} value={jdk.id}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>{jdk.name}</span>
                    <span style={{ color: '#666', fontSize: '12px' }}>{jdk.version}</span>
                  </div>
                </Option>
              ))}
            </Select>
            <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
              {installedJdks.length === 0 ? (
                <span>未检测到已安装的JDK，将使用系统默认Java。您可以在"环境安装"-"Java环境"中安装JDK。</span>
              ) : (
                <span>选择特定的JDK版本，或留空使用系统默认Java</span>
              )}
            </div>
          </Col>
        )}

        {selectedServer && selectedMcVersion && selectedBuild && ((deployMode === 'new' && customName) || (deployMode === 'existing' && selectedExistingServer)) && (
          <Col span={24}>
            <Card style={{ backgroundColor: '#f6f8fa', border: '1px solid #d1d9e0' }}>
              <Title level={5}>部署信息确认</Title>
              <Row gutter={[16, 8]}>
                <Col span={12}>
                  <strong>部署模式:</strong> {deployMode === 'new' ? '新建服务端' : '部署到现有服务端中'}
                </Col>
                <Col span={12}>
                  <strong>服务端类型:</strong> {selectedServer}
                </Col>
                <Col span={12}>
                  <strong>MC版本:</strong> {selectedMcVersion}
                </Col>
                <Col span={12}>
                  <strong>构建版本:</strong> {selectedBuild}
                </Col>
                <Col span={12}>
                  <strong>服务器名称:</strong> {deployMode === 'new' ? customName : selectedExistingServer}
                </Col>
                {deployMode === 'new' && (
                  <Col span={12}>
                    <strong>Java环境:</strong> {selectedJdk ? installedJdks.find(jdk => jdk.id === selectedJdk)?.name || selectedJdk : '系统默认Java'}
                  </Col>
                )}
              </Row>
              <div style={{ marginTop: '16px', textAlign: 'center' }}>
                <Button
                  type="primary"
                  size="large"
                  onClick={deployServer}
                  loading={deploying}
                  icon={<RocketOutlined />}
                >
                  {deploying ? '部署中...' : '开始部署'}
                </Button>
              </div>
            </Card>
          </Col>
        )}
      </Row>

      {mcServers.length === 0 && !loading && (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Title level={4}>暂无可用的服务端</Title>
          <Paragraph type="secondary">
            请检查网络连接或稍后重试
          </Paragraph>
          <Button onClick={fetchMcServers} icon={<ReloadOutlined />}>
            重新加载
          </Button>
        </div>
      )}
    </div>
  );
};

// 半自动部署组件
const SemiAutoDeploy: React.FC = () => {
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [serverName, setServerName] = useState<string>('');
  const [serverType, setServerType] = useState<string>('');
  const [selectedJdk, setSelectedJdk] = useState<string>('');
  const [installedJdks, setInstalledJdks] = useState<any[]>([]);
  const [uploading, setUploading] = useState<boolean>(false);
  const [deploying, setDeploying] = useState<boolean>(false);

  // 获取已安装的JDK列表
  const fetchInstalledJdks = async () => {
    try {
      const response = await axios.get('/api/environment/java/versions');
      if (response.data.status === 'success') {
        const installedJdks = response.data.versions.filter((jdk: any) => jdk.installed);
        setInstalledJdks(installedJdks);
      } else {
        message.error(response.data.message || '获取JDK列表失败');
      }
    } catch (error: any) {
      message.error('获取JDK列表失败: ' + (error.response?.data?.message || error.message));
    }
  };

  // 处理文件选择
  const handleFileChange = (info: any) => {
    const { file } = info;
    if (file.status === 'removed') {
      setUploadFile(null);
      setServerName('');
      return;
    }
    
    setUploadFile(file.originFileObj || file);
    
    // 根据文件名自动设置服务器名称
    const fileName = file.name;
    const nameWithoutExt = fileName.replace(/\.(zip|rar|tar\.gz|tar|7z)$/i, '');
    setServerName(nameWithoutExt);
  };

  // 上传并部署
  const handleDeploy = async () => {
    if (!uploadFile) {
      message.error('请选择要上传的压缩包');
      return;
    }
    
    if (!serverName.trim()) {
      message.error('请输入服务器名称');
      return;
    }
    
    if (!serverType) {
      message.error('请选择服务端类型');
      return;
    }

    try {
      setUploading(true);
      
      // 创建FormData
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('server_name', serverName.trim());
      formData.append('server_type', serverType);
      if (selectedJdk) {
        formData.append('jdk_version', selectedJdk);
      }
      
      // 显示上传开始消息
      const hideLoading = message.loading('准备上传...', 0);
      
      // 上传文件并部署
      const response = await axios.post('/api/semi-auto-deploy', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / (progressEvent.total || 1));
          hideLoading();
          const hideProgress = message.loading(`上传中... ${percentCompleted}%`, 0);
          // 保存当前进度消息的隐藏函数，以便下次更新时清除
          if (window.currentProgressHide) {
            window.currentProgressHide();
          }
          window.currentProgressHide = hideProgress;
        }
      });
      
      // 清除所有上传相关消息
      if (window.currentProgressHide) {
        window.currentProgressHide();
        window.currentProgressHide = null;
      }
      message.destroy();
      
      if (response.data.status === 'success') {
        message.success('服务器部署成功!');
        Modal.success({
          title: '部署成功',
          content: (
            <div>
              <p>服务器已成功部署到: {response.data.data.game_dir}</p>
              <p>服务器名称: {response.data.data.server_name}</p>
              {response.data.data.start_script && (
                <p>启动脚本: {response.data.data.start_script}</p>
              )}
              <p>您可以在"服务端管理"页面启动服务器</p>
            </div>
          )
        });
        
        // 重置表单
        setUploadFile(null);
        setServerName('');
        setServerType('');
        setSelectedJdk('');
      } else {
        message.error(response.data.message || '部署失败');
      }
    } catch (error: any) {
      message.destroy();
      message.error('部署失败: ' + (error.response?.data?.message || error.message));
    } finally {
      setUploading(false);
    }
  };

  // 组件挂载时获取JDK列表
  React.useEffect(() => {
    fetchInstalledJdks();
  }, []);

  return (
    <div>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Title level={4}>上传服务端压缩包</Title>
          <Upload.Dragger
            name="file"
            multiple={false}
            accept=".zip,.rar,.tar.gz,.tar,.7z"
            beforeUpload={() => false} // 阻止自动上传
            onChange={handleFileChange}
            fileList={uploadFile ? [{
              uid: '1',
              name: uploadFile.name,
              status: 'done' as const,
              size: uploadFile.size
            }] : []}
          >
            <p className="ant-upload-drag-icon">
              <CloudServerOutlined />
            </p>
            <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
            <p className="ant-upload-hint">
              支持 .zip, .rar, .tar.gz, .tar, .7z 格式的压缩包
            </p>
          </Upload.Dragger>
        </Col>

        {uploadFile && (
          <>
            <Col span={24}>
              <Title level={4} style={{ padding: '70px' }}>服务器名称</Title>
              <Input
                placeholder="请输入服务器名称（将作为目录名）"
                value={serverName}
                onChange={(e) => setServerName(e.target.value)}
              />
              <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
                服务器将部署到: /home/steam/games/{serverName || '服务器名称'}
              </div>
            </Col>

            <Col span={24}>
              <Title level={4}>服务端类型</Title>
              <Radio.Group
                value={serverType}
                onChange={(e) => setServerType(e.target.value)}
                style={{ width: '100%' }}
              >
                <Radio.Button value="java" style={{ width: '50%', textAlign: 'center' }}>
                  Java
                </Radio.Button>
                <Radio.Button value="other" style={{ width: '50%', textAlign: 'center' }}>
                  其它
                </Radio.Button>
              </Radio.Group>
            </Col>

            {serverType === 'java' && (
              <Col span={24}>
                <Title level={4}>Java环境选择</Title>
                <Select
                  style={{ width: '100%' }}
                  placeholder="请选择Java版本"
                  value={selectedJdk}
                  onChange={setSelectedJdk}
                  allowClear
                >
                  {installedJdks.map(jdk => (
                    <Option key={jdk.id} value={jdk.id}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>{jdk.name}</span>
                        <span style={{ color: '#666', fontSize: '12px' }}>{jdk.version}</span>
                      </div>
                    </Option>
                  ))}
                </Select>
                <div style={{ marginTop: '8px', color: '#666', fontSize: '12px' }}>
                  {installedJdks.length === 0 ? (
                    <span>未检测到已安装的JDK，将使用系统默认Java。您可以在"环境安装"-"Java环境"中安装JDK。</span>
                  ) : (
                    <span>选择特定的JDK版本，或留空使用系统默认Java</span>
                  )}
                </div>
              </Col>
            )}

            {serverName && serverType && (
              <Col span={24}>
                <Card style={{ backgroundColor: '#f6f8fa', border: '1px solid #d1d9e0' }}>
                  <Title level={5}>部署信息确认</Title>
                  <Row gutter={[16, 8]}>
                    <Col span={12}>
                      <strong>压缩包:</strong> {uploadFile.name}
                    </Col>
                    <Col span={12}>
                      <strong>文件大小:</strong> {(uploadFile.size / 1024 / 1024).toFixed(2)} MB
                    </Col>
                    <Col span={12}>
                      <strong>服务器名称:</strong> {serverName}
                    </Col>
                    <Col span={12}>
                      <strong>服务端类型:</strong> {serverType === 'java' ? 'Java' : '其它'}
                    </Col>
                    {serverType === 'java' && (
                      <Col span={12}>
                        <strong>Java环境:</strong> {selectedJdk ? installedJdks.find(jdk => jdk.id === selectedJdk)?.name || selectedJdk : '系统默认Java'}
                      </Col>
                    )}
                  </Row>
                  <div style={{ marginTop: '16px', textAlign: 'center' }}>
                    <Button
                      type="primary"
                      size="large"
                      onClick={handleDeploy}
                      loading={uploading}
                      icon={<RocketOutlined />}
                    >
                      {uploading ? '部署中...' : '开始部署'}
                    </Button>
                  </div>
                </Card>
              </Col>
            )}
          </>
        )}
      </Row>
    </div>
  );
};

const App: React.FC = () => {
  const { login, logout, username, isAuthenticated, loading, isFirstUse, setAuthenticated } = useAuth();
  const [games, setGames] = useState<GameInfo[]>([]);
  const [gameLoading, setGameLoading] = useState<boolean>(true);
  const [selectedGame, setSelectedGame] = useState<GameInfo | null>(null);
  const [terminalVisible, setTerminalVisible] = useState<boolean>(false);
  // 保存每个游戏的输出和状态
  const [installOutputs, setInstallOutputs] = useState<{[key: string]: InstallOutput}>({});
  const [installedGames, setInstalledGames] = useState<string[]>([]);
  const [externalGames, setExternalGames] = useState<GameInfo[]>([]);  // 添加外部游戏状态
  const [tabKey, setTabKey] = useState<string>('install');
  const [accountModalVisible, setAccountModalVisible] = useState(false);
  const [accountForm] = Form.useForm();
  const [pendingInstallGame, setPendingInstallGame] = useState<GameInfo | null>(null);
  const [accountModalLoading, setAccountModalLoading] = useState<boolean>(false);
  // 新增游戏详情对话框状态
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [detailGame, setDetailGame] = useState<GameInfo | null>(null);
  // 新增AppID安装状态
  const [appIdInstalling, setAppIdInstalling] = useState(false);
  const [accountFormLoading, setAccountFormLoading] = useState<boolean>(false);
  // 新增：服务器相关状态
  const [serverOutputs, setServerOutputs] = useState<{[key: string]: string[]}>({});
  const [runningServers, setRunningServers] = useState<string[]>([]);
  // 新增：自启动服务器列表
  const [autoRestartServers, setAutoRestartServers] = useState<string[]>([]);
  const [selectedServerGame, setSelectedServerGame] = useState<GameInfo | null>(null);
  const [serverModalVisible, setServerModalVisible] = useState<boolean>(false);
  const [serverInput, setServerInput] = useState<string>('');
  const [inputHistory, setInputHistory] = useState<string[]>([]);
  const [inputHistoryIndex, setInputHistoryIndex] = useState<number>(0);
  // 新增：保存EventSource引用
  const serverEventSourceRef = useRef<EventSource | null>(null);
  // 新增：背景图片开关
  const [enableRandomBackground, setEnableRandomBackground] = useState<boolean>(() => {
    // 从localStorage读取用户偏好设置，默认开启
    const savedPreference = localStorage.getItem('enableRandomBackground');
    return savedPreference === null ? true : savedPreference === 'true';
  });
  
  // 新增：当前背景图片URL
  const [currentBackgroundUrl, setCurrentBackgroundUrl] = useState<string>('https://t.alcy.cc/ycy');
  
  // 新增：背景图片API列表
  const backgroundApis = [
    'https://t.alcy.cc/ycy',
    'https://random-image-api.bakacookie520.top/pc-dark'
  ];
  
  // 新增：竞速加载背景图片
  const loadRandomBackground = useCallback(() => {
    if (!enableRandomBackground) return;
    
    // 创建Promise数组，每个API一个Promise
    const imagePromises = backgroundApis.map((apiUrl, index) => {
      return new Promise<{url: string, index: number}>((resolve, reject) => {
        const img = new Image();
        const timestamp = Date.now();
        const urlWithTimestamp = `${apiUrl}${apiUrl.includes('?') ? '&' : '?'}t=${timestamp}`;
        
        // 移除跨域属性以避免CORS错误
        // img.crossOrigin = 'anonymous';
        
        const timeoutId = setTimeout(() => {
          reject(new Error(`Timeout loading image from API ${index + 1}: ${apiUrl}`));
        }, 8000); // 增加超时时间到8秒
        
        img.onload = () => {
          clearTimeout(timeoutId);
          resolve({ url: urlWithTimestamp, index });
        };
        
        img.onerror = (event) => {
          clearTimeout(timeoutId);
          console.warn(`API ${index + 1} (${apiUrl}) 加载失败:`, event);
          reject(new Error(`Failed to load image from API ${index + 1}: ${apiUrl}`));
        };
        
        img.src = urlWithTimestamp;
      });
    });
    
    // 使用Promise.race来获取最快加载完成的图片
    Promise.race(imagePromises)
      .then(({ url, index }) => {
        setCurrentBackgroundUrl(url);
        console.log(`背景图片加载成功 (API ${index + 1}):`, url);
      })
      .catch((error) => {
        console.warn('竞速加载失败，尝试逐个加载:', error);
        
        // 如果竞速失败，尝试逐个加载
        Promise.allSettled(imagePromises)
          .then((results) => {
            const successResult = results.find(result => result.status === 'fulfilled');
            if (successResult && successResult.status === 'fulfilled') {
              setCurrentBackgroundUrl(successResult.value.url);
              console.log(`背景图片备用加载成功 (API ${successResult.value.index + 1}):`, successResult.value.url);
            } else {
              console.warn('所有背景图片API都加载失败，使用默认图片');
              // 如果所有API都失败，直接使用第一个API URL（不带时间戳）
              setCurrentBackgroundUrl(backgroundApis[0]);
            }
          });
      });
  }, [enableRandomBackground]);
  
  // 新增：在组件挂载时和背景开关变化时加载随机背景
  useEffect(() => {
    loadRandomBackground();
  }, [loadRandomBackground]);
  
  // 移除自动刷新背景图片的定时器，确保每次网页刷新时只显示一次
  // useEffect(() => {
  //   if (!enableRandomBackground) return;
  //   
  //   const interval = setInterval(() => {
  //     loadRandomBackground();
  //   }, 30000); // 30秒
  //   
  //   return () => clearInterval(interval);
  // }, [loadRandomBackground]);
  
  // 新增：动态设置CSS变量来更新背景图片
  useEffect(() => {
    if (enableRandomBackground && currentBackgroundUrl) {
      document.documentElement.style.setProperty('--dynamic-bg-url', `url('${currentBackgroundUrl}')`);
    } else {
      document.documentElement.style.removeProperty('--dynamic-bg-url');
    }
  }, [currentBackgroundUrl, enableRandomBackground]);
  
  // 新增：是否启用不活动透明效果
  const [enableInactiveEffect, setEnableInactiveEffect] = useState<boolean>(() => {
    // 从localStorage读取用户偏好设置，默认开启
    const savedPreference = localStorage.getItem('enableInactiveEffect');
    return savedPreference === null ? true : savedPreference === 'true';
  });
  
  // 备份相关状态
  const [backupTasks, setBackupTasks] = useState<any[]>([]);
  const [backupModalVisible, setBackupModalVisible] = useState(false);
  const [editingBackupTask, setEditingBackupTask] = useState<any>(null);
  const [backupForm] = Form.useForm();
  
  // 文件收藏相关状态
  const [favoriteFiles, setFavoriteFiles] = useState<any[]>([]);
  const [favoriteModalVisible, setFavoriteModalVisible] = useState(false);
  const [editingFavorite, setEditingFavorite] = useState<any>(null);
  const [favoriteForm] = Form.useForm();
  // 目录选择器状态
  const [directoryPickerVisible, setDirectoryPickerVisible] = useState(false);
  const [backupDirectoryPickerVisible, setBackupDirectoryPickerVisible] = useState(false);
  
  // 保存不活动效果设置到localStorage
  useEffect(() => {
    localStorage.setItem('enableInactiveEffect', enableInactiveEffect.toString());
  }, [enableInactiveEffect]);
  
  // 新增：用户活动状态和定时器
  const [isUserActive, setIsUserActive] = useState<boolean>(true);
  const userActivityTimerRef = useRef<number | null>(null);
  
  // 处理用户活动
  const handleUserActivity = useCallback(() => {
    // 如果未启用不活跃效果，则不设置定时器
    if (!enableInactiveEffect || !enableRandomBackground) {
      setIsUserActive(true);
      return;
    }
    
    setIsUserActive(true);
    
    // 重置定时器
    if (userActivityTimerRef.current) {
      window.clearTimeout(userActivityTimerRef.current);
    }
    
    // 设置新的定时器，20秒后将用户状态设为不活跃
    userActivityTimerRef.current = window.setTimeout(() => {
      setIsUserActive(false);
    }, 20000); // 20秒
  }, [enableInactiveEffect, enableRandomBackground]);
  
  // 当启用/禁用不活跃效果或随机背景时，重置用户活跃状态
  useEffect(() => {
    // 如果禁用了不活跃效果或随机背景，则强制设置为活跃状态
    if (!enableInactiveEffect || !enableRandomBackground) {
      setIsUserActive(true);
      if (userActivityTimerRef.current) {
        window.clearTimeout(userActivityTimerRef.current);
        userActivityTimerRef.current = null;
      }
    } else {
      // 重新启动活动检测
      handleUserActivity();
    }
  }, [enableInactiveEffect, enableRandomBackground, handleUserActivity]);
  
  // 设置用户活动监听器
  useEffect(() => {
    // 初始设置定时器
    handleUserActivity();
    
    // 添加鼠标移动和点击事件监听器
    window.addEventListener('mousemove', handleUserActivity);
    window.addEventListener('click', handleUserActivity);
    window.addEventListener('keydown', handleUserActivity);
    window.addEventListener('scroll', handleUserActivity);
    window.addEventListener('touchstart', handleUserActivity);
    
    // 组件卸载时清除事件监听器和定时器
    return () => {
      window.removeEventListener('mousemove', handleUserActivity);
      window.removeEventListener('click', handleUserActivity);
      window.removeEventListener('keydown', handleUserActivity);
      window.removeEventListener('scroll', handleUserActivity);
      window.removeEventListener('touchstart', handleUserActivity);
      
      if (userActivityTimerRef.current) {
        window.clearTimeout(userActivityTimerRef.current);
      }
    };
  }, [handleUserActivity]);
  
  // 保存背景图片设置到localStorage
  useEffect(() => {
    localStorage.setItem('enableRandomBackground', enableRandomBackground.toString());
  }, [enableRandomBackground]);
  
  // 监听serverModalVisible变化，当模态框关闭时关闭EventSource连接
  useEffect(() => {
    if (!serverModalVisible && serverEventSourceRef.current) {
      console.log('服务器控制台关闭，关闭SSE连接');
      serverEventSourceRef.current.close();
      serverEventSourceRef.current = null;
    }
  }, [serverModalVisible]);

  // 导航和文件管理相关状态
  const [currentNav, setCurrentNav_orig] = useState<string>('dashboard');
  const [collapsed, setCollapsed] = useState<boolean>(false);
  const [fileManagerVisible, setFileManagerVisible_orig] = useState<boolean>(false);
  const [fileManagerPath, setFileManagerPath_orig] = useState<string>('/home/steam');
  const [initialFileToOpen, setInitialFileToOpen] = useState<string | undefined>(undefined);
  const [isTransitioning, setIsTransitioning] = useState<boolean>(false);

  // Wrapped state setters with logging
  const setCurrentNav = (nav: string) => {
    if (nav !== currentNav) {
      setIsTransitioning(true);
      setTimeout(() => {
        setCurrentNav_orig(nav);
        setIsTransitioning(false);
      }, 300); // 匹配 CSS navFadeOut 动画时间 0.3s
    }
    // 如果 nav === currentNav，则不执行任何操作以避免不必要的重渲染
  };

  const setFileManagerVisible = (visible: boolean) => {
    setFileManagerVisible_orig(visible);
  };

  const setFileManagerPath = (path: string) => {
    setFileManagerPath_orig(path);
  };
  
  // 移动端适配状态
  const isMobile = useIsMobile();
  const [mobileMenuVisible, setMobileMenuVisible] = useState<boolean>(false);

  // 在移动设备上自动折叠侧边栏
  useEffect(() => {
    if (isMobile) {
      setCollapsed(true);
    }
  }, [isMobile]);

  const navigate = useNavigate();

  // 在适当位置添加 terminalEndRef
  const terminalEndRef = useRef<HTMLDivElement>(null);

  // 输出更新后自动滚动到底部（仅在新输出时滚动，不在历史输出加载时滚动）
  const lastOutputCountRef = useRef<number>(0);
  useEffect(() => {
    if (terminalEndRef.current && serverModalVisible && selectedServerGame) {
      const currentOutputCount = (serverOutputs[selectedServerGame.id] || []).length;
      // 只有当输出数量增加时才滚动（新输出），而不是在Modal打开时滚动
      if (currentOutputCount > lastOutputCountRef.current) {
        const outputContainer = terminalEndRef.current.parentElement;
        if (outputContainer) {
          outputContainer.scrollTop = outputContainer.scrollHeight;
        }
      }
      lastOutputCountRef.current = currentOutputCount;
    }
  }, [serverOutputs, selectedServerGame, serverModalVisible]);
  
  // Modal打开时确保显示底部（CSS已处理，无需滚动）
  useEffect(() => {
    if (serverModalVisible && terminalEndRef.current && selectedServerGame) {
      // CSS flex布局已自动显示底部，无需额外滚动
      // 只在有新内容时才需要确保可见性
      const outputContainer = terminalEndRef.current.parentElement;
      if (outputContainer) {
        outputContainer.scrollTop = outputContainer.scrollHeight;
      }
    }
  }, [serverModalVisible, selectedServerGame]);

  // 添加 handleSendServerInput 函数
  const handleSendServerInput = async (gameId: string, input: string) => {
    try {
      // 允许换行符通过，但过滤掉空字符串和只有空格的输入
      if (!gameId || (input.trim() === '' && input !== '\\n')) return;
      
      // 添加到输出，以便用户可以看到自己的输入
      setServerOutputs(prev => {
        const oldOutput = prev[gameId] || [];
        return {
          ...prev,
          [gameId]: [...oldOutput, `> ${input}`]
        };
      });
      
      // 发送输入到服务器
      const response = await sendServerInput(gameId, input);
      
      if (response.status !== 'success') {
        console.error(`发送命令失败: ${response.message}`);
        message.error(`发送命令失败: ${response.message}`);
        // 如果发送失败是因为服务器停止了，这里可以更新状态
        if (response.server_status === 'stopped') {
           setRunningServers(prev => prev.filter(id => id !== gameId));
        }
      }
    } catch (error: any) {
      console.error(`发送命令异常: ${error}`);
      
      // 处理400错误，表示服务器未运行
      if (error.response && error.response.status === 400) {
        message.error('服务器未运行或已停止，请重新启动服务器');
        // 从运行中的服务器列表中移除
        setRunningServers(prev => prev.filter(id => id !== gameId));
        
        // 添加错误信息到终端输出
        setServerOutputs(prev => {
          const oldOutput = prev[gameId] || [];
          return {
            ...prev,
            [gameId]: [...oldOutput, "错误: 服务器未运行或已停止，请重新启动服务器"]
          };
        });
      } else {
        handleError(error);
      }
    }
  };

  // 加载游戏列表
  useEffect(() => {
    // 并行加载游戏列表和已安装游戏
    const loadAll = async () => {
      setGameLoading(true);
      try {
        const [gameResp, installedResp] = await Promise.all([
          axios.get('/api/games'),
          axios.get('/api/installed_games')
        ]);
        
        // 检查游戏列表来源
        if (gameResp.data.status === 'success') {
          setGames(gameResp.data.games || []);
          
          // 添加游戏来源提示
          if (gameResp.data.source === 'cloud') {
            message.success('赞助者验证通过');
          } 
          // 如果有云端错误但仍然使用了本地游戏列表
          else if (gameResp.data.cloud_error) {
            if (gameResp.data.cloud_error.includes('403')) {
              message.error('赞助者凭证验证不通过，已自动清除无效凭证');
              // 删除无效的赞助者凭证
              try {
                await axios.delete('/api/settings/sponsor-key');
              } catch (error) {
                console.error('删除赞助者凭证失败:', error);
              }
            } else {
              message.warn(`云端连接失败：${gameResp.data.cloud_error}，已使用本地游戏列表`);
            }
          }
        }
        
        if (installedResp.data.status === 'success') {
          setInstalledGames(installedResp.data.installed || []);
          setExternalGames(installedResp.data.external || []);  // 设置外部游戏
        }
        
        // 初始化每个游戏的installOutputs
        const initialOutputs: {[key: string]: InstallOutput} = {};
        if (gameResp.data.games) {
          gameResp.data.games.forEach((game: GameInfo) => {
            initialOutputs[game.id] = {
              output: [],
              complete: false,
              installing: false
            };
          });
        }
        setInstallOutputs(initialOutputs);
        
      } catch (error) {
        // 直接处理错误
        handleError(error);
      } finally {
        setGameLoading(false);
      }
    };
    loadAll();
  }, []);

  // 添加一个防抖标志
  const isRefreshingRef = useRef<boolean>(false);
  // 添加上次刷新时间记录
  const lastRefreshTimeRef = useRef<number>(Date.now());

  // 检查正在运行的服务器
  const refreshServerStatus = useCallback(async () => {
    try {
      // 避免重复请求，使用防抖
      if (isRefreshingRef.current) return [];
      
      // 检查距离上次刷新的时间，如果小于3秒则跳过
      const now = Date.now();
      if (now - lastRefreshTimeRef.current < 3000) {
        console.log('刷新服务器状态太频繁，跳过此次请求');
        return runningServers; // 直接返回当前状态
      }
      
      isRefreshingRef.current = true;
      lastRefreshTimeRef.current = now;
      
      // 设置请求超时
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000); // 5秒超时
      
      try {
        const response = await axios.get('/api/server/status', {
          signal: controller.signal,
          timeout: 5000
        });
        
        // 清除超时计时器
        clearTimeout(timeoutId);
        
        if (response.data.status === 'success' && response.data.servers) {
          const running = Object.keys(response.data.servers).filter(
            id => response.data.servers[id].status === 'running'
          );
          
          // 只有当运行状态真正变化时才更新状态
          setRunningServers(prevRunning => {
            // 检查是否有变化
            if (prevRunning.length !== running.length || 
                !prevRunning.every(id => running.includes(id))) {
              return running;
            }
            return prevRunning;
          });
          
          isRefreshingRef.current = false;
          return running;
        }
      } catch (error) {
        // 清除超时计时器
        clearTimeout(timeoutId);
        
        // 处理超时或网络错误
        if (error.name === 'AbortError' || error.code === 'ECONNABORTED') {
          console.warn('服务器状态请求超时');
        } else {
          console.error('检查服务器状态失败:', error);
        }
      }
      
      isRefreshingRef.current = false;
      return runningServers; // 出错时返回当前状态
    } catch (error) {
      console.error('刷新服务器状态失败:', error);
      isRefreshingRef.current = false;
      return runningServers; // 出错时返回当前状态
    }
  }, [runningServers]);

  // 安装游戏的处理函数
  const handleInstall = useCallback(async (game: GameInfo, account?: string, password?: string) => {
    setSelectedGame(game);
    setTerminalVisible(true);
    if (installOutputs[game.id]?.installing) {
      return;
    }
    setInstallOutputs(prev => ({
      ...prev,
      [game.id]: { output: [], complete: false, installing: true }
    }));
    try {
      const eventSource = await installGame(
        game.id,
        (line) => {
          // console.log('SSE output:', line);
          setInstallOutputs(prev => {
            const old = prev[game.id]?.output || [];
            return {
              ...prev,
              [game.id]: {
                ...prev[game.id],
                output: [...old, line],
                installing: true,
                complete: false
              }
            };
          });
        },
        () => {
          setInstallOutputs(prev => ({
            ...prev,
            [game.id]: {
              ...prev[game.id],
              installing: false,
              complete: true
            }
          }));
          message.success(`${game.name} 安装完成`);
          axios.get('/api/installed_games').then(res => {
            if (res.data.status === 'success') setInstalledGames(res.data.installed || []);
          });
        },
        (error) => {
          setInstallOutputs(prev => ({
            ...prev,
            [game.id]: {
              ...prev[game.id],
              installing: false,
              complete: true
            }
          }));
          handleError(error);
        },
        account,
        password
      );
      return () => {
        if (eventSource) eventSource.close();
      };
    } catch (error) {
      setInstallOutputs(prev => ({
        ...prev,
        [game.id]: {
          ...prev[game.id],
          installing: false,
          complete: true
        }
      }));
      handleError(error);
    }
  }, [installOutputs]);

  // 关闭终端窗口，只隐藏，不清空输出
  const closeTerminal = useCallback(() => {
    setTerminalVisible(false);
    message.info('窗口已关闭。若您正在安装，请不用担心，任务仍在继续运行中，刷新页面点击更新即可继续查看');
  }, []);

  // 获取当前选中游戏的输出和状态
  const currentOutput = selectedGame ? installOutputs[selectedGame.id]?.output || [] : [];
  // console.log('currentOutput:', currentOutput);
  const currentInstalling = selectedGame ? installOutputs[selectedGame.id]?.installing || false : false;
  const currentComplete = selectedGame ? installOutputs[selectedGame.id]?.complete || false : false;

  // 卸载游戏
  const handleUninstall = async (gameIdOrGame: string | GameInfo) => {
    try {
      // 判断传入的是游戏ID还是游戏对象
      let gameId: string;
      let gameName: string;
      let isExternal = false;
      
      if (typeof gameIdOrGame === 'string') {
        // 如果是从ContainerInfo传来的游戏ID，需要查找对应的游戏信息
        gameId = gameIdOrGame;
        
        // 先在正常游戏列表中查找
        const game = games.find(g => g.id === gameId);
        if (game) {
          gameName = game.name;
        } else {
          // 在外部游戏列表中查找
          const externalGame = externalGames.find(g => g.id === gameId);
          if (externalGame) {
            gameName = externalGame.name;
            isExternal = true;
          } else {
            // 如果在外部游戏列表中也找不到，则使用游戏ID作为游戏名称
            // 这种情况可能是外来游戏但没有被正确识别
            gameName = gameId;
            isExternal = true;
            console.warn(`未在游戏列表中找到游戏信息，将使用ID作为名称: ${gameId}`);
          }
        }
      } else {
        // 如果是从游戏列表传来的游戏对象
        gameId = gameIdOrGame.id;
        gameName = gameIdOrGame.name;
        isExternal = gameIdOrGame.external || false;
      }
      
      if (runningServers.includes(gameId)) {
        message.warning(`请先停止游戏 ${gameName} 的服务器`);
        return;
      }
      
      const confirmContent = isExternal
        ? `这是一个外部游戏文件夹，卸载将直接删除 /home/steam/games/${gameId} 目录及其所有内容。此操作不可恢复！`
        : '卸载后游戏数据将被删除，请确保您已备份重要数据。';
      
      Modal.confirm({
        title: `确定要卸载${isExternal ? '外部游戏' : ''} ${gameName} 吗?`,
        content: confirmContent,
        okText: '确认卸载',
        okType: 'danger',
        cancelText: '取消',
        onOk: async () => {
          const response = await axios.post('/api/uninstall', { game_id: gameId });
          if (response.data.status === 'success') {
            message.success(`${gameName} 已卸载`);
            
            // 刷新游戏列表和服务器状态
            refreshGameLists();
            refreshServerStatus();
          }
        }
      });
    } catch (error) {
      handleError(error);
    }
  };

  // 处理"安装"按钮点击
  const handleInstallClick = (game: GameInfo) => {
    // 如果已经在安装中，不执行任何操作
    if (installOutputs[game.id]?.installing) {
      return;
    }
    
    if (game.anonymous === false) {
      setPendingInstallGame(game);
      setAccountModalVisible(true);
      accountForm.resetFields();
    } else {
      handleInstall(game);
    }
  };

  // 提交账号密码表单
  const onAccountModalOk = async () => {
    try {
      // 验证表单
      const values = await accountForm.validateFields();
      
      if (pendingInstallGame) {
        // 关闭模态框
        setAccountModalVisible(false);
        
        // 使用表单中的账号密码安装游戏
        handleInstall(pendingInstallGame, values.account, values.password);
        
        // 清空待安装游戏
        setPendingInstallGame(null);
      }
    } catch (error) {
      // 表单验证失败
      console.error('表单验证失败:', error);
    }
  };

  // 刷新已安装游戏和外部游戏列表
  const refreshGameLists = useCallback(async () => {
    try {
      // console.log('刷新游戏列表...');
      const response = await axios.get('/api/installed_games');
      if (response.data.status === 'success') {
        setInstalledGames(response.data.installed || []);
        setExternalGames(response.data.external || []);
        // console.log('游戏列表已更新', {
        //   installed: response.data.installed?.length || 0,
        //   external: response.data.external?.length || 0
        // });
      }
    } catch (error) {
      console.error('刷新游戏列表失败:', error);
    }
  }, []);

  // 当已安装游戏列表变化时，刷新服务器状态
  useEffect(() => {
    refreshServerStatus();
  }, [installedGames, externalGames, refreshServerStatus]);

  // 添加启动SteamCMD的函数
  const handleStartSteamCmd = async () => {
    try {
      // 设置当前选中的服务器游戏为steamcmd
      const steamcmd = { id: "steamcmd", name: "SteamCMD", external: false };
      
      setSelectedServerGame(steamcmd);
      setServerModalVisible(true);
      
      // 清空之前的输出
      setServerOutputs(prev => ({
        ...prev,
        ["steamcmd"]: []
      }));
      
      // 启动SteamCMD并获取输出流
      const eventSource = await axios.post('/api/server/start_steamcmd')
        .then(() => {
          // 建立EventSource连接
          const token = localStorage.getItem('auth_token');
          const source = new EventSource(`/api/server/stream?game_id=steamcmd${token ? `&token=${token}` : ''}&include_history=true`);
          
          source.onmessage = (event) => {
            try {
              const data = JSON.parse(event.data);
              
              // 处理完成消息
              if (data.complete) {
                console.log(`SteamCMD输出完成，关闭SSE连接`);
                source.close();
                message.success(`SteamCMD已停止`);
                // 刷新状态
                refreshServerStatus();
                // 清除EventSource引用
                serverEventSourceRef.current = null;
                return;
              }
              
              // 处理心跳包
              if (data.heartbeat) {
                return;
              }
              
              // 处理超时消息
              if (data.timeout) {
                console.log(`SteamCMD连接超时`);
                source.close();
                handleError(new Error(data.message || '连接超时'));
                return;
              }
              
              // 处理错误消息
              if (data.error) {
                console.error(`SteamCMD返回错误: ${data.error}`);
                source.close();
                handleError(new Error(data.error));
                return;
              }
              
              // 处理普通输出行
              if (data.line) {
                setServerOutputs(prev => {
                  const oldOutput = prev["steamcmd"] || [];
                  return {
                    ...prev,
                    ["steamcmd"]: [...oldOutput, data.line]
                  };
                });
                
                // 确保滚动到底部
                setTimeout(() => {
                  const terminalEndRef = document.querySelector('.terminal-end-ref');
                  if (terminalEndRef && terminalEndRef.parentElement) {
                    terminalEndRef.parentElement.scrollTop = terminalEndRef.parentElement.scrollHeight;
                  }
                }, 10);
              }
            } catch (err) {
              console.error('解析SteamCMD输出失败:', err, event.data);
              handleError(new Error(`解析SteamCMD输出失败: ${err}`));
            }
          };
          
          source.onerror = (error) => {
            console.error('SSE连接错误:', error);
            source.close();
            handleError(error || new Error('SteamCMD连接错误'));
          };
          
          return source;
        })
        .catch(error => {
          console.error(`启动SteamCMD失败: ${error}`);
          handleError(error);
          throw error;
        });
      
      // 保存EventSource引用
      serverEventSourceRef.current = eventSource;
      
      // 服务器启动后立即刷新状态列表
      message.success(`SteamCMD启动成功`);
      
      // 添加到运行中服务器列表
      setRunningServers(prev => {
        if (!prev.includes("steamcmd")) {
          return [...prev, "steamcmd"];
        }
        return prev;
      });
      
      // 延迟再次刷新以确保状态更新
      setTimeout(() => {
        refreshServerStatus();
      }, 2000);
      
    } catch (error) {
      console.error(`启动SteamCMD失败: ${error}`);
      handleError(error);
    }
  };

  // 服务器相关函数
  const handleStartServer = async (gameId: string, reconnect: boolean = false, scriptName?: string) => {
    try {
      // 设置当前选中的服务器游戏
      const game = games.find(g => g.id === gameId) || 
                  externalGames.find(g => g.id === gameId) || 
                  { id: gameId, name: gameId, external: true };
      
      // console.log(`处理启动服务器: gameId=${gameId}, reconnect=${reconnect}, 游戏名称=${game.name}`);
      
      setSelectedServerGame(game);
      setServerModalVisible(true);
      
      // 先检查服务器是否已经在运行
      try {
        const statusResponse = await checkServerStatus(gameId);
        
        // 如果是重连模式，但服务器未运行，显示提示并要求用户完全重启
        if (reconnect && statusResponse.server_status !== 'running') {
          console.log(`重连模式，但服务器 ${gameId} 未运行，需要重新启动`);
          message.warning('服务器已经停止运行，需要重新启动服务器');
          
          setServerOutputs(prev => ({
            ...prev,
            [gameId]: [...(prev[gameId] || []), "警告：服务器已经停止运行，请点击【启动】按钮重新启动服务器"]
          }));
          
          // 从运行中的服务器列表移除
          setRunningServers(prev => prev.filter(id => id !== gameId));
          return;
        }
        
        if (statusResponse.server_status === 'running') {
          console.log(`服务器 ${gameId} 已经在运行，直接打开控制台`);
          
          // 如果是重新连接，不清空之前的输出
          if (!reconnect) {
            // 清空之前的输出
            setServerOutputs(prev => ({
              ...prev,
              [gameId]: ["服务器已经在运行，正在连接到控制台..."]
            }));
          } else {
            // 添加一条分隔线
            setServerOutputs(prev => {
              const oldOutput = prev[gameId] || [];
              return {
                ...prev,
                [gameId]: [...oldOutput, "--- 重新连接到服务器 ---"]
              };
            });
          }
          
          // 确保服务器在运行中列表中
          setRunningServers(prev => {
            if (!prev.includes(gameId)) {
              return [...prev, gameId];
            }
            return prev;
          });
          
          // 启动服务器流但不实际启动服务器
          const result = await startServer(
            gameId,
            (line) => {
              if (typeof line === 'string') {
                setServerOutputs(prev => {
                  const oldOutput = prev[gameId] || [];
                  return {
                    ...prev,
                    [gameId]: [...oldOutput, line]
                  };
                });
              } else if (typeof line === 'object' && line !== null) {
                const outputLine = JSON.stringify(line);
                setServerOutputs(prev => {
                  const oldOutput = prev[gameId] || [];
                  return {
                    ...prev,
                    [gameId]: [...oldOutput, `[对象] ${outputLine}`]
                  };
                });
              }
            },
            () => {
              message.success(`${game.name} 服务器已停止`);
              // 立即更新UI中的服务器状态
              setRunningServers(prev => prev.filter(id => id !== gameId));
              // 然后再刷新实际状态
              setTimeout(() => refreshServerStatus(), 500);
              serverEventSourceRef.current = null;
            },
            (error) => {
              console.error(`服务器输出错误: ${error.message}`);
              
              // 向输出窗口添加错误信息
              setServerOutputs(prev => {
                const oldOutput = prev[gameId] || [];
                return {
                  ...prev,
                  [gameId]: [
                    ...oldOutput, 
                    `错误: ${error.message}`, 
                    "如果看到'启动失败'错误，请检查启动脚本和配置文件是否正确，并确保权限设置合适"
                  ]
                };
              });
              
              // 显示错误消息
              message.error(`${game.name} 服务器错误: ${error.message}`);
              
              // 发生错误时也刷新状态
              // 立即更新UI中的服务器状态
              setRunningServers(prev => prev.filter(id => id !== gameId));
              // 然后再刷新实际状态
              setTimeout(() => refreshServerStatus(), 500);
              // 清除EventSource引用
              serverEventSourceRef.current = null;
            },
            true,
            reconnect,
            scriptName
          );
          
          // 保存EventSource引用
          if (result && !('multipleScripts' in result)) {
            serverEventSourceRef.current = result;
          }
          
          return;
        }
      } catch (error) {
        console.error(`检查服务器状态失败: ${error}`);
        // 继续尝试启动服务器
      }
      
      // 如果是重新连接，不清空之前的输出
      if (!reconnect) {
        // console.log(`清空之前的输出: gameId=${gameId}`);
        // 清空之前的输出
        setServerOutputs(prev => ({
          ...prev,
          [gameId]: []
        }));
      } else {
        // console.log(`重新连接，保留之前的输出: gameId=${gameId}, 当前输出行数=${serverOutputs[gameId]?.length || 0}`);
        // 添加一条分隔线
        setServerOutputs(prev => {
          const oldOutput = prev[gameId] || [];
          return {
            ...prev,
            [gameId]: [...oldOutput, "--- 重新连接到服务器 ---"]
          };
        });
      }
      
      // 启动服务器并获取输出流
      const result = await startServer(
        gameId,
        (line) => {
          // console.log(`接收到服务器输出行: ${typeof line === 'string' ? (line.substring(0, 50) + (line.length > 50 ? '...' : '')) : JSON.stringify(line)}`);
          
          // 处理不同类型的输出行
          if (typeof line === 'string') {
            setServerOutputs(prev => {
              const oldOutput = prev[gameId] || [];
              // 检查是否为历史记录
              if (line.includes('[历史记录]')) {
                return {
                  ...prev,
                  [gameId]: [...oldOutput, line]
                };
              } else {
                return {
                  ...prev,
                  [gameId]: [...oldOutput, line]
                };
              }
            });
          } else if (typeof line === 'object' && line !== null) {
            // 处理对象类型的输出
            const outputLine = JSON.stringify(line);
            setServerOutputs(prev => {
              const oldOutput = prev[gameId] || [];
              return {
                ...prev,
                [gameId]: [...oldOutput, `[对象] ${outputLine}`]
              };
            });
          }
        },
        () => {
          // console.log(`服务器输出完成: gameId=${gameId}`);
          message.success(`${game.name} 服务器已停止`);
          // 服务器停止时刷新状态
          refreshServerStatus();
          // 清除EventSource引用
          serverEventSourceRef.current = null;
        },
        (error) => {
          console.error(`服务器输出错误: ${error.message}`);
          handleError(error);
          // 发生错误时也刷新状态
          refreshServerStatus();
          // 清除EventSource引用
          serverEventSourceRef.current = null;
        },
        true,  // 始终包含历史输出
        reconnect,  // 传递reconnect参数作为restart参数
        scriptName  // 传递脚本名称
      );
      
      // 处理多个脚本的情况
      if (result && 'multipleScripts' in result && result.multipleScripts && result.scripts) {
        // 弹出选择框让用户选择要执行的脚本
        Modal.confirm({
          title: '选择启动脚本',
          content: (
            <div>
              <p>{result.message || '请选择要执行的脚本：'}</p>
              <List
                bordered
                dataSource={result.scripts}
                renderItem={script => (
                  <List.Item 
                    className="server-script-item"
                    onClick={() => {
                      Modal.destroyAll();
                      // 用户选择后启动对应脚本
                      handleStartServer(
                        gameId, 
                        'reconnect' in result ? result.reconnect : reconnect, 
                        script
                      );
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    <Typography.Text strong>{script}</Typography.Text>
                  </List.Item>
                )}
              />
            </div>
          ),
          okText: '取消',
          cancelText: null,
          okCancel: false,
        });
        return;
      }
      
      // 保存EventSource引用
      if (result && !('multipleScripts' in result)) {
        serverEventSourceRef.current = result;
        
        // 服务器启动后立即刷新状态列表
        if (!reconnect) {
          // console.log(`服务器启动成功: gameId=${gameId}`);
          message.success(`${game.name} 服务器启动成功`);
        } else {
          // console.log(`重新连接到服务器: gameId=${gameId}`);
          message.success(`已重新连接到 ${game.name} 服务器`);
        }
        
        // 添加到运行中服务器列表
        setRunningServers(prev => {
          if (!prev.includes(gameId)) {
            return [...prev, gameId];
          }
          return prev;
        });
        
        // 延迟再次刷新以确保状态更新
        setTimeout(() => {
          refreshServerStatus();
        }, 2000);
      }
      
    } catch (error) {
      console.error(`启动服务器失败: ${error}`);
      handleError(error);
    }
  };

  // 添加一个清理服务器输出的函数
  const clearServerOutput = useCallback((gameId: string) => {
    setServerOutputs(prev => ({
      ...prev,
      [gameId]: []
    }));
  }, []);

  const handleStopServer = useCallback(async (gameId: string, force = false) => {
    try {
      // 如果不是强制停止，先显示确认对话框
      if (!force) {
        Modal.confirm({
          title: '停止服务器',
          content: (
            <div>
              <p>请选择停止服务器的方式：</p>
              <p>- 标准停止：发送Ctrl+C到控制台，让服务器正常退出</p>
              <p>- 强行停止：直接杀死进程，可能导致数据丢失</p>
            </div>
          ),
          okText: '标准停止',
          cancelText: '取消',
          okButtonProps: { type: 'primary' },
          onOk: async () => {
            // 显示加载消息
            const loadingKey = `stopping_${gameId}`;
            message.loading({ content: '正在停止服务器...', key: loadingKey, duration: 0 });
            
            // 立即在UI中反映状态变化，提高响应速度
            setRunningServers(prev => prev.filter(id => id !== gameId));
            
            const response = await stopServer(gameId, false);
            
            if (response.status === 'success') {
              message.success({ content: `服务器已标准停止`, key: loadingKey });
              // 刷新服务器状态
              setTimeout(() => refreshServerStatus(), 500);
              // 清空服务器输出
              clearServerOutput(gameId);
            } else if (response.status === 'warning') {
              // 处理警告状态，例如服务器未响应标准停止
              message.warning({ content: response.message || '服务器可能未完全停止', key: loadingKey });
              Modal.confirm({
                title: '停止服务器警告',
                content: response.message || '服务器未完全停止，是否尝试强行停止？',
                okText: '强行停止',
                cancelText: '取消',
                okButtonProps: { danger: true },
                onOk: () => handleStopServer(gameId, true),
              });
              // 刷新服务器状态以确认实际状态
              setTimeout(() => refreshServerStatus(), 500);
            } else {
              message.error({ content: response.message || '停止服务器失败', key: loadingKey });
              // 刷新服务器状态以确认实际状态
              setTimeout(() => refreshServerStatus(), 500);
            }
          },
          footer: (_, { OkBtn, CancelBtn }) => (
            <>
              <Button danger onClick={() => handleStopServer(gameId, true)}>强行停止</Button>
              <CancelBtn />
              <OkBtn />
            </>
          ),
        });
        return;
      }
      
      // 显示加载消息
      const loadingKey = `stopping_${gameId}`;
      message.loading({ content: `正在强制停止服务器...`, key: loadingKey, duration: 0 });
      
      // 立即在UI中反映状态变化，提高响应速度
      setRunningServers(prev => prev.filter(id => id !== gameId));
      
      // 发送停止请求
      const response = await stopServer(gameId, force);
      
      if (response.status === 'success') {
        message.success({ content: `服务器已强制停止`, key: loadingKey });
        // 刷新服务器状态
        setTimeout(() => refreshServerStatus(), 500);
        // 清空服务器输出
        clearServerOutput(gameId);
        
        // 检查是否有隐藏的服务器仍在运行警告
        if (response._serverStillRunning) {
          // 处理警告状态，服务器可能仍在运行
          Modal.confirm({
            title: '服务器可能仍在运行',
            content: '服务器报告已停止，但状态检查显示可能仍在运行。是否尝试再次强制停止？',
            okText: '再次强制停止',
            cancelText: '忽略',
            okButtonProps: { danger: true },
            onOk: () => handleStopServer(gameId, true),
          });
        }
      } else if (response.status === 'warning') {
        // 处理警告状态，例如服务器未响应标准停止
        message.warning({ content: response.message || '服务器可能未完全停止', key: loadingKey });
        Modal.confirm({
          title: '停止服务器警告',
          content: response.message || '服务器未完全停止，是否再次尝试强行停止？',
          okText: '再次强制停止',
          cancelText: '取消',
          okButtonProps: { danger: true },
          onOk: () => handleStopServer(gameId, true),
        });
        // 刷新服务器状态以确认实际状态
        setTimeout(() => refreshServerStatus(), 500);
      } else {
        message.error({ content: response.message || '停止服务器失败', key: loadingKey });
        // 刷新服务器状态以确认实际状态
        setTimeout(() => refreshServerStatus(), 500);
      }
    } catch (error) {
      // 即使出错也刷新服务器状态
      setTimeout(() => refreshServerStatus(), 500);
      handleError(error);
    }
  }, [refreshServerStatus, clearServerOutput]);

  const handleServerInput = useCallback(async (gameId: string, value: string) => {
    try {
      await sendServerInput(gameId, value);
    } catch (e: any) {
      message.error(e?.message || '发送输入失败');
    }
  }, []);

  // 渲染游戏卡片安装按钮 (用于游戏安装页面)
  const renderGameButtons = (game: GameInfo) => {
    // 添加调试代码
    const primaryBtnStyle = {
      background: 'linear-gradient(90deg, #1677ff 0%, #69b1ff 100%)',
      color: 'white',
      padding: '5px 15px',
      border: 'none',
      borderRadius: '2px',
      cursor: 'pointer',
      fontSize: '14px'
    };
    
    const defaultBtnStyle = {
      background: '#f0f0f0',
      color: '#000',
      padding: '5px 15px',
      border: '1px solid #d9d9d9',
      borderRadius: '2px',
      cursor: 'pointer',
      marginRight: '8px',
      fontSize: '14px'
    };
    
    if (installedGames.includes(game.id)) {
      return (
        <>
          <button 
            style={defaultBtnStyle}
            onClick={() => handleUninstall(game)}
          >卸载</button>
          <button 
            style={primaryBtnStyle}
            onClick={() => handleInstall(game)}
          >{installOutputs[game.id]?.installing ? '安装中...' : '更新'}</button>
        </>
      );
    }
    return (
      <button 
        style={primaryBtnStyle}
        onClick={(e) => {
          e.stopPropagation();
          if (!installOutputs[game.id]?.installing) {
            handleInstallClick(game);
          }
        }}
      >
        {installOutputs[game.id]?.installing ? '安装中...' : '安装'}
      </button>
    );
  };

  // 服务器管理按钮已内联到各个使用位置

  // 服务器管理Tab内容
  const renderServerManager = () => (
    <div style={{marginTop: 32}}>
      <Title level={3}>已安装的游戏</Title>
      <Row gutter={[isMobile ? 8 : 16, isMobile ? 8 : 16]}>
        {/* 固定显示SteamCMD */}
        <Col xs={24} sm={12} md={8} lg={6} key="steamcmd">
          <Card
            hoverable
            className="game-card"
            title={
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>SteamCMD</span>
                <Tag color="blue">工具</Tag>
              </div>
            }
            style={{ borderRadius: '8px', overflow: 'hidden' }}
          >
            <p>Steam游戏服务器命令行工具</p>
            <p>位置: /home/steam/steamcmd</p>
            <Button 
              type="primary" 
              size="small"
              onClick={() => handleStartSteamCmd()}
            >
              启动
            </Button>
          </Card>
        </Col>
        
        {/* 显示配置中的已安装游戏 */}
        {games.filter(g => installedGames.includes(g.id)).map(game => (
          <Col xs={24} sm={12} md={8} lg={6} key={game.id}>
            <Card
              hoverable
              className="game-card"
              title={
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>{game.name}</span>
                  {runningServers.includes(game.id) ? (
                    <Tag color="green">运行中</Tag>
                  ) : (
                    <Tag color="default">未运行</Tag>
                  )}
                </div>
              }
              size={isMobile ? "small" : "default"}
              style={{ borderRadius: '8px', overflow: 'hidden' }}
            >
              <p>位置: /home/steam/games/{game.id}</p>
              {runningServers.includes(game.id) ? (
                <div>
                  <div style={{marginBottom: 8}}>
                    <Button 
                      danger
                      size="small"
                      onClick={() => handleUninstall(game.id)}
                    >
                      卸载
                    </Button>
                    <span style={{marginLeft: 8}}>
                      自启动: 
                      <Switch 
                        size="small" 
                        checked={autoRestartServers.includes(game.id)}
                        onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                        style={{marginLeft: 4}}
                      />
                    </span>
                  </div>
                  <Button 
                    type="default" 
                    size="small" 
                    style={{marginRight: 8}}
                    onClick={() => handleStopServer(game.id)}
                  >
                    停止
                  </Button>
                  <Button 
                    type="primary" 
                    size="small"
                    style={{marginRight: 8}}
                    onClick={() => handleStartServer(game.id)}
                  >
                    控制台
                  </Button>
                  <Button
                    icon={<FolderOutlined />}
                    size="small"
                    onClick={() => handleOpenGameFolder(game.id)}
                  >
                    文件夹
                  </Button>
                </div>
              ) : (
                <div>
                  <div style={{marginBottom: 8}}>
                    <Button 
                      danger
                      size="small"
                      onClick={() => handleUninstall(game.id)}
                    >
                      卸载
                    </Button>
                    <span style={{marginLeft: 8}}>
                      自启动: 
                      <Switch 
                        size="small" 
                        checked={autoRestartServers.includes(game.id)}
                        onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                        style={{marginLeft: 4}}
                      />
                    </span>
                  </div>
                  <Button 
                    type="primary" 
                    size="small"
                    style={{marginRight: 8}}
                    onClick={() => handleStartServer(game.id)}
                  >
                    启动
                  </Button>
                  <Button
                    icon={<FolderOutlined />}
                    size="small"
                    onClick={() => handleOpenGameFolder(game.id)}
                  >
                    文件夹
                  </Button>
                </div>
              )}
            </Card>
          </Col>
        ))}

        {/* 显示外部游戏 */}
        {externalGames.map(game => (
          <Col xs={24} sm={12} md={8} lg={6}>
            <Card
              hoverable
              className="game-card"
              title={
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>{game.name}</span>
                  <Tag color="orange">外来</Tag>
                </div>
              }
              style={{ borderRadius: '8px', overflow: 'hidden' }}
            >
              <p>位置: /home/steam/games/{game.id}</p>
              <div style={{marginTop: 12}}>
                <div style={{marginBottom: 8}}>服务器控制:</div>
                {runningServers.includes(game.id) ? (
                  <div>
                    <div style={{marginBottom: 8}}>
                      <Button 
                        danger
                        size="small"
                        onClick={() => handleUninstall(game.id)}
                      >
                        卸载
                      </Button>
                      <span style={{marginLeft: 8}}>
                        自启动: 
                        <Switch 
                          size="small" 
                          checked={autoRestartServers.includes(game.id)}
                          onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                          style={{marginLeft: 4}}
                        />
                      </span>
                    </div>
                    <Button 
                      type="default" 
                      size="small" 
                      style={{marginRight: 8}}
                      onClick={() => handleStopServer(game.id)}
                    >
                      停止
                    </Button>
                    <Button 
                      type="primary" 
                      size="small"
                      style={{marginRight: 8}}
                      onClick={() => handleStartServer(game.id)}
                    >
                      控制台
                    </Button>
                    <Button
                      icon={<FolderOutlined />}
                      size="small"
                      onClick={() => handleOpenGameFolder(game.id)}
                    >
                      文件夹
                    </Button>
                  </div>
                ) : (
                  <div>
                    <div style={{marginBottom: 8}}>
                      <Button 
                        danger
                        size="small"
                        onClick={() => handleUninstall(game.id)}
                      >
                        卸载
                      </Button>
                      <span style={{marginLeft: 8}}>
                        自启动: 
                        <Switch 
                          size="small" 
                          checked={autoRestartServers.includes(game.id)}
                          onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                          style={{marginLeft: 4}}
                        />
                      </span>
                    </div>
                    <div style={{display: 'flex', justifyContent: 'center'}}>
                      <Button 
                        type="primary"
                        size="middle"
                        style={{marginRight: 8, width: '45%'}}
                        onClick={() => handleStartServer(game.id)}
                      >
                        启动
                      </Button>
                      <Button
                        icon={<FolderOutlined />}
                        size="middle"
                        style={{width: '45%'}}
                        onClick={() => handleOpenGameFolder(game.id)}
                      >
                        文件夹
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          </Col>
        ))}

        {games.filter(g => installedGames.includes(g.id)).length === 0 && externalGames.length === 0 && (
          <Col span={24}><p>除了SteamCMD外，暂无已安装的游戏。</p></Col>
        )}
      </Row>
    </div>
  );

  // 发送验证码/令牌到后端
  const handleSendInput = async (gameId: string, value: string) => {
    try {
      await axios.post('/api/send_input', { game_id: gameId, value });
      message.success('已提交验证码/令牌');
    } catch (e: any) {
      message.error(e?.response?.data?.message || e?.message || '提交失败');
    }
  };

  // 添加终止安装函数
  const handleTerminateInstall = useCallback(async (gameId: string) => {
    if (!gameId) return;
    
    try {
      const success = await terminateInstall(gameId);
      
      if (success) {
        message.success('安装已终止');
        // 更新安装状态
        setInstallOutputs(prev => ({
          ...prev,
          [gameId]: {
            ...prev[gameId],
            installing: false,
            complete: true,
            output: [...(prev[gameId]?.output || []), '安装已被用户手动终止']
          }
        }));
      } else {
        message.error('终止安装失败');
      }
    } catch (error) {
      handleError(error);
    }
  }, []);

  // 处理显示游戏详情
  const handleShowDetail = (game: GameInfo) => {
    setDetailGame(game);
    setDetailModalVisible(true);
  };

  // 处理在Steam中打开
  const handleOpenInSteam = (url: string, appid: string) => {
    // 如果url不完整，使用appid构建完整的Steam商店URL
    const fullUrl = url.includes('store.steampowered.com') 
      ? url 
      : `https://store.steampowered.com/app/${appid}`;
      
    // 直接在新窗口打开Steam页面
    window.open(fullUrl, '_blank', 'noopener,noreferrer');
  };

  // 添加通过AppID安装的处理函数
  const handleInstallByAppId = useCallback(async (values: any) => {
    try {
      setAppIdInstalling(true);
      setTerminalVisible(true);
      
      // 创建一个临时的游戏ID
      const gameId = `app_${values.appid}`;
      
      // 重置该游戏的安装输出
      setInstallOutputs(prev => ({
        ...prev,
        [gameId]: { output: [], complete: false, installing: true }
      }));
      
      // 调用API安装游戏
      await installByAppId(
        values.appid,
        values.name,
        values.anonymous,
        (line) => {
          // console.log('SSE output:', line);
          setInstallOutputs(prev => {
            const old = prev[gameId]?.output || [];
            return {
              ...prev,
              [gameId]: {
                ...prev[gameId],
                output: [...old, line],
                installing: true,
                complete: false
              }
            };
          });
        },
        () => {
          setInstallOutputs(prev => ({
            ...prev,
            [gameId]: {
              ...prev[gameId],
              installing: false,
              complete: true
            }
          }));
          message.success(`${values.name} (AppID: ${values.appid}) 安装完成`);
          // 刷新已安装游戏列表
          axios.get('/api/installed_games').then(res => {
            if (res.data.status === 'success') {
              setInstalledGames(res.data.installed || []);
              setExternalGames(res.data.external || []);
            }
          });
        },
        (error) => {
          setInstallOutputs(prev => ({
            ...prev,
            [gameId]: {
              ...prev[gameId],
              installing: false,
              complete: true
            }
          }));
          handleError(error);
        },
        !values.anonymous ? values.account : undefined,
        !values.anonymous ? values.password : undefined
      );
      
      // 创建一个临时游戏对象用于显示
      const tempGame: GameInfo = {
        id: gameId,
        name: values.name,
        appid: values.appid,
        anonymous: values.anonymous,
        has_script: false,
        external: false,
        tip: `通过AppID ${values.appid} 手动安装的游戏`
      };
      
      // 设置为当前选中的游戏，以便显示安装输出
      setSelectedGame(tempGame);
      
      message.success(`已开始安装 ${values.name} (AppID: ${values.appid})`);
    } catch (error) {
      handleError(error);
    } finally {
      setAppIdInstalling(false);
    }
  }, []);

  // 监听打开文件管理器的事件
  useEffect(() => {
    const handleOpenFileManager = (event: CustomEvent) => {
      // const timestamp = () => new Date().toLocaleTimeString();
      // console.log(`${timestamp()} APP: handleOpenFileManager EVENT received. Detail:`, event.detail);
      const path = event.detail?.path;
      if (path && typeof path === 'string' && path.startsWith('/')) {
        setFileManagerPath(path); // Uses wrapped setter
      } else {
        setFileManagerPath('/home/steam'); // Uses wrapped setter
      }
      setFileManagerVisible(true); // Uses wrapped setter
      // This should primarily control the Modal's visibility.
      // It should NOT directly change currentNav if it's a true "nested window".
    };

    window.addEventListener('openFileManager', handleOpenFileManager as EventListener);
    
    return () => {
      window.removeEventListener('openFileManager', handleOpenFileManager as EventListener);
    };
  }, []);

  // 添加处理打开文件夹的函数
  const handleOpenGameFolder = async (gameId: string) => {
    // const timestamp = () => new Date().toLocaleTimeString();
    // console.log(`${timestamp()} APP: handleOpenGameFolder called for gameId: ${gameId}`);
    try {
      const gamePath = `/home/steam/games/${gameId}`;
      setFileManagerPath(gamePath);    // Uses wrapped setter
      setFileManagerVisible(true); // Uses wrapped setter - this should open the Modal
      message.info(`准备打开文件管理器: ${gamePath}`);
      // setCurrentNav('files'); // We DON'T want to do this if it's a modal/nested window
    } catch (error) {
      message.error(`打开游戏文件夹失败: ${error}`);
    }
  };

  // 处理注册成功
  const handleRegisterSuccess = (token: string, username: string, role: string) => {
    setAuthenticated(token, username, role);
    message.success('注册成功，欢迎使用游戏容器！');
  };

  // 备份相关处理函数
  const refreshBackupTasks = useCallback(async () => {
    try {
      const response = await axios.get('/api/backup/tasks');
      if (response.data.status === 'success') {
        setBackupTasks(response.data.tasks || []);
      }
    } catch (error) {
      console.error('获取备份任务失败:', error);
      message.error('获取备份任务失败');
    }
  }, []);

  const handleToggleBackupTask = async (taskId: string) => {
    try {
      const response = await axios.post(`/api/backup/tasks/${taskId}/toggle`);
      if (response.data.status === 'success') {
        const task = response.data.task;
        const statusText = task.enabled ? '启用' : '禁用';
        message.success(`备份任务已${statusText}`);
        refreshBackupTasks();
      }
    } catch (error) {
      console.error('切换备份任务状态失败:', error);
      message.error('操作失败');
    }
  };

  const handleRunBackupNow = async (taskId: string) => {
    try {
      const response = await axios.post(`/api/backup/tasks/${taskId}/run`);
      if (response.data.status === 'success') {
        message.success('备份任务已启动');
      }
    } catch (error) {
      console.error('启动备份任务失败:', error);
      message.error('启动备份任务失败');
    }
  };

  const handleEditBackupTask = (task: any) => {
    setEditingBackupTask(task);
    
    // 从后端的interval值推导出intervalValue和intervalUnit
    let intervalValue = task.intervalValue || task.interval;
    let intervalUnit = task.intervalUnit || 'hours';
    
    // 如果没有保存的单位信息，根据interval值推导
    if (!task.intervalValue && !task.intervalUnit) {
      const hours = task.interval;
      if (hours < 1) {
        // 小于1小时，转换为分钟
        intervalValue = Math.round(hours * 60);
        intervalUnit = 'minutes';
      } else if (hours >= 24 && hours % 24 === 0) {
        // 整数天，转换为天数
        intervalValue = hours / 24;
        intervalUnit = 'days';
      } else {
        // 保持小时
        intervalValue = hours;
        intervalUnit = 'hours';
      }
    }
    
    backupForm.setFieldsValue({
      name: task.name,
      directory: task.directory,
      intervalValue: intervalValue,
      intervalUnit: intervalUnit,
      keepCount: task.keepCount,
      linkedServerId: task.linkedServerId,
      autoControl: task.autoControl
    });
    setBackupModalVisible(true);
  };

  const handleDeleteBackupTask = async (taskId: string) => {
    try {
      const response = await axios.delete(`/api/backup/tasks/${taskId}`);
      if (response.data.status === 'success') {
        message.success('备份任务已删除');
        refreshBackupTasks();
      }
    } catch (error) {
      console.error('删除备份任务失败:', error);
      message.error('删除备份任务失败');
    }
  };

  const handleBackupFormSubmit = async (values: any) => {
    try {
      const url = editingBackupTask 
        ? `/api/backup/tasks/${editingBackupTask.id}` 
        : '/api/backup/tasks';
      const method = editingBackupTask ? 'put' : 'post';
      
      // 转换时间单位为小时
      let intervalInHours = values.intervalValue;
      if (values.intervalUnit === 'minutes') {
        intervalInHours = values.intervalValue / 60;
      } else if (values.intervalUnit === 'days') {
        intervalInHours = values.intervalValue * 24;
      }
      
      // 构建发送给后端的数据
      const submitData = {
        ...values,
        interval: intervalInHours,
        intervalValue: values.intervalValue,
        intervalUnit: values.intervalUnit
      };
      
      const response = await axios[method](url, submitData);
      if (response.data.status === 'success') {
        message.success(editingBackupTask ? '备份任务已更新' : '备份任务已创建');
        setBackupModalVisible(false);
        setEditingBackupTask(null);
        backupForm.resetFields();
        refreshBackupTasks();
      }
    } catch (error) {
      console.error('保存备份任务失败:', error);
      message.error('保存备份任务失败');
    }
  };

  // 文件收藏相关处理函数
  const refreshFavoriteFiles = useCallback(async () => {
    try {
      const response = await axios.get('/api/settings/favorite-files');
      if (response.data.status === 'success') {
        setFavoriteFiles(response.data.favorite_files || []);
      } else {
        console.error('获取收藏文件失败:', response.data.message);
        message.error('获取收藏文件失败');
      }
    } catch (error) {
      console.error('获取收藏文件失败:', error);
      message.error('获取收藏文件失败');
    }
  }, []);

  const handleAddFavoriteFile = () => {
    setEditingFavorite(null);
    favoriteForm.resetFields();
    setFavoriteModalVisible(true);
  };

  const handleEditFavoriteFile = (favorite: any) => {
    setEditingFavorite(favorite);
    favoriteForm.setFieldsValue({
      name: favorite.name,
      filePath: favorite.filePath,
      description: favorite.description
    });
    setFavoriteModalVisible(true);
  };

  const handleDeleteFavoriteFile = async (favoriteId: string) => {
    try {
      const updatedFavorites = favoriteFiles.filter(f => f.id !== favoriteId);
      
      const response = await axios.post('/api/settings/favorite-files', {
        favorite_files: updatedFavorites
      });
      
      if (response.data.status === 'success') {
        setFavoriteFiles(updatedFavorites);
        message.success('收藏文件已删除');
      } else {
        console.error('删除收藏文件失败:', response.data.message);
        message.error('删除收藏文件失败');
      }
    } catch (error) {
      console.error('删除收藏文件失败:', error);
      message.error('删除收藏文件失败');
    }
  };

  const handleFavoriteFormSubmit = async (values: any) => {
    try {
      // 验证必填字段
      if (!values.name || !values.name.trim()) {
        message.error('请输入文件备注');
        return;
      }
      if (!values.filePath || !values.filePath.trim()) {
        message.error('请输入文件路径');
        return;
      }

      const favoriteData = {
        id: editingFavorite ? editingFavorite.id : Date.now().toString(),
        name: values.name.trim(),
        filePath: values.filePath.trim(),
        description: values.description ? values.description.trim() : '',
        createdAt: editingFavorite ? editingFavorite.createdAt : new Date().toISOString()
      };

      let updatedFavorites;
      if (editingFavorite) {
        updatedFavorites = favoriteFiles.map(f => f.id === editingFavorite.id ? favoriteData : f);
      } else {
        updatedFavorites = [...favoriteFiles, favoriteData];
      }

      const response = await axios.post('/api/settings/favorite-files', {
        favorite_files: updatedFavorites
      });
      
      if (response.data.status === 'success') {
        setFavoriteFiles(updatedFavorites);
        message.success(editingFavorite ? '收藏文件已更新' : '收藏文件已添加');
        setFavoriteModalVisible(false);
        setEditingFavorite(null);
        favoriteForm.resetFields();
      } else {
        console.error('保存收藏文件失败:', response.data.message);
        message.error('保存收藏文件失败');
      }
    } catch (error) {
      console.error('保存收藏文件失败:', error);
      message.error('保存收藏文件失败');
    }
  };

  const handleOpenFavoriteFile = (favorite: any) => {
    // 提取目录路径
    const dirPath = favorite.filePath.substring(0, favorite.filePath.lastIndexOf('/'));
    setFileManagerPath(dirPath || '/home/steam');
    setInitialFileToOpen(favorite.filePath);
    setFileManagerVisible(true);
    message.success(`正在打开文件: ${favorite.name}`);
  };

  // 清除initialFileToOpen状态，确保文件打开后状态被重置
  useEffect(() => {
    if (!fileManagerVisible && initialFileToOpen) {
      setInitialFileToOpen(undefined);
    }
  }, [fileManagerVisible, initialFileToOpen]);

  // 初始化
  useEffect(() => {
    // 如果已登录，加载游戏列表
    if (isAuthenticated) {
      // 并行加载游戏列表和已安装游戏
      const loadGames = async () => {
        setGameLoading(true);
        try {
          const [gameResp, installedResp] = await Promise.all([
            axios.get('/api/games'),
            axios.get('/api/installed_games')
          ]);
          
          // 检查游戏列表来源
          if (gameResp.data.status === 'success') {
            setGames(gameResp.data.games || []);
            
            // 删除重复的消息提示，因为在前面的useEffect中已经有了
            // 但仍然需要处理cloud_error
            if (gameResp.data.source === 'local' && gameResp.data.cloud_error) {
              // 不显示消息，因为在前面的useEffect中已经有消息提示了
            }
          }
          
          if (installedResp.data.status === 'success') {
            setInstalledGames(installedResp.data.installed || []);
            setExternalGames(installedResp.data.external || []);  // 设置外部游戏
          }
          
          // 初始化每个游戏的installOutputs
          const initialOutputs: {[key: string]: InstallOutput} = {};
          if (gameResp.data.games) {
            gameResp.data.games.forEach((game: GameInfo) => {
              initialOutputs[game.id] = {
                output: [],
                complete: false,
                installing: false
              };
            });
          }
          setInstallOutputs(initialOutputs);
          
        } catch (error) {
          // 简化错误处理，避免重复消息
          message.error('加载游戏列表失败，请刷新或重新登录');
        } finally {
          setGameLoading(false);
        }
      };
      
      loadGames();
      
      // 加载收藏文件
      refreshFavoriteFiles();
    }
  }, [isAuthenticated, refreshFavoriteFiles]);

  // 加载自启动服务器列表
  const loadAutoRestartServers = async () => {
    try {
      const response = await axios.get('/api/server/auto_restart');
      if (response.data.status === 'success') {
        setAutoRestartServers(response.data.auto_restart_servers || []);
      }
    } catch (error) {
      console.error('加载自启动服务器列表失败:', error);
    }
  };

  // 处理自启动开关变化
  const handleAutoRestartChange = async (gameId: string, checked: boolean) => {
    try {
      const response = await axios.post('/api/server/set_auto_restart', {
        game_id: gameId,
        auto_restart: checked
      });
      
      if (response.data.status === 'success') {
        message.success(`已${checked ? '开启' : '关闭'}服务端自启动`);
        // 更新自启动服务器列表
        setAutoRestartServers(prev => {
          if (checked && !prev.includes(gameId)) {
            return [...prev, gameId];
          } else if (!checked) {
            return prev.filter(id => id !== gameId);
          }
          return prev;
        });
      } else {
        message.error(response.data.message || '操作失败');
      }
    } catch (error) {
      console.error('设置自启动失败:', error);
      message.error('设置自启动失败');
    }
  };

  // 添加定期刷新服务器状态
  useEffect(() => {
    // 初始加载时刷新一次服务器状态
    refreshServerStatus();
    
    // 加载自启动服务器列表
    loadAutoRestartServers();
    
    // 设置定时器，根据运行服务器数量调整刷新频率，避免频繁刷新
    const interval = setInterval(() => {
      // 只在当前页面是服务器管理或仪表盘时刷新
      if (currentNav === 'servers' || currentNav === 'dashboard') {
        // 根据运行中的服务器数量调整刷新间隔
        if (runningServers.length > 0) {
          // 有服务器运行时，降低刷新频率，避免卡顿
          const now = Date.now();
          if (now - lastRefreshTimeRef.current >= 30000) { // 至少30秒刷新一次
            refreshServerStatus();
          }
        } else {
          // 没有服务器运行时，可以适当提高刷新频率
          refreshServerStatus();
        }
      }
    }, 15000); // 基础间隔为15秒
    
    // 组件卸载时清除定时器
    return () => clearInterval(interval);
  }, [refreshServerStatus, currentNav, runningServers.length]);
  
  // 服务端状态刷新优化总结：
  // 1. 使用防抖机制避免短时间内多次触发刷新，通过isRefreshingRef和lastRefreshTimeRef控制
  // 2. 根据运行服务器数量动态调整刷新频率，有服务器运行时降低频率至少30秒一次
  // 3. 添加请求超时处理，避免请求挂起导致页面卡顿
  // 4. 在切换标签页时检查上次刷新时间，避免频繁刷新
  // 5. 后端添加缓存机制，减少计算密集型操作（如游戏空间计算）
  // 6. 使用AbortController实现请求取消，防止请求堆积

  // 当切换到服务器tab时刷新状态，但避免重复刷新
  useEffect(() => {
    if (currentNav === 'servers') {
      // 使用setTimeout避免可能的渲染冲突
      const timer = setTimeout(() => {
        // 检查距离上次刷新的时间，如果小于5秒则跳过
        const now = Date.now();
        if (now - lastRefreshTimeRef.current >= 5000) {
          console.log('切换到服务器管理页面，刷新服务器状态');
          refreshServerStatus();
        } else {
          console.log('切换到服务器管理页面，但上次刷新时间太近，跳过刷新');
        }
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [currentNav, refreshServerStatus, lastRefreshTimeRef]);

  // 添加标签页切换处理函数
  const handleTabChange = useCallback((key: string) => {
    setTabKey(key);
    // 如果切换到"正在运行服务端"标签页，刷新服务器状态
    if (key === 'running') {
      // 检查距离上次刷新的时间，如果小于5秒则跳过
      const now = Date.now();
      if (now - lastRefreshTimeRef.current >= 5000) {
        console.log('切换到正在运行服务端标签页，刷新服务器状态');
        refreshServerStatus();
      } else {
        console.log('切换到正在运行服务端标签页，但上次刷新时间太近，跳过刷新');
      }
    }
  }, [refreshServerStatus, lastRefreshTimeRef]);

  const [frpDocModalVisible, setFrpDocModalVisible] = useState<boolean>(false);
  
  // 版本检查相关状态
  const [versionUpdateModalVisible, setVersionUpdateModalVisible] = useState<boolean>(false);
  const [latestVersionInfo, setLatestVersionInfo] = useState<{version: string, description: any} | null>(null);
  const [downloadingImage, setDownloadingImage] = useState<boolean>(false);
  const currentVersion = '2.4.1'; // 当前版本号
  
  // 版本检查功能
  const checkForUpdates = async () => {
    try {
      const response = await checkVersionUpdate();
      
      // 如果返回skip状态，说明没有赞助者密钥，静默跳过
      if (response && response.status === 'skip') {
        console.log('跳过版本检查:', response.message);
        return;
      }
      
      // 如果有版本信息且版本不同，显示更新弹窗
      if (response && response.version && response.version !== currentVersion) {
        setLatestVersionInfo(response);
        setVersionUpdateModalVisible(true);
      }
    } catch (error) {
      // 静默处理版本检查错误，不影响用户体验
      console.warn('版本检查失败:', error);
    }
  };
  
  // 下载镜像功能
  const handleDownloadImage = async () => {
    try {
      setDownloadingImage(true);
      message.loading('正在下载并导入镜像，请稍候...', 0);
      
      const response = await downloadDockerImage();
      
      message.destroy(); // 清除loading消息
      
      if (response && response.status === 'success') {
        message.success(response.message);
        
        // 如果有Docker命令，显示复制对话框
        if (response.docker_command) {
          Modal.info({
            title: '镜像下载成功',
            content: (
              <div>
                <p>镜像已成功下载并导入，请复制以下命令手动执行：</p>
                <div style={{
                  background: '#f5f5f5',
                  padding: '12px',
                  borderRadius: '6px',
                  fontFamily: 'monospace',
                  fontSize: '12px',
                  wordBreak: 'break-all',
                  marginTop: '12px'
                }}>
                  {response.docker_command}
                </div>
                <Button 
                  type="primary" 
                  style={{ marginTop: '12px' }}
                  onClick={() => {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                      navigator.clipboard.writeText(response.docker_command!).then(() => {
                        message.success('命令已复制到剪贴板');
                      }).catch(() => {
                        message.error('复制失败，请手动复制');
                      });
                    } else {
                      // 降级方案
                      try {
                        const textArea = document.createElement('textarea');
                        textArea.value = response.docker_command!;
                        textArea.style.position = 'fixed';
                        textArea.style.opacity = '0';
                        document.body.appendChild(textArea);
                        textArea.focus();
                        textArea.select();
                        const successful = document.execCommand('copy');
                        document.body.removeChild(textArea);
                        
                        if (successful) {
                          message.success('命令已复制到剪贴板');
                        } else {
                          message.error('复制失败，请手动复制');
                        }
                      } catch (err) {
                        message.error('复制失败，请手动复制');
                      }
                    }
                  }}
                >
                  复制命令
                </Button>
              </div>
            ),
            width: 600
          });
        }
        
        setVersionUpdateModalVisible(false);
      } else {
        message.error(response?.message || '下载失败');
      }
    } catch (error: any) {
      message.destroy();
      message.error(error?.message || '下载镜像时发生错误');
    } finally {
      setDownloadingImage(false);
    }
  };
  
  // 在用户登录后检查版本更新
  useEffect(() => {
    if (isAuthenticated) {
      // 延迟3秒后检查版本，避免影响应用启动速度
      const timer = setTimeout(() => {
        checkForUpdates();
      }, 3000);
      
      return () => clearTimeout(timer);
    }
  }, [isAuthenticated]);
  
  // 检查是否需要显示内网穿透文档弹窗（仅在首次访问时）
  useEffect(() => {
    const frpDocViewed = Cookies.get('frp_doc_viewed');
    const currentPath = window.location.pathname;
    // 只有当用户访问内网穿透页面且没有查看过文档时才显示
    if (!frpDocViewed && currentPath.includes('/frp')) {
      setFrpDocModalVisible(true);
    }
  }, []);
  
  // 关闭内网穿透文档弹窗
  const handleCloseFrpDocModal = () => {
    setFrpDocModalVisible(false);
  };

  // 如果正在加载认证状态，显示加载中
  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  // 如果是首次使用，显示注册界面 - 强制渲染
  if (isFirstUse === true) {
    // 使用行内样式确保显示，避免样式冲突
    return (
      <div style={{ position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh', zIndex: 9999 }}>
        <Register onRegisterSuccess={handleRegisterSuccess} />
      </div>
    );
  }

  // 如果未认证，显示登录界面
  if (!isAuthenticated) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
        <Card style={{ width: 400, boxShadow: '0 4px 8px rgba(0,0,0,0.1)' }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <Title level={2}>游戏容器登录</Title>
          </div>
          
          <Form
            name="login_form"
            initialValues={{ remember: true }}
            onFinish={(values) => login(values.username, values.password)}
            layout="vertical"
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: '请输入用户名!' }]}
            >
              <Input 
                prefix={<UserOutlined />} 
                placeholder="用户名" 
                size="large"
              />
            </Form.Item>
            
            <Form.Item
              name="password"
              rules={[{ required: true, message: '请输入密码!' }]}
            >
              <Input.Password 
                prefix={<LockOutlined />} 
                placeholder="密码" 
                size="large"
              />
            </Form.Item>
            
            <Form.Item>
              <Button 
                type="primary" 
                htmlType="submit" 
                style={{ width: '100%' }} 
                size="large"
                loading={accountFormLoading}
              >
                登录
              </Button>
            </Form.Item>
          </Form>
        </Card>
      </div>
    );
  }

  // 主应用界面
  return (
    <Layout 
      className={`site-layout ${enableRandomBackground ? 'with-random-bg' : 'without-random-bg'} ${!isUserActive && enableInactiveEffect && enableRandomBackground ? 'user-inactive' : ''}`} 
      style={{ minHeight: '100vh' }}
    >
      {isMobile ? (
        // 移动端侧边栏使用抽屉组件
        <>
          <Header className="site-header">
            <Button 
              type="text" 
              icon={<MenuOutlined />}
              onClick={() => setMobileMenuVisible(true)}
              style={{ fontSize: '16px', padding: '0 8px' }}
            />
            <div className="header-title">
              <img src="/logo/logo.png" alt="GameServerManager" style={{ height: '32px', objectFit: 'contain' }} />
            </div>
            <div className="user-info">
              <Tooltip title={enableRandomBackground ? "关闭随机背景" : "开启随机背景"}>
                <Switch 
                  checkedChildren="背景" 
                  unCheckedChildren="背景" 
                  checked={enableRandomBackground}
                  onChange={(checked) => setEnableRandomBackground(checked)}
                  size="small"
                  style={{marginRight: 8}}
                />
              </Tooltip>
              {enableRandomBackground && (
                <Tooltip title={enableInactiveEffect ? "关闭20秒后自动透明效果" : "开启20秒后自动透明效果"}>
                  <Switch 
                    checkedChildren="透明" 
                    unCheckedChildren="透明" 
                    checked={enableInactiveEffect}
                    onChange={(checked) => setEnableInactiveEffect(checked)}
                    size="small"
                    style={{marginRight: 8}}
                  />
                </Tooltip>
              )}
              <span><UserOutlined /> {username}</span>
              <Button 
                type="link" 
                icon={<LogoutOutlined className="logout-icon" />} 
                onClick={async () => {
                  await logout();
                  navigate('/login');
                }}
                className="logout-btn"
                size={isMobile ? "small" : "middle"}
              >
                {!isMobile && "退出"}
              </Button>
            </div>
          </Header>
          <Drawer
            title="GameServerManager"
            placement="left"
            onClose={() => setMobileMenuVisible(false)}
            visible={mobileMenuVisible}
            bodyStyle={{ padding: 0 }}
          >
            <div className="logo">
              <img src="/logo/logo2.png" alt="GSManager" style={{ height: '50px', objectFit: 'contain' }} />
            </div>
            <Menu
              theme="light"
              mode="inline"
              selectedKeys={[currentNav]}
              onClick={({ key }) => {
                setCurrentNav(key.toString());
                setMobileMenuVisible(false);
                // 当切换到文件管理时，确保设置有效的默认路径
                if (key === 'files' && (!fileManagerPath || fileManagerPath === '')) {
                  setFileManagerPath('/home/steam');
                }
              }}
              items={[
                {
                  key: 'dashboard',
                  icon: <DashboardOutlined />,
                  label: '系统概览'
                },
                {
                  key: 'games',
                  icon: <RocketOutlined />,
                  label: '游戏部署'
                },
                {
                  key: 'environment',
                  icon: <ToolOutlined />,
                  label: '环境安装'
                },
                {
                  key: 'servers',
                  icon: <PlayCircleOutlined />,
                  label: '服务端管理'
                },
                {
                  key: 'game-config',
                  icon: <SettingOutlined />,
                  label: '游戏配置文件'
                },
                {
                  key: 'frp',
                  icon: <GlobalOutlined />,
                  label: '内网穿透'
                },
                {
                  key: 'files',
                  icon: <FolderOutlined />,
                  label: '文件管理'
                },
                {
                  key: 'about',
                  icon: <InfoCircleOutlined />,
                  label: '关于项目'
                },
                {
                  key: 'server-guide',
                  icon: <BookOutlined />,
                  label: '开服指南'
                },
                {
                  key: 'settings',
                  icon: <SettingOutlined />,
                  label: '设置'
                }
              ]}
            />
          </Drawer>
        </>
      ) : (
        // 桌面端侧边栏
      <Sider 
        className="fixed-sider"
        collapsible 
        collapsed={collapsed} 
        onCollapse={setCollapsed} 
        theme="light"
        width="var(--sider-width)"
        collapsedWidth="var(--sider-collapsed-width)"
      >
        <div className="logo">
          <img src="/logo/logo2.png" alt="GSManager" style={{ height: '50px', objectFit: 'contain' }} />
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[currentNav]}
          onClick={({ key }) => {
            setCurrentNav(key.toString());
            // 当切换到文件管理时，确保设置有效的默认路径
            if (key === 'files' && (!fileManagerPath || fileManagerPath === '')) {
              setFileManagerPath('/home/steam');
            }
          }}
          items={[
            {
              key: 'dashboard',
              icon: <DashboardOutlined />,
              label: '系统概览'
            },
            {
              key: 'games',
              icon: <RocketOutlined />,
              label: '游戏部署'
            },
            {
              key: 'environment',
              icon: <ToolOutlined />,
              label: '环境安装'
            },
            {
              key: 'servers',
              icon: <PlayCircleOutlined />,
              label: '服务端管理'
            },
            {
              key: 'game-config',
              icon: <ToolOutlined />,
              label: '游戏配置文件'
            },
            {
              key: 'frp',
              icon: <GlobalOutlined />,
              label: '内网穿透'
            },
            {
              key: 'files',
              icon: <FolderOutlined />,
              label: '文件管理'
            },
            {
              key: 'about',
              icon: <InfoCircleOutlined />,
              label: '关于项目'
            },
            {
              key: 'server-guide',
              icon: <BookOutlined />,
              label: '开服指南'
            },
            {
              key: 'settings',
              icon: <SettingOutlined />,
              label: '设置'
            }
          ]}
        />
      </Sider>
      )}
      
      <Layout 
        className={`site-layout content-with-fixed-sider ${isMobile ? '' : (collapsed ? 'sider-collapsed' : 'sider-expanded')} ${enableRandomBackground ? 'with-random-bg' : 'without-random-bg'} ${!isUserActive && enableInactiveEffect && enableRandomBackground ? 'user-inactive' : ''}`}
      >
        {!isMobile && (
        <Header className="site-header">
          <div className="header-title">
            <img src="/logo/logo.png" alt="GameServerManager" style={{ height: '60px', width: '200px', objectFit: 'contain' }} />
          </div>
          <div className="user-info">
            <Tooltip title={enableRandomBackground ? "关闭随机背景" : "开启随机背景"}>
              <Switch 
                checkedChildren="背景" 
                unCheckedChildren="背景" 
                checked={enableRandomBackground}
                onChange={(checked) => setEnableRandomBackground(checked)}
                size="small"
                style={{marginRight: 8}}
              />
            </Tooltip>
            {enableRandomBackground && (
              <Tooltip title={enableInactiveEffect ? "关闭20秒后自动透明效果" : "开启20秒后自动透明效果"}>
                <Switch 
                  checkedChildren="透明" 
                  unCheckedChildren="透明" 
                  checked={enableInactiveEffect}
                  onChange={(checked) => setEnableInactiveEffect(checked)}
                  size="small"
                  style={{marginRight: 8}}
                />
              </Tooltip>
            )}
            <span><UserOutlined /> {username}</span>
            <Button 
              type="link" 
              icon={<LogoutOutlined className="logout-icon" />} 
              onClick={async () => {
                await logout();
                navigate('/login');
              }}
              className="logout-btn"
                size={isMobile ? "small" : "middle"}
            >
                {!isMobile && "退出"}
            </Button>
          </div>
        </Header>
        )}
        
        <Content style={{ width: '100%', maxWidth: '100%', margin: 0, padding: isMobile ? '4px' : '16px' }}>
          {currentNav === 'dashboard' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <ContainerInfo 
                onStartServer={handleStartServer}
                onStopServer={handleStopServer}
                onUninstallGame={handleUninstall}
              />
            </div>
          )}
          
          {currentNav === 'games' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="game-cards">
                <Title level={2}>游戏服务器管理</Title>
              <Tabs activeKey={tabKey} onChange={setTabKey}>
                <TabPane tab="快速部署" key="install">
                  {gameLoading ? (
                    <div className="loading-container">
                      <Spin size="large" />
                    </div>
                  ) : (
                    <Row gutter={[16, 16]}>
                      {games.map((game) => {
                        const isInstalled = installedGames.includes(game.id);
                        const isInstalling = installOutputs[game.id]?.installing;
                        
                        return (
                          <Col key={game.id} xs={24} sm={12} md={8} lg={6}>
                            <div className="custom-game-card">
                              {/* 游戏封面图片 */}
                              <div className="game-cover">
                                {game.image ? (
                                  <img src={game.image} alt={game.name} />
                                ) : (
                                  <div className="game-cover-placeholder">
                                    <AppstoreOutlined />
                                  </div>
                                )}
                              </div>
                              <div className="card-header">
                                <h3>{game.name}</h3>
                                {isInstalled ? (
                                  <Tag color="green">已安装</Tag>
                                ) : (
                                  <Tag color="blue">{game.anonymous ? '匿名安装' : '需要登录'}</Tag>
                                )}
                              </div>
                              <div className="card-content">
                                <p>AppID: {game.appid}</p>
                              </div>
                              <div className="card-actions">
                                {isInstalled ? (
                                  <>
                                    <button 
                                      className="btn-info"
                                      onClick={() => handleShowDetail(game)}
                                    >
                                      <InfoCircleOutlined /> 详情
                                    </button>
                                    <button 
                                      className="btn-default"
                                      onClick={() => handleUninstall(game)}
                                    >卸载</button>
                                    <button 
                                      className="btn-primary"
                                      onClick={() => handleInstall(game)}
                                    >
                                      {isInstalling ? '更新中...' : '更新'}
                                    </button>
                                  </>
                                ) : (
                                  <>
                                    <button 
                                      className="btn-info"
                                      onClick={() => handleShowDetail(game)}
                                    >
                                      <InfoCircleOutlined /> 详情
                                    </button>
                                    <button 
                                      className="btn-primary"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        if (!isInstalling) {
                                          handleInstallClick(game);
                                        }
                                      }}
                                    >
                                      {isInstalling ? '安装中...' : '安装'}
                                    </button>
                                  </>
                                )}
                              </div>
                            </div>
                          </Col>
                        );
                      })}
                    </Row>
                  )}
                </TabPane>
                <TabPane tab="通过AppID安装" key="install-by-appid">
                  <div style={{ maxWidth: 600, margin: '0 auto', padding: '20px 0' }}>
                    <Card title="通过AppID安装游戏">
                      <Form layout="vertical" onFinish={handleInstallByAppId}>
                        <Form.Item
                          name="appid"
                          label="Steam AppID"
                          rules={[{ required: true, message: '请输入Steam AppID' }]}
                        >
                          <Input placeholder="请输入游戏的Steam AppID，例如: 252490" />
                        </Form.Item>
                        <Form.Item
                          name="name"
                          label="游戏名称"
                          rules={[{ required: true, message: '请输入游戏名称' }]}
                        >
                          <Input placeholder="请输入游戏名称，用于显示" />
                        </Form.Item>
                        <Form.Item
                          name="anonymous"
                          label="安装方式"
                          initialValue={true}
                        >
                          <Radio.Group>
                            <Radio value={true}>匿名安装（无需账号）</Radio>
                            <Radio value={false}>登录安装（需要Steam账号）</Radio>
                          </Radio.Group>
                        </Form.Item>
                        
                        <Form.Item noStyle dependencies={['anonymous']}>
                          {({ getFieldValue }) => {
                            const anonymous = getFieldValue('anonymous');
                            return !anonymous ? (
                              <>
                                <Form.Item
                                  name="account"
                                  label="Steam账号"
                                  rules={[{ required: true, message: '请输入Steam账号' }]}
                                >
                                  <Input placeholder="输入您的Steam账号" />
                                </Form.Item>
                                <Form.Item
                                  name="password"
                                  label="密码"
                                  extra="如您的账号启用了二步验证，安装过程中会提示您输入Steam Guard码"
                                >
                                  <Input.Password placeholder="输入密码 (可选)" />
                                </Form.Item>
                              </>
                            ) : null;
                          }}
                        </Form.Item>
                        
                        <Form.Item>
                          <Button type="primary" htmlType="submit" loading={appIdInstalling}>
                            开始安装
                          </Button>
                        </Form.Item>
                      </Form>
                    </Card>
                  </div>
                </TabPane>
                <TabPane tab="Minecraft部署" key="minecraft-deploy">
                  <div style={{ maxWidth: 1000, margin: '0 auto', padding: '20px 0' }}>
                    <Card title="Minecraft服务器快速部署">
                      <MinecraftDeploy />
                    </Card>
                  </div>
                </TabPane>
                <TabPane tab="Minecraft整合包部署" key="minecraft-modpack-deploy">
                  <div style={{ maxWidth: 1200, margin: '0 auto', padding: '20px 0' }}>
                    <MinecraftModpackDeploy />
                  </div>
                </TabPane>
                <TabPane tab="半自动部署" key="semi-auto-deploy">
                  <div style={{ maxWidth: 1000, margin: '0 auto', padding: '20px 0' }}>
                    <Card title="半自动部署">
                      <SemiAutoDeploy />
                    </Card>
                  </div>
                </TabPane>
                <TabPane tab="在线部署" key="online-deploy">
                  <div style={{ maxWidth: 1000, margin: '0 auto', padding: '20px 0' }}>
                    <OnlineDeploy />
                  </div>
                </TabPane>

              </Tabs>
              </div>
            </div>
          )}
          
          {currentNav === 'servers' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="running-servers">
                <Title level={2}>服务端管理</Title>
              <Tabs defaultActiveKey="all" onChange={handleTabChange}>
                <TabPane tab="全部服务端" key="all">
                  <div className="server-management">
                    <div className="server-controls">
                      <Button onClick={refreshGameLists} icon={<ReloadOutlined />} style={{marginRight: 8}}>刷新列表</Button>
                      <Button onClick={refreshServerStatus} icon={<ReloadOutlined />}>刷新状态</Button>
                    </div>
                    <Row gutter={[16, 16]}>
                      {/* 固定显示SteamCMD */}
                      <Col xs={24} sm={12} md={8} lg={6} key="steamcmd">
                        <Card
                          hoverable
                          className="game-card"
                          title={
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span>SteamCMD</span>
                              <Tag color="blue">工具</Tag>
                            </div>
                          }
                          style={{ borderRadius: '8px', overflow: 'hidden' }}
                        >
                          <p>Steam游戏服务器命令行工具</p>
                          <p>位置: /home/steam/steamcmd</p>
                          <div style={{marginTop: 12}}>
                            <div style={{marginBottom: 8}}>SteamCMD控制:</div>
                            {runningServers.includes("steamcmd") ? (
                              <div>
                                <Button 
                                  type="default" 
                                  size="small" 
                                  style={{marginRight: 8}}
                                  onClick={() => handleStopServer("steamcmd")}
                                >
                                  停止
                                </Button>
                                <Button 
                                  type="primary" 
                                  size="small"
                                  style={{marginRight: 8}}
                                  onClick={() => handleStartSteamCmd()}
                                >
                                  控制台
                                </Button>
                              </div>
                            ) : (
                              <div style={{display: 'flex', justifyContent: 'center'}}>
                                <Button 
                                  type="primary"
                                  size="middle"
                                  style={{width: '100%'}}
                                  onClick={() => handleStartSteamCmd()}
                                >
                                  启动
                                </Button>
                              </div>
                            )}
                          </div>
                        </Card>
                      </Col>
                      
                      {/* 显示配置中的已安装游戏 */}
                      {games
                        .filter(game => installedGames.includes(game.id))
                        .map(game => (
                          <Col key={game.id} xs={24} sm={12} md={8} lg={6}>
                            <Card
                              title={game.name}
                              extra={
                                runningServers.includes(game.id) ? (
                                  <Tag color="green">运行中</Tag>
                                ) : (
                                  <Tag color="default">未运行</Tag>
                                )
                              }
                              style={{ borderRadius: '8px', overflow: 'hidden' }}
                            >
                              <p>服务端状态: {runningServers.includes(game.id) ? '运行中' : '已停止'}</p>
                              <div style={{marginTop: 12}}>
                                {runningServers.includes(game.id) ? (
                                  <div>
                                    <div style={{marginBottom: 8}}>
                                      <Button 
                                        danger
                                        size="small"
                                        onClick={() => handleUninstall(game.id)}
                                      >
                                        卸载
                                      </Button>
                                      <span style={{marginLeft: 8}}>
                                        自启动: 
                                        <Switch 
                                          size="small" 
                                          checked={autoRestartServers.includes(game.id)}
                                          onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                          style={{marginLeft: 4}}
                                        />
                                      </span>
                                    </div>
                                    <Button 
                                      type="default" 
                                      size="small" 
                                      style={{marginRight: 8}}
                                      onClick={() => handleStopServer(game.id)}
                                    >
                                      停止
                                    </Button>
                                    <Button 
                                      type="primary" 
                                      size="small"
                                      style={{marginRight: 8}}
                                      onClick={() => handleStartServer(game.id)}
                                    >
                                      控制台
                                    </Button>
                                    <Button
                                      icon={<FolderOutlined />}
                                      size="small"
                                      onClick={() => handleOpenGameFolder(game.id)}
                                    >
                                      文件夹
                                    </Button>
                                  </div>
                                ) : (
                                  <div>
                                    <div style={{marginBottom: 8}}>
                                      <Button 
                                        danger
                                        size="small"
                                        onClick={() => handleUninstall(game.id)}
                                      >
                                        卸载
                                      </Button>
                                      <span style={{marginLeft: 8}}>
                                        自启动: 
                                        <Switch 
                                          size="small" 
                                          checked={autoRestartServers.includes(game.id)}
                                          onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                          style={{marginLeft: 4}}
                                        />
                                      </span>
                                    </div>
                                    <div style={{display: 'flex', justifyContent: 'center'}}>
                                      <Button 
                                        type="primary"
                                        size="middle"
                                        style={{marginRight: 8, width: '45%'}}
                                        onClick={() => handleStartServer(game.id)}
                                      >
                                        启动
                                      </Button>
                                      <Button
                                        icon={<FolderOutlined />}
                                        size="middle"
                                        style={{width: '45%'}}
                                        onClick={() => handleOpenGameFolder(game.id)}
                                      >
                                        文件夹
                                      </Button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </Card>
                          </Col>
                        ))}
                        
                      {/* 显示外部游戏 */}
                      {externalGames.map(game => (
                        <Col key={game.id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <span>{game.name}</span>
                                <Tag color="orange">外来</Tag>
                              </div>
                            }
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <p>位置: /home/steam/games/{game.id}</p>
                            <div style={{marginTop: 12}}>
                              <div style={{marginBottom: 8}}>服务器控制:</div>
                              {runningServers.includes(game.id) ? (
                                <div>
                                  <div style={{marginBottom: 8}}>
                                    <Button 
                                      danger
                                      size="small"
                                      onClick={() => handleUninstall(game.id)}
                                    >
                                      卸载
                                    </Button>
                                    <span style={{marginLeft: 8}}>
                                      自启动: 
                                      <Switch 
                                        size="small" 
                                        checked={autoRestartServers.includes(game.id)}
                                        onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                        style={{marginLeft: 4}}
                                      />
                                    </span>
                                  </div>
                                  <Button 
                                    type="default" 
                                    size="small" 
                                    style={{marginRight: 8}}
                                    onClick={() => handleStopServer(game.id)}
                                  >
                                    停止
                                  </Button>
                                  <Button 
                                    type="primary" 
                                    size="small"
                                    style={{marginRight: 8}}
                                    onClick={() => handleStartServer(game.id)}
                                  >
                                    控制台
                                  </Button>
                                  <Button
                                    icon={<FolderOutlined />}
                                    size="small"
                                    onClick={() => handleOpenGameFolder(game.id)}
                                  >
                                    文件夹
                                  </Button>
                                </div>
                              ) : (
                                <div>
                                  <div style={{marginBottom: 8}}>
                                    <Button 
                                      danger
                                      size="small"
                                      onClick={() => handleUninstall(game.id)}
                                    >
                                      卸载
                                    </Button>
                                    <span style={{marginLeft: 8}}>
                                      自启动: 
                                      <Switch 
                                        size="small" 
                                        checked={autoRestartServers.includes(game.id)}
                                        onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                        style={{marginLeft: 4}}
                                      />
                                    </span>
                                  </div>
                                  <div style={{display: 'flex', justifyContent: 'center'}}>
                                    <Button 
                                      type="primary"
                                      size="middle"
                                      style={{marginRight: 8, width: '45%'}}
                                      onClick={() => handleStartServer(game.id)}
                                    >
                                      启动
                                    </Button>
                                    <Button
                                      icon={<FolderOutlined />}
                                      size="middle"
                                      style={{width: '45%'}}
                                      onClick={() => handleOpenGameFolder(game.id)}
                                    >
                                      文件夹
                                    </Button>
                                  </div>
                                </div>
                              )}
                            </div>
                          </Card>
                        </Col>
                      ))}

                      {games.filter(g => installedGames.includes(g.id)).length === 0 && externalGames.length === 0 && (
                        <Col span={24}><p>除了SteamCMD外，暂无已安装的游戏。</p></Col>
                      )}
                    </Row>
                  </div>
                </TabPane>
                <TabPane tab="正在运行服务端" key="running">
                  <div className="server-controls">
                    <Button onClick={refreshServerStatus} icon={<ReloadOutlined />} style={{ marginBottom: 16 }}>
                      刷新状态
                    </Button>
                  </div>
                  <Row gutter={[16, 16]}>
                    {/* 显示配置中的游戏 */}
                    {games
                      .filter(game => runningServers.includes(game.id))
                      .map(game => (
                        <Col key={game.id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={game.name}
                            extra={<Tag color="green">运行中</Tag>}
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <div style={{marginBottom: 12}}>
                              <p>位置: /home/steam/games/{game.id}</p>
                            </div>
                            <div style={{display: 'flex', justifyContent: 'space-between'}}>
                              <Button 
                                type="default" 
                                danger
                                size="small" 
                                onClick={() => handleStopServer(game.id)}
                              >
                                停止
                              </Button>
                              <Button 
                                type="primary" 
                                size="small"
                                onClick={() => handleStartServer(game.id, true)}
                              >
                                控制台
                              </Button>
                              <Button
                                icon={<FolderOutlined />}
                                size="small"
                                onClick={() => handleOpenGameFolder(game.id)}
                              >
                                文件夹
                              </Button>
                            </div>
                            <div style={{marginTop: 8}}>
                              自启动: 
                              <Switch 
                                size="small" 
                                checked={autoRestartServers.includes(game.id)}
                                onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                style={{marginLeft: 4}}
                              />
                            </div>
                          </Card>
                        </Col>
                      ))}
                      
                    {/* 显示外部游戏 */}
                    {externalGames
                      .filter(game => runningServers.includes(game.id))
                      .map(game => (
                        <Col key={game.id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <span>{game.name}</span>
                                <Tag color="orange">外来</Tag>
                              </div>
                            }
                            extra={<Tag color="green">运行中</Tag>}
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <div style={{marginBottom: 12}}>
                              <p>位置: /home/steam/games/{game.id}</p>
                            </div>
                            <div style={{display: 'flex', justifyContent: 'space-between'}}>
                              <Button 
                                type="default" 
                                danger
                                size="small" 
                                onClick={() => handleStopServer(game.id)}
                              >
                                停止
                              </Button>
                              <Button 
                                type="primary" 
                                size="small"
                                onClick={() => handleStartServer(game.id, true)}
                              >
                                控制台
                              </Button>
                              <Button
                                icon={<FolderOutlined />}
                                size="small"
                                onClick={() => handleOpenGameFolder(game.id)}
                              >
                                文件夹
                              </Button>
                            </div>
                            <div style={{marginTop: 8}}>
                              自启动: 
                              <Switch 
                                size="small" 
                                checked={autoRestartServers.includes(game.id)}
                                onChange={(checked) => handleAutoRestartChange(game.id, checked)}
                                style={{marginLeft: 4}}
                              />
                            </div>
                          </Card>
                        </Col>
                      ))}
                      
                    {/* 显示其他运行中的服务器（可能是未识别的外部游戏） */}
                    {runningServers
                      .filter(id => !games.some(g => g.id === id) && !externalGames.some(g => g.id === id))
                      .map(id => (
                        <Col key={id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <span>{id}</span>
                                <Tag color="purple">未识别</Tag>
                              </div>
                            }
                            extra={<Tag color="green">运行中</Tag>}
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <div style={{marginBottom: 12}}>
                              <p>位置: /home/steam/games/{id}</p>
                            </div>
                            <div style={{display: 'flex', justifyContent: 'space-between'}}>
                              <Button 
                                type="default" 
                                danger
                                size="small" 
                                onClick={() => handleStopServer(id)}
                              >
                                停止
                              </Button>
                              <Button 
                                type="primary" 
                                size="small"
                                onClick={() => handleStartServer(id, true)}
                              >
                                控制台
                              </Button>
                              <Button
                                icon={<FolderOutlined />}
                                size="small"
                                onClick={() => handleOpenGameFolder(id)}
                              >
                                文件夹
                              </Button>
                            </div>
                            <div style={{marginTop: 8}}>
                              自启动: 
                              <Switch 
                                size="small" 
                                checked={autoRestartServers.includes(id)}
                                onChange={(checked) => handleAutoRestartChange(id, checked)}
                                style={{marginLeft: 4}}
                              />
                            </div>
                          </Card>
                        </Col>
                      ))}
                      
                    {runningServers.length === 0 && (
                      <Col span={24}>
                        <div className="empty-servers">
                          <p>当前没有正在运行的服务端</p>
                        </div>
                      </Col>
                    )}
                  </Row>
                </TabPane>
                <TabPane tab="定时备份" key="backup">
                  <div className="backup-management">
                    <div className="backup-controls">
                      <Button onClick={refreshBackupTasks} icon={<ReloadOutlined />} style={{marginRight: 8}}>刷新任务</Button>
                      <Button type="primary" onClick={() => setBackupModalVisible(true)}>添加备份任务</Button>
                    </div>
                    <Row gutter={[16, 16]}>
                      {backupTasks.map(task => (
                        <Col key={task.id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={task.name}
                            extra={
                              <Tag color={task.enabled ? "green" : "default"}>
                                {task.enabled ? "启用" : "禁用"}
                              </Tag>
                            }
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <div style={{marginBottom: 12}}>
                              <p>目录: {task.directory}</p>
                              <p>间隔: {(() => {
                                if (task.intervalValue && task.intervalUnit) {
                                  const unitMap = {
                                    'minutes': '分钟',
                                    'hours': '小时', 
                                    'days': '天'
                                  };
                                  return `${task.intervalValue}${unitMap[task.intervalUnit] || '小时'}`;
                                } else {
                                  // 兼容旧数据
                                  const hours = task.interval;
                                  if (hours < 1) {
                                    return `${Math.round(hours * 60)}分钟`;
                                  } else if (hours >= 24 && hours % 24 === 0) {
                                    return `${hours / 24}天`;
                                  } else {
                                    return `${hours}小时`;
                                  }
                                }
                              })()}</p>
                              <p>保留: {task.keepCount}份</p>
                              <p>下次备份: {task.nextBackup || '未设置'}</p>
                              {task.linkedServerId && (
                                <p>关联服务端: {task.linkedServerId} 
                                  {task.autoControl && <Tag color="blue" size="small">自动控制</Tag>}
                                </p>
                              )}
                            </div>
                            <div style={{display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px'}}>
                              <Button 
                                size="small"
                                onClick={() => handleToggleBackupTask(task.id)}
                              >
                                {task.enabled ? '禁用' : '启用'}
                              </Button>
                              <Button 
                                size="small"
                                onClick={() => handleRunBackupNow(task.id)}
                              >
                                立即备份
                              </Button>
                              <Button 
                                size="small"
                                onClick={() => handleEditBackupTask(task)}
                              >
                                编辑
                              </Button>
                              <Button 
                                danger
                                size="small"
                                onClick={() => handleDeleteBackupTask(task.id)}
                              >
                                删除
                              </Button>
                            </div>
                          </Card>
                        </Col>
                      ))}
                      {backupTasks.length === 0 && (
                        <Col span={24}>
                          <div className="empty-backup-tasks">
                            <p>暂无备份任务，点击"添加备份任务"创建新任务</p>
                          </div>
                        </Col>
                      )}
                    </Row>
                  </div>
                </TabPane>
                <TabPane tab="文件收藏" key="favorites">
                  <div className="favorite-files-management">
                    <div className="favorite-controls">
                      <Button onClick={handleAddFavoriteFile} type="primary" style={{marginRight: 8}}>添加收藏文件</Button>
                      <Button onClick={refreshFavoriteFiles} icon={<ReloadOutlined />}>刷新列表</Button>
                    </div>
                    <Row gutter={[16, 16]} style={{marginTop: 16}}>
                      {favoriteFiles.map(favorite => (
                        <Col key={favorite.id} xs={24} sm={12} md={8} lg={6}>
                          <Card
                            title={favorite.name}
                            extra={
                              <Tag color="blue">收藏</Tag>
                            }
                            style={{ borderRadius: '8px', overflow: 'hidden' }}
                          >
                            <div style={{marginBottom: 8}}>
                              <strong>文件路径:</strong>
                              <div style={{wordBreak: 'break-all', fontSize: '12px', color: '#666'}}>
                                {favorite.filePath}
                              </div>
                            </div>
                            {favorite.description && (
                              <div style={{marginBottom: 12}}>
                                <strong>描述:</strong>
                                <div style={{fontSize: '12px', color: '#666'}}>
                                  {favorite.description}
                                </div>
                              </div>
                            )}
                            <div style={{marginBottom: 8, fontSize: '12px', color: '#999'}}>
                              创建时间: {new Date(favorite.createdAt).toLocaleString()}
                            </div>
                            <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
                              <Button 
                                type="primary"
                                size="small"
                                onClick={() => handleOpenFavoriteFile(favorite)}
                              >
                                打开编辑
                              </Button>
                              <Button 
                                size="small"
                                onClick={() => handleEditFavoriteFile(favorite)}
                              >
                                编辑
                              </Button>
                              <Button 
                                danger
                                size="small"
                                onClick={() => handleDeleteFavoriteFile(favorite.id)}
                              >
                                删除
                              </Button>
                            </div>
                          </Card>
                        </Col>
                      ))}
                      {favoriteFiles.length === 0 && (
                        <Col span={24}>
                          <div className="empty-favorite-files">
                            <p>暂无收藏文件，点击"添加收藏文件"创建新收藏</p>
                          </div>
                        </Col>
                      )}
                    </Row>
                  </div>
                </TabPane>
              </Tabs>
              </div>
            </div>
          )}

          {currentNav === 'files' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="file-management">
                <Title level={2}>文件管理</Title>
                <FileManager 
                  initialPath={fileManagerPath || '/home/steam'} 
                  // This FileManager is part of the main navigation.
                  // Its visibility is tied to whether 'files' is the currentNav.
                  isVisible={currentNav === 'files'} 
                />
              </div>
            </div>
          )}

          {currentNav === 'game-config' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="game-config-management">
                <GameConfigManager />
              </div>
            </div>
          )}

          {currentNav === 'frp' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="frp-management">
                <FrpManager />
              </div>
            </div>
          )}
          
          {currentNav === 'about' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="about-page">
                <About />
              </div>
            </div>
          )}
          
          {currentNav === 'server-guide' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="server-guide-page">
                <ServerGuide />
              </div>
            </div>
          )}
          
          {currentNav === 'settings' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="settings-page">
                <Settings />
              </div>
            </div>
          )}
          {currentNav === 'environment' && (
            <div className={`nav-content ${isTransitioning ? 'fade-out' : ''}`}>
              <div className="environment-page">
                <Environment />
              </div>
            </div>
          )}
        </Content>
        <Footer style={{ textAlign: 'center' }}>GameServerManager ©2025 又菜又爱玩的小朱 最后更新日期2025.7.7-Dev</Footer>
      </Layout>

      {/* 安装终端Modal */}
      <Modal
        title={`安装 ${selectedGame?.name || ''} 服务端`}
        open={terminalVisible}
        onCancel={closeTerminal}
        footer={null}
        width={800}
        maskClosable={false}
        style={{ top: 20 }}
        bodyStyle={{ padding: 0 }}
      >
        {selectedGame && (
          <Terminal
            output={currentOutput}
            loading={currentInstalling}
            complete={currentComplete}
            gameId={selectedGame.id}
            onSendInput={handleSendInput}
            onTerminate={handleTerminateInstall}
          />
        )}
      </Modal>

      {/* 服务器终端Modal */}
      <Modal
        title={`${selectedServerGame?.name || ''} 服务端控制台`}
        open={serverModalVisible}
        onCancel={() => {
          setServerModalVisible(false);
          // 关闭控制台时刷新服务器状态
          refreshServerStatus();
          
          // 关闭EventSource连接
          if (serverEventSourceRef.current) {
            serverEventSourceRef.current.close();
            serverEventSourceRef.current = null;
          }
        }}
        afterOpenChange={(visible) => {
          // 当模态框打开时，检查服务器状态
          if (visible && selectedServerGame) {
            checkServerStatus(selectedServerGame.id)
              .then(statusResponse => {
                if (statusResponse.server_status !== 'running') {
                  message.warning('服务器未运行，请先启动服务器');
                  // 可以在这里添加一条信息到终端输出
                  setServerOutputs(prev => {
                    const oldOutput = prev[selectedServerGame.id] || [];
                    return {
                      ...prev,
                      [selectedServerGame.id]: [...oldOutput, "警告：服务器未运行，请先启动服务器"]
                    };
                  });
                  
                  // 从运行中的服务器列表中移除
                  setRunningServers(prev => prev.filter(id => id !== selectedServerGame.id));
                  
                  // 如果有EventSource连接，关闭它
                  if (serverEventSourceRef.current) {
                    serverEventSourceRef.current.close();
                    serverEventSourceRef.current = null;
                  }
                } else {
                  // 服务器正在运行，添加一条信息到终端输出
                  setServerOutputs(prev => {
                    const oldOutput = prev[selectedServerGame.id] || [];
                    return {
                      ...prev,
                      [selectedServerGame.id]: [...oldOutput, "终端已连接，服务器正在运行中..."]
                    };
                  });
                }
              })
              .catch(error => {
                console.error('检查服务器状态失败:', error);
                message.error('无法确认服务器状态');
                
                // 发生错误时也从运行中的服务器列表中移除
                if (selectedServerGame) {
                  setRunningServers(prev => prev.filter(id => id !== selectedServerGame.id));
                }
              });
          }
        }}
        footer={
          <div className="server-console-buttons">
            <Button key="reconnect" type="primary" ghost 
              onClick={() => {
                // 重新连接到控制台，保留现有输出并获取历史记录
                handleStartServer(selectedServerGame?.id, true);
              }}
              size={isMobile ? "small" : "middle"}
            >
              重新连接
            </Button>
            <Button key="clear" 
              onClick={() => {
                // 清空当前输出
                if (selectedServerGame?.id) {
                  setServerOutputs(prev => ({
                    ...prev,
                    [selectedServerGame.id]: []
                  }));
                }
              }}
              size={isMobile ? "small" : "middle"}
            >
              清空输出
            </Button>
            <Button key="stop" danger
              onClick={() => {
                handleStopServer(selectedServerGame?.id);
              }}
              size={isMobile ? "small" : "middle"}
            >
              停止服务器
            </Button>
            <Button key="close" 
              onClick={() => {
                setServerModalVisible(false);
                // 关闭控制台时刷新服务器状态
                refreshServerStatus();
              }}
              size={isMobile ? "small" : "middle"}
            >
              关闭控制台
            </Button>
          </div>
        }
        width={isMobile ? "95%" : 1200}
      >
        <div className="server-console">
          <SimpleServerTerminal
            outputs={(serverOutputs[selectedServerGame?.id] || []).filter(line => !line.includes('等待服务器输出...'))}
            onSendCommand={async (command) => {
              console.log('[App.tsx] onSendCommand triggered. Command:', command, 'Selected Game ID:', selectedServerGame?.id); // 新增日志1

              if (selectedServerGame?.id) {
                try {
                  console.log('[App.tsx] Checking server status for game ID:', selectedServerGame.id); // 新增日志2
                  const statusResponse = await checkServerStatus(selectedServerGame.id);
                  console.log('[App.tsx] Server status response:', statusResponse); // 新增日志3

                  if (statusResponse.server_status !== 'running') {
                    message.error('服务器未运行，无法发送命令');
                    console.log('[App.tsx] Server not running or status check failed. Status:', statusResponse.server_status); // 新增日志4
                    return;
                  }

                  console.log('[App.tsx] Server is running. Calling handleSendServerInput for game ID:', selectedServerGame.id); // 新增日志5
                  handleSendServerInput(selectedServerGame.id, command);
                  
                  // 添加到历史记录
                  setInputHistory(prev => {
                    const newHistory = [...prev, command];
                    return newHistory.slice(-50); // 保留最近50条
                  });
                  setInputHistoryIndex(-1);
                } catch (error) {
                  console.error('[App.tsx] Error in onSendCommand during status check or sending:', error); // 修改日志6
                  message.error('无法确认服务器状态或发送命令时出错，请刷新页面后重试');
                  
                  // 发生错误时也从运行中的服务器列表中移除
                  if (selectedServerGame?.id) {
                    setRunningServers(prev => prev.filter(id => id !== selectedServerGame.id));
                  }
                  return;
                }
              } else {
                console.log('[App.tsx] onSendCommand: selectedServerGame or selectedServerGame.id is null/undefined.'); // 新增日志7
              }
            }}
            onClear={() => {
              if (selectedServerGame?.id) {
                setServerOutputs(prev => ({
                  ...prev,
                  [selectedServerGame.id]: []
                }));
              }
            }}
            onReconnect={() => {
              if (selectedServerGame?.id) {
                handleStartServer(selectedServerGame.id, true);
              }
            }}
            style={{ height: '600px' }}
          />
        </div>
      </Modal>

      {/* 账号输入Modal */}
      <Modal
        title="输入Steam账号"
        open={accountModalVisible}
        onOk={onAccountModalOk}
        onCancel={() => {
          setAccountModalVisible(false);
          setPendingInstallGame(null);
        }}
        okText="安装"
        cancelText="取消"
      >
        <Form form={accountForm} layout="vertical">
          <Form.Item
            name="account"
            label="Steam账号"
            rules={[{ required: true, message: '请输入Steam账号' }]}
          >
            <Input placeholder="输入您的Steam账号" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码 (可选)"
            extra="如您的账号启用了二步验证，安装过程中会提示您输入Steam Guard码"
          >
            <Input.Password placeholder="输入密码 (可选)" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 游戏详情Modal */}
      <Modal
        title={`${detailGame?.name || ''} 详细信息`}
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={null}
        width={isMobile ? "95%" : 600}
      >
        {detailGame && (
          <div className="game-detail">
            {detailGame.image && (
              <div style={{ textAlign: 'center', marginBottom: 20 }}>
                <img 
                  src={detailGame.image} 
                  alt={detailGame.name} 
                  style={{ maxWidth: '100%', maxHeight: '200px' }} 
                />
              </div>
            )}
            <p><strong>游戏ID:</strong> {detailGame.id}</p>
            <p><strong>AppID:</strong> {detailGame.appid}</p>
            <p><strong>安装方式:</strong> {detailGame.anonymous ? '匿名安装' : '需要登录'}</p>
            <p><strong>包含启动脚本:</strong> {detailGame.has_script ? '是' : '否'}</p>
            
            {detailGame.tip && (
              <div>
                <strong>安装提示:</strong>
                <div className="game-detail-tip">
                  {detailGame.tip}
                </div>
              </div>
            )}
            
            {/* 添加从Steam中打开按钮 */}
            <div style={{ textAlign: 'center', marginTop: 24 }}>
              <p style={{ marginBottom: 10, fontSize: 13, color: '#888' }}>
                点击下方按钮将在新窗口打开Steam商店页面
              </p>
              <Button 
                type="primary" 
                size="large"
                onClick={() => handleOpenInSteam(detailGame.url || '', detailGame.appid)}
                icon={<CloudServerOutlined />}
              >
                在Steam中查看
              </Button>
            </div>
          </div>
        )}
      </Modal>
      
      {/* 备份任务Modal */}
      <Modal
        title={editingBackupTask ? '编辑备份任务' : '添加备份任务'}
        open={backupModalVisible}
        onCancel={() => {
          setBackupModalVisible(false);
          setEditingBackupTask(null);
          backupForm.resetFields();
        }}
        footer={null}
        width={isMobile ? "95%" : 600}
      >
        <Form
          form={backupForm}
          layout="vertical"
          onFinish={handleBackupFormSubmit}
          style={{ marginTop: 20 }}
        >
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, message: '请输入任务名称' }]}
          >
            <Input placeholder="例如：我的世界服务器备份" />
          </Form.Item>
          
          <Form.Item
            name="directory"
            label="备份目录"
            rules={[{ required: true, message: '请输入要备份的目录路径' }]}
          >
            <Input.Group compact>
              <Form.Item name="directory" noStyle>
                <Input 
                  style={{ width: 'calc(100% - 80px)' }}
                  placeholder="例如：/home/steam/games/minecraft" 
                />
              </Form.Item>
              <Button 
                style={{ width: 80 }}
                onClick={() => setBackupDirectoryPickerVisible(true)}
              >
                浏览
              </Button>
            </Input.Group>
          </Form.Item>
          
          <Form.Item label="备份间隔">
            <Input.Group compact>
              <Form.Item
                name="intervalValue"
                style={{ width: '70%', marginBottom: 0 }}
                rules={[
                  { required: true, message: '请输入备份间隔' },
                  { 
                    validator: (_, value) => {
                      const num = Number(value);
                      if (!value || isNaN(num) || num < 1) {
                        return Promise.reject(new Error('间隔时间至少为1'));
                      }
                      return Promise.resolve();
                    }
                  }
                ]}
              >
                <Input type="number" placeholder="例如：6" />
              </Form.Item>
              <Form.Item
                name="intervalUnit"
                style={{ width: '30%', marginBottom: 0 }}
                initialValue="hours"
              >
                <Select>
                  <Select.Option value="minutes">分钟</Select.Option>
                  <Select.Option value="hours">小时</Select.Option>
                  <Select.Option value="days">天</Select.Option>
                </Select>
              </Form.Item>
            </Input.Group>
          </Form.Item>
          
          <Form.Item
            name="keepCount"
            label="保留份数"
            rules={[
              { required: true, message: '请输入保留份数' },
              { 
                validator: (_, value) => {
                  const num = Number(value);
                  if (!value || isNaN(num) || num < 1) {
                    return Promise.reject(new Error('至少保留1份备份'));
                  }
                  return Promise.resolve();
                }
              }
            ]}
          >
            <Input type="number" placeholder="例如：7" addonAfter="份" />
          </Form.Item>
          
          <Form.Item
            name="linkedServerId"
            label="关联服务端"
            tooltip="选择要关联的服务端，可实现自动控制备份任务"
          >
            <Select placeholder="请选择服务端（可选）" allowClear>
              {installedGames.map(game => (
                <Select.Option key={game.id || game} value={game.id || game}>
                  {game.name || game}
                </Select.Option>
              ))}
              {externalGames.map(game => (
                <Select.Option key={game.id} value={game.id}>
                  {game.name} (外部)
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
          
          <Form.Item
            name="autoControl"
            valuePropName="checked"
            tooltip="启用后，当关联的服务端启动时自动启用备份任务，服务端停止时自动停用备份任务"
          >
            <Checkbox>自动控制（根据服务端状态）</Checkbox>
          </Form.Item>
          
          <div style={{ textAlign: 'center', marginTop: 24 }}>
            <Button 
              type="default" 
              style={{ marginRight: 8 }}
              onClick={() => {
                setBackupModalVisible(false);
                setEditingBackupTask(null);
                backupForm.resetFields();
              }}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit">
              {editingBackupTask ? '更新任务' : '创建任务'}
            </Button>
          </div>
        </Form>
        
        <div style={{ marginTop: 20, padding: 16, backgroundColor: '#f6f8fa', borderRadius: 6 }}>
          <p style={{ margin: 0, fontSize: 12, color: '#666' }}>
            <strong>说明：</strong><br/>
            • 路径全部为容器路径，也就是文件管理中的路径<br/>
            • 备份文件将保存到 /home/steam/backup/任务名称/ 目录<br/>
            • 使用tar格式进行归档压缩<br/>
            • 自动删除超出保留份数的旧备份文件
          </p>
        </div>
      </Modal>
      
      {/* 文件收藏Modal */}
      <Modal
        title={editingFavorite ? '编辑收藏文件' : '添加收藏文件'}
        open={favoriteModalVisible}
        onCancel={() => {
          setFavoriteModalVisible(false);
          setEditingFavorite(null);
          favoriteForm.resetFields();
        }}
        footer={null}
        width={isMobile ? "95%" : 600}
      >
        <Form
          form={favoriteForm}
          layout="vertical"
          onFinish={handleFavoriteFormSubmit}
          style={{ marginTop: 20 }}
        >
          <Form.Item
            name="name"
            label="文件备注"
            rules={[{ required: true, message: '请输入文件备注' }]}
          >
            <Input placeholder="例如：服务器配置文件" />
          </Form.Item>
          
          <Form.Item
            name="filePath"
            label="文件路径"
            rules={[{ required: true, message: '请输入文件路径' }]}
          >
            <Input.Group compact>
              <Form.Item name="filePath" noStyle>
                <Input 
                  style={{ width: 'calc(100% - 80px)' }}
                  placeholder="例如：/home/steam/games/minecraft/server.properties" 
                />
              </Form.Item>
              <Button 
                style={{ width: 80 }}
                onClick={() => setDirectoryPickerVisible(true)}
              >
                浏览
              </Button>
            </Input.Group>
          </Form.Item>
          
          <Form.Item
            name="description"
            label="描述（可选）"
          >
            <Input.TextArea 
              placeholder="例如：Minecraft服务器的主要配置文件，包含端口、游戏模式等设置" 
              rows={3}
            />
          </Form.Item>
          
          <div style={{ textAlign: 'center', marginTop: 24 }}>
            <Button 
              type="default" 
              style={{ marginRight: 8 }}
              onClick={() => {
                setFavoriteModalVisible(false);
                setEditingFavorite(null);
                favoriteForm.resetFields();
              }}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit">
              {editingFavorite ? '更新收藏' : '添加收藏'}
            </Button>
          </div>
        </Form>
        
        <div style={{ marginTop: 20, padding: 16, backgroundColor: '#f6f8fa', borderRadius: 6 }}>
          <p style={{ margin: 0, fontSize: 12, color: '#666' }}>
            <strong>说明：</strong><br/>
            • 文件路径为容器内的绝对路径，也就是文件管理中显示的路径<br/>
            • 点击"打开编辑"将跳转到文件管理页面并定位到该文件<br/>
            • 文件备注和文件路径为必填项，描述为可选项
          </p>
        </div>
      </Modal>
      
      {/* 文件管理器Modal - THIS IS THE NESTED WINDOW */}
      <Modal
        title={`游戏文件管理 - ${fileManagerPath.split('/').pop() || ''}`} // Dynamic title based on path
        open={fileManagerVisible} // Controlled by fileManagerVisible state
        onCancel={() => {
          // const timestamp = () => new Date().toLocaleTimeString();
          // console.log(`${timestamp()} APP: Closing FileManager Modal via onCancel. Setting fileManagerVisible to false.`);
          setFileManagerVisible(false); // Uses wrapped setter
        }}
        destroyOnClose // Ensures FileManager instance is unmounted when Modal is closed
        footer={null}
        width={isMobile ? "95%" : "80%"}
        style={{ top: 20 }}
        bodyStyle={{ 
          padding: 0, 
          maxHeight: 'calc(100vh - 150px)',
          minHeight: isMobile ? '400px' : '550px',
          overflow: 'auto',
          paddingBottom: '30px' // Added some padding at the bottom
        }}
      >
        {/* 
          Conditionally render FileManager only when the modal is supposed to be visible.
          Crucially, pass fileManagerVisible to the isVisible prop of this FileManager instance.
        */}
        {fileManagerVisible && (
          <FileManager 
            initialPath={fileManagerPath} 
            isVisible={fileManagerVisible} // Pass the modal's visibility state
            initialFileToOpen={initialFileToOpen}
          />
        )}
      </Modal>
      
      {/* 添加内网穿透文档弹窗 */}
      <FrpDocModal visible={frpDocModalVisible} onClose={handleCloseFrpDocModal} />
      
      {/* 版本更新提示弹窗 */}
      <Modal
        title="🎉 发现新版本"
        open={versionUpdateModalVisible}
        onCancel={() => setVersionUpdateModalVisible(false)}
        footer={[
          <Button key="later" onClick={() => setVersionUpdateModalVisible(false)}>
            稍后提醒
          </Button>,
          <Button key="copy" onClick={() => {
            const dockerCommand = `docker pull xiaozhu674/gameservermanager:${latestVersionInfo?.version || 'latest'}`;
            
            // 检查是否支持现代剪贴板API
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(dockerCommand).then(() => {
                message.success('Docker镜像地址已复制到剪贴板');
              }).catch(() => {
                message.error('复制失败，请手动复制');
              });
            } else {
              // 降级方案：使用传统的document.execCommand
              try {
                const textArea = document.createElement('textarea');
                textArea.value = dockerCommand;
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                
                if (successful) {
                  message.success('Docker镜像地址已复制到剪贴板');
                } else {
                  message.error('复制失败，请手动复制：' + dockerCommand);
                }
              } catch (err) {
                message.error('复制失败，请手动复制：' + dockerCommand);
              }
            }
          }}>
            复制镜像地址
          </Button>,
          <Button 
            key="downloadImage" 
            type="default"
            loading={downloadingImage}
            onClick={handleDownloadImage}
          >
            下载镜像
          </Button>,
          <Button key="download" type="primary" onClick={() => {
            window.open('https://pan.baidu.com/s/1NyinYIwX1xeL4jWafIuOgw?pwd=v75z', '_blank');
          }}>
            前往下载离线镜像
          </Button>
        ]}
        width={500}
      >
        <div style={{ padding: '16px 0' }}>
          <p style={{ fontSize: '16px', marginBottom: '16px' }}>
            <strong>当前版本：</strong>{currentVersion}
          </p>
          <p style={{ fontSize: '16px', marginBottom: '16px' }}>
            <strong>最新版本：</strong>{latestVersionInfo?.version}
          </p>
          {latestVersionInfo?.description && (
            <div>
              <p style={{ fontSize: '16px', marginBottom: '8px' }}>
                <strong>更新内容：</strong>
              </p>
              <div style={{ 
                background: '#f5f5f5', 
                padding: '12px', 
                borderRadius: '6px',
                fontSize: '14px',
                lineHeight: '1.6'
              }}>
                {typeof latestVersionInfo.description === 'object' ? 
                  Object.entries(latestVersionInfo.description).map(([type, content], index) => (
                    <div key={index} style={{ marginBottom: index < Object.entries(latestVersionInfo.description).length - 1 ? '8px' : '0' }}>
                      <strong style={{ color: '#1890ff' }}>{type}：</strong>{content}
                    </div>
                  )) :
                  latestVersionInfo.description
                }
              </div>
            </div>
          )}
        </div>
      </Modal>
      
      {/* 目录选择器 - 收藏文件 */}
      <DirectoryPicker
        visible={directoryPickerVisible}
        onCancel={() => setDirectoryPickerVisible(false)}
        onSelect={(path) => {
          favoriteForm.setFieldsValue({ filePath: path });
          setDirectoryPickerVisible(false);
        }}
        title="选择文件路径"
        allowFileSelection={true}
      />
      
      {/* 目录选择器 - 定时备份 */}
      <DirectoryPicker
        visible={backupDirectoryPickerVisible}
        onCancel={() => setBackupDirectoryPickerVisible(false)}
        onSelect={(path) => {
          backupForm.setFieldsValue({ directory: path });
          setBackupDirectoryPickerVisible(false);
        }}
        title="选择备份目录"
      />
      
      {/* 全局音乐播放器 */}
      <GlobalMusicPlayer />
    </Layout>
  );
};

export default App;