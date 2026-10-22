import os
import logging
import pandas as pd
from tqdm import tqdm
from datetime import datetime
from prompt.defects4j import *
from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat
import json
import re

# 用于预测模板
def extract_templates(response: str):
    """
    从模型输出中提取前3个模板。
    首选JSON解析，次选正则兜底。
    """
    try:
        data = json.loads(response)
        if "predicted_templates" in data:
            return data["predicted_templates"][:3]
    except json.JSONDecodeError:
        pass

    matches = re.findall(r'"([A-Za-z ]+?)"', response)
    if matches:
        return matches[:3]

    logging.warning("无法从响应中提取模板，返回空列表")
    return []


def write_slug_log(slug: str, prompt: str, response: str, log_dir: str):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{slug}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"==== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ====\n")
        f.write("=== Prompt 输入 ===\n")
        f.write(prompt + "\n")
        f.write("=== 模型输出 ===\n")
        f.write(response + "\n\n")



def predict_func_template(args):
    logging.info("==== 开始模板预测任务 ====")

    # 读取数据
    data = pd.read_csv(args.data_path, sep=",", encoding="utf-8", engine="python")
    msg = pd.read_csv(args.msg_path, sep=",", encoding="utf-8", engine="python")
    #data["class_path"] = data["class_path"].str.replace(
    #    r"^defects4j/", "defects4j_buggy/", regex=True
    #)
    data = data.groupby("slug").filter(lambda x: len(x) == 1)

    # 初始化模型接口
    if args.chat_mode == 'local':
        debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        debugger = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

    # 输出 CSV 路径
    result_path = os.path.join("result/rwb", "template_rwb1.0_predict.csv")
    if os.path.exists(result_path):
        df_results = pd.read_csv(result_path)
    else:
        df_results = pd.DataFrame(
            columns=["slug", "template1", "template2", "template3"]
        )

    # 日志目录
    log_dir = os.path.join("log", "template")
    os.makedirs(log_dir, exist_ok=True)

    for i, row in tqdm(data.iterrows(), total=len(data)):
        slug = row["slug"]
        buggy_code = row["buggy_code"].strip()
        comment = row.get("comment", "")
        if not isinstance(comment, str):
            comment = "This function has no comment."

        error_info = msg[msg["slug"] == slug]["exception_info"].values
        failed_test = msg[msg["slug"] == slug]["test_method"].values
        error_info = error_info[0] if len(error_info) > 0 else "This function has no exception info."
        failed_test = failed_test[0] if len(failed_test) > 0 else "This function has no failed test."

        # 读取定位信息
        faulty_lines_info = load_faulty_lines(slug)

        # 构造 Prompt
        query = f"""你是一名自动程序修复专家。
现在你需要根据给定的错误代码、错误信息与模板列表，判断该错误最有可能对应哪些修复模板类型。

请仔细阅读以下信息：
### Buggy function:
{buggy_code}
### Buggy function comment:
{comment}
### Error message from JUnit test:
{error_info}
### Failed JUnit test:
{failed_test}

【可选修复模板列表】
1.ClassCastChecker：插入类型转换检查（在类型不匹配处添加类型转换）
2.RangeChecker：插入范围检查（添加边界条件判断）
3.NullPointerChecker：插入空指针检查（添加 `if (x != null)` 判断）
4.StatementInserter：根据可疑语句及其上下文，在适当位置插入新的语句或返回值
5.ConditionalExpressionMutator：修改整个条件表达式进行添加、删除或替换
6.DataTypeReplacer：修改数据类型（修正变量或返回类型）
7.LiteralExpressionMutator：修改字面量（改变常量值）
8.MethodInvocationMutator：修改方法调用（更换方法或参数）
9.CNIdiomNoSuperCall：修改对象创建语句（更换构造函数或类名）
10.ICASTIdivCastToDouble：修改整数除法操作，通过对被除数或除数进行浮点类型转换或改写表达式结构等方式
11.OperatorMutator：修改可疑的算术、关系、条件、位运算等操作符，尝试对它们进行替换或优先级调整
12.ReturnStatementMutator：修改返回语句（修正返回值逻辑）
13.VariableReplacer：修改变量引用（使用正确变量）
14.StatementMover：移动语句（调整语句执行顺序）
15.StatementRemover：删除错误语句
16.NPEqualsShouldHandleNullArgument：修改布尔比较表达式以处理空对象（修正空指针风险，例如加上 this == other 或 other != null 这种条件保护
17.Other Template：不参考模板（现有模板不适用）

【任务要求】
1.对上面17个模板进行相关性评分(相关性在0~1之间,评分越接近1越可能匹配该Buggy function)
2.只返回评分大于0.65的模板,评分越高越优先。最多不超过3个模板,模板数量不是必须满足的目标，仅作为上限限制。
3.Other Template 仅当所有模板评分均低于阈值时才允许输出。
4.输出格式必须遵守以下 JSON 结构predicted_templates 数组中仅包含满足评分阈值的模板名称，数组长度不固定，可为 0~3：
{{
  "predicted_templates": [
    "template_name"
  ]
}}
"""


        prompt = [{"role": "user", "content": query}]

        try:
            response = debugger.chat(prompt, i, temperature=args.temperature)
            write_slug_log(slug, query, response, log_dir)

            top_templates = extract_templates(response)

            df_results.loc[len(df_results)] = {
                "slug": slug,
                "template1": top_templates[0] if len(top_templates) > 0 else "",
                "template2": top_templates[1] if len(top_templates) > 1 else "",
                "template3": top_templates[2] if len(top_templates) > 2 else ""
            }

            df_results.to_csv(result_path, sep=",", encoding="utf-8", index=False)

        except Exception as e:
            logging.error(f"{slug} 模板推理过程中出现异常: {str(e)}")
            continue

    logging.info("==== 模板预测任务结束 ====")