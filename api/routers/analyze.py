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
    GuidanceRefineRequest,
    GuidanceRequest,
    GuidanceResponse,
    IncrementalInfo,
)
from api.services.analyze_service import AnalyzeService
from api.services.guidance_service import GuidanceService

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


@router.get("/knowledge-docs", response_model=DataResponse)
async def get_knowledge_docs():
    """获取服务端维护的知识库文档列表"""
    try:
        docs = GuidanceService.list_knowledge_docs()
        return DataResponse(
            success=True,
            message=f"共 {len(docs)} 份知识库文档",
            data={"docs": docs},
        )
    except Exception as e:
        return DataResponse(
            success=False,
            message=f"获取知识库文档失败: {str(e)}",
            data={"docs": []},
        )


@router.post("", response_model=AnalyzeResponse)
async def run_analysis(request: AnalyzeRequest):
    """
    执行评估分析
    
    可以指定分析器 key 列表，不指定则执行全部
    """
    try:
        effective_agent_assist_keys = request.agent_assist_keys if request.agent_assist_keys else None
        effective_agent_assist = bool(effective_agent_assist_keys)

        # 在后台线程中执行，避免阻塞其他请求
        results, summary, total_score, total_max, total_pct, maturity, incr_info = \
            await asyncio.to_thread(
                AnalyzeService.run_analysis,
                keys=request.keys if request.keys else None,
                agent_assist=effective_agent_assist,
                agent_assist_keys=effective_agent_assist_keys,
                agent_assist_temperature=request.agent_assist_temperature,
                incremental=request.incremental,
            )

        mode_label = "增量" if incr_info.get("mode") == "incremental" else "全量"
        return AnalyzeResponse(
            success=True,
            message=f"{mode_label}分析完成: 共 {len(results)} 个评估项",
            results=results,
            summary=summary,
            total_score=total_score,
            total_max_score=total_max,
            total_percentage=total_pct,
            overall_maturity=maturity,
            incremental_info=IncrementalInfo(**incr_info),
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


@router.post("/guidance", response_model=GuidanceResponse)
async def generate_guidance(request: GuidanceRequest):
    """基于评估结果生成首轮改进建议"""
    try:
        effective_agent_assist_keys = request.agent_assist_keys if request.agent_assist_keys else None
        effective_agent_assist = bool(effective_agent_assist_keys)

        session, current_turn = await asyncio.to_thread(
            GuidanceService.generate_guidance,
            keys=request.keys if request.keys else None,
            focus_keys=request.focus_keys if request.focus_keys else None,
            max_focus=request.max_focus,
            max_dataitems=request.max_dataitems,
            max_records=request.max_records,
            temperature=request.temperature,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            agent_assist=effective_agent_assist,
            agent_assist_keys=effective_agent_assist_keys,
            agent_assist_temperature=request.agent_assist_temperature,
            external_knowledge_max_chars=request.external_knowledge_max_chars,
            external_knowledge_max_chunks=request.external_knowledge_max_chunks,
            external_knowledge_chunk_chars=request.external_knowledge_chunk_chars,
            knowledge_doc_ids=request.knowledge_doc_ids if request.knowledge_doc_ids else None,
        )

        return GuidanceResponse(
            success=True,
            message="已生成首轮改进建议",
            session=session,
            current_turn=current_turn,
        )
    except FileNotFoundError as e:
        return GuidanceResponse(
            success=False,
            message=f"数据库不存在，请先采集数据: {str(e)}",
        )
    except Exception as e:
        return GuidanceResponse(
            success=False,
            message=f"生成改进建议失败: {str(e)}",
        )


@router.post("/guidance/refine", response_model=GuidanceResponse)
async def refine_guidance(request: GuidanceRefineRequest):
    """基于用户反馈迭代完善改进建议"""
    try:
        session, current_turn = await asyncio.to_thread(
            GuidanceService.refine_guidance,
            session=request.session,
            feedback=request.feedback,
            db_name=request.db_name,
            max_focus=request.max_focus,
            max_dataitems=request.max_dataitems,
            max_records=request.max_records,
            temperature=request.temperature,
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            external_knowledge_max_chars=request.external_knowledge_max_chars,
            external_knowledge_max_chunks=request.external_knowledge_max_chunks,
            external_knowledge_chunk_chars=request.external_knowledge_chunk_chars,
            knowledge_doc_ids=request.knowledge_doc_ids,
        )

        return GuidanceResponse(
            success=True,
            message="已基于反馈更新改进建议",
            session=session,
            current_turn=current_turn,
        )
    except FileNotFoundError as e:
        return GuidanceResponse(
            success=False,
            message=f"数据库不存在，请先采集数据: {str(e)}",
        )
    except Exception as e:
        return GuidanceResponse(
            success=False,
            message=f"更新改进建议失败: {str(e)}",
        )
