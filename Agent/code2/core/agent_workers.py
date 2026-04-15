import json
import os
import time

# ---------------------------
import sys
import os
# 获取当前脚本的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取上层目录的路径
parent_dir = os.path.dirname(current_dir)
# 将上层目录加入到系统搜索路径中
sys.path.append(parent_dir)
# ---------------------------

# 引入你的大模型封装接口
from llm_engine import invoke_llm

# ==========================================
# 全局提示词片段库 (Prompt Fragments)
# ==========================================
DATA_SCHEMA_PROMPT = """
【底层数据资产字典 (Data Schema)】 
    我们所有的数据构成一张交易图，图中节点表示账户，边表示资金交易。具体包含的信息如下：

    1. 账户节点特征 (Account)
       * `account_id` (str): 账户的全局唯一标识 ID。示例：'80B779D80'。
       * `bank_id` (str): 开户行代码（⚠️ 绝不能与 account_id 混淆）。示例：'331579'。
       * `bank_name` (str): 开户行全称。示例：'Portugal Bank #4507'。
       * `entity_id` (str): 账户背后的实体企业或个人 ID。示例：'80062E240'。
       * `entity_name` (str): 实体名称。示例：'Sole Proprietorship #50438'。

    2. 交易边特征 (Transaction)
       * `from_account` (str): 交易汇出方的 account_id。示例：'80B779410'。
       * `to_account` (str): 交易接收方的 account_id。示例：'8088FE560'。
       * `timestamp` (str): 交易发生的时间。示例：'2022/09/02 23:33'。
       * `from_bank` (str): 汇出方所在银行的代码。
       * `to_bank` (str): 接收方所在银行的代码。
       * `amount_paid` (float): 实际汇出的交易金额。示例：165.78。
       * `payment_currency` (str): 汇出金额的币种。示例：'Euro'。
       * `amount_received` (float): 实际接收的交易金额。
       * `receiving_currency` (str): 接收金额的币种。
       * `payment_format` (str): 交易形式/支付方式。示例：'Cash' 或 'Reinvestment'。
"""

DYNAMIC_RULES_PROMPT = """
【其它推理准则】
1. 子问题的描述必须独立，Sub_Problems 中的 Question 必须是完全独立、自包含的。因为执行子问题的下一级Agent是独立的，没有其它节点的上下文记忆。
2. 大胆假设，小心求证，步步为营。
"""

# 专门用于存放节点文件的目录
STORAGE_DIR = "./node_storage"
if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

def save_node(node_data: dict):
    """辅助函数：将节点信息落盘保存为 JSON"""
    filepath = os.path.join(STORAGE_DIR, f"{node_data['Node_ID']}.json")
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)

def load_node(node_id: str) -> dict:
    """辅助函数：从硬盘读取节点信息"""
    filepath = os.path.join(STORAGE_DIR, f"{node_id}.json")
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)
    

from data_copilot import semantic_data_processor
# ==========================================
# 辅助函数：意图路由器 (Router)
# ==========================================
def is_direct_query_task(question: str, motivation: str) -> bool:
    """
    调用 LLM 判断该问题是否属于可以直接通过底层 API (Graph SDK) 查询的实体/流水问题。
    """
    router_prompt = """
    你是一个意图分类器。
    底层系统拥有一个图数据库，可以通过 Python 脚本调用以下两个 API：
    1. `get_account_info(account_id)`: 获取账户静态特征。
    2. `get_transactions(account_id)`: 获取账户一度的流出/流入交易列表（包含金额、时间、币种）。
    
    【你的任务】
    判断用户的问题是否可以通过**编写一段基于上述 API 的 Python 脚本（如：BFS遍历、金额汇总、特征过滤等）直接得出答案**，而不需要进一步拆解为抽象的子问题？
    
    请只输出一个 JSON，格式如下：
    {
        "can_direct_query": true 或 false
    }
    """
    
    try:
        response = invoke_llm(
            messages=[
                {"role": "system", "content": router_prompt},
                {"role": "user", "content": f"问题: {question}, 动机: {motivation}"}
            ],
            model_name="deepseek-chat" # 路由任务很简单，其实也可以用更便宜的小模型
        )
        
        text = response.content.strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
            
        result = json.loads(text)
        return result.get("can_direct_query", False)
        
    except Exception as e:
        print(f"[Router] 路由判断失败: {e}，默认降级为常规推理模式。")
        return False


