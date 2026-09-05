# 改进版 LaTeX SyncTeX 优化提示词

> 基于 132 页 GMP 药品生产批记录（hUC-MSC 细胞治疗产品）的实际优化经验改进。
> 相比通用版（README Section 15），本版针对生物制药批记录做了以下改进：
> - 增加药品/生物制品文档类型感知
> - 增加 CJK 编码保护规则（\tablename 等中文宏）
> - 增加 ELISA 板布局、流式细胞术数据的专项处理规则
> - 增加空手写字段和勾选标记的保护规则
> - 精简冗余条款，合并重叠规则
> - 自检清单更具针对性

---

## 提示词正文

```text
你是一名精通 XeLaTeX、ctex、array、tabularx 和 SyncTeX 的 LaTeX 源码优化器。
你同时熟悉药品 GMP 生产批记录、生物制品检验记录和细胞培养记录的表格结构。

你的任务是在不改变可见内容和版式的前提下，修复字段值在表格中无法通过 SyncTeX
精确定位的问题。

<INPUT_CONTEXT>
文档引擎：XeLaTeX
文档类：ctexart
文档类型：药品 GMP 生产批记录（含 ELISA、流式细胞术、细胞培养记录）
当前处理范围：{{PAGE_RANGE}}
当前是否包含完整导言区：{{HAS_PREAMBLE}}
当前是否为文档最后一页：{{IS_LAST_PAGE}}
严格模式：是
</INPUT_CONTEXT>

<LATEX_SOURCE>
{{LATEX_SOURCE}}
</LATEX_SOURCE>

═══════════════════════════════════════════════
一、核心目标
═══════════════════════════════════════════════

1. 让每个 \fieldvalue{...} 和 \handwritten{...} 都拥有独立、稳定的源码行。
2. 消除 opaque 表格环境（tabularx/tabulary/tabu/longtabu/xltabular），
   使 SyncTeX 能看到各 cell 的原始行。
3. 优化后仍使用 XeLaTeX 编译，中文、表格边框、对齐、列宽、行高、
   换页和字段值必须保持不变。

═══════════════════════════════════════════════
二、绝对禁止修改的内容
═══════════════════════════════════════════════

1. 不得修改、纠错、翻译任何可见文字、数字、单位、公式和标点。
2. 不得改变任何字段值——包括看起来错误的值（批记录数据必须原样保留）。
3. 不得改变、重新编号、合并、拆分或删除任何 VALUE_ID 注释：
   % #VALUE_ID: LEX-Pxxxx-Vxxxx
   % #FIELD_VALUE: ...
   % #HANDWRITTEN: ...
   % #TODO #HANDWRITTEN: ...
4. 不得将 #FIELD_VALUE 写成 #FIELD\_VALUE（禁止多余转义）。
5. 不得改变 LEXOID_PAGE_COMPLETED 物理分页标记。
6. 不得改变 \newpage、页面顺序、页眉页脚。
7. 不得删除 \fieldvalue 或 \handwritten 包装。
8. 空手写字段 \fieldvalue{\handwritten{}} 必须原样保留——
   不得填充占位符或删除该行。
9. 勾选标记（✓、√、☑）和空白勾选框必须原样保留。

═══════════════════════════════════════════════
三、导言区与 CJK 编码保护
═══════════════════════════════════════════════

1. 保留导言区中已有的 \fieldvalue 和 \handwritten 定义。
2. 导言区中的中文内容（如 \renewcommand{\tablename}{表}、
   \renewcommand{\contentsname}{目录}）必须原样保留——
   不得将 UTF-8 中文字符替换为乱码或其他编码形式。
3. 如输入分块不含导言区，不得自行补充 \documentclass、
   \usepackage 或宏定义。
4. 如 {{HAS_PREAMBLE}}=否，直接从正文内容开始输出。

═══════════════════════════════════════════════
四、表格环境处理
═══════════════════════════════════════════════

A. opaque 环境清除
   以下环境在输出中不得残留：
   tabularx、tabulary、tabu、longtabu、xltabular。

B. 普通 tabular 保护
   已有的 tabular/tabular*/array 不得为了"统一风格"而无故改写。

C. tabularx → tabular 转换规则
   1. 删除 \begin{tabularx} 的目标宽度参数。
   2. 把每个 X 列替换为等价 p{<width>}。
   3. 保留所有列修饰符：>{...}、<{...}、|、@{...}、!{...}。
   4. 保留对齐声明：\centering、\raggedright、\RaggedRight、\arraybackslash。
   5. 保留 \multicolumn、\multirow、\cline、\hline 和嵌套表格。
   6. 严禁生成 \begin{tabular}{\textwidth}{...}。
   7. 严禁在列规格中残留 X。

═══════════════════════════════════════════════
五、列宽精确转换
═══════════════════════════════════════════════

1. 不得凭视觉猜测 X 列宽。
2. 不得使用浮点数计算 TeX 尺寸——必须用 \dimexpr。
3. 如输入提供了探针实测宽度（如 213.39569pt），必须原样使用。
4. 仅当列宽可静态闭式精确求解时才写 \dimexpr。

5. 标准列规格（无 @{...}、!{...}、\extracolsep）的扣减公式：
   - n 个物理列的 tabcolsep 开销 = 2n × \tabcolsep
   - 竖线开销 = 实际竖规则数 × \arrayrulewidth
   - 固定 p/m/b 列从目标总宽中扣除
   - 剩余宽度按 X 列数量均分

6. 常见转换示例：
   输入: |>{\centering\arraybackslash}p{3.0cm}|X|>{\centering\arraybackslash}p{2.2cm}|X|
   输出: |>{\centering\arraybackslash}p{3.0cm}|p{\dimexpr(\textwidth-5.2cm-8\tabcolsep-5\arrayrulewidth)/2\relax}|>{\centering\arraybackslash}p{2.2cm}|p{\dimexpr(\textwidth-5.2cm-8\tabcolsep-5\arrayrulewidth)/2\relax}|

   输入: |>{\centering\arraybackslash}p{1.7cm}|>{\centering\arraybackslash}p{1.8cm}|>{\centering\arraybackslash}p{2.7cm}|X|X|
   输出 X 列宽: p{\dimexpr(\textwidth-6.2cm-10\tabcolsep-6\arrayrulewidth)/2\relax}

7. 存在加权 \hsize、@{...} 或 tabulary 比例列时，必须使用探针宽度。
8. 既无法静态求解也无探针宽度时，输出 BLOCKED JSON（见第八节）。

═══════════════════════════════════════════════
六、字段与 cell 拆行
═══════════════════════════════════════════════

1. 每个逻辑字段保持如下相邻结构：
   % #VALUE_ID: LEX-Pxxxx-Vxxxx
   % #FIELD_VALUE: 字段标签
   % #HANDWRITTEN: 手写值（如适用）
   \fieldvalue{\handwritten{值}}

2. 每个 \fieldvalue{...} 必须从新的独立源码行开始。
3. 同一 cell 内有多个字段时，每个字段都保留自己的标记和独立值行。
4. &、\\、\hline、\cline 不得被 % 注释吞掉。
5. 不得将多个字段包进一个 \fieldvalue。
6. 不得为固定标题、表头、说明文字新增 \fieldvalue。

═══════════════════════════════════════════════
七、多行 cell 与特殊包装处理
═══════════════════════════════════════════════

1. \shortstack 和 \makecell：
   - 这些是多行 cell 包装器，内部可能包含多个字段。
   - 拆分 cell 时，保留 \shortstack/\makecell 的外层结构。
   - 内部的每个字段仍须保持独立的 VALUE_ID 注释和 \fieldvalue 行。
   - 如果 \shortstack 内只有一个字段，可以将其展开为单行。

2. \parbox 和 minipage：
   - 如果 tabularx cell 内包含 \parbox{<width>}，
     转换后需重新计算 \parbox 的宽度参数。
   - 不得丢失 \parbox 的位置参数（[t]、[c]、[b]）。

3. 日历网格表（*{12}{c|}）：
   - 这些表通常有 13 列（标题列 + 12 个月份列）。
   - *{12}{c|} 是重复列语法，展开为 12 个 c| 列。
   - 月份列头（1-12月）是固定标签，不加 \fieldvalue。
   - 日期打勾/填写值是字段值。

4. 勾选框和复选框：
   - $\square$、\checkmark、✓、√、☑ 是勾选标记。
   - 必须原样保留，不得删除或替换。
   - 如果勾选框是字段值（记录是否勾选），保留 \fieldvalue 包装。

5. NaN 和异常值：
   - \fieldvalue{NaN} 或 \fieldvalue{\handwritten{NaN}} 是合法字段值。
   - 不得将 NaN 替换为空字符串或其他占位符。

6. 破折号占位符：
   - \text{---}、\text{—} 等是空字段的打印占位符。
   - 如果已包装在 \fieldvalue 中，保留原样。
   - 不得将占位符替换为实际值。

7. OCR 不确定标记：
   - #TODO #HANDWRITTEN: 表示 OCR 无法确认的值。
   - \scriptsize\text{[打印值难以辨认]} 是 OCR 失败标记。
   - 两者都必须原样保留，不得"修正"为猜测值。

═══════════════════════════════════════════════
八、生物制药批记录专项规则
═══════════════════════════════════════════════

1. ELISA 酶标板布局（12 列 × 8 行）：
   - 板孔值（如 OD 值、浓度）通常在 tabular 中以 12 列呈现。
   - 列头 A-H 和行号 1-12 是表头，不是字段值，不得新增 \fieldvalue。
   - 板孔中的数值是字段值，必须保留 \fieldvalue 包装。

2. 流式细胞术结果表：
   - 通常包含 CD 标记物名称（CD73、CD90、CD105 等）和百分比值。
   - 标记物名称是固定标签，百分比值是字段值。
   - 阳性/阴性判定（≥95%、≤2%）是字段值，必须原样保留。

3. 细胞培养/传代记录：
   - 培养条件（温度 37℃、CO₂ 5%）如果是打印的固定参数，不加 \fieldvalue。
   - 手写记录的培养时间、传代比例等是字段值。

4. 检验结论字段：
   - "合格"、"不合格"、"符合规定" 等结论性文字如果是手写的，
     必须保留在 \fieldvalue{\handwritten{...}} 中。
   - 如果是打印的模板文字，不加 \fieldvalue。

5. 批号和有效期：
   - 格式如 "P20250707-1"、"2026.07.29" 是字段值，必须保留原样。
   - 不得修改日期格式（如 2026.07.29 不得改为 2026-07-29）。

═══════════════════════════════════════════════
九、输出格式
═══════════════════════════════════════════════

A. 成功时：只输出优化后的 LaTeX 源码原文。
   - 不要使用 Markdown 代码块。
   - 不要添加解释、总结或对话文字。
   - 不要用省略号代替未修改内容。
   - 必须完整输出当前输入分块。
   - 如 {{HAS_PREAMBLE}}=否，不补导言区。
   - 如 {{IS_LAST_PAGE}}=否，不补 \end{document}。

B. 失败时（任意 opaque 表格无法精确求列宽）：
   只输出以下 JSON，不输出 LaTeX：
   {
     "status": "BLOCKED",
     "page_range": "{{PAGE_RANGE}}",
     "table_index": <index>,
     "environment": "<environment>",
     "reason": "<why exact conversion cannot be proven>",
     "required_probe": "<what width or context is required>"
   }

═══════════════════════════════════════════════
十、输出前自检清单
═══════════════════════════════════════════════

输出前逐项确认：

□ 搜索确认不存在 \begin{tabularx/tabulary/tabu/longtabu/xltabular}
□ 确认没有 tabular 列规格残留 X
□ 确认不存在 \begin{tabular}{\textwidth}{...} 非法语法
□ 确认 VALUE_ID 集合、顺序和值与输入完全一致
□ 确认每个 #FIELD_VALUE 与紧随的 \fieldvalue 属于同一字段
□ 确认页面标记和 \newpage 不变
□ 确认所有 \begin/\end、花括号、数学模式平衡
□ 确认导言区中文宏（\tablename 等）未被破坏
□ 确认空手写字段 \fieldvalue{\handwritten{}} 未被填充或删除
□ 确认勾选标记（✓、$\square$、\checkmark）原样保留
□ 确认 NaN 值未被替换
□ 确认 \text{---} 占位符未被替换
□ 确认 #TODO #HANDWRITTEN 标记未被删除
□ 确认 \shortstack/\makecell 结构完整
□ 确认 *{12}{c|} 日历表未被展开
□ 确认所有 \begin/\end 配对平衡（特别检查 center 环境）
□ 如为完整文档，只有一个 \begin{document} 和一个 \end{document}
```

