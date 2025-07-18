import { Router, Request, Response } from 'express'
import { AuthManager } from '../modules/auth/AuthManager.js'
import { authenticateToken, AuthenticatedRequest, requireAdmin } from '../middleware/auth.js'
import logger from '../utils/logger.js'
import Joi from 'joi'

const router = Router()

// 登录限流已移除

// 验证schemas
const loginSchema = Joi.object({
  username: Joi.string().alphanum().min(3).max(30).required().messages({
    'string.alphanum': '用户名只能包含字母和数字',
    'string.min': '用户名至少3个字符',
    'string.max': '用户名最多30个字符',
    'any.required': '用户名是必填项'
  }),
  password: Joi.string().min(6).required().messages({
    'string.min': '密码至少6个字符',
    'any.required': '密码是必填项'
  }),
  captchaId: Joi.string().optional(),
  captchaCode: Joi.string().optional()
})

const changePasswordSchema = Joi.object({
  oldPassword: Joi.string().required().messages({
    'any.required': '原密码是必填项'
  }),
  newPassword: Joi.string().min(6).required().messages({
    'string.min': '新密码至少6个字符',
    'any.required': '新密码是必填项'
  })
})

const changeUsernameSchema = Joi.object({
  newUsername: Joi.string().alphanum().min(3).max(30).required().messages({
    'string.alphanum': '用户名只能包含字母和数字',
    'string.min': '用户名至少3个字符',
    'string.max': '用户名最多30个字符',
    'any.required': '新用户名是必填项'
  })
})

const registerSchema = Joi.object({
  username: Joi.string().alphanum().min(3).max(30).required().messages({
    'string.alphanum': '用户名只能包含字母和数字',
    'string.min': '用户名至少3个字符',
    'string.max': '用户名最多30个字符',
    'any.required': '用户名是必填项'
  }),
  password: Joi.string().min(6).required().messages({
    'string.min': '密码至少6个字符',
    'any.required': '密码是必填项'
  })
})

