import os
import logging
import pandas as pd
from tqdm import tqdm
from prompt.defects4j import *
from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat
from datetime import datetime
from generator.patch_processor import process_candidate_patch
import json


# ============================================================
# 消融实验：加载“模板修复模式”（不使用 reference patches）
# ============================================================

def load_template_patterns(
    slug,
    template_csv="result/defects4j/template_funcdebug_predict.csv",
    pattern_dir="template/fixtxt"
):
    """
    根据 bug 的模板预测结果，加载对应模板的修复模式文本（多模板）
    """
    if not os.path.exists(template_csv):
        return "No template patterns available."

    df = pd.read_csv(template_csv, encoding="utf-8")
    row = df[df["slug"] == slug]

    if row.empty:
        return "No template patterns available."

    template_names = [
        t for t in row.iloc[0, 1:].tolist()
        if isinstance(t, str) and t.strip()
    ]

    if not template_names:
        return "No template patterns available."

    blocks = []

    for tmpl in template_names:
        txt_path = os.path.join(pattern_dir, f"{tmpl}.txt")
        if not os.path.exists(txt_path):
            logging.warning(f"Template pattern file not found: {txt_path}")
            continue

        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            if not content:
                continue

            block = (
                f"### Repair Template: {tmpl} ###\n"
                f"{content}"
            )
            blocks.append(block)

        except Exception as e:
            logging.warning(f"Failed to load template pattern {tmpl}: {e}")

    if not blocks:
        return "No template patterns available."

    return "\n\n".join(blocks)


# ============================================================
# Debug 主流程
# ============================================================

def debug(args):
    logging.info("==== 开始 Debug（Ablation: Template-only） ====")
    os.makedirs("result/defects4j", exist_ok=True)

    data = pd.read_csv(args.data_path, sep=",", encoding="utf-8", engine="python")
    msg = pd.read_csv(args.msg_path, sep=",", encoding="utf-8", engine="python")

    # 替换路径
    data["class_path"] = data["class_path"].str.replace(
        r"^defects4j/", "defects4j_buggy/", regex=True
    )
    if os.path.exists(args.eval_path):
        df_eval_old = pd.read_csv(args.eval_path, sep=",", encoding="utf-8")
    else:
        df_eval_old = pd.DataFrame(
            columns=["ID", "slug", "reward", "submission_result", "num_candidates", "failing_test_num", "iter_num"]
        )
 
    if os.path.exists(args.result_path):
        df_results_old = pd.read_csv(args.result_path, sep=",", encoding="utf-8")
    else:
        df_results_old = pd.DataFrame(
            columns=["ID", "lang", "slug", "bug", "diff", "fix"]
        )
    
    # 历史 prompt
    history_base = HISTORY_AGENT_D4J if args.mode == "agent" else HISTORY_PURE_D4J

    # 初始化模型
    if args.chat_mode == 'local':
        debugger = LocalChat(
            args.local_model_dir,
            args.local_model,
            args.local_proxy
        )
    else:
        debugger = RemoteChat(
            args.api_key,
            args.remote_model,
            args.remote_proxy
        )
    df_eval = df_eval_old.copy()
    df_results = df_results_old.copy()
    row_num = df_eval["ID"].iloc[-1] + 1 if not df_eval.empty else 0
    for i, row in tqdm(data.iterrows(), total=len(data)):
        if i < row_num:
            continue
        sample = row
        bug_fixed = False

        if args.mode == "agent":
            prompt = history_base.copy()

            buggy_code_block = sample["buggy_code"].strip()
            query = AGENT_PROMPT_template.replace("{BUGGY_CODE}", buggy_code_block)

            row_msg = msg[msg["slug"] == sample["slug"]]
            error_message = (
                row_msg["exception_info"].values[0]
                if len(row_msg) > 0
                else "No error message available."
            )
            query = query.replace("{ERROR_MESSAGE}", error_message)

            # ★★★ 消融实验关键：模板修复模式 ★★★
            template_patterns = load_template_patterns(sample["slug"])
            query = query.replace("{patchs}", template_patterns)

            query = query.replace("{BUGGY_COMMENT}", "")
            query = query.replace("{FAILED_TEST}", "")

            prompt.append({"role": "user", "content": query})

            for _ in range(args.max_try):
                if bug_fixed:
                    break

                reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                    sample,
                    prompt,
                    debugger,
                    i,
                    args,
                    df_results,
                    df_eval,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    args.mode,
                    return_failure_info=True
                )

                if reward:
                    # 非迭代成功，记录 iter_num=0
                    df_eval.loc[len(df_eval)] = {
                        "ID": i,
                        "slug": sample["slug"],
                        "reward": reward,
                        "submission_result": "Success",
                        "num_candidates": len([]),
                        "failing_test_num": 0,
                        "iter_num": 0
                    }
                    bug_fixed = True
                    break  # 本轮成功，不进行迭代

                for iter_idx in range(1, getattr(args, 'max_iter', 0) + 1):
                    iter_prompt = history_base.copy()
                    iter_query = AGENT_PROMPT_template.replace(
                        "{BUGGY_CODE}", buggy_code_block
                    )
                    iter_query = iter_query.replace(
                        "{ERROR_MESSAGE}", error_message
                    )
                    iter_query = iter_query.replace(
                        "{patchs}", template_patterns
                    )
                    iter_query = iter_query.replace("{BUGGY_COMMENT}", "")
                    iter_query = iter_query.replace("{FAILED_TEST}", "")

                    failure_info = (
                        f"\n### 上一次失败补丁 ###\n{last_failed_patch}\n"
                        f"### 上一次失败原因 ###\n{last_failed_reason}"
                    )
                    iter_query += failure_info

                    iter_prompt.append(
                        {"role": "user", "content": iter_query}
                    )

                    reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                        sample,
                        iter_prompt,
                        debugger,
                        i,
                        args,
                        df_results,
                        df_eval,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        args.mode,
                        return_failure_info=True
                    )

                    if reward:
                        df_eval.loc[len(df_eval)] = {
                            "ID": i,
                            "slug": sample["slug"],
                            "reward": reward,
                            "submission_result": "Success",
                            "num_candidates": len([]),
                            "failing_test_num": 0,
                            "iter_num": iter_idx
                        }
                        bug_fixed = True
                        break  # 本轮迭代成功，跳出迭代循环

        else:
            prompt = history_base.copy()
            query = USER_PROMPT.replace(
                "{BUGGY_CODE}", sample["buggy_code"].strip()
            )
            prompt.append({"role": "user", "content": query})

            for _ in range(args.max_try):
                if bug_fixed:
                    break
                if process_candidate_patch(
                    sample,
                    prompt,
                    debugger,
                    i,
                    args,
                    df_results,
                    df_eval,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    args.mode
                ):
                    bug_fixed = True
                    break

    logging.info("==== Debug 结束（Ablation: Template-only） ====")
