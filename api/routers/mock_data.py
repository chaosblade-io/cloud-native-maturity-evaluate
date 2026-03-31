"""
Mock 数据路由

提供 Mock 数据上传和示例获取接口
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException

from api.models.schemas import MockUploadResponse, DataResponse

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

router = APIRouter(prefix="/mock", tags=["Mock数据"])


@router.post("/upload", response_model=MockUploadResponse)
async def upload_mock_data(file: UploadFile = File(...)):
    """
    上传 Mock 数据文件
    
    接受 JSON 文件，解析后导入到数据库
    """
    # 验证文件类型
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="只支持 JSON 文件")
    
    try:
        # 读取文件内容
        content = await file.read()
        mock_data = json.loads(content.decode("utf-8"))
        
        if not isinstance(mock_data, dict):
            raise HTTPException(status_code=400, detail="JSON 格式错误，应为对象格式")
        
        # 导入数据
        from sesora.collectors.generic_collector import GenericCollector
        from sesora.core.dataitem import DataSource, SourceStatus
        from sesora.store.sqlite_store import SQLiteDataStore
        from sesora.schema.registry import DATAITEM_SCHEMA_REGISTRY
        
        # 数据库路径
        db_dir = PROJECT_ROOT / "data"
        db_dir.mkdir(exist_ok=True)
        db_path = db_dir / "sesora.db"
        
        # 使用 GenericCollector 转换数据
        collector = GenericCollector(mock_data, collector_name="web_upload")
        data_source = collector.collect()
        
        # 按 DataItem 名称分组记录
        grouped_records: dict[str, list] = data_source.records_dict
        
        # 保存到数据库
        with SQLiteDataStore(db_path) as store:
            for item_name, records in grouped_records.items():
                source = DataSource(
                    collector="web_upload",
                    collected_at=datetime.now(),
                    status=SourceStatus.OK,
                    records=records,
                )
                store.put(item_name, source)
        
        # 统计结果
        items_dict = {name: len(records) for name, records in grouped_records.items()}
        total_records = sum(items_dict.values())
        
        return MockUploadResponse(
            success=True,
            message=f"成功导入 {len(items_dict)} 个数据项，共 {total_records} 条记录",
            items_count=len(items_dict),
            records_count=total_records,
            items=items_dict,
        )
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@router.get("/sample", response_model=DataResponse)
async def get_sample_data():
    """
    获取 Mock 数据示例格式
    
    返回示例 JSON 结构供参考
    """
    sample = {
        "k8s.deployment.list": [
            {
                "namespace": "default",
                "name": "example-app",
                "replicas": 3,
                "ready_replicas": 3,
                "strategy": "RollingUpdate",
            }
        ],
        "k8s.service.list": [
            {
                "namespace": "default",
                "name": "example-service",
                "type": "ClusterIP",
                "cluster_ip": "10.96.100.1",
            }
        ],
        "codeup.pipeline.list": [
            {
                "pipeline_id": "pipeline-001",
                "name": "build-pipeline",
                "repo_id": "repo-001",
                "enabled": True,
            }
        ],
    }
    
    return DataResponse(
        success=True,
        message="Mock 数据示例格式",
        data=sample,
    )


@router.get("/template", response_model=DataResponse)
async def get_full_template():
    """
    获取完整的 Mock 数据模板
    
    从 mock.json 文件读取完整模板
    """
    mock_file = PROJECT_ROOT / "run_pipeline" / "mock.json"
    
    if not mock_file.exists():
        return DataResponse(
            success=False,
            message="模板文件不存在",
            data=None,
        )
    
    try:
        with open(mock_file, "r", encoding="utf-8") as f:
            template = json.load(f)
        
        return DataResponse(
            success=True,
            message="完整 Mock 数据模板",
            data=template,
        )
    except Exception as e:
        return DataResponse(
            success=False,
            message=f"读取模板失败: {str(e)}",
            data=None,
        )
