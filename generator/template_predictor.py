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
#预测模板，但是是行级别定位
# ==========================
# 模板提取
# ==========================
def extract_templates(response):
    """
    从模型输出中提取前3个模板。
    支持模型返回 (text, info) 的情况。
    """
    # 如果 response 是二元组，取第一个元素
    if isinstance(response, tuple):
        response_text = response[0]
    else:
        response_text = response

    # 先完整打印响应，用于调试
    logging.debug(f"模型原始输出:\n{response_text}")

    # 尝试提取 JSON 块
    try:
        match = re.search(r'\{.*"predicted_templates".*?\}', response_text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            templates = data.get("predicted_templates", [])
            if templates:
                return templates[:3]
    except Exception as e:
        logging.warning(f"JSON 解析失败: {e}")

    # 正则兜底，匹配字母、数字、下划线
    matches = re.findall(r'"([A-Za-z0-9_ ]+?)"', response_text)
    if matches:
        return matches[:3]

    logging.warning("无法从响应中提取模板，返回空列表")
    return []

# ==========================
# 日志记录
# ==========================
def write_slug_log(slug: str, prompt: str, response, log_dir: str):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{slug}.log")

    # 如果 response 是二元组，取文本部分
    if isinstance(response, tuple):
        response_text = response[0]
    else:
        response_text = response

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"==== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ====\n")
        f.write("=== Prompt 输入 ===\n")
        f.write(prompt + "\n")
        f.write("=== 模型输出 ===\n")
        f.write(response_text + "\n\n")

# ==========================
# 读取定位信息
# ==========================
def load_faulty_lines(slug: str):
    """
    从 faulty_lines/{slug}.json 中读取定位信息
    """
    faulty_file = os.path.join(
        os.path.dirname(__file__),  # generator/
        "..",
        "faulty_lines",
        f"{slug}.json"
    )
    faulty_file = os.path.abspath(faulty_file)

    if not os.path.exists(faulty_file):
        return "No fault localization information is provided."

    try:
        with open(faulty_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"{slug} 定位信息读取失败: {str(e)}")
        return "Fault localization information exists but cannot be parsed."

# ==========================
# 模板预测主函数
# ==========================
def predict_template(args):
    logging.info("==== 开始模板预测任务 ====")

    # 读取数据
    data = pd.read_csv(args.data_path, sep=",", encoding="utf-8", engine="python")
    msg = pd.read_csv(args.msg_path, sep=",", encoding="utf-8", engine="python")
    data = data.groupby("slug").filter(lambda x: len(x) == 1)

    # 初始化模型接口
    if args.chat_mode == 'local':
        debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        debugger = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

    # 输出 CSV 路径
    result_path = os.path.join("result/RWB", "template_rwb1.0_predict.csv")
    if os.path.exists(result_path):
        df_results = pd.read_csv(result_path)
    else:
        df_results = pd.DataFrame(columns=["slug", "template1", "template2", "template3"])

    # 日志目录
    log_dir = os.path.join("log", "rwbtemplate")
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
现在你需要根据给定的错误信息、定位信息与模板列表，判断该错误最有可能对应哪些修复模板类型。

请仔细阅读以下信息：
### Buggy function:
{buggy_code}
### Fault Localization Information:
{faulty_lines_info}
### Buggy function comment:
{comment}
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
1.评分越高越可能匹配该Buggy function
2.只返回评分大于0.65的模板,最多不超过3个
3.Other Template 仅当所有模板评分均低于阈值时才允许输出
4.输出格式必须遵守 JSON 结构，predicted_templates 数组中仅包含满足评分阈值的模板名称
{{
  "predicted_templates": [
    "template_name"
  ]
}}
"""

        prompt = [{"role": "user", "content": query}]

        try:
            # 调用模型
            response = debugger.chat(prompt, i, temperature=args.temperature)

            # 写日志
            write_slug_log(slug, query, response, log_dir)

            # 提取模板
            top_templates = extract_templates(response)

            # 写入结果
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