import logging
import os
import time
import pandas as pd
from generator.test import test
from utils.logging_util import wrap_java_code, write_bug_log
from utils.patch_apply import extract_code


# 用于处理补丁
def process_candidate_patch(sample, prompt, debugger, i, args, df_results, df_eval, now_time_str, mode, return_failure_info=False):

    start_time = time.time()

    try:
        print("STEP0: calling LLM")

# ===============================
# 🔥 DEBUG 1：确认函数是否真的执行到这里
# ===============================
        print(">>> ENTER STEP0", flush=True)
        print("prompt type:", type(prompt), flush=True)
        print("prompt len:", len(prompt), flush=True)
        print("first msg preview:", str(prompt[0])[:200], flush=True)

        # ===============================
        # 🔥 DEBUG 2：标记即将进入 LLM
        # ===============================
        print(">>> BEFORE CHAT CALL", flush=True)

        response, usage = debugger.chat(prompt, i, temperature=args.temperature)

        # ===============================
        # 🔥 DEBUG 3：确认是否从 chat 返回
        # ===============================
        print(">>> AFTER CHAT CALL", flush=True)

        print("STEP1: LLM response received")

        # 打印 LLM 返回内容（用于调试）
        print("LLM RESPONSE PREVIEW:\n", str(response)[:500])



                # ===============================
                # 2 token 统计
                # ===============================
        if usage:
            input_tokens = usage.get("prompt_tokens", sum(len(p["content"].split()) for p in prompt))
            output_tokens = usage.get("completion_tokens", len(response.split()))
        else:
            input_tokens = sum(len(p["content"].split()) for p in prompt)
            output_tokens = len(response.split())

        # ===============================
        # 3 处理代码块
        # ===============================
        response = wrap_java_code(response)
        print("STEP2: wrap_java_code done")

        all_codes = extract_code(response)
        print("STEP3: extract_code done, num =", len(all_codes))

        candidate_codes = all_codes[:3]

        print("STEP4: candidate_codes =", len(candidate_codes))

        # ===============================
        # 4 写 LLM 日志
        # ===============================
        print("STEP5: writing bug log")

        os.makedirs("log/defect/information", exist_ok=True)

        write_bug_log(sample["slug"], mode, prompt, response, candidate_codes)

        print("STEP6: bug log written")

        # ===============================
        # 5 如果没有解析出代码
        # ===============================
        if not candidate_codes:
            logging.error(f"未检测到代码块: {response}")

            if return_failure_info:
                return False, None, "No code detected"

            return False

        # ===============================
        # 6 运行测试
        # ===============================
        print("STEP7: running test()")

        reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail = test(
            sample["slug"],
            sample["class_path"],
            sample["buggy_code"],
            candidate_codes
        )

        print("STEP8: test finished")

        elapsed_time = round(time.time() - start_time, 2)

        # ===============================
        # 7 写结果 CSV
        # ===============================
        print("STEP9: writing result CSV")

        os.makedirs(os.path.dirname(args.result_path), exist_ok=True)

        df_results.loc[len(df_results)] = {
            "ID": i,
            "lang": "java",
            "slug": sample["slug"],
            "bug": sample["buggy_code"],
            "diff": "None",
            "fix": best_patch if best_patch else candidate_codes[0],
        }

        df_results.to_csv(args.result_path, sep=",", encoding="utf-8", index=False)

        print("STEP10: result CSV written")

        # ===============================
        # 8 写 eval CSV
        # ===============================
        os.makedirs(os.path.dirname(args.eval_path), exist_ok=True)

        df_eval.loc[len(df_eval)] = {
            "ID": i,
            "slug": sample["slug"],
            "reward": reward,
            "submission_result": submission_result,
            "num_candidates": len(candidate_codes),
            "failing_test_num": failing_test_num,
        }

        df_eval.to_csv(args.eval_path, sep=",", encoding="utf-8", index=False)

        print("STEP11: eval CSV written")

        # ===============================
        # 9 写 token / time
        # ===============================
        print("STEP12: writing time_token")

        os.makedirs("result/rwb", exist_ok=True)

        date_str = time.strftime("%Y%m%d")
        time_token_filename = f"time_token_{args.ablation}_{date_str}.csv"
        time_token_path = os.path.join("result/rwb", time_token_filename)

        if os.path.exists(time_token_path):
            df_time_token = pd.read_csv(time_token_path)
        else:
            df_time_token = pd.DataFrame(
                columns=["slug", "time", "input_tokens", "output_tokens"]
            )

        df_time_token.loc[len(df_time_token)] = {
            "slug": sample["slug"],
            "time": elapsed_time,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }

        df_time_token.to_csv(time_token_path, sep=",", encoding="utf-8", index=False)

        print("STEP13: time_token written")

        # ===============================
        # 10 返回结果
        # ===============================
        if return_failure_info:

            if reward:
                return True, None, None

            last_failed_patch = best_patch if best_patch else (
                candidate_codes[0] if candidate_codes else None
            )

            last_failed_reason = failing_detail or submission_result or "Unknown reason"

            return False, last_failed_patch, last_failed_reason

        return reward

    except Exception as e:

        print("PATCH_PROCESSOR ERROR:", e)

        import traceback
        traceback.print_exc()

        logging.error(f"修复 {sample['slug']} 出错: {str(e)}")

        if return_failure_info:
            return False, None, str(e)

        return False