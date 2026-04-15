import os
from langchain_openai import ChatOpenAI

# 建议在运行前配置好环境变量，或者直接在这里临时写入
os.environ["DEEPSEEK_API_KEY"] = "sk-013cf50caa774d389dc624ad1bbf6a52"
# os.environ["OPENAI_API_KEY"] = "sk-你的OpenAI密钥" 

def invoke_llm(messages: list, model_name: str = "deepseek-chat", temperature: float = 0.0):
    """
    通用大模型对话接口封装。
    
    参数:
    - messages: 包含角色和内容的字典列表。例如：
                [
                    {"role": "system", "content": "..."},
                    {"role": "user", "content": "..."}
                ]
    - model_name: 调用的模型名称 (如 "deepseek-chat", "gpt-4o-mini")。
    - temperature: 采样温度 (默认 0.0 保证输出一致性)。
    
    返回:
    - response: 模型的原始响应对象。
    """
    
    if "deepseek" in model_name.lower():
        llm = ChatOpenAI(
            model=model_name,
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            temperature=temperature
        )
    elif "gpt" in model_name.lower():
        llm = ChatOpenAI(
            model=model_name,
            api_key=os.environ.get("OPENAI_API_KEY"),
            temperature=temperature
        )
    else:
        raise ValueError(f"未配置支持的模型: {model_name}")

    # 执行调用
    response = llm.invoke(messages)
    
    return response


# ==========================================
# 测试模块 (保持具体业务逻辑用于验证)
# ==========================================
if __name__ == "__main__":
    
    # 在应用层（外层逻辑）构建具体的任务和上下文
    test_messages = [
        {
            "role": "system", 
            "content": "你是一个图分析引擎。请根据输入的数据判断是否存在洗钱风险。如果你需要更多信息，请直接回复需要查询的账户ID。"
        },
        {
            "role": "user", 
            "content": "当前账户Acc_X向Acc_Y转账100万，且Acc_X是刚注册的新账户。请给出你的分析。"
        }
    ]
    
    try:
        print(f"正在调用 {test_messages[0]['role']} 和 {test_messages[1]['role']} 构成的消息体...")
        result = invoke_llm(messages=test_messages, model_name="deepseek-chat")
        
        print("\n【大模型输出】:")
        print(result.content)
                
    except Exception as e:
        print(f"\n调用失败: {e}")