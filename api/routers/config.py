"""
配置管理路由

提供环境变量配置的读取、保存和检查接口
"""
from fastapi import APIRouter, UploadFile, File

from api.models.schemas import (
    ConfigData,
    ConfigCheckResponse,
    ConfigResponse,
    BaseResponse,
)
from api.services.config_service import ConfigService

router = APIRouter(prefix="/config", tags=["配置管理"])


@router.get("/check", response_model=ConfigCheckResponse)
async def check_config():
    """
    检查配置是否存在
    
    返回配置文件是否存在以及是否配置了阿里云凭证
    """
    return ConfigCheckResponse(
        success=True,
        exists=ConfigService.config_exists(),
        has_credentials=ConfigService.has_credentials(),
    )


@router.get("", response_model=ConfigResponse)
async def get_config():
    """
    获取当前配置
    
    返回所有配置项的当前值，按分组组织
    """
    config = ConfigService.load_config()
    groups = ConfigService.get_config_groups(config)
    
    return ConfigResponse(
        success=True,
        config=config,
        groups=groups,
    )


@router.put("", response_model=BaseResponse)
async def save_config(config: ConfigData):
    """
    保存配置
    
    将配置写入 .env 文件
    """
    try:
        ConfigService.save_config(config)
        return BaseResponse(
            success=True,
            message="配置保存成功",
        )
    except Exception as e:
        return BaseResponse(
            success=False,
            message=f"保存配置失败: {str(e)}",
        )


@router.post("/upload", response_model=ConfigResponse)
async def upload_env_file(file: UploadFile = File(...)):
    """
    上传 .env 文件
    
    解析上传的 .env 文件并返回配置内容
    """
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        # 解析 .env 文件内容
        config = ConfigService.parse_env_content(text)
        groups = ConfigService.get_config_groups(config)
        
        # 统计非空配置项数量
        config_dict = config.model_dump()
        filled_count = sum(1 for v in config_dict.values() if v)
        
        return ConfigResponse(
            success=True,
            message=f"文件解析成功，共 {filled_count} 个配置项",
            config=config,
            groups=groups,
        )
    except Exception as e:
        return ConfigResponse(
            success=False,
            message=f"解析文件失败: {str(e)}",
            config={},
            groups=[],
        )
