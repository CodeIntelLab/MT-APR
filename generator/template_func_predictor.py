import os
import logging
import pandas as pd
from tqdm import tqdm
from datetime import datetime
import json
import re

from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat


# =========================
# log
# =========================
def write_log(log_path, slug, prompt, response):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write(f"SLUG: {slug}\n")
        f.write(f"TIME: {datetime.now()}\n")
        f.write("\n=== PROMPT ===\n")
        f.write(prompt + "\n")
        f.write("\n=== RESPONSE ===\n")
        f.write(str(response) + "\n")


# =========================
# 提取 top-k（只解析 JSON + fallback regex）
# =========================
def extract_templates(response, k=9):

    if isinstance(response, tuple):
        text = response[0]
    else:
        text = str(response)

    # 1) 尝试 JSON
    try:
        match = re.search(r'\{.*"predicted_templates".*?\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            templates = data.get("predicted_templates", [])
            return templates[:k]
    except:
        pass

    # 2) fallback regex
    matches = re.findall(r'"([A-Za-z0-9_ ]+?)"', text)
    return matches[:k]


# =========================
# 主流程
# =========================
def predict_func_template(args):

    print("🚀 START CLEAN PIPELINE")

    # -------------------------
    # load data
    # -------------------------
    data = pd.read_csv(args.data_path)
    msg = pd.read_csv(args.msg_path)

    print("DATA SIZE:", len(data))

    # -------------------------
    # model
    # -------------------------
    if args.chat_mode == "local":
        debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        debugger = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

    # -------------------------
    # output dir（保持一致）
    # -------------------------
    output_dir = "result/AAAbuchongshiyan"
    os.makedirs(output_dir, exist_ok=True)

    result_path = os.path.join(output_dir, "topk_templates.csv")
    log_path = os.path.join(output_dir, "run.log")

    # -------------------------
    # 固定 top-9 列
    # -------------------------
    K = 9
    columns = ["slug"] + [f"template{i+1}" for i in range(K)]
    df_results = pd.DataFrame(columns=columns)

    # -------------------------
    # loop
    # -------------------------
    for i, row in tqdm(data.iterrows(), total=len(data)):

        slug = row["slug"]
        buggy_code = str(row.get("buggy_code", ""))

        # 获取错误信息和失败测试
        error_info = msg[msg["slug"] == slug]["exception_info"].values
        failed_test = msg[msg["slug"] == slug]["test_method"].values

        error_info = error_info[0] if len(error_info) > 0 else ""
        failed_test = failed_test[0] if len(failed_test) > 0 else ""

        # =========================
        # prompt（完全对齐第一个文件）
        # =========================
        query = f"""
你是一名自动程序修复专家。
现在你需要根据给定信息判断最可能的修复模板类型。

### Buggy function:
{buggy_code}

### Error message from JUnit test:
{error_info}

### Failed JUnit test:
{failed_test}

【可选修复模板列表】
1.ClassCastChecker
2.RangeChecker
3.NullPointerChecker
4.StatementInserter
5.ConditionalExpressionMutator
6.DataTypeReplacer
7.LiteralExpressionMutator
8.MethodInvocationMutator
9.CNIdiomNoSuperCall
10.ICASTIdivCastToDouble
11.OperatorMutator
12.ReturnStatementMutator
13.VariableReplacer
14.StatementMover
15.StatementRemover
16.NPEqualsShouldHandleNullArgument
17.Other Template

【任务要求】
1. 对以上17个模板分别进行相关性评分（0~1之间）
2. 按评分从高到低排序所有模板
3. 选择最相关的前9个模板作为最终结果
4. 必须保证输出顺序即为相关性排序（最相关在前）
5. 不要输出评分，只输出模板名称
6. 即使不确定，也必须输出9个模板

【输出格式要求（严格）】
只返回 JSON：

{{
  "predicted_templates": [
    "template1",
    "template2",
    "template3",
    "template4",
    "template5",
    "template6",
    "template7",
    "template8",
    "template9"
  ]
}}
"""

        prompt = [{"role": "user", "content": query}]

        try:
            # 调用模型
            response = debugger.chat(prompt, i, temperature=args.temperature)

            # 写日志
            write_log(log_path, slug, query, response)

            # extract top-9
            topk = extract_templates(response, k=K)

            # 写入 CSV
            row_data = {"slug": slug}
            for j in range(K):
                row_data[f"template{j+1}"] = topk[j] if j < len(topk) else ""
            df_results.loc[len(df_results)] = row_data

            df_results.to_csv(result_path, index=False)

        except Exception as e:
            logging.error(f"{slug} error: {str(e)}")
            continue

    print("✅ FINISHED")
    print("RESULT:", result_path)
    print("LOG:", log_path)