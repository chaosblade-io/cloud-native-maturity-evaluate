"""
SESORA Web API 主入口

FastAPI 应用配置和路由注册
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载环境变量
from dotenv import load_dotenv
env_path = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=env_path, override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import config, mock_data, collect, analyze

# 创建 FastAPI 应用
app = FastAPI(
    title="SESORA Web API",
    description="云原生成熟度评估系统 Web 管理接口",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(config.router, prefix="/api")
app.include_router(mock_data.router, prefix="/api")
app.include_router(collect.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "message": "SESORA Web API is running",
    }


@app.get("/api")
async def api_info():
    """API 信息"""
    return {
        "name": "SESORA Web API",
        "version": "1.0.0",
        "description": "云原生成熟度评估系统 Web 管理接口",
        "endpoints": {
            "config": "/api/config - 配置管理",
            "mock": "/api/mock - Mock数据管理",
            "collect": "/api/collect - 数据采集",
            "analyze": "/api/analyze - 评估分析",
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
