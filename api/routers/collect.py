"""
数据采集路由

提供数据采集触发和状态查询接口
"""
from fastapi import APIRouter

from api.models.schemas import (
    CollectorInfo,
    CollectRequest,
    CollectResponse,
    DataResponse,
)
from api.services.collect_service import CollectService

router = APIRouter(prefix="/collect", tags=["数据采集"])


@router.get("/collectors", response_model=DataResponse)
async def get_collectors():
    """
    获取可用的采集器列表
    
    返回所有支持的采集器及其配置需求
    """
    collectors = CollectService.get_available_collectors()
    
    return DataResponse(
        success=True,
        message=f"共 {len(collectors)} 个可用采集器",
        data=[c.model_dump() for c in collectors],
    )


@router.post("/one", response_model=CollectResponse)
def run_one_collection(request: CollectRequest):
    """
    采集单个采集器（同步，在主线程执行，避免 signal 问题）
    
    每次只采集一个，由前端串行调用
    """
    collector_name = request.collectors[0] if request.collectors else None
    if not collector_name:
        return CollectResponse(
            success=False,
            message="未指定采集器",
            results=[],
            total_success=0,
            total_failed=0,
        )
    
    try:
        results = CollectService.run_collection(
            collectors=[collector_name],
        )
        total_success = sum(1 for r in results if r.success)
        total_failed = len(results) - total_success
        
        return CollectResponse(
            success=True,
            message=results[0].message if results else "采集完成",
            results=results,
            total_success=total_success,
            total_failed=total_failed,
        )
    except Exception as e:
        return CollectResponse(
            success=False,
            message=f"采集失败: {str(e)}",
            results=[],
            total_success=0,
            total_failed=0,
        )
