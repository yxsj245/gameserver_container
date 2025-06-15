import React, { useState, useEffect } from 'react';
import {
  Card,
  Input,
  Button,
  List,
  Select,
  Form,
  message,
  Modal,
  Spin,
  Tag,
  Space,
  Divider,
  Typography,
  Row,
  Col,
  Alert,
  Steps,
  Tooltip,
  Progress
} from 'antd';
import {
  SearchOutlined,
  DownloadOutlined,
  InfoCircleOutlined,
  RocketOutlined,
  CheckCircleOutlined,
  LoadingOutlined
} from '@ant-design/icons';
import axios from 'axios';

const { Option } = Select;
const { Title, Paragraph, Text } = Typography;
const { Step } = Steps;

interface Modpack {
  id: string;
  title: string;
  description: string;
  author: string;
  downloads?: number;
  icon_url?: string;
  categories?: string[];
  game_versions?: string[];
  loaders?: string[];
}

interface ModpackVersion {
  id: string;
  name: string;
  version_number: string;
  game_versions: string[];
  loaders: string[];
  date_published: string;
  downloads: number;
  changelog?: string;
}

interface JavaVersion {
  id: string;
  name: string;
  installed: boolean;
  version: string;
}

const MinecraftModpackDeploy: React.FC = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [maxResults, setMaxResults] = useState(20);
  const [modpacks, setModpacks] = useState<Modpack[]>([]);
  const [selectedModpack, setSelectedModpack] = useState<Modpack | null>(null);
  const [versions, setVersions] = useState<ModpackVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<ModpackVersion | null>(null);
  const [javaVersions, setJavaVersions] = useState<JavaVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployProgress, setDeployProgress] = useState(0);
  const [deployMessage, setDeployMessage] = useState('');
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [form] = Form.useForm();

  // 获取Java版本列表
  useEffect(() => {
    fetchJavaVersions();
  }, []);

  const fetchJavaVersions = async () => {
    try {
      const response = await axios.get('/api/environment/java/versions');
      if (response.data.status === 'success') {
        // 转换API响应格式以匹配组件期望的格式
        const formattedVersions = [
          {
            id: 'system',
            name: '系统默认Java',
            installed: true,
            version: 'System Default'
          },
          ...response.data.versions.map((v: any) => ({
            id: v.id,
            name: v.name,
            installed: v.installed,
            version: v.version || 'Not Installed'
          }))
        ];
        setJavaVersions(formattedVersions);
      }
    } catch (error) {
      console.error('获取Java版本失败:', error);
    }
  };

  // 搜索整合包
  const searchModpacks = async () => {
    if (!searchQuery.trim()) {
      message.warning('请输入搜索关键词');
      return;
    }

    setLoading(true);
    try {
      const response = await axios.get('/api/minecraft/modpack/search', {
        params: {
          query: searchQuery,
          max_results: maxResults
        }
      });

      if (response.data.status === 'success') {
        setModpacks(response.data.data);
        setCurrentStep(1);
      } else {
        message.error(response.data.message || '搜索失败');
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '搜索失败');
    } finally {
      setLoading(false);
    }
  };

  // 选择整合包
  const selectModpack = async (modpack: Modpack) => {
    setSelectedModpack(modpack);
    setLoading(true);

    try {
      const response = await axios.get(`/api/minecraft/modpack/${modpack.id}/versions`);
      if (response.data.status === 'success') {
        setVersions(response.data.data);
        setCurrentStep(2);
      } else {
        message.error(response.data.message || '获取版本失败');
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '获取版本失败');
    } finally {
      setLoading(false);
    }
  };

  // 选择版本
  const selectVersion = (version: ModpackVersion) => {
    setSelectedVersion(version);
    setCurrentStep(3);
  };

  // 部署整合包
  const deployModpack = async (values: any) => {
    if (!selectedModpack || !selectedVersion) {
      message.error('请先选择整合包和版本');
      return;
    }

    setDeploying(true);
    setDeployProgress(0);
    setDeployMessage('正在努力整理整合包信息...');
    
    try {
      // 启动部署
      const response = await axios.post('/api/minecraft/modpack/deploy', {
        modpack_id: selectedModpack.id,
        version_id: selectedVersion.id,
        folder_name: values.folder_name,
        java_version: values.java_version
      });

      if (response.data.status === 'success') {
        const deploymentId = response.data.deployment_id;
        setDeploymentId(deploymentId);
        
        // 开始监听部署进度
        const token = localStorage.getItem('auth_token');
        const eventSource = new EventSource(`/api/minecraft/modpack/deploy/stream?deployment_id=${deploymentId}&token=${token}`);
        
        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            
            if (data.error) {
              message.error(data.error);
              eventSource.close();
              setDeploying(false);
              return;
            }
            
            // 更新进度
            if (data.progress !== undefined) {
              setDeployProgress(data.progress);
            }
            if (data.message) {
              setDeployMessage(data.message);
            }
            
            // 检查是否完成
            if (data.complete) {
              eventSource.close();
              setDeploying(false);
              
              if (data.status === 'completed') {
                message.success('整合包部署成功！');
                setCurrentStep(4);
                
                // 显示部署结果
                Modal.success({
                  title: '部署成功',
                  content: (
                    <div>
                      <p><strong>整合包:</strong> {selectedModpack.title}</p>
                      <p><strong>版本:</strong> {selectedVersion.version_number}</p>
                      {data.data && (
                        <>
                          <p><strong>安装目录:</strong> {data.data.install_dir}</p>
                          <p><strong>启动脚本:</strong> {data.data.start_script}</p>
                        </>
                      )}
                      <p style={{ marginTop: 16, color: '#666' }}>
                        部署完成后，您可以在游戏管理页面找到新部署的服务器。
                      </p>
                    </div>
                  ),
                  onOk: () => {
                    // 重置表单
                    resetForm();
                  }
                });
              } else if (data.status === 'error') {
                message.error(data.message || '部署失败');
              }
            }
          } catch (e) {
            console.error('解析进度数据失败:', e);
          }
        };
        
        eventSource.onerror = (error) => {
          console.error('EventSource错误:', error);
          eventSource.close();
          setDeploying(false);
          message.error('连接部署进度流失败');
        };
        
        // 组件卸载时关闭EventSource
        return () => {
          eventSource.close();
        };
        
      } else {
        message.error(response.data.message || '启动部署失败');
        setDeploying(false);
      }
    } catch (error: any) {
      message.error(error.response?.data?.message || '启动部署失败');
      setDeploying(false);
    }
  };

  // 重置表单
  const resetForm = () => {
    setSearchQuery('');
    setMaxResults(20);
    setModpacks([]);
    setSelectedModpack(null);
    setVersions([]);
    setSelectedVersion(null);
    setCurrentStep(0);
    setDeploying(false);
    setDeployProgress(0);
    setDeployMessage('');
    setDeploymentId(null);
    form.resetFields();
  };

  // 获取推荐的Java版本
  const getRecommendedJavaVersion = (gameVersions: string[]) => {
    if (!gameVersions || gameVersions.length === 0) return 'system';
    
    const latestVersion = gameVersions[0]; // 假设第一个是最新版本
    const versionParts = latestVersion.split('.');
    if (versionParts.length >= 2) {
      const minorVersion = parseInt(versionParts[1]);
      if (minorVersion >= 18) return 'jdk17';
      if (minorVersion >= 17) return 'jdk17';
      if (minorVersion >= 12) return 'jdk11';
    }
    return 'jdk8';
  };

  const steps = [
    {
      title: '搜索整合包',
      description: '输入关键词搜索整合包'
    },
    {
      title: '选择整合包',
      description: '从搜索结果中选择整合包'
    },
    {
      title: '选择版本',
      description: '选择整合包版本'
    },
    {
      title: '配置部署',
      description: '配置安装选项并部署'
    },
    {
      title: '部署完成',
      description: '整合包部署成功'
    }
  ];

  return (
    <div style={{ padding: '20px' }}>
      <Title level={2}>Minecraft 整合包部署</Title>
      <Paragraph type="secondary">
        从 Modrinth 搜索并自动部署 Minecraft 整合包到服务器
      </Paragraph>

      <Steps current={currentStep} style={{ marginBottom: 32 }}>
        {steps.map((step, index) => (
          <Step
            key={index}
            title={step.title}
            description={step.description}
            icon={currentStep === index && (loading || deploying) ? <LoadingOutlined /> : undefined}
          />
        ))}
      </Steps>

      {/* 步骤1: 搜索整合包 */}
      {currentStep === 0 && (
        <Card title="搜索整合包" style={{ marginBottom: 16 }}>
          <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
            <Input
              placeholder="输入整合包名称进行搜索..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onPressEnter={searchModpacks}
              style={{ flex: 1 }}
            />
            <Button
              type="primary"
              icon={<SearchOutlined />}
              onClick={searchModpacks}
              loading={loading}
            >
              搜索
            </Button>
          </Space.Compact>
          
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}>
              <div>
                <Text strong style={{ marginBottom: 8, display: 'block' }}>搜索结果数量</Text>
                <Select
                  value={maxResults}
                  onChange={setMaxResults}
                  style={{ width: '100%' }}
                  placeholder="选择搜索结果数量"
                >
                  <Option value={10}>10个结果</Option>
                  <Option value={20}>20个结果</Option>
                  <Option value={50}>50个结果</Option>
                  <Option value={100}>100个结果</Option>
                </Select>
              </div>
            </Col>
          </Row>
          
          <Alert
            message="提示"
            description="您可以搜索整合包名称、作者或关键词。可以调整搜索结果数量来获取更多或更少的结果。"
            type="info"
            showIcon
          />
        </Card>
      )}

      {/* 步骤2: 选择整合包 */}
      {currentStep === 1 && (
        <Card 
          title={`搜索结果 (${modpacks.length} 个整合包)`}
          extra={
            <Button onClick={() => setCurrentStep(0)}>重新搜索</Button>
          }
          style={{ marginBottom: 16 }}
        >
          <List
            dataSource={modpacks}
            renderItem={(modpack) => (
              <List.Item
                actions={[
                  <Button
                    type="primary"
                    onClick={() => selectModpack(modpack)}
                    loading={loading && selectedModpack?.id === modpack.id}
                  >
                    选择
                  </Button>
                ]}
              >
                <List.Item.Meta
                  avatar={
                    modpack.icon_url ? (
                      <img
                        src={modpack.icon_url}
                        alt={modpack.title}
                        style={{ width: 48, height: 48, borderRadius: 4 }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 48,
                          height: 48,
                          backgroundColor: '#f0f0f0',
                          borderRadius: 4,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center'
                        }}
                      >
                        📦
                      </div>
                    )
                  }
                  title={
                    <div>
                      <Text strong>{modpack.title}</Text>
                      <Text type="secondary" style={{ marginLeft: 8 }}>by {modpack.author}</Text>
                    </div>
                  }
                  description={
                    <div>
                      <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 8 }}>
                        {modpack.description}
                      </Paragraph>
                      <Space wrap>
                        <Text type="secondary">下载量: {modpack.downloads?.toLocaleString() || 0}</Text>
                        {(modpack.game_versions || []).slice(0, 3).map(version => (
                          <Tag key={version} color="blue">{version}</Tag>
                        ))}
                        {(modpack.loaders || modpack.categories || []).map(loader => (
                          <Tag key={loader} color="green">{loader}</Tag>
                        ))}
                      </Space>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* 步骤3: 选择版本 */}
      {currentStep === 2 && selectedModpack && (
        <Card
          title={`${selectedModpack.title} - 选择版本`}
          extra={
            <Button onClick={() => setCurrentStep(1)}>返回选择整合包</Button>
          }
          style={{ marginBottom: 16 }}
        >
          <List
            dataSource={versions}
            renderItem={(version) => (
              <List.Item
                actions={[
                  <Button
                    type="primary"
                    onClick={() => selectVersion(version)}
                  >
                    选择
                  </Button>
                ]}
              >
                <List.Item.Meta
                  title={
                    <div>
                      <Text strong>{version.name}</Text>
                      <Text type="secondary" style={{ marginLeft: 8 }}>v{version.version_number}</Text>
                    </div>
                  }
                  description={
                    <div>
                      <Space wrap style={{ marginBottom: 8 }}>
                        <Text type="secondary">
                          发布时间: {new Date(version.date_published).toLocaleDateString()}
                        </Text>
                        <Text type="secondary">
                          下载量: {version.downloads.toLocaleString()}
                        </Text>
                      </Space>
                      <div>
                        <Space wrap>
                          {version.game_versions.map(gameVersion => (
                            <Tag key={gameVersion} color="blue">{gameVersion}</Tag>
                          ))}
                          {version.loaders.map(loader => (
                            <Tag key={loader} color="green">{loader}</Tag>
                          ))}
                        </Space>
                      </div>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      )}

      {/* 步骤4: 配置部署 */}
      {currentStep === 3 && selectedModpack && selectedVersion && (
        <Card
          title="配置部署选项"
          extra={
            <Button onClick={() => setCurrentStep(2)}>返回选择版本</Button>
          }
          style={{ marginBottom: 16 }}
        >
          <Row gutter={24}>
            <Col span={12}>
              <Card size="small" title="整合包信息">
                <p><strong>名称:</strong> {selectedModpack.title}</p>
                <p><strong>版本:</strong> {selectedVersion.version_number}</p>
                <p><strong>游戏版本:</strong> {selectedVersion.game_versions.join(', ')}</p>
                <p><strong>加载器:</strong> {selectedVersion.loaders.join(', ')}</p>
              </Card>
            </Col>
            <Col span={12}>
              <Form
                form={form}
                layout="vertical"
                onFinish={deployModpack}
                initialValues={{
                  java_version: getRecommendedJavaVersion(selectedVersion.game_versions)
                }}
              >
                <Form.Item
                  label="安装文件夹名称(请使用英文字符)"
                  name="folder_name"
                  rules={[
                    { required: true, message: '请输入文件夹名称' },
                    { pattern: /^[^/\\:*?"<>|]+$/, message: '文件夹名称包含非法字符' }
                  ]}
                >
                  <Input placeholder="例如: my-modpack-server" />
                </Form.Item>

                <Form.Item
                  label={
                    <span>
                      Java 版本
                      <Tooltip title="根据游戏版本自动推荐合适的Java版本">
                        <InfoCircleOutlined style={{ marginLeft: 4 }} />
                      </Tooltip>
                    </span>
                  }
                  name="java_version"
                  rules={[{ required: true, message: '请选择Java版本' }]}
                >
                  <Select placeholder="选择Java版本">
                    {javaVersions.map(java => (
                      <Option key={java.id} value={java.id} disabled={!java.installed}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>{java.name}</span>
                          <div>
                            {java.installed ? (
                              <Tag color="green">已安装</Tag>
                            ) : (
                              <Tag color="red">未安装</Tag>
                            )}
                          </div>
                        </div>
                      </Option>
                    ))}
                  </Select>
                </Form.Item>

                <Form.Item>
                  <Space>
                    <Button
                      type="primary"
                      htmlType="submit"
                      icon={<RocketOutlined />}
                      loading={deploying}
                      size="large"
                    >
                      开始部署
                    </Button>
                    <Button onClick={resetForm}>重新开始</Button>
                  </Space>
                </Form.Item>
                
                {/* 部署进度显示 */}
                {deploying && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ marginBottom: 8 }}>
                      <Text strong>部署进度</Text>
                      <Text style={{ float: 'right' }}>{deployProgress}%</Text>
                    </div>
                    <Progress 
                      percent={deployProgress} 
                      status={deployProgress === 100 ? 'success' : 'active'}
                      strokeColor={{
                        '0%': '#108ee9',
                        '100%': '#87d068',
                      }}
                    />
                    <div style={{ marginTop: 8, color: '#666' }}>
                      <Text type="secondary">{deployMessage}</Text>
                    </div>
                  </div>
                )}
              </Form>
            </Col>
          </Row>

          <Alert
            message="部署说明"
            description={
              <div>
                <p>• 整合包文件下载需要一定的时间，请耐心等待。下载到最后几个文件卡住属于正常现象。您可以切换到其它页面程序将会在后台继续完成下载。</p>
                <p>• 系统会自动创建启动脚本和下载核心文件</p>
                <p>• 一些核心文件可能存在问题，启动失败建议您从“Minecraft部署”中重新下载核心到服务端，然后修改启动脚本中的核心名称即可。</p>
                <p>• 部署完成后可在游戏管理页面启动服务器</p>
                <p>• 若启动报错可发给AI进行判断。若报错存在HTTP字眼则代表网络问题，您需要使用代理模式</p>
              </div>
            }
            type="info"
            showIcon
            style={{ marginTop: 16 }}
          />
        </Card>
      )}

      {/* 步骤5: 部署完成 */}
      {currentStep === 4 && (
        <Card title="部署完成" style={{ textAlign: 'center', marginBottom: 16 }}>
          <div style={{ padding: '40px 20px' }}>
            <CheckCircleOutlined style={{ fontSize: 64, color: '#52c41a', marginBottom: 16 }} />
            <Title level={3}>整合包部署成功！</Title>
            <Paragraph>
              您的 Minecraft 整合包已成功部署，现在可以在游戏管理页面启动服务器了。
            </Paragraph>
            <Space>
              <Button type="primary" onClick={resetForm}>
                部署新的整合包
              </Button>
              <Button onClick={() => window.location.reload()}>
                返回游戏管理
              </Button>
            </Space>
          </div>
        </Card>
      )}
    </div>
  );
};

export default MinecraftModpackDeploy;