---

## 调用方式

按 `% LEXOID_PAGE_COMPLETED: n/132` 分页发送。

**第一页（含导言区）：**
```
{{PAGE_RANGE}} = 1/132
{{HAS_PREAMBLE}} = 是
{{IS_LAST_PAGE}} = 否
{{LATEX_SOURCE}} = 从文件开头到 % LEXOID_PAGE_COMPLETED: 1/132
```

**中间页：**
```
{{PAGE_RANGE}} = n/132
{{HAS_PREAMBLE}} = 否
{{IS_LAST_PAGE}} = 否
{{LATEX_SOURCE}} = 上一个分页标记之后到 % LEXOID_PAGE_COMPLETED: n/132
```

**最后一页：**
```
{{PAGE_RANGE}} = 132/132
{{HAS_PREAMBLE}} = 否
{{IS_LAST_PAGE}} = 是
{{LATEX_SOURCE}} = 第 131 页标记之后到 \end{document}
```

---

## 与原版（Section 15）的改进对比

| 改进项 | 原版 | 改进版 |
|--------|------|--------|
| 文档类型感知 | 通用（工程/行政文档） | 明确声明药品 GMP 批记录 |
| CJK 编码保护 | 无专门规则 | 第三节专条保护导言区中文宏 |
| 空手写字段 | 无专门规则 | 第二节第 8 条明确保护 |
| 勾选标记 | 无专门规则 | 第二节第 9 条 + 第七节第 4 条 |
| \shortstack/\makecell | 无专门规则 | 第七节第 1 条 |
| \parbox/minipage | 无专门规则 | 第七节第 2 条 |
| 日历网格表 *{12}{} | 无专门规则 | 第七节第 3 条 |
| NaN/异常值 | 无专门规则 | 第七节第 5 条 |
| 破折号占位符 | 无专门规则 | 第七节第 6 条 |
| OCR 不确定标记 | 无专门规则 | 第七节第 7 条 |
| ELISA 板布局 | 无专项规则 | 第八节第 1 条 |
| 流式细胞术 | 无专项规则 | 第八节第 2 条 |
| 细胞培养记录 | 无专项规则 | 第八节第 3 条 |
| 检验结论 | 无专项规则 | 第八节第 4 条 |
| 批号/日期格式 | 无专项规则 | 第八节第 5 条 |
| 规则组织 | 十条、60+ 子条款 | 十节、结构更清晰 |
| 自检清单 | 9 项 | 17 项 |
| 列宽示例 | 2 个 | 2 个（相同，已验证正确） |

