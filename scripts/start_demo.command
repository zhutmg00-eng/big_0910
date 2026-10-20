#!/bin/bash
# ============================================
# 碳路 v0.4 一键演示启动器（macOS 双击运行）
# 自动完成：检查环境 -> 装依赖 -> 初始化知识库 -> 起双服务 -> 开浏览器
# 幂等：重复运行只会跳过已完成的步骤
# ============================================
APP="$(cd "$(dirname "$0")/.." && pwd)"   # 本脚本位于 scripts/，项目根是上一级
cd "$APP" || exit 1

echo "== [1/5] 检查 Python 环境 =="
if [ ! -d ".venv" ]; then
  echo "  首次运行：创建虚拟环境 .venv ..."
  # 优先用新版 Python（3.13/3.12/3.11），都没有再用系统 python3
  PYBASE="$(command -v python3.12 || command -v python3.11 || command -v python3.13 || command -v python3)"
  echo "  使用解释器: $PYBASE"
  "$PYBASE" -m venv .venv || { echo "[失败] 创建虚拟环境出错，请确认已安装 Python 3.10+"; exit 1; }
fi
if ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "[失败] 现有 .venv 是 $(.venv/bin/python -V 2>&1)，项目需要 3.10+。"
  echo "   请执行：rm -rf .venv 后重新双击本脚本（推荐安装 Python 3.11/3.12）"
  exit 1
fi
PY="$APP/.venv/bin/python"
PIP="$APP/.venv/bin/pip"
echo "  Python: $("$PY" -V 2>&1)"

echo "== [2/5] 安装依赖（首次约 3-5 分钟，之后秒过）=="
"$PIP" install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null
REQ=requirements.txt
[ -f requirements-lock.txt ] && REQ=requirements-lock.txt   # 答辩机优先用锁定版本，保证与测试环境一致
"$PIP" install -q -r "$REQ" -i https://pypi.tuna.tsinghua.edu.cn/simple \
  || { echo "[失败] 依赖安装出错，请检查网络后重试"; exit 1; }
echo "  依赖就绪"

echo "== [3/5] 同步知识库（按内容哈希增量；未改动的文档秒级跳过，首次需下载嵌入模型）=="
export HF_ENDPOINT=https://hf-mirror.com
if ! "$PY" scripts/ingest_policy_docs.py; then
  echo "[警告] 知识库初始化未完成（多为模型下载网络问题）。系统仍可运行："
  echo "   RAG 问答会自动降级为 BM25 词法检索模式，其余功能不受影响。"
fi

echo "== [4/5] 清理残留服务并启动 =="
# 关掉可能残留的旧实例，避免端口被占后漂移到 8502/8503...
lsof -ti tcp:8000 2>/dev/null | xargs kill 2>/dev/null
lsof -ti tcp:8501 2>/dev/null | xargs kill 2>/dev/null
sleep 1

# 关键：把项目根目录加入模块搜索路径，否则 Streamlit 页面找不到 src 包
export PYTHONPATH="$APP"
export HF_ENDPOINT=https://hf-mirror.com

"$PY" -m uvicorn src.api.main:app --port 8000 > .api_demo.log 2>&1 &
API_PID=$!
"$PY" -m streamlit run src/ui/app.py --server.headless true --server.port 8501 > .ui_demo.log 2>&1 &
ST_PID=$!
trap 'kill $API_PID $ST_PID 2>/dev/null' EXIT

echo "== [5/5] 等待服务就绪 =="
UI_OK=0
for i in $(seq 1 30); do
  API_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null)
  UI_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501 2>/dev/null)
  if [ "$API_CODE" = "200" ] && [ "$UI_CODE" = "200" ]; then UI_OK=1; break; fi
  sleep 1
done

if [ "$UI_OK" = "1" ]; then
  open "http://localhost:8501"
else
  echo "[警告] 服务启动较慢或失败，30 秒后可手动访问；详见日志："
  echo "   $APP/.api_demo.log"
  echo "   $APP/.ui_demo.log"
  open "http://localhost:8501"
fi

echo ""
echo "=============================================="
echo "  碳路已启动"
echo "  前端界面:  http://localhost:8501"
echo "  API 文档:  http://localhost:8000/docs"
echo "  一条命令看决策链: $PY scripts/e2e_demo.py"
echo "  关闭本窗口（或按 Ctrl+C）即停止全部服务"
echo "=============================================="
wait
