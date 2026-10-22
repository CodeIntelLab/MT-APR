import logging
import subprocess
import re
from validator.rwb_junit import run_JUnit_RWB, extract_method_start_end_index, replace_file


def calculate_patch_lines(original_code, patched_code):
    return sum(
        1 for o, p in zip(original_code.splitlines(), patched_code.splitlines()) if o != p
    )


def reset_rwb_repo(bug_id):
    """
    重置 RWB 项目到干净状态（使用 git reset + git clean）
    """
    project, slug = bug_id.split("-")
    repo_path = f"RWB/{project}/{slug}f"

    try:
        subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["git", "clean", "-df"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        logging.error(f"[{bug_id}] Git reset failed: {str(e)}")


def escape_string_literals(java_code):
    """
    将 Java 代码中双引号字符串字面量内的物理换行符替换为 \n。
    """
    def replacer(match):
        full_str = match.group(0)        # 包含双引号的整个字符串
        inner = full_str[1:-1]
        escaped = inner.replace('\n', '\\n')
        return '"' + escaped + '"'

    pattern = r'"(.*?)"'
    return re.sub(pattern, replacer, java_code, flags=re.DOTALL)


def test(bug_id, class_path, original_method, candidate_codes, verbose=False):
    """
    测试 patch 并恢复原始代码
    返回六元组：
        reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail
    """
    if not candidate_codes:
        if verbose:
            print(f"[{bug_id}] No candidate codes")
        return False, "No candidate codes", -1, None, "None", None

    best_result = (False, "No valid patch", -1, None, "None", None)
    best_fail_count = float("inf")

    try:
        for idx, fixed_method in enumerate(candidate_codes, 1):
            try:
                # 每次测试前 reset
                reset_rwb_repo(bug_id)

                # 字符串字面量转义
                fixed_method = escape_string_literals(fixed_method)

                # 找到方法位置
                replace_index = extract_method_start_end_index(class_path, fixed_method)
                if not replace_index:
                    if verbose:
                        print(f"[{bug_id}] Patch #{idx} apply fail: method not found")
                    continue

                # 替换源码
                replace_file(class_path, replace_index, fixed_method)

                # 执行测试
                reward, junit_output, failing_count, _ = run_JUnit_RWB(bug_id)

                submission_result = "Test success" if reward else "Test fail"
                min_changes = calculate_patch_lines(original_method, fixed_method)
                best_patch = fixed_method

                # CSV 样式信息打印
                csv_row = {
                    "ID": idx,
                    "slug": bug_id,
                    "reward": reward,
                    "submission_result": submission_result,
                    "num_candidates": len(candidate_codes),
                    "failing_test_num": failing_count,
                    "min_changes": min_changes,
                    "applied_patch": best_patch
                }
                if verbose:
                    print(f"[{bug_id}] Patch #{idx} CSV Info: {csv_row}")

                # 如果成功直接返回
                if reward:
                    return reward, submission_result, min_changes, best_patch, 0, None

                # 更新最优失败 patch
                if failing_count < best_fail_count:
                    best_result = (
                        False,
                        submission_result,
                        min_changes,
                        best_patch,
                        failing_count,
                        None
                    )
                    best_fail_count = failing_count

            except Exception as e:
                logging.error(f"[{bug_id}] Patch #{idx} error: {str(e)}")

    finally:
        # 测试后再次 reset repo，确保干净
        reset_rwb_repo(bug_id)

    return best_result