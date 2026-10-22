import os
import logging
import pandas as pd
from tqdm import tqdm
from prompt.defects4j import *
from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat
from datetime import datetime
from generator.patch_processor_mul import process_candidate_patch
import json
import re


# =========================
# 🔥 构造多函数 buggy functions prompt 块
# =========================
def build_buggy_functions_block(buggy_items):
    blocks = []
    for item in buggy_items:
        block = f"""### Buggy Function ID {item['bugid']}
File path: {item['class_path']}
```java
{item['buggy_code'].strip()}
```"""
        blocks.append(block)
    return "\n\n".join(blocks)


# =========================
# 🔥 加载 patch_mul 中的参考补丁（仅用于提示）
# =========================
def load_reference_patches(bugid, patch_base="patch_mul"):
    bug_folder = os.path.join(patch_base, bugid)
    if not os.path.exists(bug_folder):
        return "No reference patches available."

    template_blocks = []

    for func_id in os.listdir(bug_folder):
        func_path = os.path.join(bug_folder, func_id)
        if not os.path.isdir(func_path):
            continue

        for template_name in os.listdir(func_path):
            template_path = os.path.join(func_path, template_name)
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
                        p = str(p).strip()
                        if p:
                            patches.append(p)

                except Exception as e:
                    logging.warning(f"Failed to load patch file: {fpath}, error: {e}")
                    continue

            if not patches:
                continue

            block = [
                f"### Repair Template：{template_name} (BugID {func_id}) ###",
                "Candidate Implementations："
            ]
            for p in patches:
                block.append(f"- {p}")

            template_blocks.append("\n".join(block))

    if not template_blocks:
        return "No reference patches available."

    return "\n\n".join(template_blocks)


# =========================
# 🔥 debug_mul 主函数
# =========================
def debug_mul(args):
    logging.info("==== 开始 Debug ====")
    os.makedirs("result/defects4j", exist_ok=True)

    data = pd.read_csv(args.data_path, sep=",", encoding="utf-8", engine="python")
    msg = pd.read_csv(args.msg_path, sep=",", encoding="utf-8", engine="python")



    # ===== 结果文件（断点续传）=====
    if os.path.exists(args.eval_path):
        df_eval_old = pd.read_csv(args.eval_path, sep=",", encoding="utf-8")
    else:
        df_eval_old = pd.DataFrame(columns=["ID", "slug", "reward", "submission_result", "num_candidates", "failing_test_num", "iter_num"])

    if os.path.exists(args.result_path):
        df_results_old = pd.read_csv(args.result_path, sep=",", encoding="utf-8")
    else:
        df_results_old = pd.DataFrame(columns=["ID", "lang", "slug", "bug", "diff", "fix"])

    history_base = HISTORY_AGENT_D4J if args.mode == "agent" else HISTORY_PURE_D4J

    # 初始化模型
    debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy) if args.chat_mode == 'local' else RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

    df_eval = df_eval_old.copy()
    df_results = df_results_old.copy()

    # ===== 生成 slug 的自然数字排序 ID，从 Chart2 开始 =====
    def slug_sort_key(slug):
        m = re.match(r'([A-Za-z]+)_(\d+)', slug)
        if m:
            project = m.group(1)
            bug_id = int(m.group(2))
            return (project, bug_id)
        return (slug, 0)

    slug_list = sorted(data["slug"].unique(), key=slug_sort_key)
    slug_to_id = {slug: idx + 2 for idx, slug in enumerate(slug_list)}  # Chart2 开始

    grouped = data.groupby("slug")

    for slug in tqdm(slug_list, total=len(slug_list)):
        group = grouped.get_group(slug)
        current_id = slug_to_id[slug]  # 相同 slug 保持同 ID

        buggy_items = [{"bugid": int(r["bugid"]), "buggy_code": r["buggy_code"], "class_path": r["class_path"]} for _, r in group.iterrows()]

        logging.info(f"Processing slug={slug}, bugids={[item['bugid'] for item in buggy_items]}")

        sample = {"slug": slug, "buggy_items": buggy_items}
        bug_fixed = False

        if args.mode == "agent":
            prompt_base = history_base.copy()
            buggy_block = build_buggy_functions_block(buggy_items)
            row_msg = msg[msg["slug"] == slug]
            error_message = row_msg["exception_info"].values[0] if len(row_msg) > 0 else "No error message available."
            reference_patches = load_reference_patches(slug, patch_base="result/patch_mul")

            for try_idx in range(args.max_try):
                if bug_fixed:
                    break
                prompt = prompt_base.copy()
                query = AGENT_PROMPT_MUL.replace("{BUGGY_FUNCTIONS}", buggy_block)\
                                        .replace("{ERROR_MESSAGE}", error_message)\
                                        .replace("{patchs}", reference_patches)\
                                        .replace("{BUGGY_COMMENT}", "")\
                                        .replace("{FAILED_TEST}", "")
                prompt.append({"role": "user", "content": query})

                reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                    sample, prompt, debugger, current_id, args, df_results, df_eval,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.mode,
                    return_failure_info=True, force_write_csv=True
                )

                # 写入 eval.csv
                df_eval.loc[len(df_eval)] = {
                    "ID": current_id,
                    "slug": slug,
                    "reward": reward,
                    "submission_result": "Success" if reward else "Fail",
                    "num_candidates": len(buggy_items),
                    "failing_test_num": 0 if reward else len(buggy_items),
                    "iter_num": 0
                }
                df_eval.to_csv(args.eval_path, sep=",", encoding="utf-8", index=False)

                if reward:
                    bug_fixed = True
                    break

                # 多函数迭代修复
                for iter_idx in range(1, getattr(args, 'max_iter', 0) + 1):
                    if bug_fixed:
                        break
                    iter_prompt = prompt_base.copy()
                    iter_query = AGENT_PROMPT_MUL.replace("{BUGGY_FUNCTIONS}", buggy_block)\
                                                 .replace("{ERROR_MESSAGE}", error_message)\
                                                 .replace("{patchs}", reference_patches)\
                                                 .replace("{BUGGY_COMMENT}", "")\
                                                 .replace("{FAILED_TEST}", "")
                    iter_query += f"\n### Previous failed patch ###\n{last_failed_patch}\n### Failure reason ###\n{last_failed_reason}"
                    iter_prompt.append({"role": "user", "content": iter_query})

                    reward, last_failed_patch, last_failed_reason = process_candidate_patch(
                        sample, iter_prompt, debugger, current_id, args, df_results, df_eval,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.mode,
                        return_failure_info=True, force_write_csv=True
                    )

                    df_eval.loc[len(df_eval)] = {
                        "ID": current_id,
                        "slug": slug,
                        "reward": reward,
                        "submission_result": "Success" if reward else "Fail",
                        "num_candidates": len(buggy_items),
                        "failing_test_num": 0 if reward else len(buggy_items),
                        "iter_num": iter_idx
                    }
                    df_eval.to_csv(args.eval_path, sep=",", encoding="utf-8", index=False)

                    if reward:
                        bug_fixed = True
                        break

        else:
            # 非 agent 模式，保持原逻辑
            prompt = history_base.copy()
            query = USER_PROMPT.replace("{BUGGY_CODE}", buggy_items[0]["buggy_code"].strip())
            prompt.append({"role": "user", "content": query})
            for _ in range(args.max_try):
                if bug_fixed:
                    break
                if process_candidate_patch(sample, prompt, debugger, current_id, args, df_results, df_eval, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), args.mode, force_write_csv=True):
                    bug_fixed = True
                    break

    logging.info("==== Debug 结束 ====")
