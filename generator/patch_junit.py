import pandas as pd
import json
import logging
from tqdm import tqdm
from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat
import os


def build_prompt(slug, buggy_code, generated_patch, correct_patch):

    prompt = f"""
你是一个专业的自动化程序修复评估。

Bug ID:
{slug}

缺陷代码（Buggy Code）:
{buggy_code}

生成的补丁（Generated Patch）:
{generated_patch}

正确补丁的diff（Ground Truth Patch DIff）:
{correct_patch}

任务：
判断生成的补丁是否修复了缺陷，只要与正确补丁的修复意图相似，修复策略与行为可以不同，即使修复意图不同，只要该生成补丁合理也认为是正确补丁。
在判断之前，你要根据buggycode看一下正确补丁的diff的+-，有些diff的增删是相反的
评估指南：

将补丁标记为 "Correct"（正确修复）的情况：
- 补丁以与正确补丁相同或非常相似的方式修复了缺陷。
- 补丁引入了等价的逻辑，即使实现方式有所不同。
- 补丁对于缺陷代码产生的行为很可能与正确补丁等价。
- 补丁采用了不同的修复策略，只改变了语义。
- 补丁与正确补丁的意图不同，但修复行为合理。

将补丁标记为 "Plausible"（可能正确）的情况：
- 补丁仅通过了测试，但存在明显的错误。
- 补丁添加或移除了无修复行为的逻辑。

输出格式（必须严格遵循 JSON 格式）：

{{
 "label": "Correct 或 Plausible",
 "reason": "简短解释正确原因"
}}
"""

    return prompt.strip()


def main(args):

    passed_df = pd.read_csv(args.passed_patch_csv)
    correct_df = pd.read_csv(args.correct_patch_csv)
    buggy_df = pd.read_csv("data/multi_functionspace.csv")

    # patch -> fix
    if "patch" in correct_df.columns and "fix" not in correct_df.columns:
        correct_df.rename(columns={"patch": "fix"}, inplace=True)

    # 初始化 LLM
    if args.chat_mode == "local":
        llm = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        llm = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)

    correct_slug_list = []
    log_rows = []

    for _, row in tqdm(passed_df.iterrows(), total=len(passed_df)):

        slug = row["slug"]
        gen_patch = str(row["fix"])

        correct_row = correct_df[correct_df["slug"] == slug]
        buggy_row = buggy_df[buggy_df["slug"] == slug]

        if correct_row.empty or buggy_row.empty:
            continue

        correct_patch = str(correct_row.iloc[0]["fix"])
        buggy_code = str(buggy_row.iloc[0]["buggy_code"])

        prompt = build_prompt(slug, buggy_code, gen_patch, correct_patch)

        try:

            response, _ = llm.chat(
                [{"role": "user", "content": prompt}],
                ID=slug
            )

            label = "Unknown"
            reason = ""

            try:
                parsed = json.loads(response)
                label = parsed.get("label", "Unknown")
                reason = parsed.get("reason", "")
            except:
                logging.warning(f"{slug} JSON解析失败")

            if label.lower() == "correct":
                correct_slug_list.append({"slug": slug})

            log_rows.append({
                "slug": slug,
                "buggy_code": buggy_code,
                "generated_patch": gen_patch,
                "ground_truth_patch": correct_patch,
                "llm_label": label,
                "llm_reason": reason,
                "llm_raw_response": response
            })

        except Exception as e:
            logging.error(f"{slug} 调用失败: {str(e)}")

    output_dir = os.path.dirname(args.output_correct_csv)
    os.makedirs(output_dir, exist_ok=True)

    pd.DataFrame(correct_slug_list).to_csv(args.output_correct_csv, index=False)
    pd.DataFrame(log_rows).to_csv(args.output_log_csv, index=False)

    print("验证完成")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("--passed_patch_csv", type=str)
    parser.add_argument("--correct_patch_csv", type=str)

    parser.add_argument("--output_correct_csv", default="result/patch_junit/gpt4omul_correct_by_llm.csv")
    parser.add_argument("--output_log_csv", default="result/patch_junit/gpt4omul_llm_validation_log.csv")

    parser.add_argument("--api_key", type=str)
    parser.add_argument("--chat_mode", default="remote")

    parser.add_argument("--remote_model", default="deepseek-v3.2")
    parser.add_argument("--remote_proxy", default="YUNWU")

    parser.add_argument("--local_model_dir", type=str)
    parser.add_argument("--local_model", type=str)
    parser.add_argument("--local_proxy", default="batch")

    args = parser.parse_args()

    main(args)