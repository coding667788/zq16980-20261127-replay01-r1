# veilresponse

内部审阅工具的**布尔标志间接泄露审计器**与**状态码归并修复规划器**。

给定一组布尔标志位、表达“合法记录”的布尔约束、按接收方不同而变化的字段可见
范围、明确允许披露的派生事实，以及一套“首条命中即返回”的状态码规则，
veilresponse 回答两个问题：

1. **审计（audit）**：对每个接收方，任意两条在“可见字段 + 获准派生事实”上完全
   相同的合法记录，返回的状态码是否一定相同？若不同，给出字段序下**字典序最小**
   的记录对（记录对内部也按字典序排列）。
2. **修复（repair）**：在“只能把指定返回码归并到一个通用码、每个码有一次性成
   本、默认码可选纳入”的约束下，求覆盖所有接收方的**最小成本归并集合**；若无论
   如何归并都仍有冲突，给出全部候选归并后仍冲突的证据。

全程只使用 Python 3.12 标准库，在 Windows 上运行。

---

## 1. 输入 JSON 格式

输入是纯合成 JSON，字段最多 24 个布尔量。

```json
{
  "fields": ["a", "b", "c"],
  "derived_facts": { "either": {"or": ["a", "b"]} },
  "legal": {"and": ["c", {"imp": ["a", "b"]}]},
  "rules": [
    {"when": "a", "code": 201},
    {"when": "either", "code": 202}
  ],
  "default_code": 0,
  "receivers": [
    {"name": "ops", "visible_fields": ["c"], "derived_facts": []}
  ],
  "repair": {
    "merge_costs": {"0": 1, "201": 3, "202": 4},
    "default_code_optional": true
  }
}
```

### 布尔表达式语法

表达式是递归 JSON 值：

| 形态 | 含义 |
| --- | --- |
| `true` / `false` | 布尔常量 |
| `"name"` | 字段名或已声明的派生事实名 |
| `{"not": e}` | 否定 |
| `{"and": [e, ...]}` | 合取（空数组为 `true`） |
| `{"or": [e, ...]}` | 析取（空数组为 `false`） |
| `{"xor": [e1, e2]}` | 异或 |
| `{"imp": [e1, e2]}` | 蕴含 `e1 -> e2` |
| `{"iff": [e1, e2]}` | 逻辑等价 |

派生事实可引用字段与其它已声明的派生事实（按依赖拓扑解析，环会被拒绝）。
表达式节点是**驻留（hash-consed）**的：语法相同的子表达式是同一个对象，因此
被多条规则共享的子表达式在 SAT 编码时只生成一套门。

### 顶层字段

- `fields`：非空、唯一的布尔字段名列表，长度 ≤ 24。
- `derived_facts`：派生事实名到表达式的映射，可为空。
- `legal`：一条布尔表达式，定义合法记录集合；**允许其不可满足（合法集合为空）**。
- `rules`：有序规则列表，每条 `{"when": 表达式, "code": 状态码}`。自上而下
  依次求值，**第一条为真的规则决定返回码**；全部不命中时返回 `default_code`。
- `default_code`：统一默认状态码（任意 JSON 标量/值均可）。
- `receivers`：接收方列表，各自声明 `visible_fields` 与允许披露的
  `derived_facts`。
- `repair.merge_costs`：可归并码到一次性成本（非负整数）的映射。**键是状态码的
  JSON 文本**（如 `"201"`、`"\"HIT\""`）。
- `repair.default_code_optional`：为 `true` 时默认码也成为可归并候选。

---

## 2. 命令行用法

提供两个 JSON CLI，建议在隔离模式下运行（防止工作目录中的同名模块被导入）：

```powershell
python -I audit_case.py  samples\simple_leak.json
python -I repair_case.py samples\unrepairable.json
```

也可用模块入口：

```powershell
python -I -m veilresponse audit  samples\simple_leak.json
python -I -m veilresponse repair samples\unrepairable.json
```

### 审计输出

```json
{
  "status": "leak_detected",
  "legal_records_feasible": true,
  "rule_diagnostics": [
    {
      "rule_index": 0,
      "code": 201,
      "has_feasible_assignment": true,
      "shadowed_by_earlier_rule": false,
      "can_fire": true
    }
  ],
  "receivers": [
    {
      "name": "ops",
      "compliant": false,
      "leaks": [
        {
          "codes": [0, 202],
          "record_pair": [
            {"a": false, "b": false, "c": true},
            {"a": false, "b": true, "c": true}
          ]
        }
      ]
    }
  ]
}
```

- `rule_diagnostics` 覆盖题目要求的三类检查：
  - `has_feasible_assignment`：规则表达式在 `legal` 约束下是否存在可行赋值
    （**无可行赋值的规则**）；
  - `shadowed_by_earlier_rule`：规则是否因更早的规则总先命中而永远无法触发
    （**首条命中语义下的死规则**）；
  - `can_fire`：两者综合，规则是否真的可能成为返回结果。
- 默认分支作为一个额外 outcome 参与全部检查（**默认分支泄露**会被报告）。
- 当 `legal_records_feasible` 为 `false`（合法记录集合为空）时，不存在任何两条
  记录，所有接收方**空洞地合规**，审计返回 `compliant`。

### 修复输出

可修复时：

```json
{
  "status": "repairable",
  "merge_codes": [0, 202],
  "total_cost": 5,
  "generic_code": "GENERIC",
  "conflicts": [ {"codes": [0, 202], "witnesses": [ ... ]} ]
}
```