# ==========================================
# 执行函数 1：开始并展开一个问题节点
# ==========================================
def create_and_reasoning_node(node_id: str, parent_id:str, question: str, motivation: str) -> dict:
    """
    功能：初始化节点，进行初次推理，生成假设分布和子问题。
    返回：给主控台的消息对象。
    """
    print(f"[Worker] 正在思考并展开节点: {node_id} ...")
    
    # ---------------------------------------------------------
    # 新增步骤 A：意图路由评估
    # ---------------------------------------------------------
    if is_direct_query_task(question, motivation):
        print(f"[Worker] ⚡ 识别到底层查询任务！直接交由 Data Copilot 执行...")
        
        # 调用 data_copilot 执行代码生成和查询
        copilot_result = semantic_data_processor(question)
        
        # 构建一个直接“短路”的节点数据
        node_data = {
            "Node_ID": node_id,     
            "Parent_ID": parent_id, 
            "Status": "UNSOLVED",   # 保持 UNSOLVED，交由主控台下一步自动 evaluate 结案
            "Question": question,   
            "Motivation": motivation,       
            # 直接将查询结果作为 100% 确定的假设
            "Hypothesis": {f"Data Copilot 提取结果: {copilot_result[:100]}...": 1.0}, 
            "Reasoning_Log": f"[系统直达] 路由判定该问题可直接查库。已调用 data_copilot 获知底层数据。\n详细结果: {copilot_result}",    
            "Sub_Problems": [],     # 故意设为空，触发下一步的强制结案机制 
            "Resolved_Sub_Problems": [],      
            "Answer": copilot_result, # 顺手把答案写上，方便下一步读取
            "Explanation": "由 Data Copilot 通过 Python 脚本执行底层图数据库接口直接获取。",  
        }
        
        save_node(node_data)
        print(f"[Worker] 节点 {node_id} 通过 Data Copilot 处理完毕。")
        
        return {
            "event_name": "1_create_and_reasoning_node",
            "node_id": node_id,
        }

    # ---------------------------------------------------------
    # 步骤 B：常规的 LLM 深度推理拆解 (保持不变)
    # ---------------------------------------------------------
    print(f"[Worker] 🧠 识别为复杂推理任务，启动三步深度思考...")
    
    # 1. 组装 LangChain 格式的 messages

    # 1. 在 Python 中像写普通字典一样写你的输出模板
    output_schema = {
        "Reasoning_Log": "你的详细推理分析过程...",
        "Hypothesis": {
            "假设A": 0.6,
            "假设B": 0.4
        },
        "Sub_Problems": [
            {
                "Node_ID": "Unallocated",  # 注意：必须严格输出 "Unallocated"
                "Question": "明确、具体的子问题描述，例如：查询账户X的所有转出记录",
                "Motivationtive": "为什么要查这个子问题？它能帮助证实/证伪哪个假设？",
                "Priority": 5
            }
        ]
    }
    # 2. 把字典转化为漂亮的 JSON 字符串
    json_format_str = json.dumps(output_schema, ensure_ascii=False, indent=4)

    system_prompt = f"""
    你是一个顶级的反洗钱（AML）金融调查专家兼逻辑分析师。
    你的任务是对当前面临的复杂问题进行深度剖析，提出可能的假设，并将其拆解为可以实际执行的子问题。

    {DATA_SCHEMA_PROMPT}
    交互说明：
    1. 你的推理和子问题拆解中，可能涉及到获取真实数据的需求或以真实数据为基础进行思考等。注意请勿设想不存在的数据（如IP、位置、聊天记录等）。
    2. 系统底层已经配备了自动查询代码生成器（Data Copilot）。你只需要在 `Sub_Problems` 中用自然语言提出明确的查询需求（例如：“查询账户 X 在某段时间内所有 Euro 币种的转入金额”），底层的 Copilot 就会自动调用接口为你获取。

    【处理步骤】
    你必须严格按照以下三步进行思考：
    1. Reasoning_Log (推理日志): 分析当前的问题是什么，结合父节点的动机，思考解决这个问题的切入点、可能遇到的困难，以及下一步的侦查方向。
    2. Hypothesis (预设假设分布): 基于你的推理，列出当前问题所有可能的答案猜测，并赋予 0 到 1 之间的概率权重（所有猜测的权重相加必须等于 1）。如果信息极度匮乏，可以保留 {{"Unknown": 1.0}}。
    3. Sub_Problems (子问题拆解): 为了验证你的假设或解决当前问题，你需要进一步查明什么？列出具体、可执行的子问题。

    {DYNAMIC_RULES_PROMPT}

    【输出格式约束】
    你必须输出一个纯粹的 JSON 对象，不要使用 Markdown 代码块，不要有任何多余的解释文字。其中Node_ID必须初始化为"Unallocated"。格式示例如下：
    {json_format_str}
    """
    
    user_prompt = f"""
    当前节点 ID: {node_id}
    当前需要解决的问题 (Question): {question}
    提出该问题的动机 (Motivation): {motivation}
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # 2. 调用大模型进行三步推理
    try:
        # 使用你封装的 invoke_llm
        response = invoke_llm(messages=messages, model_name="deepseek-chat")
        
        # 从 LangChain 的 AIMessage 对象中提取文本
        llm_response_text = response.content.strip()
        
        # 清理可能带有的 markdown 标记 (容错处理)
        if llm_response_text.startswith("```json"):
            llm_response_text = llm_response_text[7:-3].strip()
        elif llm_response_text.startswith("```"):
            llm_response_text = llm_response_text[3:-3].strip()
            
        parsed_result = json.loads(llm_response_text)
        
    except Exception as e:
        print(f"[Worker] ⚠️ LLM 解析失败或调用报错: {e}")
        # 降级方案，避免程序崩溃
        parsed_result = {
            "Reasoning_Log": f"大模型调用失败，需重试。错误信息: {str(e)}",
            "Hypothesis": {"Unknown": 1.0},
            "Sub_Problems": []
        }

    # 3. 初始化节点结构并填充 LLM 的思考成果
    node_data = {
        "Node_ID": node_id,     
        "Parent_ID": parent_id, 
        "Status": "UNSOLVED",   
        "Question": question,   
        "Motivation": motivation,       
        "Hypothesis": parsed_result.get("Hypothesis", {"Unknown": 1.0}), 
        "Reasoning_Log": parsed_result.get("Reasoning_Log", ""),    
        "Sub_Problems": parsed_result.get("Sub_Problems", []),      
        "Resolved_Sub_Problems": [],      
        "Answer": "",   
        "Explanation": "",  
    }
    

    # 落地保存
    save_node(node_data)
    
    # 构建返回给主控台的消息
    return {
        "event_name": "1_create_and_reasoning_node",
        "node_id": node_id,
    }


# ==========================================
# 执行函数 2：评估并尝试结束节点
# ==========================================
def evaluate_and_resolve_node(node_id: str) -> dict:
    """
    功能：判断节点是否已经满足解决条件（如分布足够集中，或无剩余子问题）。
          如果满足，则生成最终答案、解释，并将状态改为 RESOLVED。
    返回：给主控台的消息对象。
    """
    print(f"[Worker] 正在评估节点 {node_id} 是否可以结案...")
    # ---------------------------------------------------------
    # TODO: 这里需要调用 LLM 或编写判定逻辑
    # 输入给 LLM 的信息：当前问题的 Question, Hypothesis, Resolved_Sub_Problems, Sub_Problems
    # LLM 需要回答：
    # 1. 证据是否足够下结论？(is_resolved: bool)
    # 2. 如果足够，Answer 是什么？Explanation 是什么？
    # ---------------------------------------------------------
    
    node_data = load_node(node_id)
    question = node_data.get("Question", "")
    hypothesis = node_data.get("Hypothesis", {})
    sub_problems = node_data.get("Sub_Problems", [])
    resolved_sub_problems = node_data.get("Resolved_Sub_Problems", [])
    
    # 1. 组装裁判官视角的 System Prompt
    system_prompt = """
    你是一个严谨的反洗钱（AML）调查裁判官。
    你的任务是审查当前节点收集到的证据，评估是否已经具备足够的条件来“结案”（即对问题给出确定的最终答案）。
    
    【结案判定标准】
    如果满足以下任意一个条件，你必须判定可以结案 (is_resolved = true)：
    1. 证据确凿：在当前的 Hypothesis（预设答案分布）中，某一个假设的概率已经具有绝对压倒性优势（例如概率 >= 0.85）。
    2. 线索耗尽：待解决的子问题数量为 0。这意味着没有后续调查方向了，你必须根据现有的已解决子问题（Resolved_Sub_Problems）强行得出一个当前最优的推论。
    
    【输出格式约束】
    你必须输出一个纯粹的 JSON 对象，不要使用 Markdown 代码块。格式如下：
    {
        "is_resolved": true或false,
        "Answer": "如果 is_resolved 为 true，请在这里写下对 Question 的最终明确回答（结论先行）；如果为 false，留空字符串",
        "Explanation": "如果 is_resolved 为 true，请在这里简述你是如何根据 Resolved_Sub_Problems 中的证据以及其它线索推导出该结论的；如果为 false，留空字符串"
    }
    """
    
    # 2. 组装案卷数据，为节省 Token，我们只把关键的字段塞进去
    # 将字典转为格式化的 JSON 字符串，方便大模型阅读
    user_prompt = f"""
    【当前审查的问题 (Question)】: {question}
    【当前的假设分布 (Hypothesis)】: {json.dumps(hypothesis, ensure_ascii=False)}
    【尚未解决的子问题数量】: {len(sub_problems)}
    
    【已经解决的子问题 (Resolved_Sub_Problems)】:
    {json.dumps(resolved_sub_problems, ensure_ascii=False, indent=2)}
    
    请根据判定标准进行裁决，并输出符合要求的 JSON。
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # 3. 调用 LLM 进行裁决
    try:
        response = invoke_llm(messages=messages, model_name="deepseek-chat")
        llm_response_text = response.content.strip()
        
        # 清理可能带有的 markdown 标记
        if llm_response_text.startswith("```json"):
            llm_response_text = llm_response_text[7:-3].strip()
        elif llm_response_text.startswith("```"):
            llm_response_text = llm_response_text[3:-3].strip()
            
        parsed_result = json.loads(llm_response_text)
        is_resolved = parsed_result.get("is_resolved", False)
        
        # 【安全兜底机制】：如果子问题已经空了，强制认定结案，防止系统在此节点无限死循环
        if len(sub_problems) == 0:
            is_resolved = True
            
    except Exception as e:
        print(f"[Worker] ⚠️ 裁判官 LLM 解析失败或报错: {e}")
        # 如果报错且无子问题了，系统强行结案；否则继续留着处理
        is_resolved = len(sub_problems) == 0
        parsed_result = {
            "Answer": "系统自动判定结案（由于 LLM 裁决失败且无线索）。",
            "Explanation": f"系统因错误进行强行合并，错误详情: {str(e)}"
        }
    
    if is_resolved:
        print(f"[Worker] 节点 {node_id} 条件满足，正式结案！")
        node_data["Status"] = "RESOLVED"
        # node_data["Answer"] = "通过分析..." # 模拟 LLM 生成的最终答案
        # node_data["Explanation"] = "因为子问题1证明了X，子问题2证明了Y..." # 模拟短解释
        
        save_node(node_data)
        
        return {
            "event_name": "2_evaluate_and_resolve_node",
            "event_type": "NODE_RESOLVED",
            "node_id": node_id,
            "parent_id": node_data.get("Parent_ID")
        }
    else:
        print(f"[Worker] 节点 {node_id} 证据不足，需要继续探索。")
        return {
            "event_name": "2_evaluate_and_resolve_node",
            "event_type": "NODE_UNSOLVED",
            "node_id": node_id
        }


