import os
import re
import subprocess
import signal
import logging
import time
import difflib

# 超时控制
def signal_handler(signum, frame):
    raise TimeoutError("Time out")

def set_timeout(seconds):  # 超时警告
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)

def reset_timeout():  # 清除超时
    signal.alarm(0)

# 在模块加载时，创建整体日志文件（整个运行只创建一次）
overall_log_dir = 'result/defects4j/logs'
os.makedirs(overall_log_dir, exist_ok=True)
overall_time_str = time.strftime("%m-%d-%H-%M")
junit_log_path = os.path.join(overall_log_dir, f'{overall_time_str}junit.log')

def run_JUnit(bug_id, test_config=None):
    try:
        if test_config is None:
            test_config = {'time_out': 600}

        os.chdir('defects4j_buggy/' + bug_id + '_buggy')
        set_timeout(test_config['time_out'])
        cmd = 'defects4j test'
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        os.chdir('../../')
        output, _ = process.communicate()
        process.kill()
        output = output.decode('utf-8')
        reset_timeout()

        # 打印完整原始输出
        print(f"\n[原始 JUnit 输出 {bug_id}]:\n{output}\n")

        # 当前时间
        time_str = time.strftime("%m-%d-%H-%M")

        # 写入单个 bug 日志
        log_directory = 'log/defect'
        os.makedirs(log_directory, exist_ok=True)
        log_file_path = os.path.join(log_directory, f'junitbug_{bug_id}.txt')
        with open(log_file_path, 'a', encoding='utf-8') as log_file:
            log_file.write(f"\n==== Time: {time_str} ====\n")
            log_file.write(output + '\n')

        # 写入总日志
        with open(junit_log_path, 'a', encoding='utf-8') as junit_log:
            junit_log.write(f'Bug ID: {bug_id}  | Time: {time_str}\n')
            junit_log.write(output + '\n')
            junit_log.write('=' * 80 + '\n')
            junit_log.flush()

        # ======== 1. 编译失败 ========
        if 'Running ant (compile.tests)................................................ FAIL' in output:
            print(f"[JUnit-{bug_id}] 编译失败：Compile failed")
            return False, "Compile failed", 0

        # ======== 2. 提取 failing 数量 ========
        failing_count_match = re.search(r'Failing tests:\s*(\d+)', output)
        failing_count = int(failing_count_match.group(1)) if failing_count_match else 0

        # ======== 3. 测试失败（但能编译）→ 返回完整原始输出 ========
        if failing_count > 0:
            print("\n================ JUnit 失败信息 ================")
            print(f"Bug ID: {bug_id}")
            print(f"Failing tests: {failing_count}")
            print("================================================\n")

            # 直接返回完整原始输出，不做额外解析
            return False, output, failing_count

        # ======== 4. 所有测试通过 ========
        print("\n================ JUnit 测试通过 ================")
        print(f"Bug ID: {bug_id}  All tests passed.")
        print("================================================\n")

        return True, output, 0

    except Exception as e:
        print(f"[JUnit-{bug_id}] 运行异常：{str(e)}")
        if 'process' in locals():
            process.kill()
        return False, str(e), 0




# 计算补丁修改行数
def calculate_patch_lines(original_code, patched_code):
    original_lines = [line for line in original_code.split('\n') if line.strip()]
    patched_lines = [line for line in patched_code.split('\n') if line.strip()]

    logging.debug(
        f"行数统计: 原始代码={len(original_lines)}行, 补丁代码={len(patched_lines)}行"
        f"\n原始代码片段:\n{original_code[:100]}..."
        f"\n补丁代码片段:\n{patched_code[:100]}..."
    )

    diff = difflib.SequenceMatcher(None, original_lines, patched_lines)
    changed_lines = 0
    for op in diff.get_opcodes():
        if op[0] != 'equal':
            changed_lines += max(op[2]-op[1], op[4]-op[3])

    logging.debug(f"计算得到修改行数: {changed_lines}")
    return changed_lines


# java文件读写
def class_read(java_file_path):
    try:
        with open(java_file_path, 'r', encoding='utf-8') as file:
            content = file.read()
    except UnicodeDecodeError:
        with open(java_file_path, 'r', encoding='iso-8859-1') as file:
            content = file.read()
    return content

def class_write(java_file_path, content):
    with open(java_file_path, 'w', encoding='utf-8', errors='ignore') as outfile:
        outfile.write(content)
    outfile.close()


# 提取方法起始和结束行
def extract_method_start_end_index(java_file_path, function_head, method_length):
    """
    根据函数头和函数长度，返回函数在文件中的起止行号 [start_line, end_line)
    """
    content = class_read(java_file_path)
    lines = content.split('\n')
    pattern_lines = [line.strip() for line in function_head.split('\n') if line.strip()]

    # 1. 精确匹配整个函数头字符串
    start_char_idx = content.find(function_head)
    if start_char_idx != -1:
        start_line_idx = content[:start_char_idx].count('\n')
        end_line_idx = min(start_line_idx + method_length, len(lines))
        return [start_line_idx, end_line_idx]

    # 2. 按行匹配
    for i in range(len(lines)):
        if lines[i].strip() == pattern_lines[0]:
            match = True
            for j in range(1, len(pattern_lines)):
                if i + j >= len(lines) or lines[i + j].strip() != pattern_lines[j]:
                    match = False
                    break
            if match:
                end_line_idx = min(i + method_length, len(lines))
                return [i, end_line_idx]

    # 未找到
    return None


# 方法替换
def replace_file(java_file_path, replace_index, fixed_method):
    content = class_read(java_file_path)
    class_lines = content.split('\n')
    fixed_method_lines = fixed_method.split('\n')
    fixed_method_lines[-1] = fixed_method_lines[-1].split('@Override')[0]  # remove redundant '@Override'
    class_lines[replace_index[0]:replace_index[1]] = fixed_method_lines
    code = '\n'.join(class_lines)
    class_write(java_file_path, code)


# 恢复原始java文件
def restore_file(file_path, bug_id):
    try:
        os.chdir('defects4j_buggy/' + bug_id + '_buggy')
        cmd = 'git checkout -- ' + file_path.replace('defects4j_buggy/' + bug_id + '_buggy/', '')
        os.system(cmd)
        os.chdir('../../')
    except (RuntimeError, TypeError, NameError, FileNotFoundError) as e:
        print(f"An error occurred while restoring changes to the file: {e}")
