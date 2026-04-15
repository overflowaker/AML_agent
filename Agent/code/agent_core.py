from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI # 这里以 OpenAI 为例，可换成其他模型

# 导入我们刚刚写的工具文件
import graph_tools

# ==========================================
# 1. 定义状态空间 (State)
# ==========================================
# 使用 add_messages 可以自动将新消息追加到列表中，而不是覆盖
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# # ==========================================
# # 2. 初始化大模型并绑定工具
# # ==========================================
# # 请确保你的环境变量中配置了 API Key，或者在这里直接传入
# # 你可以替换成任何支持 Tool Calling 的模型 (如 Qwen, Claude, GLM 等)
# llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# # 将底层接口绑定到大模型的大脑中
# llm_with_tools = llm.bind_tools(graph_tools.aml_tools)


# ==========================================
# 2. 初始化大模型并绑定工具 (DeepSeek 版本)
# ==========================================

# 填入你刚刚申请的 DeepSeek API Key
DEEPSEEK_API_KEY = "sk-013cf50caa774d389dc624ad1bbf6a52" 

# 初始化 DeepSeek 模型
llm = ChatOpenAI(
    model="deepseek-chat",               # deepseek-chat 是 DeepSeek-V3 的官方模型调用名称
    api_key=DEEPSEEK_API_KEY,            # 显式传入 API Key
    base_url="https://api.deepseek.com", # 将请求地址重定向到 DeepSeek 的服务器
    temperature=0                        # 针对这种严谨的推理、工具调用任务，设为 0 能让输出更稳定、逻辑更严密
)

# 将底层接口绑定到大模型的大脑中
llm_with_tools = llm.bind_tools(graph_tools.aml_tools)

# ==========================================
# 3. 定义图节点函数
# ==========================================
def agent_reasoning_node(state: AgentState):
    """大模型思考节点：读取历史信息，决定是输出结论还是调用工具"""
    print("\n[Agent 正在思考...]")
    response = llm_with_tools.invoke(state["messages"])
    # 将大模型的回复追加到状态中
    return {"messages": [response]}

# LangGraph 提供了一个预置的 ToolNode，它会自动解析 LLM 的请求并执行我们传进去的 python 函数
tool_execution_node = ToolNode(graph_tools.aml_tools)

# ==========================================
# 4. 构建流转图 (Graph Topology)
# ==========================================
workflow = StateGraph(AgentState)

# 添加节点
workflow.add_node("agent", agent_reasoning_node)
workflow.add_node("tools", tool_execution_node)

# 定义边和路由逻辑
workflow.add_edge(START, "agent")

# tools_condition 是 LangGraph 的内置路由：
# 如果 agent 的最新消息要求调用工具，就走到 "tools" 节点
# 如果 agent 输出了最终文本结论，就走到 END 结束
workflow.add_conditional_edges("agent", tools_condition)

# 工具执行完毕后，强制将查到的图信息送回给 agent 继续推理
workflow.add_edge("tools", "agent")

# 编译成可运行的应用
aml_agent_app = workflow.compile()

# ==========================================
# 5. 主程序测试入口
# ==========================================
if __name__ == "__main__":
    # # 先初始化图数据 (这里会使用 mock 数据)
    # graph_tools.load_ibm_aml_data()

    # 填入你下载的 IBM AML 数据集的真实本地路径
    # 比如: "data/HI-Small_Trans.csv"
    # real_csv_path = "../../data/original/HI-Small_Trans.csv" 
    real_csv_path = "../../data/deal2/AML_Test_Subgraph.csv" 
    
    # 传入路径以加载真实数据
    graph_tools.load_ibm_aml_data(real_csv_path)
    
    print("==================================================")
    print("非法交易审查 Agent 已启动。")
    print("==================================================")
    
    # 初始 Prompt
    user_prompt = "系统检测到账户 100428660 有异常，请你在交易网络中顺藤摸瓜，看看资金最终流向了哪里，并判断是否存在洗钱嫌疑网络。"
    
    inputs = {"messages": [HumanMessage(content=user_prompt)]}
    
    # stream 方法可以让我们看到 Agent 每次在哪个节点流转
    for event in aml_agent_app.stream(inputs, stream_mode="values"):
        # 打印最新的一条消息内容
        last_message = event["messages"][-1]
        
        # 打印大模型的输出或思考
        if hasattr(last_message, "content") and last_message.content:
            print(f"\n🧠 Agent: {last_message.content}")
            
        # 打印工具调用请求
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                print(f"\n🛠️  [调用工具]: 尝试执行 {tool_call['name']}，参数: {tool_call['args']}")
        
        # 打印工具返回的图数据结果
        if last_message.type == "tool":
            print(f"\n📊 [图数据返回]:\n{last_message.content}")