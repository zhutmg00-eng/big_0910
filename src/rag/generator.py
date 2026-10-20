"""LLM调用与Prompt模板引擎

支持错误处理：
- API key缺失 → 返回提示信息
- API超时/限流 → 重试1次后降级
- 其他异常 → 返回错误信息
"""
from typing import List, Dict
from src.config import LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, get_llm_config

# ============================================================
# Prompt模板
# ============================================================

SYSTEM_PROMPT = """你是一位严谨的交通低碳政策研究助手，服务于物流运输企业。
你的职责是：基于提供的政策条款（检索结果）和企业数据，为企业生成准确、可操作的政策分析与减排建议。

请遵循以下原则：
1. 只基于提供的政策条款内容作答，不要编造信息
2. 如果检索到的政策条款不足以回答用户问题，请明确说明"根据当前检索结果，无法确定..."
3. 引用政策时，注明来源文件名和发布日期
4. 建议应具体、可执行，避免空泛的"应加强管理"类表述
5. 必须先判断政策适用范围；不得把发电、钢铁等行业的配额义务直接套用于物流企业
6. 物流运输行业目前未纳入全国碳市场配额管理，不得宣称其模拟预算差额是法定配额、履约义务或可交易资产
7. 回答格式：【政策依据】→【适用情况分析】→【建议措施】→【风险提示】"""


def build_user_prompt(
    user_question: str,
    retrieved_chunks: List[Dict],
    carbon_profile: dict,
) -> str:
    """
    构建发送给LLM的完整用户Prompt

    结构：
    1. 检索到的政策条款（作为上下文）
    2. 企业碳画像（碳排放数据）
    3. 用户问题
    """
    # 组装检索上下文
    context_parts = []
    for i, chunk in enumerate(retrieved_chunks, 1):
        source = chunk.get("metadata", {}).get("source", "未知来源")
        date = chunk.get("metadata", {}).get("date", "")
        date_str = f" ({date})" if date else ""
        context_parts.append(
            f"[参考条款{i}] 来源: {source}{date_str}\n{chunk['text']}"
        )
    context = "\n\n---\n\n".join(context_parts) if context_parts else "（未检索到相关政策条款）"

    # 兼容 API 当前结构和早期脚本中的平铺结构。
    budget = carbon_profile.get("carbon_budget", {})
    scenario_cost = carbon_profile.get("scenario_cost", {})
    profile_str = f"""企业类型: {carbon_profile.get('企业类型', '物流运输企业')}
车队规模: {carbon_profile.get('total_vehicles', carbon_profile.get('总车辆数', '未知'))} 辆
年度直接运营排放: {carbon_profile.get('total_emission_t', carbon_profile.get('年度碳排放_t', '未知'))} tCO2e
模拟碳预算差额: {budget.get('预算差额_t', carbon_profile.get('预算差额_t', '未知'))} tCO2e
情景状态: {budget.get('状态', carbon_profile.get('情景状态', '未知'))}
碳价对标情景成本: {scenario_cost.get('情景成本_参考价', carbon_profile.get('情景成本_元', '未知'))} 元"""

    return f"""请根据以下政策条款，结合该企业的排放与减排情景，回答企业的问题。

====== 相关碳交易政策条款 ======
{context}

====== 企业排放与减排情景 ======
{profile_str}

====== 企业问题 ======
{user_question}

请按以下格式回答：
【政策依据】列出适用的政策条款（注明来源文件名）
【适用情况分析】先判断政策是否适用于物流运输企业，再结合排放数据分析
【建议措施】给出具体可执行的减排或数据管理建议
【风险提示】说明政策适用边界、核算边界和信息时效性"""


