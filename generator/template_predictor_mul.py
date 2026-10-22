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

# =========================
# 从模型输出中提取模板
# =========================
def extract_templates(response: str):
    """从模型输出中提取前 3 个模板，优先 JSON 解析，失败则正则兜底。"""
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

# =========================
# 写函数级日志
# =========================
def write_func_log(slug, func_id, prompt, response, log_dir):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{slug}_func_{func_id}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"==== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ====\n")
        f.write("=== Prompt 输入 ===\n")
        f.write(prompt + "\n")
        f.write("=== 模型输出 ===\n")
        f.write(response + "\n\n")

# =========================
# 多函数模板预测
# =========================
def predict_func_template_mul(args):
    logging.info("==== 开始【多 buggy functions】模板预测任务 ====")

    # ---------- 读取数据 ----------
    data = pd.read_csv(args.data_path, encoding="utf-8", engine="python")
    data["class_path"] = data["class_path"].str.replace(
        r"^defects4j/", "defects4j_buggy/", regex=True
    )

    # 为同一 slug 下的每个 buggy function 分配 func_id
    data["func_id"] = data.groupby("slug").cumcount()

    # ---------- 初始化模型 ----------
    debugger = (
        LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
        if args.chat_mode == "local"
        else RemoteChat(args.api_key, args.remote_model, args.remote_proxy)
    )

    # ---------- 输出 CSV ----------
    result_dir = os.path.join("result", "defects4j")
    os.makedirs(result_dir, exist_ok=True)
    result_path = os.path.join(result_dir, "template_funcdebug_predict_multi.csv")
    print(f"[INFO] 结果 CSV 将写入：{os.path.abspath(result_path)}")

    # ---------- 初始化 DataFrame ----------
    df_results = pd.DataFrame(
        columns=[
            "slug",
            "class_path",
            "func_id",
            "template1",
            "template2",
            "template3",
        ]
    )
    # 提前写空 CSV，保证文件存在
    df_results.to_csv(result_path, index=False, encoding="utf-8")

    # ---------- 日志目录 ----------
    log_dir = os.path.join("log", "template_multi_func")
    os.makedirs(log_dir, exist_ok=True)

    # ---------- 遍历预测 ----------
    for step, (_, row) in enumerate(tqdm(data.iterrows(), total=len(data)), start=1):
        slug = row["slug"]
        class_path = row["class_path"]
        func_id = row["func_id"]
        buggy_code = str(row["buggy_code"]).strip()

        query = f"""你是一名自动程序修复专家。
下面给定的是一个存在缺陷的 Java 函数，请判断它最可能对应哪些修复模板类型。

### Buggy function
(class_path = {class_path}, func_id = {func_id})
{buggy_code}

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
1.对上面17个模板进行相关性评分(0~1)
2.只返回评分>0.65的模板,最多3个
3.Other Template 仅当所有模板评分均低于阈值时才允许输出
4.输出严格遵守 JSON：
{{
  "predicted_templates": ["template_name"]
}}
"""
        prompt = [{"role": "user", "content": query}]

        try:
            # =========================
            # 关键修改：兼容新 API 返回 tuple
            # =========================
            response_raw = debugger.chat(
                prompt, func_id, temperature=getattr(args, "temperature", 1.0)
            )
            response = response_raw[0] if isinstance(response_raw, (tuple, list)) else response_raw

            write_func_log(slug, func_id, query, response, log_dir)
            top_templates = extract_templates(response)

        except Exception as e:
            logging.error(f"{slug} func_{func_id} 模板预测异常: {str(e)}")
            top_templates = []

        # ---------- 写入一行结果 ----------
        df_results.loc[len(df_results)] = {
            "slug": slug,
            "class_path": class_path,
            "func_id": func_id,
            "template1": top_templates[0] if len(top_templates) > 0 else "",
            "template2": top_templates[1] if len(top_templates) > 1 else "",
            "template3": top_templates[2] if len(top_templates) > 2 else "",
        }

        # 每 10 条写一次，防止意外丢失
        if step % 10 == 0:
            df_results.to_csv(result_path, index=False, encoding="utf-8")

    # ---------- 循环结束，最终写入 ----------
    df_results.to_csv(result_path, index=False, encoding="utf-8")
    print(f"[INFO] 模板预测 CSV 写入完成：{os.path.abspath(result_path)}")
    logging.info("==== 多 buggy functions 模板预测任务结束 ====")
