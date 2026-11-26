---
name: veilresponse-project
description: veilresponse 布尔标志间接泄露审计/修复工具的任务要点与设计决策
metadata:
  type: project
---

任务（2026-11-27，空仓库起步，工作目录 D:\\Zhongqiang-20261127-hvklggal\\zq16980-20261127-replay01-r1-work）：实现 veilresponse，Python 3.12 标准库，Windows。

核心约束：
- 输入纯合成 JSON：≤24 布尔字段、legal 合法约束、接收方可见字段/派生事实、首条命中的状态码规则+默认码。
- 审计：对每个接收方，判断公开字段+获准派生事实相同的两条合法记录是否必然同码；差异给字段序字典序最小记录对（对内也排序）；支持合法记录集为空；检查默认分支、共享子表达式、无可行赋值规则。
- 修复：只能把候选码归并到一个通用码，每码一次性成本，默认码可选纳入；求最小成本集合，同成本按排序码列表决胜；不可修复时给全归并后仍冲突的证据。
- 禁止枚举 2^24 记录或二次方记录对；审计/修复都必须带原始 legal 约束。
- 交付 audit CASE / repair CASE 两个 JSON CLI、README、合成样例、unittest、≤8 字段独立穷举参照。

关键设计：Tseitin CNF + 自研 DPLL（stdlib 无 SAT 库）；双副本乘积构造（每条 legal 都复核）；首条命中语义 hit_i = r_i & ~r_0..~r_{i-1}；严格字典序 x<y 用 Tseitin 链编码，再逐变量强制求字典序最小见证；修复集合在单通用码语义下等于所有冲突码对端点的并集（唯一最小）。

实现状态（2026-11-27 完成，33 个 unittest 全过）：包 veilresponse/（expr/sat/tseitin/model/audit/repair/exhaustive/fuzzgen/cli），根包装 audit_case.py、repair_case.py，6 个样例，README。关键易错点（已修）：① AND 门 Tseitin 必须每个输入一条 [-z,input] 子句，不能合并成 [-z,*inputs]；② crossing 门要建全部有序对 (i,j)，因为严格字典序只约束字段不约束 outcome 索引；③ 同状态码的不同 outcome 不算泄露，审计按码对去重并保留字典序最小见证；④ SAT 求解器子句状态在每次赋值时按全部字面量重算、回溯从 trail 重建，增量计数不可靠；⑤ 测试在 `python -I` 下需各自内联 sys.path 插入（discover 按裸名导入，tests 包不可导入）。24 字段端到端约 3.6s。