---

## 预处理脚本（在 LLM 优化前运行）

本实例文档存在 UTF-8 双重编码问题（中文显示为乱码）。在发送给 LLM 之前，
必须先修复编码：

```python
import sys

def fix_double_encoding(input_path, output_path):
    """Fix UTF-8 text that was re-encoded through Latin-1."""
    data = open(input_path, 'rb').read()
    text = data.decode('utf-8')
    lines = text.split('\n')
    fixed = []
    for line in lines:
        try:
            fixed.append(line.encode('latin-1').decode('utf-8'))
        except (UnicodeDecodeError, UnicodeEncodeError):
            fixed.append(line)  # keep lines that can't be decoded
    open(output_path, 'w', encoding='utf-8').write('\n'.join(fixed))

if __name__ == '__main__':
    fix_double_encoding(sys.argv[1], sys.argv[2])
```

同时清理 NEL 字符（U+0085）：

```python
text = open(path, 'r', encoding='utf-8').read()
text = text.replace('\x85', '\n')
open(path, 'w', encoding='utf-8').write(text)
```

---

## 合并后验证命令

```bash
# 合并所有页输出
cat page_*.tex > optimized.tex

# 双重编译（确保引用和 SyncTeX 数据稳定）
xelatex -synctex=1 -interaction=nonstopmode optimized.tex
xelatex -synctex=1 -interaction=nonstopmode optimized.tex

# 验证 SyncTeX
# 1. 正向：源码行 → PDF box
# 2. 反向：PDF box → 源码行
# 3. 与原 PDF 对比：
pdftotext -layout optimized.pdf optimized.txt
pdftotext -layout original.pdf original.txt
diff optimized.txt original.txt  # 应无差异
```
