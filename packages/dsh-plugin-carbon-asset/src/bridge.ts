/**
 * DeepSeek Harness (dsh) 碳资产引擎双模通信适配桥
 * 
 * 通信策略：
 * 1. 优先尝试向 FastAPI 服务 (默认 http://127.0.0.1:8000) 发起异步 HTTP 请求；
 * 2. 若 API 服务未启动或通信超时，自动降级为启动 Python 子进程调用 scripts/cli_bridge.py；
 * 3. 具备自适应路径发现与错误自愈容错，杜绝未捕获异常导致 Agent 崩溃。
 */

// @ts-ignore
import { spawn } from 'node:child_process'
// @ts-ignore
import * as fs from 'node:fs'
// @ts-ignore
import * as path from 'node:path'
// @ts-ignore
import { fileURLToPath } from 'node:url'

declare const process: any

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export interface BridgeConfig {
  apiBaseUrl?: string
  preferHttp?: boolean
  pythonPath?: string
  projectRoot?: string
}

export class CarbonEngineBridge {
  private apiBaseUrl: string
  private preferHttp: boolean
  private pythonPath: string
  private projectRoot: string

  constructor(config: BridgeConfig = {}) {
    const env = (typeof process !== 'undefined' && process.env) ? process.env : {}
    this.apiBaseUrl = config.apiBaseUrl || env.CARBON_API_BASE_URL || 'http://127.0.0.1:8000'
    this.preferHttp = config.preferHttp !== false

    // 1. 自适应探测项目根目录 (需包含 scripts/cli_bridge.py)
    this.projectRoot = this.detectProjectRoot(config.projectRoot, env)

    // 2. 自适应探测有效 Python 解释器路径
    this.pythonPath = this.detectPythonPath(config.pythonPath, env, this.projectRoot)
  }

  private detectProjectRoot(explicitRoot?: string, env: any = {}): string {
    const candidates = [
      explicitRoot,
      env.CARBON_PROJECT_ROOT,
      path.resolve(__dirname, '../../../'),
      path.resolve(__dirname, '../../'),
      process.cwd(),
    ]
    for (const c of candidates) {
      if (c && typeof c === 'string') {
        try {
          const script = path.resolve(c, 'scripts', 'cli_bridge.py')
          if (fs.existsSync(script)) {
            return path.resolve(c)
          }
        } catch {
          // ignore
        }
      }
    }
    return path.resolve(__dirname, '../../../')
  }

  private detectPythonPath(explicitPython?: string, env: any = {}, projectRoot: string = ''): string {
    const candidates = [
      explicitPython,
      env.PYTHON_PATH,
      path.resolve(projectRoot, '.venv', 'Scripts', 'python.exe'),
      path.resolve(projectRoot, '.venv', 'bin', 'python'),
      path.resolve(projectRoot, 'venv', 'Scripts', 'python.exe'),
      path.resolve(projectRoot, 'venv', 'bin', 'python'),
      process.platform === 'win32' ? 'python' : 'python3',
      'python',
    ]
    for (const c of candidates) {
      if (c && typeof c === 'string') {
        try {
          if (fs.existsSync(c)) {
            return c
          }
        } catch {
          // ignore
        }
      }
    }
    return explicitPython || 'python'
  }

  /**
   * 统一执行入口（带自动降级回退与异常软隔离机制）
   */
  async execute<T = any>(endpoint: string, command: string, payload: any): Promise<T> {
    if (this.preferHttp) {
      try {
        return await this.callHttp<T>(endpoint, payload)
      } catch (httpErr: any) {
        // HTTP 连接失败（服务未启动），自动降级为本地 CLI 进程
        try {
          return await this.callCli<T>(command, payload)
        } catch (cliErr: any) {
          // 双通道均失败时，返回结构化错误报告，避免 Harness 调度循环崩溃
          return {
            status: 'error',
            error: `碳资产计算引擎调用失败: [HTTP] ${httpErr.message}; [CLI] ${cliErr.message}`,
            suggestion: '请确认已启动后端服务 (http://127.0.0.1:8000) 或配置正确的 Python 运行环境。',
          } as T
        }
      }
    } else {
      try {
        return await this.callCli<T>(command, payload)
      } catch (cliErr: any) {
        try {
          return await this.callHttp<T>(endpoint, payload)
        } catch (httpErr: any) {
          return {
            status: 'error',
            error: `碳资产计算引擎调用失败: [CLI] ${cliErr.message}; [HTTP] ${httpErr.message}`,
            suggestion: '请确认已启动后端服务 (http://127.0.0.1:8000) 或配置正确的 Python 运行环境。',
          } as T
        }
      }
    }
  }

  /**
   * HTTP 通信
   */
  private async callHttp<T>(endpoint: string, payload: any): Promise<T> {
    const url = `${this.apiBaseUrl.replace(/\/+$/, '')}${endpoint}`
    const isGet = !payload || Object.keys(payload).length === 0

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 8000)

    try {
      const response = await fetch(url, {
        method: isGet ? 'GET' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: isGet ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`HTTP ${response.status}: ${errorText}`)
      }

      return await response.json() as T
    } finally {
      clearTimeout(timeout)
    }
  }

  /**
   * Python 子进程 CLI 降级调用
   */
  private async callCli<T>(command: string, payload: any): Promise<T> {
    const scriptPath = path.resolve(this.projectRoot, 'scripts', 'cli_bridge.py')
    if (!fs.existsSync(scriptPath)) {
      throw new Error(`未找到桥接脚本: ${scriptPath}`)
    }

    const jsonInput = JSON.stringify(payload || {})
    const env = (typeof process !== 'undefined' && process.env) ? process.env : {}

    return new Promise((resolve, reject) => {
      const proc = spawn(this.pythonPath, [scriptPath, command, '--json', jsonInput], {
        cwd: this.projectRoot,
        env: { ...env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
      })

      let stdout = ''
      let stderr = ''
      let isSettled = false

      const timer = setTimeout(() => {
        if (!isSettled) {
          isSettled = true
          proc.kill()
          reject(new Error(`Python CLI 执行超时 (30s): ${command}`))
        }
      }, 30000)

      proc.stdout.on('data', (data: any) => { stdout += data.toString('utf-8') })
      proc.stderr.on('data', (data: any) => { stderr += data.toString('utf-8') })

      proc.on('close', (code: any) => {
        if (isSettled) return
        isSettled = true
        clearTimeout(timer)
        if (code === 0) {
          try {
            resolve(JSON.parse(stdout) as T)
          } catch (e: any) {
            reject(new Error(`CLI 输出 JSON 解析失败: ${stdout}`))
          }
        } else {
          reject(new Error(`Python CLI 执行失败 (code ${code}): ${stderr || stdout}`))
        }
      })

      proc.on('error', (err: any) => {
        if (isSettled) return
        isSettled = true
        clearTimeout(timer)
        reject(new Error(`无法启动 Python 解释器 (${this.pythonPath}): ${err.message}`))
      })
    })
  }
}
