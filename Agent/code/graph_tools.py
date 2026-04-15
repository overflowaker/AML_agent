import pandas as pd
from collections import defaultdict
from langchain_core.tools import tool

# ==========================================
# 1. 内存图数据结构初始化
# ==========================================
graph_out = defaultdict(list)
graph_in = defaultdict(list)
node_features = {}

def load_ibm_aml_data(csv_path: str = None):
    """
    加载 IBM AML 数据集构建内存邻接表。
    这里为了 MVP 能直接运行，如果没有传入路径，会生成几条 mock 数据。
    """
    global graph_out, graph_in
    
    if csv_path:
        print(f"正在从 {csv_path} 加载真实数据...")
        df = pd.read_csv(csv_path, nrows=10000) 
        
        # 重新映射列名，确保涵盖银行信息
        df.rename(columns={
            'From Bank': 'Source_Bank',
            'Account': 'Sender_Account',
            'To Bank': 'Target_Bank',
            'Account.1': 'Receiver_Account',
            'Amount Paid': 'Amount',
            'Payment Format': 'Pay_Method'
        }, inplace=True)
        
        for _, row in df.iterrows():
            sender = str(row['Sender_Account'])
            receiver = str(row['Receiver_Account'])
            
            # 将转出记录补全：包含转出银行和接收银行
            graph_out[sender].append({
                "from_bank": str(row['Source_Bank']),
                "to_acc": receiver, 
                "to_bank": str(row['Target_Bank']),
                "amount": row['Amount'], 
                "currency": row['Payment Currency'],
                "time": row['Timestamp'],
                "method": row['Pay_Method']
            })
            
            # 同理补全转入记录
            graph_in[receiver].append({
                "from_acc": sender,
                "from_bank": str(row['Source_Bank']),
                "to_bank": str(row['Target_Bank']),
                "amount": row['Amount'], 
                "currency": row['Receiving Currency'],
                "time": row['Timestamp'],
                "method": row['Pay_Method']
            })
            
        print(f"数据加载完成。现在 Agent 可以识别跨行转账行为。")
    else:
        # Mock 数据，模拟几个账户之间的洗钱链路
        print("未提供数据路径，使用内置 Mock 数据初始化图结构...")
        transactions = [
            ("Acc_A", "Acc_B", 500000, "2026-04-01 10:00"),
            ("Acc_B", "Acc_C", 490000, "2026-04-01 11:00"),
            ("Acc_C", "Acc_D", 480000, "2026-04-01 12:00"),
            ("Acc_X", "Acc_A", 100, "2026-04-01 09:00"), # 正常小额交易
        ]
        for src, dst, amt, time in transactions:
            graph_out[src].append({"to": dst, "amount": amt, "time": time})
            graph_in[dst].append({"from": src, "amount": amt, "time": time})

# ==========================================
# 2. 暴露给大模型的 Tool 接口
# ==========================================

@tool
def get_one_hop_transactions(node_id: str, limit: int = 5) -> str:
    """
    获取目标账户的一度交易网络（转入与转出记录）。
    
    参数:
    - node_id: 账户的唯一标识符
    - limit: 最多返回的交易记录条数，防止信息过载（默认5条）
    """
    out_records = graph_out.get(node_id, [])
    in_records = graph_in.get(node_id, [])
    
    if not out_records and not in_records:
        return f"图数据库中未找到账户 {node_id} 的任何交易记录。"
        
    report = f"【账户 {node_id} 的一度交易特征】\n"
    report += f"总计转出 {len(out_records)} 笔，转入 {len(in_records)} 笔。\n"
    
    # 截断数据，防止 token 爆炸
    report += f"最近转出记录: {out_records[:limit]}\n"
    report += f"最近转入记录: {in_records[:limit]}\n"
    
    return report

@tool
def search_high_value_transactions(node_id: str, min_amount: float) -> str:
    """
    针对可疑账户，查询其金额大于指定阈值的交易记录。
    
    参数:
    - node_id: 账户标识符
    - min_amount: 最小金额阈值（如 10000）
    """
    out_records = [r for r in graph_out.get(node_id, []) if r["amount"] >= min_amount]
    in_records = [r for r in graph_in.get(node_id, []) if r["amount"] >= min_amount]
    
    if not out_records and not in_records:
        return f"账户 {node_id} 没有发现大于 {min_amount} 的交易。"
        
    return f"账户 {node_id} 大于 {min_amount} 的交易如下：\n转出: {out_records}\n转入: {in_records}"

# 将所有需要给大模型用的工具打包
aml_tools = [get_one_hop_transactions, search_high_value_transactions]