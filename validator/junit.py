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
        process = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

        os.chdir('../../')
        output, _ = process.communicate()
        process.kill()
        output = output.decode('utf-8')
        reset_timeout()

        # ===== 解析 failing tests =====
        failing_tests = []
        failing_count = 0

        failing_count_match = re.search(r'Failing tests:\s*(\d+)', output)
        if failing_count_match:
            failing_count = int(failing_count_match.group(1))

        for line in output.splitlines():
            line = line.strip()
            if line.startswith('- '):
                failing_tests.append(line[2:])

        # ===== 编译失败 =====
        if 'Running ant (compile.tests)' in output and 'FAIL' in output:
            return False, output, 0, []

        # ===== 测试失败 =====
        if failing_count > 0:
            return False, output, failing_count, failing_tests

        # ===== 测试通过 =====
        return True, output, 0, []

    except Exception as e:
        try:
            reset_timeout()
        except Exception:
            pass
        return False, str(e), 0, []



def run_junitcore(test_class, bug_id):
    """
    使用 JUnitCore 执行单个测试类，返回完整失败信息
    """
    try:
        os.chdir(f'defects4j_buggy/{bug_id}_buggy')

        cmd = (
            'java -cp "$(defects4j export -p cp.test)" '
            'org.junit.runner.JUnitCore '
            f'{test_class}'
        )

        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        output, _ = process.communicate()

        return output.decode('utf-8')

    except Exception as e:
        return f"JUnitCore failed: {str(e)}"

    finally:
        os.chdir('../../')

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
