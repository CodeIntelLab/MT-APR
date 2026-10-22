import logging
import os
import time
import pandas as pd
from generator.test_mul import test
from utils.logging_util import wrap_java_code, write_bug_log
from utils.patch_apply import extract_code


def process_candidate_patch(
    sample,
    prompt,
    debugger,
    i,
    args,
    df_results,
    df_eval,
    now_time_str,
    mode,
    return_failure_info=False,
    force_write_csv=False
):
    """
    多函数版本 patch processor
    """
    start_time = time.time()

    # =========================
    # ✅ bugid 语义修正：
    # 一个 sample = 一个 bugid（csv 中第几个 buggycode）
    # =========================
    buggy_items = sample.get("buggy_items", [])
    if not buggy_items:
        raise ValueError("sample has no buggy_items")

    bug_key = f"{sample['slug']}#MULTI"

    try:
        # =========================
        # 1️⃣ 调用 LLM
        # =========================
        response, usage = debugger.chat(prompt, i, temperature=args.temperature)

        input_tokens = (
            usage.get("prompt_tokens", sum(len(p["content"].split()) for p in prompt))
            if usage else sum(len(p["content"].split()) for p in prompt)
        )
        output_tokens = (
            usage.get("completion_tokens", len(response.split()))
            if usage else len(response.split())
        )

        response = wrap_java_code(response)
        candidate_codes = extract_code(response)

        write_bug_log(bug_key, mode, prompt, response, candidate_codes)

        # =========================
        # 2️⃣ 基本一致性检查
        # =========================
        expected_num = len(buggy_items)

        if not candidate_codes:
            msg = "No code detected"
            logging.error(f"[{bug_key}] {msg}")
            if return_failure_info and force_write_csv:
                _write_eval_csv(
                    df_eval, sample,
                    reward=False,
                    submission_result="Fail",
                    num_candidates=expected_num,
                    iter_num=0
                )
            return (False, None, msg) if return_failure_info else False

        if len(candidate_codes) != expected_num:
            msg = f"Patch number mismatch: expect {expected_num}, got {len(candidate_codes)}"
            logging.error(f"[{bug_key}] {msg}")
            if return_failure_info and force_write_csv:
                _write_eval_csv(
                    df_eval, sample,
                    reward=False,
                    submission_result="Fail",
                    num_candidates=expected_num,
                    iter_num=0
                )
            return (False, None, msg) if return_failure_info else False

        # ⚠️ 约定：
        # candidate_codes[i] ↔ buggy_items[i]
        # 顺序必须保持一致（LLM prompt 已保证）
        ordered_candidate_codes = candidate_codes

        # =========================
        # 3️⃣ 调用多函数 test
        # =========================
        reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail = test(
            sample["slug"],
            sample,
            ordered_candidate_codes
        )

        elapsed_time = round(time.time() - start_time, 2)

        # =========================
        # 4️⃣ 写结果文件
        # =========================
        if not return_failure_info or force_write_csv:
            df_results.loc[len(df_results)] = {
                "ID": i,
                "lang": "java",
                "slug": sample["slug"],
                "bugid": "MULTI",   # ✅
                "bug": "MULTI_FUNCTION",
                "diff": "None",
                "fix": best_patch if best_patch else ordered_candidate_codes,
                "reward": reward,                       # ⭐ 新增
                "submission_result": submission_result
            }
            df_results.to_csv(args.result_path, sep=",", encoding="utf-8", index=False)

            _write_eval_csv(
                df_eval,
                sample,
                reward,
                submission_result if reward else "Fail",
                len(ordered_candidate_codes),
                failing_test_num=failing_test_num,
                iter_num=0
            )

            date_str = time.strftime("%Y%m%d")
            time_token_filename = f"time_token_{args.ablation}_{date_str}.csv"
            time_token_path = os.path.join("result/defects4j", time_token_filename)

            df_time_token = (
                pd.read_csv(time_token_path)
                if os.path.exists(time_token_path)
                else pd.DataFrame(columns=["slug", "bugid", "time", "input_tokens", "output_tokens"])
            )

            df_time_token.loc[len(df_time_token)] = {
                "slug": sample["slug"],
                "bugid": "MULTI",
                "time": elapsed_time,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens
            }
            df_time_token.to_csv(time_token_path, sep=",", encoding="utf-8", index=False)

        # =========================
        # 5️⃣ agent 失败反馈
        # =========================
        if return_failure_info:
            if reward:
                return True, None, None

            last_failed_patch = best_patch if best_patch else ordered_candidate_codes
            last_failed_reason = failing_detail or submission_result or "Unknown reason"
            return False, last_failed_patch, last_failed_reason

        return reward

    except Exception as e:
        logging.exception(f"[{bug_key}] 修复过程异常")
        if return_failure_info and force_write_csv:
            _write_eval_csv(
                df_eval,
                sample,
                reward=False,
                submission_result="Fail",
                num_candidates=len(buggy_items),
                iter_num=0
            )
        return (False, None, str(e)) if return_failure_info else False


def _write_eval_csv(df_eval, sample, reward, submission_result, num_candidates, failing_test_num=0, iter_num=0):
    df_eval.loc[len(df_eval)] = {
        "ID": len(df_eval),
        "slug": sample["slug"],
        "bugid": "MULTI",
        "reward": reward,
        "submission_result": submission_result,
        "num_candidates": num_candidates,
        "failing_test_num": failing_test_num,
        "iter_num": iter_num
    }
    df_eval.to_csv("result/defects4j/eval.csv", sep=",", encoding="utf-8", index=False)
