from collections import deque

# 假设你的三个执行函数和 load_node 都写在 agent_workers.py 里
from agent_workers import (
    create_and_reasoning_node,
    evaluate_and_resolve_node,
    update_parent_node,
    load_node,  # 路由分支需要它来读取最高优先级的子问题
    save_node  # 新增：需要引入 save_node 来保存分配好 ID 的父节点
)

# 新增：全局节点发号计数器
GLOBAL_NODE_COUNTER = 0

def main_loop():
    # ⚠️ 新增这一行：声明我们要修改的是外面的全局变量
    global GLOBAL_NODE_COUNTER

    # 消息队列，存放所有待处理的事件
    event_queue = deque()
    
    # 启动系统的第一推力：这不是执行结果，而是一个触发初始化的伪指令
    event_queue.append({
        "event_name": "CMD_START_ROOT",
        "node_id": "P-ROOT",
        "parent_id": "ROOT",
        "question": "找出 8088FE560 账户是否参与了洗钱网络？",
        "motivation": "最高指令：解答用户的终极问题"
    })
    
    print("=== 🚀 推理引擎启动 ===")
    
    while event_queue:
        current_event = event_queue.popleft()
        event_name = current_event["event_name"]
        
        # -----------------------------------------------------------
        # 0. 启动根节点 (系统入口)
        # -----------------------------------------------------------
        if event_name == "CMD_START_ROOT":
            # 触发：创建根节点
            result_msg = create_and_reasoning_node(
                node_id=current_event["node_id"],
                parent_id=current_event["parent_id"],
                question=current_event["question"],
                motivation=current_event["motivation"]
            )
            event_queue.append(result_msg)
            
        # -----------------------------------------------------------
        # 1. 检测到新建及推理完毕
        # -----------------------------------------------------------
        elif event_name == "1_create_and_reasoning_node":
            node_id = current_event["node_id"]
            print(f"[Controller] 收到节点 {node_id} 的建立反馈。触发评估...")
            
            # 规则：对该新建节点执行 evaluate_and_resolve_node
            result_msg = evaluate_and_resolve_node(node_id)
            event_queue.append(result_msg)
            
        # -----------------------------------------------------------
        # 2. 检测到节点评估完毕
        # -----------------------------------------------------------
        elif event_name == "2_evaluate_and_resolve_node":
            node_id = current_event["node_id"]
            event_type = current_event["event_type"] # 期待执行函数返回 "RESOLVED" 或 "UNSOLVED"
            
            # 规则 A：若已解决，执行 update_parent_node
            if event_type == "NODE_RESOLVED":
                print(f"[Controller] 节点 {node_id} 已解决。准备向上反馈情报...")
                result_msg = update_parent_node(node_id)
                event_queue.append(result_msg)
                
            # 规则 B：若未解决，找出优先级最高的子问题执行新建
            elif event_type == "NODE_UNSOLVED":
                print(f"[Controller] 节点 {node_id} 尚需探索。查找最高优先级子问题...")
                
                # 读取硬盘上的节点文件，获取子问题清单
                node_data = load_node(node_id)
                sub_problems = node_data.get("Sub_Problems", [])
                
                if not sub_problems:
                    print(f"[Controller] ⚠️ 警告: 节点 {node_id} 无法解决，且没有待处理的子问题，陷入停滞。")
                    continue
                
                # 寻找优先级最高的一个 (假设 Priority 是数值型，越大越优先)
                # 容错处理：如果字典里没写 Priority，默认当成 0 处理
                highest_sub = max(sub_problems, key=lambda x: x.get("Priority", 0))
                
                # -------------------------------------------------------------
                # ✨ 新增核心逻辑：拦截并分配确定性的 Node_ID
                # -------------------------------------------------------------
                if highest_sub.get("Node_ID", "Unallocated") == "Unallocated":
                    GLOBAL_NODE_COUNTER += 1
                    # 严格格式：P{自己的id}_{parent_id}
                    new_node_id = f"P{GLOBAL_NODE_COUNTER}_{node_id}" 
                    highest_sub["Node_ID"] = new_node_id
                    
                    # 写回父节点硬盘
                    save_node(node_data)
                
                sub_node_id = highest_sub["Node_ID"]
                # -------------------------------------------------------------
                
                print(f"[Controller] -> 派发新任务: {sub_node_id}")
                
                # 对优先级最高的子问题执行 create_and_reasoning_node
                result_msg = create_and_reasoning_node(
                    node_id=sub_node_id,
                    parent_id=node_id,
                    question=highest_sub["Question"],
                    motivation=highest_sub.get("Motivation", highest_sub.get("Motivation", ""))
                )
                event_queue.append(result_msg)
                
        # -----------------------------------------------------------
        # 3. 检测到父节点更新完毕
        # -----------------------------------------------------------
        elif event_name == "3_update_parent_node":
            parent_id = current_event["parent_id"]
            print(f"[Controller] 父节点 {parent_id} 吸收情报完毕。触发重新评估...")
            
            # 规则：对 parent_node 执行 evaluate_and_resolve_node
            result_msg = evaluate_and_resolve_node(parent_id)
            event_queue.append(result_msg)
            
        # -----------------------------------------------------------
        # 4. 检测到全局完结
        # -----------------------------------------------------------
        elif event_type == "ROOT_COMPLETED":
            print("\n" + "="*50)
            print("=== 🎉 推理引擎大功告成！ ===")
            print(f"【最终结论】\n{current_event.get('final_answer', '暂无答案')}")
            print(f"\n【详细解释】\n{current_event.get('explanation', '暂无解释')}")
            print("="*50 + "\n")
            break

if __name__ == "__main__":
    main_loop()