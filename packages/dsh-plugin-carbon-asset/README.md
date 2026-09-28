# dsh-plugin-carbon-asset

[![dsh-plugin](https://img.shields.io/badge/dsh-plugin-brightgreen)](https://github.com/deepseek-ai/deepseek-harness)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness) 官方规范生态插件，为 DeepSeek AI 智能体赋予面向物流运输与交通领域的**碳排放核算、TCO 投资回收期经济账、减排多情景模拟与双碳政策合规解读**能力。

---

## 🚀 核心功能与 Agent Tools

插件基于 dsh 的 `defineTool` 规范为智能体注册了 6 大专业垂直工具：

| 工具名称 | 描述 | 核心输出 |
| :--- | :--- | :--- |
| **`carbon_calculate`** | 物流车队直接运营碳排放核算 | 总直接排放 (tCO2e)、模拟碳预算差额、分车型排放明细、对标碳成本 |
| **`carbon_tco_evaluate`** | 新能源替换 TCO 与投资回收期测算 | 增量投资 $\Delta\text{CAPEX}$、年运营节省 $\Delta\text{OPEX}$、静态回收期、吨碳减排边际成本 (MAC) |
| **`carbon_reduction_scenario`** | 综合减排多情景模拟 (替换+提满载) | 情景直接减排量、减排百分比、情景成本变化、TCO 投资评估建议 |
| **`carbon_policy_query`** | 碳市场与绿色低碳政策法规智能解读 | 政策依据（带法规名称及发布日期）、适用性分析、合规建议与风险提示 |
| **`carbon_enterprise_compare`** | 多物流企业/车队碳资产横向对标 | 排放量横向排名、预算缺口对标、情景成本对比矩阵 |
| **`carbon_turnover_evaluate`** | 货物周转量与外购电间接排放对标 | 万吨公里周转量、单位周转量碳排放强度 (gCO2/t·km)、新能源车 Scope 2 间接排放 |
---

## 📦 安装与配置

### 方式一：在 DeepSeek Harness 中本地挂载

在您的 DeepSeek Harness 工程的 `cordis.yml` 中添加本地路径：

```yaml
- name: './packages/dsh-plugin-carbon-asset'
  config:
    apiBaseUrl: 'http://127.0.0.1:8000' # 可选，FastAPI 服务地址
    preferHttp: true                    # 默认 true：服务在线时走 HTTP，离线自动降级为 Python CLI 进程
```

### 方式二：通过 CLI 载入

```bash
dsh plugin add ./packages/dsh-plugin-carbon-asset
```

---

## ⚡ 双模通信机制 (Dual-mode Architecture)

本插件采用零门槛自适应架构：
1. **高性能 HTTP 模式**：若本地启动了项目的 FastAPI 后端（`uvicorn src.api.main:app --port 8000`），插件以毫秒级异步 HTTP 请求与计算引擎交互。
2. **免服务 CLI 模式**：若未启动 FastAPI 后端，插件自动通过 Python 子进程启动 `scripts/cli_bridge.py` 直接调用底层计算引擎，**无需手动常驻后端服务即可即开即用**！

---

## 📄 License

MIT License.
