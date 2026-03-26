"""
评估分析路由

提供评估分析触发、分析器查询和结果获取接口
"""
import asyncio
from fastapi import APIRouter

from api.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DataResponse,
    DataStatusResponse,
)
from api.services.analyze_service import AnalyzeService

router = APIRouter(prefix="/analyze", tags=["评估分析"])


@router.get("/analyzers", response_model=DataResponse)
async def get_analyzers():
    """
    获取所有可用的分析器列表
    
    返回所有分析器的元数据，按维度分组
    """
    analyzers = AnalyzeService.get_analyzer_list()
    
    # 按维度分组
    by_dimension: dict[str, list] = {}
    for a in analyzers:
        dim = a.dimension
        if dim not in by_dimension:
            by_dimension[dim] = []
        by_dimension[dim].append(a.model_dump())
    
    return DataResponse(
        success=True,
        message=f"共 {len(analyzers)} 个分析器",
        data={
            "analyzers": [a.model_dump() for a in analyzers],
            "by_dimension": by_dimension,
            "dimensions": list(by_dimension.keys()),
        },
    )


@router.get("/data-status", response_model=DataStatusResponse)
async def get_data_status(keys: str = None):
    """
    获取数据就绪状态
    
    检查分析器所需数据的可用性
    
    Args:
        keys: 分析器 key 列表（逗号分隔），不提供则检查全部
    """
    key_list = keys.split(",") if keys else None
    
    try:
        all_items, required, optional = AnalyzeService.get_data_status(keys=key_list)
        
        return DataStatusResponse(
            success=True,
            message=f"共 {len(all_items)} 个数据项",
            items=all_items,
            required=required,
            optional=optional,
        )
        
    except Exception as e:
        return DataStatusResponse(
            success=False,
            message=f"获取数据状态失败: {str(e)}",
            items=[],
            required=[],
            optional=[],
        )


@router.post("", response_model=AnalyzeResponse)
async def run_analysis(request: AnalyzeRequest):
    """
    执行评估分析
    
    可以指定分析器 key 列表，不指定则执行全部
    """
    try:
        # 在后台线程中执行，避免阻塞其他请求
        results, summary, total_score, total_max, total_pct, maturity = \
            await asyncio.to_thread(
                AnalyzeService.run_analysis,
                keys=request.keys if request.keys else None,
            )
        
        return AnalyzeResponse(
            success=True,
            message=f"分析完成: 共 {len(results)} 个评估项",
            results=results,
            summary=summary,
            total_score=total_score,
            total_max_score=total_max,
            total_percentage=total_pct,
            overall_maturity=maturity,
        )
        
    except FileNotFoundError as e:
        return AnalyzeResponse(
            success=False,
            message=f"数据库不存在，请先采集数据: {str(e)}",
            results=[],
            summary=[],
            total_score=0,
            total_max_score=0,
            total_percentage=0,
            overall_maturity="",
        )
    except Exception as e:
        return AnalyzeResponse(
            success=False,
            message=f"分析失败: {str(e)}",
            results=[],
            summary=[],
            total_score=0,
            total_max_score=0,
            total_percentage=0,
            overall_maturity="",
        )
