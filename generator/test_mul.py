import os
import logging
from utils.patch_apply_mul import apply_multi_patches
from validator.junit_mul import run_JUnit, run_junitcore, calculate_patch_lines, restore_file

def _normalize_class_path(class_path: str, project_dir: str) -> str:
    """
    将 CSV 中的 class_path 转换为相对于 project_dir 的路径
    处理 CSV 中以 defects4j_buggy/BUG_id_buggy/ 开头的情况
    """
    class_path = class_path.strip()

    # 去掉开头的 defects4j_buggy/BUG_id_buggy/ 前缀
    parts = class_path.split('/')
    if len(parts) >= 3 and parts[0] == 'defects4j_buggy' and parts[1].endswith('_buggy'):
        relative_path = '/'.join(parts[2:])
    else:
        relative_path = class_path

    # 确保路径使用正斜杠
    return relative_path.replace("\\", "/")


def test(bug_id, sample, candidate_codes):
    buggy_items = sample.get("buggy_items", [])
    if not buggy_items or not candidate_codes:
        return False, "No candidate codes / buggy items", -1, None, 0, None
    if len(candidate_codes) != len(buggy_items):
        return False, f"Patch number mismatch: expect {len(buggy_items)}, got {len(candidate_codes)}", -1, None, 0, None

    project_dir = os.path.abspath(f"defects4j_buggy/{bug_id}_buggy")
    if not os.path.isdir(project_dir):
        raise RuntimeError(f"[{bug_id}] defects4j project dir not found: {project_dir}")

    original_cwd = os.getcwd()
    best_patch = None
    min_changes = -1
    failing_detail = None
    submission_result = "begin"
    failing_test_num = 0

    # 保存需要恢复的文件列表
    files_to_restore = []

    try:
        os.chdir(project_dir)
        logging.info(f"[{bug_id}] CWD switched to {project_dir}")

        # 构造 patch 列表
        patches = []
        for item, patch_text in zip(buggy_items, candidate_codes):
            normalized_path = _normalize_class_path(item["class_path"], project_dir)
            patches.append({
                "class_path": normalized_path,
                "patch": patch_text,
                "buggy_code": item["buggy_code"],
                "bugid": item["bugid"]
            })
            files_to_restore.append(normalized_path)

        # ✅ 打印将要替换的方法和 patch
        for patch in patches:
            logging.info(f"[{bug_id}] Will replace method in {patch['class_path']}")
            logging.debug(f"[{bug_id}] Patch content:\n{patch['patch']}")

        # 应用 multi patch
        logging.info(f"[{bug_id}] Applying multi patches")
        apply_multi_patches(patches)

        # 运行 defects4j 测试
        logging.info(f"[{bug_id}] Running defects4j test")
        reward, junit_result, failing_count, failing_tests = run_JUnit(bug_id)

        if reward:
            submission_result = "Test success"
            failing_test_num = 0
            failing_detail = None
        else:
            submission_result = "Test fail"
            failing_test_num = failing_count
            if failing_count > 0:
                junit_outputs = []
                for ft in failing_tests[:3]:
                    test_class = ft.split("::")[0]
                    junit_outputs.append(
                        f"### JUnitCore Output for {test_class} ###\n{run_junitcore(test_class, bug_id)}"
                    )
                failing_detail = "\n\n".join(junit_outputs)
            else:
                failing_detail = "Test failed but no failing tests; likely compile/runtime error"

        # 计算总代码改动
        total_changes = sum(
            calculate_patch_lines(item["buggy_code"], patch_text)
            for item, patch_text in zip(buggy_items, candidate_codes)
        )
        min_changes = total_changes
        best_patch = candidate_codes

        logging.info(f"[{bug_id}] Result={submission_result} | Failing tests={failing_test_num}")
        return reward, submission_result, min_changes, best_patch, failing_test_num, failing_detail

    except Exception as e:
        logging.exception(f"[{bug_id}] Test error")
        return False, "Other error", -1, None, 0, str(e)

    finally:
        # ✅ 保证恢复原始文件
        for f in files_to_restore:
            try:
                restore_file(f, bug_id)
                logging.info(f"[{bug_id}] Restored original file: {f}")
            except Exception as re:
                logging.error(f"[{bug_id}] Failed to restore file {f}: {re}")
        os.chdir(original_cwd)
        logging.info(f"[{bug_id}] CWD restored to {original_cwd}")
