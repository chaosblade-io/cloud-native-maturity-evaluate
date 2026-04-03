"""
AgentFactory - LangChain Agent 封装模块

提供 OpenAI 兼容的 Agent 创建和调用功能，支持结构化输出。
"""

from typing import Type, TypeVar, Union, Optional, List
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import BaseTool
from langchain.tools import tool
from langgraph.prebuilt import create_react_agent

T = TypeVar('T', bound=BaseModel)


class AgentFactory:

    def __init__(
            self,
            api_key: str,
            base_url: str,
            model_name: str,
            tools: List[BaseTool],
            sys_prompt: str,
            temperature: float = 0.0,
            max_tokens: Optional[int] = None,
    ):
        """
        初始化 AgentFactory
        
        Args:
            api_key: OpenAI API 密钥
            base_url: API 基础 URL（OpenAI 兼容端点）
            model_name: 模型名称
            tools: 工具列表
            sys_prompt: 系统提示词
            temperature: 温度参数，默认 0.0
            max_tokens: 最大 token 数，默认 None
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.tools = tools
        self.sys_prompt = sys_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens

        # 创建 LLM
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 创建 Agent（如果有工具）
        self._agent = None
        if tools:
            self._agent = create_react_agent(self.llm, tools)

    def invoke(
            self,
            query: str,
            output_schema: Optional[Type[T]] = None,
            chat_history: Optional[List] = None,
    ) -> Union[str, T]:
        """
        调用 Agent
        
        Args:
            query: 用户输入的查询字符串
            output_schema: 可选的 Pydantic 模型类，用于结构化输出
            chat_history: 可选的对话历史
            
        Returns:
            如果提供了 output_schema，返回该类的实例；否则返回字符串
        """
        if output_schema is not None:
            return self._invoke_with_structured_output(query, output_schema)

        return self._invoke_string_output(query, chat_history)

    def _invoke_string_output(
            self,
            query: str,
            chat_history: Optional[List] = None,
    ) -> str:
        """
        调用 Agent 并返回字符串输出
        
        Args:
            query: 用户输入的查询字符串
            chat_history: 可选的对话历史
            
        Returns:
            Agent 的字符串响应
        """
        if self._agent and self.tools:
            # 使用 langgraph react agent（有工具时）
            messages = [SystemMessage(content=self.sys_prompt)]
            if chat_history:
                messages.extend(chat_history)
            messages.append(HumanMessage(content=query))

            result = self._agent.invoke({"messages": messages})
            # 获取最后一条 AI 消息
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if ai_messages:
                return ai_messages[-1].content
            return ""
        else:
            # 直接使用 LLM（无工具时）
            messages = [
                SystemMessage(content=self.sys_prompt),
                HumanMessage(content=query),
            ]
            response = self.llm.invoke(messages)
            return response.content

    def _invoke_with_structured_output(
            self,
            query: str,
            output_schema: Type[T],
    ) -> T:
        """
        调用 Agent 并返回结构化输出
        
        Args:
            query: 用户输入的查询字符串
            output_schema: Pydantic 模型类
            
        Returns:
            output_schema 类的实例
        """
        # 使用 with_structured_output 进行结构化输出
        structured_llm = self.llm.with_structured_output(output_schema)

        messages = [
            SystemMessage(content=self.sys_prompt),
            HumanMessage(content=query),
        ]

        result = structured_llm.invoke(messages)
        return result

    async def ainvoke(
            self,
            query: str,
            output_schema: Optional[Type[T]] = None,
            chat_history: Optional[List] = None,
    ) -> Union[str, T]:
        """
        异步调用 Agent
        
        Args:
            query: 用户输入的查询字符串
            output_schema: 可选的 Pydantic 模型类，用于结构化输出
            chat_history: 可选的对话历史
            
        Returns:
            如果提供了 output_schema，返回该类的实例；否则返回字符串
        """
        if output_schema is not None:
            return await self._ainvoke_with_structured_output(query, output_schema)

        return await self._ainvoke_string_output(query, chat_history)

    async def _ainvoke_string_output(
            self,
            query: str,
            chat_history: Optional[List] = None,
    ) -> str:
        if self._agent and self.tools:
            messages = [SystemMessage(content=self.sys_prompt)]
            if chat_history:
                messages.extend(chat_history)
            messages.append(HumanMessage(content=query))

            result = await self._agent.ainvoke({"messages": messages})
            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
            if ai_messages:
                return ai_messages[-1].content
            return ""
        else:
            messages = [
                SystemMessage(content=self.sys_prompt),
                HumanMessage(content=query),
            ]
            response = await self.llm.ainvoke(messages)
            return response.content

    async def _ainvoke_with_structured_output(
            self,
            query: str,
            output_schema: Type[T],
    ) -> T:
        """异步调用 Agent 并返回结构化输出"""
        structured_llm = self.llm.with_structured_output(output_schema)

        messages = [
            SystemMessage(content=self.sys_prompt),
            HumanMessage(content=query),
        ]

        result = await structured_llm.ainvoke(messages)
        return result


if __name__ == "__main__":
    """测试代码"""
    from pydantic import BaseModel, Field


    # 定义结构化输出模型
    class CloudNativeAnalysis(BaseModel):
        """云原生成熟度分析结果"""
        score: int = Field(description="成熟度评分 (0-100)")
        level: str = Field(description="成熟度等级: 初级/中级/高级/专家")
        summary: str = Field(description="分析摘要")
        recommendations: list[str] = Field(description="改进建议列表")


    # 配置

    @tool
    def add(a: int, b: int) -> int:
        """
        两个数字相加
        你必须在这里写清楚工具用途，大模型才能看懂什么时候调用它
        """
        print(f"工具被调用: add({a}, {b})")
        return a + b

    # 创建 Agent
    agent = AgentFactory(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_name=MODEL_NAME,
        tools=[add],
        sys_prompt=""
    )

    print("=" * 50)
    print("测试 1: 字符串输出")
    print("=" * 50)

    query = "简要介绍一下云原生的核心概念"
    print(f"输入: {query}")
    print(f"输出: {agent.invoke(query)}")

    print("\n" + "=" * 50)
    print("测试 2: 结构化输出")
    print("=" * 50)

    query = "分析一个使用 Kubernetes 部署、有 HPA 自动扩缩容、使用 Prometheus 监控的系统的云原生成熟度"
    print(f"输入: {query}")

    result = agent.invoke(query, output_schema=CloudNativeAnalysis)

    print(f"类型: {type(result).__name__}")
    print(f"评分: {result.score}")
    print(f"等级: {result.level}")
    print(f"摘要: {result.summary}")
    print(f"建议:")
    for i, rec in enumerate(result.recommendations, 1):
        print(f"  {i}. {rec}")


    print("\n" + "=" * 50)
    print("测试 3: 工具调用")
    print("=" * 50)

    query = "调用工具计算一下 5 + 7 的结果"
    print(f"输入: {query}")
    print(f"输出: {agent.invoke(query)}")