def build_retrieval_answer(
    user_question: str,
    retrieved_chunks: List[Dict],
) -> str:
    """在未配置 LLM 时生成可读、可追溯的检索式回答。"""
    if not retrieved_chunks:
        return (
            "【检索结论】\n当前知识库未找到足够相关的政策资料，无法据此回答。\n\n"
            "【风险提示】\n请补充权威来源并核实政策时效性后再作判断。"
        )

    top_source = retrieved_chunks[0].get("metadata", {}).get("source", "未知来源")
    lines = [
        "【检索结论】",
        f"针对“{user_question}”，当前最相关的资料是《{top_source}》。以下为知识库原文摘录，未调用大模型扩写。",
        "",
        "【政策原文摘录】",
    ]
    seen_sources = set()
    for chunk in retrieved_chunks[:3]:
        metadata = chunk.get("metadata", {})
        source = metadata.get("source", "未知来源")
        date = metadata.get("date", "")
        text = " ".join(chunk.get("text", "").split())
        excerpt = text[:280] + ("..." if len(text) > 280 else "")
        source_label = f"《{source}》" + (f"（{date}）" if date else "")
        if source in seen_sources:
            source_label += "（续）"
        seen_sources.add(source)
        lines.append(f"- {source_label}：{excerpt}")

    lines.extend([
        "",
        "【适用性提示】",
        "物流运输行业目前未纳入全国碳市场配额管理。检索到的发电、钢铁等行业履约规定不能直接作为物流企业的法定义务；本系统的模拟碳预算仅用于科研情景比较。",
    ])
    return "\n".join(lines)


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = None,
    fallback_answer: str = "",
) -> str:
    """
    调用大语言模型API

    支持的模型：deepseek-chat / qwen-turbo / glm-4-flash

    错误处理：
    - API key未配置 → 返回降级提示
    - 网络超时/连接中断/限流/5xx → 按异常类型重试1次（指数退避）
    - 认证失败 → 直接提示，不重试
    - 其他异常 → 返回降级提示并注明失败类型
    """
    model = model or LLM_MODEL
    temperature = temperature if temperature is not None else LLM_TEMPERATURE
    config = get_llm_config(model)

    # 检查API key
    api_key = config.get("api_key", "")
    if not api_key:
        return fallback_answer or "未配置 LLM API 密钥，当前仅提供政策检索结果。"

    try:
        from openai import OpenAI
    except ImportError:
        return "⚠️ openai包未安装，请运行 pip install openai"

    client = OpenAI(api_key=api_key, base_url=config["base_url"])

    # 重试逻辑（最多2次）。按异常类型判断而非匹配错误文本：连接重置、DNS 失败、
    # 502/503/504 等消息里并不含 rate/timeout，靠字符串匹配会第一次失败就放弃，
    # 于是演示时一次网络抖动就直接退化成检索摘录。
    max_retries = 2
    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=LLM_MAX_TOKENS,
                timeout=30,  # 30秒超时
            )
            return _extract_completion_text(response)

        except Exception as e:
            last_error = e
            error_type = type(e).__name__

            if _is_auth_error(e):
                return f"⚠️ API认证失败，请检查API key配置: {error_type}"

            # 限流/超时/连接类错误 → 重试
            if _is_retryable_error(e):
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)  # 指数退避
                    continue

            # 其他错误
            break

    error_name = type(last_error).__name__ if last_error is not None else "未知错误"
    # 绝不把 user_prompt 拼进返回值：它含内部提示词模板与政策全文，属于内部结构，
    # 且会被误当成「模型复述的政策内容」。
    base = fallback_answer or "（未提供检索式回答，请检查 RAG 检索链路）"
    return f"LLM 调用失败（{error_name}），已返回检索式回答。\n\n{base}"


def _extract_completion_text(response) -> str:
    """从 LLM 响应中取出正文，并显式处理空响应与截断。"""
    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError("LLM 返回空 choices（可能被内容安全策略拦截）")
    choice = choices[0]
    content = (getattr(choice.message, "content", None) or "").strip()
    if not content:
        raise RuntimeError("LLM 返回空内容")
    if getattr(choice, "finish_reason", None) == "length":
        content += "\n\n⚠️ 回答因长度上限被截断，【风险提示】可能不完整，请人工复核。"
    return content


def _is_auth_error(exc: Exception) -> bool:
    """认证/权限类错误：不重试，直接提示。"""
    name = type(exc).__name__
    if "Authentication" in name or "PermissionDenied" in name:
        return True
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return "401" in text or "403" in text or "invalid api key" in text or "unauthorized" in text


def _is_retryable_error(exc: Exception) -> bool:
    """可重试的瞬时错误：超时、连接中断、限流、5xx。"""
    name = type(exc).__name__
    if any(k in name for k in ("Timeout", "Connection", "RateLimit", "InternalServer")):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    text = str(exc).lower()
    return any(k in text for k in ("timed out", "timeout", "rate limit", "connection"))
