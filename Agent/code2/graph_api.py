import kuzu
import config

# ==========================================
# 模块级数据库连接配置
# ==========================================
# 请确保此路径与你的真实数据库路径一致
# DB_PATH = './aml_kuzu_db' 
# _db = kuzu.Database(DB_PATH)
# _conn = kuzu.Connection(_db)
# DB_PATH = '../../data/graph/aml_kuzu_db'
DB_PATH = config.ROOT_DIR / "data/graph/aml_kuzu_db"
_db = kuzu.Database(DB_PATH)
_conn = kuzu.Connection(_db)

# ==========================================
# 供大模型调用的 API 接口 (纯净图信息提取层)
# ==========================================

def get_account_info(account_id: str) -> dict:
    """
    获取指定账户的所有静态属性信息。
    """
    query = """
        MATCH (a:Account {account_id: $acc_id}) 
        RETURN a.account_id, a.bank_id, a.bank_name, a.entity_id, a.entity_name
    """
    res = _conn.execute(query, parameters={"acc_id": account_id})
    
    if res.has_next():
        row = res.get_next()
        return {
            "account_id": row[0],
            "bank_id": row[1],
            "bank_name": row[2],
            "entity_id": row[3],
            "entity_name": row[4]
        }
    return {}

def get_transactions(account_id: str) -> list:
    """
    获取指定账户的所有相关交易记录（包含转出和转入）。
    ⚠️ 注意：为了模拟真实推理环境，已严格剔除 `is_laundering` 标签字段，防止目标穿越。
    """
    transactions = []
    
    # 1. 查询转出记录 (OUT: 资金从当前账户流出)
    query_out = """
        MATCH (a:Account {account_id: $acc_id})-[t:Transaction]->(b:Account)
        RETURN b.account_id, t.timestamp, t.from_bank, t.to_bank, 
               t.amount_paid, t.payment_currency, 
               t.amount_received, t.receiving_currency, t.payment_format
    """
    res_out = _conn.execute(query_out, parameters={"acc_id": account_id})
    while res_out.has_next():
        row = res_out.get_next()
        transactions.append({
            "direction": "out",             # 资金流出
            "counterparty": row[0],         # 对手方账户 (接收方)
            "timestamp": row[1],            # 交易时间
            "from_bank": row[2],            # 汇出银行
            "to_bank": row[3],              # 接收银行
            "amount_paid": row[4],          # 汇出金额
            "payment_currency": row[5],     # 汇出币种
            "amount_received": row[6],      # 接收金额
            "receiving_currency": row[7],   # 接收币种
            "payment_format": row[8]        # 交易方式 (如 Cheque, Reinvestment)
        })
        
    # 2. 查询转入记录 (IN: 资金流入当前账户)
    query_in = """
        MATCH (b:Account)-[t:Transaction]->(a:Account {account_id: $acc_id})
        RETURN b.account_id, t.timestamp, t.from_bank, t.to_bank, 
               t.amount_paid, t.payment_currency, 
               t.amount_received, t.receiving_currency, t.payment_format
    """
    res_in = _conn.execute(query_in, parameters={"acc_id": account_id})
    while res_in.has_next():
        row = res_in.get_next()
        transactions.append({
            "direction": "in",              # 资金流入
            "counterparty": row[0],         # 对手方账户 (发送方)
            "timestamp": row[1],            # 交易时间
            "from_bank": row[2],            # 汇出银行
            "to_bank": row[3],              # 接收银行
            "amount_paid": row[4],          # 汇出金额
            "payment_currency": row[5],     # 汇出币种
            "amount_received": row[6],      # 接收金额
            "receiving_currency": row[7],   # 接收币种
            "payment_format": row[8]        # 交易方式
        })
        
    return transactions

# ==========================================
# 本地测试
# ==========================================
if __name__ == "__main__":
    # 使用你样本里提供的真实账户测试
    # test_id = "8000EBD30"
    # test_id = "8088FE560"
    test_id = "80B779D80"
    
    
    print(f"--- 正在查询账户 {test_id} 的信息 ---")
    print(get_account_info(test_id))
    
    print(f"\n--- 正在查询账户 {test_id} 的交易记录 ---")
    txs = get_transactions(test_id)
    if txs:
        print(f"共找到 {len(txs)} 笔交易，示例:")
        # print(txs[0])
        print(txs)
    else:
        print("无交易记录。")