// 设置认证路由的函数
export function setupAuthRoutes(authManager: AuthManager): Router {
  // 获取验证码接口
  router.get('/captcha', (req: Request, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      const captcha = authManager.generateCaptcha()
      res.json({
        success: true,
        captcha
      })
    } catch (error) {
      logger.error('获取验证码错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '获取验证码失败'
      })
    }
  })

  // 检查是否需要验证码接口
  router.post('/check-captcha', (req: Request, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      const { username } = req.body
      if (!username) {
        return res.status(400).json({
          error: '用户名是必填项'
        })
      }

      const requireCaptcha = authManager.checkIfRequireCaptcha(username)
      res.json({
        success: true,
        requireCaptcha
      })
    } catch (error) {
      logger.error('检查验证码需求错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '检查验证码需求失败'
      })
    }
  })
  // 登录接口
  router.post('/login', async (req: Request, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

    // 验证请求数据
    const { error, value } = loginSchema.validate(req.body)
    if (error) {
      return res.status(400).json({
        error: '请求数据无效',
        message: error.details[0].message
      })
    }

    const { username, password, captchaId, captchaCode } = value
    const clientIP = req.ip || req.connection.remoteAddress || 'unknown'
    
    const result = await authManager.login(username, password, clientIP, captchaId, captchaCode)
    
    if (result.success) {
      res.json({
        success: true,
        message: result.message,
        token: result.token,
        user: result.user
      })
    } else {
      res.status(401).json({
        success: false,
        message: result.message,
        requireCaptcha: result.requireCaptcha
      })
    }
  } catch (error) {
    logger.error('登录接口错误:', error)
    res.status(500).json({
      error: '服务器内部错误',
      message: '登录失败，请稍后重试'
    })
  }
})

  // 验证token接口
  router.get('/verify', authenticateToken, (req: AuthenticatedRequest, res: Response) => {
    res.json({
      success: true,
      user: req.user,
      message: 'Token有效'
    })
  })

  // 修改密码接口
  router.post('/change-password', authenticateToken, async (req: AuthenticatedRequest, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      // 验证请求数据
      const { error, value } = changePasswordSchema.validate(req.body)
      if (error) {
        return res.status(400).json({
          error: '请求数据无效',
          message: error.details[0].message
        })
      }

      const { oldPassword, newPassword } = value
      const username = req.user!.username
      
      const result = await authManager.changePassword(username, oldPassword, newPassword)
      
      if (result.success) {
        res.json({
          success: true,
          message: result.message
        })
      } else {
        res.status(400).json({
          success: false,
          message: result.message
        })
      }
    } catch (error) {
      logger.error('修改密码接口错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '修改密码失败，请稍后重试'
      })
    }
  })

  // 修改用户名接口
  router.post('/change-username', authenticateToken, async (req: AuthenticatedRequest, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      // 验证请求数据
      const { error, value } = changeUsernameSchema.validate(req.body)
      if (error) {
        return res.status(400).json({
          error: '请求数据无效',
          message: error.details[0].message
        })
      }

      const { newUsername } = value
      const currentUsername = req.user!.username
      
      const result = await authManager.changeUsername(currentUsername, newUsername)
      
      if (result.success) {
        // 更新用户信息
        req.user!.username = newUsername
        
        res.json({
          success: true,
          message: result.message,
          user: {
            id: req.user!.userId,
            username: newUsername,
            role: req.user!.role
          }
        })
      } else {
        res.status(400).json({
          success: false,
          message: result.message
        })
      }
    } catch (error) {
      logger.error('修改用户名接口错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '修改用户名失败，请稍后重试'
      })
    }
  })

  // 获取用户列表（仅管理员）
  router.get('/users', authenticateToken, requireAdmin, (req: AuthenticatedRequest, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      const users = authManager.getUsers()
      res.json({
        success: true,
        users
      })
    } catch (error) {
      logger.error('获取用户列表错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '获取用户列表失败'
      })
    }
  })

  // 获取登录尝试记录（仅管理员）
  router.get('/login-attempts', authenticateToken, requireAdmin, (req: AuthenticatedRequest, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      const limit = parseInt(req.query.limit as string) || 100
      const attempts = authManager.getLoginAttempts(limit)
      
      res.json({
        success: true,
        attempts
      })
    } catch (error) {
      logger.error('获取登录尝试记录错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '获取登录记录失败'
      })
    }
  })

  // 检查是否有用户存在
  router.get('/has-users', (req: Request, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      const hasUsers = authManager.hasUsers()
      res.json({
        success: true,
        hasUsers
      })
    } catch (error) {
      logger.error('检查用户存在错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '检查用户失败'
      })
    }
  })

  // 注册接口（仅在没有用户时可用）
  router.post('/register', async (req: Request, res: Response) => {
    try {
      if (!authManager) {
        return res.status(500).json({ error: '认证管理器未初始化' })
      }

      // 检查是否已有用户，如果有则不允许注册
      if (authManager.hasUsers()) {
        return res.status(403).json({
          success: false,
          message: '系统已有用户，无法注册新用户'
        })
      }

      // 验证请求数据
      const { error, value } = registerSchema.validate(req.body)
      if (error) {
        return res.status(400).json({
          error: '请求数据无效',
          message: error.details[0].message
        })
      }

      const { username, password } = value
      
      // 注册第一个用户为管理员
      const result = await authManager.register(username, password, 'admin')
      
      if (result.success) {
        res.json({
          success: true,
          message: result.message,
          user: result.user
        })
      } else {
        res.status(400).json({
          success: false,
          message: result.message
        })
      }
    } catch (error) {
      logger.error('注册接口错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '注册失败，请稍后重试'
      })
    }
  })

  // 登出接口（客户端处理，服务端记录）
  router.post('/logout', authenticateToken, (req: AuthenticatedRequest, res: Response) => {
    try {
      logger.info(`用户 ${req.user!.username} 登出`)
      res.json({
        success: true,
        message: '登出成功'
      })
    } catch (error) {
      logger.error('登出接口错误:', error)
      res.status(500).json({
        error: '服务器内部错误',
        message: '登出失败'
      })
    }
  })

  return router
}