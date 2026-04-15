import kuzu
import pandas as pd
import os

import shutil

# ==========================================
# 1. 数据库初始化与 Schema 定义
# ==========================================
DB_PATH = '../../../data/graph/aml_kuzu_db'
db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

def init_schema():
    """定义与真实数据严格对应的图数据库 Schema"""
    print("正在初始化图数据库 Schema...")
    
    # 1. 创建节点表 (Account)
    conn.execute("""
        CREATE NODE TABLE Account (
            account_id STRING,
            bank_name STRING,
            bank_id STRING,
            entity_id STRING,
            entity_name STRING,
            PRIMARY KEY (account_id)
        )
    """)
    
    # 2. 创建边表 (Transaction)
    # 【修复点】：FROM Account TO Account 之间没有逗号
    conn.execute("""
        CREATE REL TABLE Transaction (
            FROM Account TO Account,
            timestamp STRING,
            from_bank STRING,
            to_bank STRING,
            amount_paid DOUBLE,
            payment_currency STRING,
            amount_received DOUBLE,
            receiving_currency STRING,
            payment_format STRING,
            is_laundering INT64
        )
    """)
    print("Schema 创建完成！")

# ==========================================
# 2. 数据清洗与超大规模导入
# ==========================================
def load_data(trans_csv_path: str, accounts_csv_path: str):
    """
    读取 CSV，对齐列名，并使用 Kùzu 的 COPY 命令实现极速落盘。
    """
    print("正在处理节点数据 (Accounts)...")
    df_acc = pd.read_csv(accounts_csv_path)
    
    # 映射节点列名，使其与 CREATE NODE TABLE 语句中的属性名完全一致
    df_acc_clean = df_acc[[
        'Account Number', 'Bank Name', 'Bank ID', 'Entity ID', 'Entity Name'
    ]].copy()
    df_acc_clean.columns = [
        'account_id', 'bank_name', 'bank_id', 'entity_id', 'entity_name'
    ]
    
    # 确保没有重复的 account_id (图数据库主键要求唯一)
    df_acc_clean = df_acc_clean.drop_duplicates(subset=['account_id'])
    
    # 执行内存导入
    conn.execute("COPY Account FROM df_acc_clean")
    print(f"成功导入 {len(df_acc_clean)} 个账户节点！")

    print("正在处理边数据 (Transactions)...")
    # MVP阶段，依然建议先用 nrows=10000 限制条数跑通测试，跑通后再去掉 nrows 读取全量
    # df_trans = pd.read_csv(trans_csv_path, nrows=10000)
    df_trans = pd.read_csv(trans_csv_path)
    
    
    # 映射边列名。注意：Pandas 读取重复列名 'Account' 时，第二个会自动命名为 'Account.1'
    df_trans_clean = df_trans[[
        'Account',              # FROM: 发起方
        'Account.1',            # TO: 接收方
        'Timestamp', 
        'From Bank',
        'To Bank',
        'Amount Paid', 
        'Payment Currency', 
        'Amount Received',
        'Receiving Currency',
        'Payment Format', 
        'Is Laundering'
    ]].copy()
    
    df_trans_clean.columns = [
        'from_acc', 'to_acc', 'timestamp', 'from_bank', 'to_bank',
        'amount_paid', 'payment_currency', 'amount_received', 'receiving_currency',
        'payment_format', 'is_laundering'
    ]
    
    # 【数据安全校验】：剔除那些在账户表中不存在的“幽灵节点”交易
    # 否则 Kuzu 在创建边时会报 Foreign Key Constraint Error
    valid_accounts = set(df_acc_clean['account_id'])
    valid_mask = df_trans_clean['from_acc'].isin(valid_accounts) & df_trans_clean['to_acc'].isin(valid_accounts)
    df_trans_final = df_trans_clean[valid_mask]
    
    dropped_count = len(df_trans_clean) - len(df_trans_final)
    if dropped_count > 0:
        print(f"⚠️ 剔除了 {dropped_count} 条涉及未注册账户的交易记录。")
    
    # 执行内存导入
    conn.execute("COPY Transaction FROM df_trans_final")
    print(f"成功导入 {len(df_trans_final)} 条交易边！数据已安全落盘。")

# ==========================================
# 3. 提供给 LLM 的基础查询工具函数
# ==========================================
def get_account_context(account_id: str) -> str:
    """
    用于给 LLM 提供某个账户的全局上下文（包含静态属性和出入度统计）
    """
    query = """
        MATCH (a:Account {account_id: $acc_id})
        OPTIONAL MATCH (a)-[out_tx:Transaction]->()
        OPTIONAL MATCH ()-[in_tx:Transaction]->(a)
        RETURN a.account_id, a.entity_name, a.bank_name, 
               count(out_tx) AS total_out, count(in_tx) AS total_in
    """
    results = conn.execute(query, parameters={"acc_id": account_id})
    
    if results.has_next():
        row = results.get_next()
        return (f"账户 {row[0]} ({row[1]}, 开户行: {row[2]}) \n"
                f"历史总计转出 {row[3]} 笔，转入 {row[4]} 笔。")
    return f"未找到账户 {account_id} 的信息。"

def get_one_hop_details(account_id: str, limit: int = 5) -> str:
    """
    获取一度邻居的详细交易列表（按照金额排序，提取最可疑的交易）
    """
    # Cypher: 查找从该账户转出的所有交易，并按金额降序排列
    query_out = """
        MATCH (a:Account {account_id: $acc_id})-[tx:Transaction]->(b:Account)
        RETURN b.account_id, b.entity_name, tx.amount_paid, tx.timestamp, tx.payment_format
        ORDER BY tx.amount_paid DESC
        LIMIT $lim
    """
    res_out = conn.execute(query_out, parameters={"acc_id": account_id, "lim": limit})
    
    out_details = []
    while res_out.has_next():
        row = res_out.get_next()
        # 组装成自然语言或结构化字符串
        out_details.append(f"向 {row[0]} ({row[1]}) 转账 {row[2]} (格式: {row[4]}, 时间: {row[3]})")
        
    return f"账户 {account_id} 的大额转出记录:\n" + "\n".join(out_details) if out_details else "无转出记录。"

# ==========================================
# 运行主逻辑
# ==========================================
if __name__ == "__main__":
 
    # 强制重置开关：如果设为 True，每次运行都会清空旧库重新导数据
    # 测试稳定后，把它改成 False，就不会再反复导数据了
    RESET_DB = False 
    
    if RESET_DB:
        print("\n--- 检测到重置模式，正在清理旧数据库... ---")
        if os.path.exists(DB_PATH):
            # 先关闭数据库连接，释放文件锁
            conn.close() 
            
            # 判断是文件夹还是单文件，并分别使用对应的删除方法
            if os.path.isdir(DB_PATH):
                shutil.rmtree(DB_PATH)
            elif os.path.isfile(DB_PATH):
                os.remove(DB_PATH)
                
            print("旧数据库已清理完毕。")
            
        # 重新初始化空的数据库连接
        db = kuzu.Database(DB_PATH)
        conn = kuzu.Connection(db)
        
        # 重新建表并导入数据
        init_schema()
        data_path = "../../../data/original/"
        load_data(data_path + "HI-Small_Trans.csv", data_path + "HI-Small_accounts.csv")

    
    # 【第二步】测试查询接口
    print("\n--- 接口测试 ---")
    
    # 提取你在样本里提供的一个账户：8000EBD30
    test_id = "8000EBD30"
    
    print("\n[账户上下文查询]")
    print(get_account_context(test_id))
    
    print("\n[一度资金流向查询]")
    print(get_one_hop_details(test_id))