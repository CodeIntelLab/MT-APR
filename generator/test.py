from validator.junit import *
from utils.patch_apply import *
import logging
import os  # 新增导入
#未知版本
def test(bug_id, class_path, original_method, candidate_codes):
    """
    测试候选补丁，返回:
    reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail
    """

    if not candidate_codes:
        return False, "No candidate codes", -1, None, "None", None

    best_result = (False, "No valid patch", -1, None, "None", None)
    best_fail_count = float("inf")

    # 构建缺陷项目根目录的绝对路径
    project_root = os.path.abspath(f'defects4j_buggy/{bug_id}_buggy')
    full_class_path = os.path.join(project_root, class_path)

    for idx, fixed_method in enumerate(candidate_codes, 1):
        failing_test_num = "begin"
        failing_detail = None
        submission_result = "begin"
        min_changes = -1
        best_patch = None

        try:
            # ===== 抽取函数头 =====
            first_brace = fixed_method.find('{')
            if first_brace == -1:
                submission_result = "Candidate no method body"
                continue

            function_head = fixed_method[:first_brace].strip()

            # ===== 应用补丁（使用绝对路径） =====
            original_lines = original_method.split('\n')
            class_replace_index = extract_method_start_end_index(
                full_class_path, function_head, len(original_lines)
            )
            if not class_replace_index:
                submission_result = "Apply fail: not find code block"
                continue

            replace_file(full_class_path, class_replace_index, fixed_method)

            # ===== defects4j test =====
            reward, junit_result, failing_count, failing_tests = run_JUnit(bug_id)

            # ===== 结果处理 =====
            if reward:
                submission_result = "Test success"
                failing_test_num = 0
                failing_detail = None

            else:
                submission_result = "Test fail"
                failing_test_num = failing_count

                # ⭐ 最多 3 次 JUnitCore
                junitcore_outputs = []
                max_junitcore = 3

                for ft in failing_tests[:max_junitcore]:
                    test_class = ft.split("::")[0]
                    junitcore_output = run_junitcore(test_class, bug_id)
                    junitcore_outputs.append(
                        f"### JUnitCore Output for {test_class} ###\n{junitcore_output}"
                    )

                failing_detail = "\n\n".join(junitcore_outputs)

            # ===== 计算修改行数 =====
            min_changes = calculate_patch_lines(original_method, fixed_method)
            best_patch = fixed_method

            logging.info(
                f"[{bug_id}] Patch #{idx} | Result={submission_result} "
                f"| Failing tests={failing_test_num}"
            )

            # ===== 成功直接返回 =====
            if reward:
                return reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail

            # ===== 更新最优失败补丁 =====
            if isinstance(failing_test_num, int) and failing_test_num < best_fail_count:
                best_result = (
                    False, submission_result, min_changes,
                    best_patch, failing_test_num, failing_detail
                )
                best_fail_count = failing_test_num

        except Exception as e:
            submission_result = f"Other error: {str(e)}"
            failing_test_num = "None"
            failing_detail = str(e)
            logging.error(f"[{bug_id}] Patch #{idx} error: {str(e)}")

        finally:
            # ✅ 必须恢复原始 Java 文件（使用相对路径，restore_file 内部会 cd 到项目目录）
            restore_file(class_path, bug_id)

    return best_result