不可修复时：

```json
{
  "status": "unrepairable",
  "generic_code": "GENERIC",
  "blocking_conflicts": [
    {"codes": [200, 403], "non_candidate_codes": [200]}
  ],
  "post_merge_evidence": [
    {
      "receiver": "guest",
      "codes": [200, 403],
      "effective_codes": [200, "GENERIC"],
      "record_pair": [ ... ]
    }
  ],
  "conflicts": [ ... ]
}
```

`post_merge_evidence` 中每条见证都在**原始 `legal` 约束**下重新求解得到，并展示
归并后的有效码类（`GENERIC` 或保留原码），证明即便把所有候选码都归并，这两条
不可区分的合法记录仍落到不同的有效码上。

---

## 3. 算法：为什么不需要枚举 2^24 条记录

核心是一个**双副本乘积 SAT 构造**。对某个接收方，构造两条记录 `x`、`y` 的联合
公式：

1. 每个字段、每道门都编码两份（副本 `x` / 副本 `y`）；
2. 原始 `legal` 约束在**两个副本中各断言一次**——审计与修复的每一次求解都因此
   复核了原始合法约束；
3. 接收方可见字段、以及其获准可见的派生事实，在两副本间约束为相等；
4. 用 Tseitin 链编码严格字段序 `x < y`，消除 `(x,y)` 与 `(y,x)` 的对称重复，并
   排除两条完全相同的记录；
5. 编码首条命中语义：
   `hit_i = rule_i ∧ ¬rule_0 ∧ … ∧ ¬rule_{i-1}`，默认分支
   `hit_m = ¬rule_0 ∧ … ∧ ¬rule_{m-1}`；这些 hit 互斥且穷尽；
6. 为每个有序 outcome 对构造 crossing 门
   `z_{i,j} ⇔ hit_i(x) ∧ hit_j(y)`。

于是“两条不可区分的合法记录是否会落到不同状态码”被归约为一次 SAT 可满足性查询
（令某个 crossing 为真）。**全程不枚举任何记录，更不会构造二次方个记录对。**

### 字典序最小见证

对每个泄露码对，先确认 crossing 可满足，再按字段序、先 `x` 后 `y` 逐位强制：每
一位在仍可满足时优先压成 `false`，否则固定 `true`。每个接收方的查询次数为
`O(字段数)` 次 SAT 求解，得到的就是字典序最小的记录对；严格 `x < y` 约束保证
记录对内部有序。

### SAT 求解

标准库没有 SAT 库，因此自带一个 DPLL 求解器（`veilresponse/sat.py`）：单位传播 +
基于出现次数的静态分支启发式 + 时间序回溯，子句状态在每次赋值时按其全部字面量
重新分类，回溯时从保留的 trail 重建，避免增量计数的不一致。Tseitin 编码把任意
布尔表达式变成 CNF，规模关于表达式大小线性。

### 修复的最优性

在“所有被归并的码都映射到**同一个**通用码”的语义下，每个冲突码对的两个端点都
必须被归并，否则该对仍可区分。因此可行的归并集合必须包含**所有冲突码对端点的并
集** `U`，而 `U` 本身即可消除全部冲突，故：

- 若 `U` 中每个码都是归并候选，`U` 是唯一的最小（也即最小成本）归并集合；
- 若 `U` 含非候选码，则不存在可行修复，返回全部候选归并后的残余冲突证据。

输出的码列表统一按确定性顺序排序；在一般化的多解情形下会以“排序后的码列表”作
为同成本决胜键。

---

## 4. 独立穷举参照（≤ 8 字段）

`veilresponse/exhaustive.py` 是与 SAT 路径**完全独立**的参照实现：当字段数 ≤ 8
时，直接枚举至多 256 条赋值，用树遍历求值器过滤合法记录，再两两配对比较。它不复
用任何乘积构造代码，因此在测试中充当真正的预言机。

`tests/test_exhaustive_oracle.py` 生成上百个随机合成实例，逐字段比较 SAT 审计/修
复与穷举参照的状态、合规结论、每个码对的字典序最小见证，以及修复集合与成本；
另有一个 24 字段实例的规模化测试，断言在不枚举记录的前提下快速完成。

---

## 5. 测试

```powershell
python -I -m unittest discover -s tests -v
```

覆盖：表达式解析/常量折叠/共享子表达式驻留、SAT 求解器（单位冲突、重复查询重置、
鸽子洞 UNSAT、各门真值表、严格字典序链）、各合成样例审计、默认分支与无可行赋值
规则、空合法集合、最小成本修复、不可修复证据、CLI，以及对独立穷举参照的随机
fuzz 对照和 24 字段规模化测试。

## 目录结构

```
veilresponse/
  expr.py        # 布尔表达式 AST、驻留、树求值
  sat.py         # 自研 DPLL SAT 求解器
  tseitin.py     # AST -> CNF 的 Tseitin 编码与严格字典序链
  model.py       # 实例加载/校验、首条命中规则引擎
  audit.py       # 双副本乘积构造与字典序最小见证
  repair.py      # 最小成本归并与不可修复证据
  exhaustive.py  # ≤8 字段独立穷举参照
  fuzzgen.py     # 随机合成实例生成
  cli.py         # audit / repair JSON 命令行
audit_case.py    # audit CLI 包装
repair_case.py   # repair CLI 包装
samples/         # 合成样例
tests/           # unittest
```
