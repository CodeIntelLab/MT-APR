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
import sys
#函数级定位，完整修复流程

def load_reference_patches(bugid, patch_base="result/patch_RWB"):
    print("DEBUG: debug function started", flush=True)
    bug_folder = os.path.join(patch_base, bugid)
    if not os.path.exists(bug_folder):
        return "No reference patches available."

    template_blocks = []

    for template_name in os.listdir(bug_folder):
        template_path = os.path.join(bug_folder, template_name)
        if not os.path.isdir(template_path):
            continue

        patches = []

        for f in os.listdir(template_path):
            if not f.endswith(".json"):
                continue

            fpath = os.path.join(template_path, f)
            try:
                with open(fpath, "r", encoding="utf-8") as jf:
                    content = json.load(jf)

                if isinstance(content, dict) and "patches" in content:
                    patch_list = content["patches"]
                elif isinstance(content, list):
                    patch_list = content
                else:
                    continue

                for p in patch_list:
                    p = p.strip()
                    if p:
                        patches.append(p)

            except Exception as e:
                logging.warning(f"Failed to load patch file: {fpath}, error: {e}")
                continue

        if not patches:
            continue

        block = [
            f"### Repair Template：{template_name} ###",
            "Candidate Implementations："
        ]
        for p in patches:
            block.append(f"- {p}")

        template_blocks.append("\n".join(block))

    if not template_blocks:
        return "No reference patches available."

    return "\n\n".join(template_blocks)


def debug_rwb(args):
    logging.info("==== 开始 Debug ====")
    os.makedirs("result/rwb", exist_ok=True)

    data = pd.read_csv(args.data_path, sep=",", encoding="utf-8", engine="python")
    print(f"Loaded {len(data)} rows from data CSV", flush=True)
    msg = pd.read_csv(args.msg_path, sep=",", encoding="utf-8", engine="python")
    print(f"Loaded {len(msg)} rows from msg CSV", flush=True)

    #data["class_path"] = data["class_path"].str.replace(
    #    r"^defects4j/", "defects4j_buggy/", regex=True
    #)



     
    if os.path.exists(args.eval_path):
        df_eval_old = pd.read_csv(args.eval_path, sep=",", encoding="utf-8")
    else:
        df_eval_old = pd.DataFrame(
            columns=["ID", "slug", "reward", "submission_result",
                     "num_candidates", "failing_test_num", "iter_num"]
        )

    if os.path.exists(args.result_path):
        df_results_old = pd.read_csv(args.result_path, sep=",", encoding="utf-8")
    else:
        df_results_old = pd.DataFrame(
            columns=["ID", "lang", "slug", "bug", "diff", "fix"]
        )

    history_base = HISTORY_AGENT_D4J if args.mode == "agent" else HISTORY_PURE_D4J

    if args.chat_mode == 'local':
        debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        debugger = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

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
            query = AGENT_PROMPT.replace("{BUGGY_CODE}", buggy_code_block)

            row_msg = msg[msg["slug"] == sample["slug"]]
            error_message = (
                row_msg["exception_info"].values[0]
                if len(row_msg) > 0 else "No error message available."
            )
            query = query.replace("{ERROR_MESSAGE}", error_message)

            reference_patches = load_reference_patches(sample["slug"])
            query = query.replace("{patchs}", reference_patches)

            query = query.replace("{BUGGY_COMMENT}", "")
            query = query.replace("{FAILED_TEST}", "")

            prompt.append({"role": "user", "content": query})

            for _ in range(args.max_try):
                if bug_fixed:
                    break

                reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                    sample, prompt, debugger, i, args, df_results, df_eval,
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
                    iter_query = AGENT_PROMPT.replace(
                        "{BUGGY_CODE}", sample["buggy_code"].strip()
                    )
                    iter_query = iter_query.replace("{ERROR_MESSAGE}", error_message)
                    iter_query = iter_query.replace("{patchs}", reference_patches)
                    iter_query = iter_query.replace("{BUGGY_COMMENT}", "")
                    iter_query = iter_query.replace("{FAILED_TEST}", "")

                    failure_info = (
                        f"\n### 上一次失败补丁 ###\n{last_failed_patch}"
                        f"\n### 上一次失败原因 ###\n{last_failed_reason}"
                    )
                    iter_query += failure_info
                    iter_prompt.append({"role": "user", "content": iter_query})

                    reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                        sample, iter_prompt, debugger, i, args, df_results, df_eval,
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
                    sample, prompt, debugger, i, args,
                    df_results, df_eval,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    args.mode
                ):
                    bug_fixed = True
                    break

    logging.info("==== Debug 结束 ====")
