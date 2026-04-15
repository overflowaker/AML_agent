import json
import io
import sys
from llm_engine import invoke_llm # 引入我们的大模型调用接口

# 引入我们刚刚写好的 Graph SDK 接口！
# 注意：这里完全没有 kuzu 的身影了，解耦完成。
from graph_api import get_account_info, get_transactions


def semantic_data_processor(intent_description: str, max_retries: int = 3) -> str:
    """
    接收自然语言需求，生成纯 Python 算法代码并调用底层 Graph SDK 进行图数据分析。
    带有自动报错重试机制。
    """
    
    # ==========================================
    # 极度纯净的 API 版 System Prompt
    # ==========================================
    system_prompt = """
    你是一个精通 Python 算法和数据结构的图分析工程师。你的任务是根据业务需求，编写纯 Python 脚本来分析金融交易网络。

    【可用 API 工具箱】
    你处于一个隔离的沙盒环境中，严禁使用任何 SQL 或图数据库查询语言（如 Cypher）。
    你只能且必须调用以下两个已经全局注入的 Python 预置函数来获取图数据：

    1. `get_account_info(account_id: str) -> dict`
       - 功能：获取账户静态信息。
       - 返回值字典键值说明：
         * `account_id` (str): 账户的全局唯一标识 ID。示例：'80B779D80'。
         * `bank_id` (str): 该账户开户行的代码（⚠️ 绝不能与 account_id 混淆）。示例：'331579'。
         * `bank_name` (str): 开户行全称。示例：'Portugal Bank #4507'。
         * `entity_id` (str): 账户背后的实体企业或个人id。示例：'80062E240'。
         * `entity_name` (str): 实体名称。示例：'Sole Proprietorship #50438'。
       - 返回示例：{'account_id': '80B779D80', 'bank_id': '331579', 'bank_name': 'Portugal Bank #4507', 'entity_id': '80062E240', 'entity_name': 'Sole Proprietorship #50438'}
       
    2. `get_transactions(account_id: str) -> list[dict]`
       - 功能：获取该账户的所有关联交易记录（一次性拉取所有一度邻居的资金流）。
       - 返回列表中，每个字典代表一笔交易，键值严格说明如下：
         * `direction` (str): 资金流向。值为 "out" 代表资金从当前账户流出；值为 "in" 代表资金流入当前账户。示例：'out'，'in'。
         * `counterparty` (str): 交易对手方的 account_id。如果 direction 为 out，此人为收款方；如果为 in，此人为汇款方。示例：'80B779410'。
         * `timestamp` (str): 交易发生的时间。示例：'2022/09/02 23:33'。
         * `from_bank` (str): 汇出方所在银行的代码。示例：'331579'。
         * `to_bank` (str): 接收方所在银行的代码。示例：'22806'。
         * `amount_paid` (float): 实际汇出的交易金额。在任何需要累加、排序交易量的场景中，请严格使用此字段。示例：165.78。
         * `payment_currency` (str): 汇出金额的币种。示例：'Euro'。
         * `amount_received` (float): 实际接收的交易金额。示例：165.78。
         * `receiving_currency` (str): 接收金额的币种。示例：'Euro'。
         * `payment_format` (str): 交易形式/支付方式。示例：'Cash' 或 'Reinvestment'。
       - 返回示例：
         [
            {'direction': 'out', 'counterparty': '80B779410', 'timestamp': '2022/09/02 23:33', 'from_bank': '331579', 'to_bank': '22806', 'amount_paid': 165.78, 'payment_currency': 'Euro', 'amount_received': 165.78, 'receiving_currency': 'Euro', 'payment_format': 'Cash'}, 
            {'direction': 'in', 'counterparty': '8088FE560', 'timestamp': '2022/09/01 22:01', 'from_bank': '214322', 'to_bank': '214322', 'amount_paid': 61.03, 'payment_currency': 'Euro', 'amount_received': 61.03, 'receiving_currency': 'Euro', 'payment_format': 'Reinvestment'}
         ]

    【算法编写规范】
    1. 计算过程中注意货币和汇率转换，如果输出中有金额则注意标注货币类型，尤其是在出现与多种货币相关的交易量统计任务时。
    2. 注意你的代码中是否有逻辑或者常识性的错误，注意输出需要符合需求的语义理解。
    3. 输出要求：使用 `print()` 输出你的最终计算结果（如字典、数字或字符串）。
    4. 代码以较为工整的格式书写，须有主函数 if __name__ == "__main__": 。

    【输出格式约束】
    请直接输出 JSON，不要使用 Markdown 代码块包裹：
    {
        "language": "python",
        "code": "你的完整 Python 脚本"
    }
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"需求：{intent_description}"}
    ]
    
    for attempt in range(max_retries):
        print(f"\n[Copilot] 正在思考算法逻辑 (第 {attempt + 1}/{max_retries} 次尝试)...")
        response = invoke_llm(messages)
        ai_output = response.content.strip()
        
        try:
            # 清理 Markdown 标记
            if ai_output.startswith("```json"):
                ai_output = ai_output[7:-3].strip()
            elif ai_output.startswith("```"):
                ai_output = ai_output[3:-3].strip()
                
            action = json.loads(ai_output)
            code = action.get("code", "")
            
        except json.JSONDecodeError:
            error_msg = "无法解析JSON格式，请修正。"
            messages.append({"role": "assistant", "content": ai_output})
            messages.append({"role": "user", "content": error_msg})
            continue

        print(f"[Copilot] 生成的 Python 算法代码如下:\n{'-'*40}\n{code}\n{'-'*40}")
        
        # ==========================================
        # 核心沙盒：执行纯 Python 代码，仅注入 API
        # ==========================================
        old_stdout = sys.stdout
        redirected_output = sys.stdout = io.StringIO()
        
        try:
            # 这里的字典就是大模型能看到的全部世界
            # 它无法访问操作系统的 os 库，也无法直连 Kuzu
            exec(code, {
                "__name__": "__main__",  # <--- 加上这一行
                "get_account_info": get_account_info,
                "get_transactions": get_transactions,
                "collections": __import__('collections') # 注入内置库方便它写 BFS
            })
            output_str = redirected_output.getvalue()
            return output_str.strip() if output_str else "代码执行完毕，无 print 输出。"
            
        except Exception as e:
            error_msg = f"Python 代码执行报错: {type(e).__name__} - {str(e)}"
            print(f"[Copilot] {error_msg} -> 正在请求自动修正...")
            
            messages.append({"role": "assistant", "content": ai_output})
            messages.append({"role": "user", "content": f"{error_msg}\n请分析错误原因，并输出修正后的完整 JSON 代码。"})
            
        finally:
            sys.stdout = old_stdout

    return "提取失败：经过多次尝试，代码均无法正确执行。"

# ==========================================
# 终极挑战测试
# ==========================================
if __name__ == "__main__":
    # 我们用上一次让大模型陷入“笛卡尔积膨胀陷阱”的那个超级难题来测试这个新架构
    # test_intent = "找到从8000EBD30出发，3步之内能找到的交易量最大的账户，并告诉我它的交易量和ID。"
    test_intent = "统计一下与80012FD40相关的交易中，每种货币的交易量都有多少？"
    
    print("=================================================")
    print(f"主 Agent 发起高难度任务: {test_intent}")
    print("=================================================")
    
    final_result = semantic_data_processor(test_intent)
    
    print("\n=================================================")
    print("返回给主 Agent 的最终精炼结果:")
    print(final_result)
    print("=================================================")