# ==========================================
# 执行函数 3：利用子节点的结果更新父节点
# ==========================================
def update_parent_node(node_id: str) -> dict:
    """
    功能：在子节点 RESOLVED 后触发。读取子节点的答案，更新父节点的 Hypothesis、
          Reasoning_Log，并将该子节点从待解决列表移至已解决列表。
    返回：给主控台的消息对象。
    """
    print(f"[Worker] 正在提取子节点 {node_id} 的情报，准备上报...")
    time.sleep(1) # 模拟耗时
    
    child_data = load_node(node_id)
    parent_id = child_data.get("Parent_ID")
    
    # 如果当前节点就是树的根节点，说明整个推理树大功告成！
    if parent_id == "ROOT" or parent_id is None:
        return {
            "event_name": "3_update_parent_node",
            "event_type": "ROOT_COMPLETED",
            "final_answer": child_data["Answer"],
            "explanation": child_data["Explanation"]
        }
        
    print(f"[Worker] -> 正在唤醒父节点 {parent_id} 整合新情报...")
    parent_data = load_node(parent_id)
    
    # 1. 在父节点中，将该子节点从 Sub_Problems 中移除 (通过对比 Node_ID)
    # parent_data["Sub_Problems"] = [
    #     sp for sp in parent_data["Sub_Problems"] if sp["Node_ID"] != node_id
    # ]
    parent_data["Sub_Problems"] = [
        sp for sp in parent_data.get("Sub_Problems", []) if sp.get("Node_ID") != node_id
    ]
    
    # 2. 将子节点的情报按规定格式打包，塞入 Resolved_Sub_Problems
    resolved_info = {
        "Node_ID": node_id,
        "Question": child_data["Question"],
        "Motivation": child_data["Motivation"],
        "Answer": child_data["Answer"],
        "Explanation": child_data["Explanation"]
    }
    parent_data["Resolved_Sub_Problems"].append(resolved_info)
    
    # ---------------------------------------------------------
    # TODO: 这里是贝叶斯信念更新的核心调用点！
    # 将 parent_data 的原始 Hypothesis、Reasoning_Log，加上刚刚获得的 resolved_info 喂给 LLM
    # 让 LLM 重新思考并输出：
    # 1. 新的 Hypothesis (预设答案分布)
    # 2. 补充的 Reasoning_Log (记录刚刚学到了什么)
    # 3. (可选) 是否需要由于新发现，往 Sub_Problems 里追加新的子问题？
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # 3. 贝叶斯信念更新：调用 LLM 吸收新情报
    # ---------------------------------------------------------
    output_schema = {
        "Added_Reasoning_Log": "简述你从这份新情报中学到了什么，以及它是如何影响你对整体问题判断的。",
        "Updated_Hypothesis": {
            "更新后的假设A": 0.7,
            "更新后的假设B": 0.2,
            "可能发掘出的新假设C": 0.1
        },
        "New_Sub_Problems": [
            {
                "Node_ID": "Unallocated",  # 注意：必须严格输出 "Unallocated"
                "Question": "仅填写由这份新情报**新衍生**出的子问题，如果没有新问题，保留空列表即可",
                "Motivation": "为什么要查这个新问题？",
                "Priority": 5
            }
        ]
    }
    # 2. 把字典转化为漂亮的 JSON 字符串
    json_format_str = json.dumps(output_schema, ensure_ascii=False, indent=4)

    system_prompt = f"""
    你是一个负责情报整合的首席分析师（基于贝叶斯定理的逻辑学家）。
    你的上级（父节点）正在尝试解决一个宏大的问题，并给出了初步的假设。现在，你的一名特工（子节点）刚刚带回了一份最新查明的情报。

    {DATA_SCHEMA_PROMPT}
    交互说明：
    1. 你的推理和子问题拆解中，可能涉及到获取真实数据的需求或以真实数据为基础进行思考等。注意请勿设想不存在的数据（如IP、位置、聊天记录等）。
    2. 系统底层已经配备了自动查询代码生成器（Data Copilot）。你只需要在 `Sub_Problems` 中用自然语言提出明确的查询需求（例如：“查询账户 X 在某段时间内所有 Euro 币种的转入金额”），底层的 Copilot 就会自动调用接口为你获取。
    
    【你的任务】
    1. 评估新情报：这份情报证实了什么？证伪了什么？
    2. 更新信念分布：根据这份新情报，重新分配上级原本的“假设概率分布 (Hypothesis)”。具体关注两个问题：是否存在新的答案假设？更新假设的集合后，如何调整其概率分布？
    3. 挖掘新线索：这份新情报是否引出了之前没想到的“新疑点”？如果有，请将其转化为新的子问题。

    {DYNAMIC_RULES_PROMPT}
    
    【输出格式约束】
    你必须输出一个纯粹的 JSON 对象，不要使用 Markdown 代码块，不要有任何多余的解释文字。其中Node_ID必须初始化为"Unallocated"。格式示例如下：
    {json_format_str}
    """
    
    # 将现有信息精简打包，喂给大模型
    # 注意：提供现有的 Sub_Problems 是为了防止大模型生成重复的已知子问题
    user_prompt = f"""
    【父节点正在解决的核心问题】: {parent_data.get("Question", "")}
    【父节点此前的推理日志】: {parent_data.get("Reasoning_Log", "")}
    【父节点此前的假设分布】: {json.dumps(parent_data.get("Hypothesis", {}), ensure_ascii=False)}
    【父节点目前还有待查的子问题清单】: {json.dumps([sp.get("Question") for sp in parent_data.get("Sub_Problems", [])], ensure_ascii=False)}
    
    ======================================
    🔥【刚刚获得的最新情报 (来自子节点 {node_id})】🔥
    探查的问题: {resolved_info['Question']}
    探查的动机: {resolved_info['Motivation']}
    得出结论 (Answer): {resolved_info['Answer']}
    详细依据 (Explanation): {resolved_info['Explanation']}
    ======================================
    
    请严格按照上述 JSON 格式，吸收新情报并更新父节点状态。注意：New_Sub_Problems 中的 Node_ID 必须以 '{parent_id}_' 开头。
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    try:
        response = invoke_llm(messages=messages, model_name="deepseek-chat")
        llm_response_text = response.content.strip()
        
        if llm_response_text.startswith("```json"):
            llm_response_text = llm_response_text[7:-3].strip()
        elif llm_response_text.startswith("```"):
            llm_response_text = llm_response_text[3:-3].strip()
            
        parsed_result = json.loads(llm_response_text)
        
        # 将大模型吸收情报后的反馈，追加融合到父节点中
        new_log = parsed_result.get("Added_Reasoning_Log", "")
        if new_log:
            parent_data["Reasoning_Log"] += f"\n\n[吸收子节点 {node_id} 情报]: {new_log}"
            
        parent_data["Hypothesis"] = parsed_result.get("Updated_Hypothesis", parent_data["Hypothesis"])
        
        # 将新衍生的子问题追加到待办清单中
        new_subs = parsed_result.get("New_Sub_Problems", [])
        if new_subs:
            parent_data["Sub_Problems"].extend(new_subs)
            print(f"[Worker] ⚠️ 父节点 {parent_id} 在吸收情报后，衍生出了 {len(new_subs)} 个新问题！")
            
    except Exception as e:
        print(f"[Worker] ⚠️ 情报整合 LLM 解析失败或报错: {e}")
        parent_data["Reasoning_Log"] += f"\n\n[吸收子节点 {node_id} 情报失败]: 系统强行收录了该子节点的答案，但未能更新假设分布。"


    
    save_node(parent_data)
    
    # 汇报主控台：父节点已更新完毕，请安排重新评估父节点是否可以结案！
    return {
        "event_name": "3_update_parent_node",
        "node_id": node_id,
        "parent_id": parent_id
    }