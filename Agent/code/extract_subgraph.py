import pandas as pd
import networkx as nx
from collections import deque

file_path = '../../data/original/HI-Small_Trans.csv'
output_path = '../../data/deal2/AML_Test_Subgraph.csv'
target_nodes_count = 10000

print("📦 正在将整个交易网络加载到内存...")
df = pd.read_csv(file_path)

print("🕸️ 正在构建全局图拓扑...")
# 构建无向图
G = nx.from_pandas_edgelist(df, source='Account', target='Account.1', create_using=nx.Graph())

# 找出所有涉及洗钱的账户作为备选“种子”
illicit_edges = df[df['Is Laundering'] == 1]
seed_candidates = list(set(illicit_edges['Account']).union(set(illicit_edges['Account.1'])))

if not seed_candidates:
    raise ValueError("数据集中没有找到洗钱节点，请检查数据！")

print(f"🎯 找到了 {len(seed_candidates)} 个潜在的洗钱种子账户，准备开始 BFS 扩散...")

best_subgraph_nodes = set()
used_seed = None

# BFS 寻找强连通子图
for seed in seed_candidates:
    visited = {seed}
    queue = deque([seed])
    
    while queue and len(visited) < target_nodes_count:
        current_node = queue.popleft()
        
        for neighbor in G.neighbors(current_node):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
                
                if len(visited) >= target_nodes_count:
                    break
                    
    if len(visited) > len(best_subgraph_nodes):
        best_subgraph_nodes = visited
        used_seed = seed
        
    if len(visited) >= target_nodes_count:
        break

print(f"\n✅ BFS 采样完成！核心洗钱种子: {used_seed}")
print("🔪 正在切割交易记录...")

# 基础切割：只保留名单内的 10000 人互相之间的交易
subgraph_df = df[df['Account'].isin(best_subgraph_nodes) & df['Account.1'].isin(best_subgraph_nodes)]

print("📌 正在将中心违法节点的数据置顶...")
# 核心改动：利用 Mask 分离出种子的交易
seed_mask = (subgraph_df['Account'] == used_seed) | (subgraph_df['Account.1'] == used_seed)

# 包含核心种子的交易
seed_transactions = subgraph_df[seed_mask]
# 其他人的背景交易
other_transactions = subgraph_df[~seed_mask]

# 将种子的交易强制拼接在最顶端 (ignore_index=True 确保行号重新排列)
final_df = pd.concat([seed_transactions, other_transactions], ignore_index=True)

# ================= 新增功能：输出子图中所有洗钱节点 =================
# 在最终切割好的子图里，筛选出带有洗钱标记的交易
illicit_in_subgraph = final_df[final_df['Is Laundering'] == 1]
# 取出这些交易里的所有发送方和接收方账户去重
laundering_nodes = set(illicit_in_subgraph['Account']).union(set(illicit_in_subgraph['Account.1']))

print(f"\n🚨 注意！在提取的这 10000 人子图中，共有 {len(laundering_nodes)} 个节点涉及洗钱。")
print(f"🔍 它们的 Account ID 列表如下：")
print(list(laundering_nodes))
print("====================================================================\n")


print(f"💾 切割完成，该连通子图共包含 {len(final_df)} 条交易记录。")
final_df.to_csv(output_path, index=False)
print(f"🎉 文件已保存至: {output_path}")
print(f"👀 快去打开 CSV 吧！前 {len(seed_transactions)} 行就是中心违法账户的所有交易！")