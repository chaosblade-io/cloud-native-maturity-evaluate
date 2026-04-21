"""
知识库路由

提供 Markdown 知识库文档的上传、删除、标签维护与列表接口。
"""
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from api.models.schemas import KnowledgeDocResponse, KnowledgeDocsResponse, KnowledgeDocTagsRequest
from api.services.knowledge_service import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["知识库"])


def _parse_tags(raw_tags: str | None) -> list[str]:
    if not raw_tags:
        return []
    return [item.strip() for item in raw_tags.split(",") if item.strip()]


@router.get("/docs", response_model=KnowledgeDocsResponse)
async def list_knowledge_docs():
    try:
        docs = KnowledgeService.list_docs()
        return KnowledgeDocsResponse(
            success=True,
            message=f"共 {len(docs)} 份知识库文档",
            docs=docs,
        )
    except Exception as exc:
        return KnowledgeDocsResponse(
            success=False,
            message=f"获取知识库文档失败: {exc}",
            docs=[],
        )


@router.post("/docs/upload", response_model=KnowledgeDocsResponse)
async def upload_knowledge_doc(files: list[UploadFile] = File(...), tags: str = Form(default="")):
    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个 Markdown 文件")

    uploaded_docs = []
    parsed_tags = _parse_tags(tags)

    try:
        for file in files:
            if not file.filename or not file.filename.lower().endswith(".md"):
                raise HTTPException(status_code=400, detail=f"只支持 Markdown 文件: {file.filename or '-'}")
            content = await file.read()
            uploaded_docs.append(
                KnowledgeService.upload_doc(
                    filename=file.filename,
                    content=content,
                    tags=parsed_tags,
                )
            )

        return KnowledgeDocsResponse(
            success=True,
            message=f"知识库文档上传成功，共 {len(uploaded_docs)} 个文件",
            docs=uploaded_docs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传知识库文档失败: {exc}")


@router.put("/docs/{doc_id}/tags", response_model=KnowledgeDocResponse)
async def update_knowledge_doc_tags(doc_id: str, request: KnowledgeDocTagsRequest):
    try:
        doc = KnowledgeService.update_tags(doc_id=doc_id, tags=request.tags)
        return KnowledgeDocResponse(
            success=True,
            message="标签更新成功",
            doc=doc,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新标签失败: {exc}")


@router.delete("/docs/{doc_id}", response_model=KnowledgeDocResponse)
async def delete_knowledge_doc(doc_id: str):
    try:
        KnowledgeService.delete_doc(doc_id)
        return KnowledgeDocResponse(
            success=True,
            message="知识库文档删除成功",
            doc=None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除知识库文档失败: {exc}")
