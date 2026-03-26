#!/bin/bash
# SESORA Web 应用启动脚本
# 同时启动 FastAPI 后端和 Vue 前端

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Conda 环境名称
CONDA_ENV="sesora"

echo "=========================================="
echo "SESORA 云原生成熟度评估系统"
echo "=========================================="

# 检查 conda 环境
if ! command -v conda &> /dev/null; then
    echo "错误: 未找到 conda，请先安装 Anaconda/Miniconda"
    exit 1
fi

# 检查 Node.js 环境
if ! command -v npm &> /dev/null; then
    echo "错误: 未找到 npm，请先安装 Node.js"
    exit 1
fi

echo "使用 Conda 环境: $CONDA_ENV"

# 安装前端依赖（如果需要）
if [ ! -d "$SCRIPT_DIR/web/node_modules" ]; then
    echo "安装前端依赖..."
    cd "$SCRIPT_DIR/web" && npm install
    cd "$SCRIPT_DIR"
fi

# 启动后端服务
echo ""
echo "启动后端服务 (http://localhost:8000)..."
cd "$SCRIPT_DIR"
conda run -n $CONDA_ENV python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 等待后端启动
sleep 2

# 启动前端服务
echo "启动前端服务 (http://localhost:5173)..."
cd "$SCRIPT_DIR/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "=========================================="
echo "服务已启动:"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  API 文档: http://localhost:8000/api/docs"
echo "=========================================="
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# 等待进程
wait
