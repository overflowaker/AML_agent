# AML LLM-Agent 推理项目架构指南

## 1. 项目概述
本项目是一个用于反洗钱（AML）的 LLM-Agent 系统。系统底层对接图数据库（包含账户节点与交易边）。其核心目标是接收自然语言问题（如“8088FE560 账户是否参与了洗钱？”），并通过一种**树形推理（Tree-of-Thought）**机制，将复杂问题拆解为可执行的子问题，最终汇总得出结论。
当前代码量约为 2000 行。**核心设计原则：高度模块化、通过事件流驱动节点状态流转。**

## 2. 核心抽象概念：推理树 (Reasoning Tree)
系统将每一次完整的推理过程抽象为一棵树。
* **节点 (Node)：** 树上的每一个节点代表一个独立的“问题”。
* **节点数据结构：** 每个节点拥有独立的信息存储，包含：
    * `Question`: 问题描述
    * `Motivation`: 提出该问题的动机
    * `Hypothesis`: 对答案的预估/当前结论
    * `Sub-questions`: 拆解出的子问题列表
    * `Reasoning_Log`: 节点内部的推理日志

## 3. 核心文件与调度管线 (Pipeline)

### 3.1 主控中心: `main_controller.py`
负责全局事件的路由与状态机流转。系统通过监听三种核心事件来驱动整棵树的生长：
1.  **`1_create_and_reasoning_node`**:
    * *触发动作:* 当发现此事件时，系统直接对新建的节点执行 `evaluate_and_resolve_node`。
2.  **`2_evaluate_and_resolve_node`**:
    * *触发动作:* * 若节点判定为【已解决】：执行 `update_parent_node`。
        * 若节点判定为【未解决】：从其子问题列表中提取**优先级最高**且未解决的子问题，对该子问题执行 `create_and_reasoning_node`。
3.  **`3_update_parent_node`**:
    * *触发动作:* 子节点将答案向上传递后，系统立刻对 `parent_node` 触发 `evaluate_and_resolve_node` 进行重新评估。

### 3.2 推理工作引擎: `agent_workers.py`
包含三个处理节点生命周期的核心函数：
* `create_and_reasoning_node`: 初始化节点（问题、动机），并调用 LLM 进行节点内的初始逻辑推理。
* `evaluate_and_resolve_node`: 判断当前节点是否满足闭合条件（如：概率分布足够集中，或无剩余待解决子问题）。
* `update_parent_node`: 接收子节点的返回结果，并更新父节点的上下文和结论。

### 3.3 图数据库智能体: `data_copilot`
系统配备了直接与底层图数据库交互的接口组件。通过调用 `data_copilot` 中的函数，LLM 可以动态生成代码来获取图中的具体特征或数据流。

## 4. 🔴 极其重要的 AI 编码原则与避坑指南 (Rules & Guardrails)

在修改代码或设计 Prompt 时，**必须严格遵守**以下原则：

### Rule 1: `data_copilot` 的短路拦截 (Bypass Logic)
在 `create_and_reasoning_node` 中展开 LLM 分析之前，**必须**先进行一步评估：当前问题能否直接用 `data_copilot` 解决？
* **如果能：** 直接调用 `data_copilot` 获取答案。将 `Hypothesis` 设为该答案，在 `Reasoning_Log` 中打上标志性说明（说明由 Copilot 解决），然后**直接返回，绝对不参与后续复杂的 LLM 树形推理**。

### Rule 2: 子问题的“绝对独立性”
LLM Agent 在拆解子问题时极易产生“上下文陷阱”（例如生成类似 *"获取父节点查询结果中的三笔交易"* 这种问题）。
* **系统限制：** 当前程序**没有**提供获取其它节点信息的接口。子问题绝对无法知道父节点或兄弟节点的内容。
* **设计要求：** 任何与 LLM 交互的 Prompt 设计或提示词优化词典（Dictionary）中，都必须强行规范：**子问题必须是完全独立的上下文，必须自带完整的执行参数，绝对不能包含“依赖上下文”或“引用其它节点”的表述**，以防止分支结构进入死循环叠加。

### 其它补充
main_controller中对几个函数的调度管线如下：

- 检测到事件名称为1_create_and_reasoning_node时，对该新建节点执行evaluate_and_resolve_node。
- 检测到事件名称为2_evaluate_and_resolve_node时，若事件类型为已解决，则执行update_parent_node；若事件类型为未解决，则找到其未解决子问题中优先级最高的那个，对它执行create_and_reasoning_node。
- 检测到事件名称为3_update_parent_node时，对parent_node执行evaluate_and_resolve_node。

从而实现了树形推理问题的效果。