"""
知识库服务

基于文件系统维护 Markdown 知识库文档及标签元数据。
"""
from typing import Optional

from sesora.utils.knowledge_base import (
    create_knowledge_doc,
    delete_knowledge_doc,
    list_knowledge_docs,
    update_knowledge_doc_tags,
)


class KnowledgeService:
    """知识库服务类"""

    @classmethod
    def list_docs(cls) -> list[dict]:
        return list_knowledge_docs()

    @classmethod
    def upload_doc(cls, filename: str, content: bytes, tags: Optional[list[str]] = None) -> dict:
        return create_knowledge_doc(filename=filename, content=content, tags=tags)

    @classmethod
    def update_tags(cls, doc_id: str, tags: Optional[list[str]] = None) -> dict:
        return update_knowledge_doc_tags(doc_id=doc_id, tags=tags)

    @classmethod
    def delete_doc(cls, doc_id: str) -> None:
        delete_knowledge_doc(doc_id)
