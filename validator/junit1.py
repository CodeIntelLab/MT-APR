import os 
import re
import subprocess
import signal

# 超时控制
def signal_handler(signum, frame):
    raise TimeoutError("Time out")

def set_timeout(seconds):  # 超时警告
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)

def reset_timeout():  # 清除超时
    signal.alarm(0)

def run_JUnit(bug_id, test_config=None):
    try:
        if test_config is None:
            test_config = {'time_out': 600}

        os.chdir('defects4j/' + bug_id + '_buggy')
        set_timeout(test_config['time_out'])
        cmd = 'defects4j test'
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        os.chdir('../../')
        output, _ = process.communicate()
        process.kill()
        output = output.decode('utf-8')
        reset_timeout()

        # 确定输出路径和文件名
        log_directory = 'log/defect'
        if not os.path.exists(log_directory):
            os.makedirs(log_directory)

        log_file_path = os.path.join(log_directory, f'junitbug_{bug_id}.txt')

        # 将输出写入到指定的日志文件
        with open(log_file_path, 'w', encoding='utf-8') as log_file:
            log_file.write(output)
        
        # 记录 defect 相关的测试信息到 junit.log
        junit_log_path = 'result/defects4j/logs/junit.log'
        os.makedirs(os.path.dirname(junit_log_path), exist_ok=True)
        with open(junit_log_path, 'a', encoding='utf-8') as junit_log:
            junit_log.write(f'Bug ID: {bug_id}\n')
            junit_log.write(output + '\n')
            junit_log.write('=' * 80 + '\n')

        if 'Running ant (compile.tests)................................................ FAIL' in output:
            return False, 'Compile failed'
        else:
            # 提取失败测试数量
            failing_count_match = re.search(r'Failing tests:\s*(\d+)', output)
            failing_count = int(failing_count_match.group(1)) if failing_count_match else 0
            failing_test_result = failing_count_match.group(0) if failing_count_match else 'Failing tests count not found'

            # 提取具体的失败测试名称和错误信息
            failure_details = []
            lines = output.split('\n')
            for i, line in enumerate(lines):
                line = line.strip()
                # 匹配 "1) testMethod(TestClass)" 格式的失败测试
                if re.match(r'^\d+\)\s+', line):
                    test_match = re.match(r'^\d+\)\s+([\w\.]+)\(([\w\.]+)\)', line)
                    if test_match:
                        test_method = test_match.group(1)
                        test_class = test_match.group(2)
                        # 收集后续错误信息（直到下一个测试或空行）
                        error_lines = []
                        j = i + 1
                        while j < len(lines) and not re.match(r'^\d+\)\s+', lines[j]) and lines[j].strip() != '':
                            error_lines.append(lines[j].strip())
                            j += 1
                        error_summary = error_lines[0] if error_lines else "Unknown error"
                        failure_details.append(f"{test_class}#{test_method}: {error_summary}")

            # 将详细信息添加到返回结果
            if failure_details:
                failing_test_result += "\nFailure Details:\n" + "\n".join(failure_details)

            success = (failing_count == 0)
            return success, failing_test_result

    except (RuntimeError, TypeError, NameError, FileNotFoundError, TimeoutError) as e:
        print(e)
        process.kill()
        return False, str(e)
#补丁调度算法
def calculate_patch_lines(original_code, patched_code):
    """计算两个代码版本的行数差异"""
    original_lines = original_code.split('\n')
    patched_lines = patched_code.split('\n')
    
    # ===== 第五步新增的调试日志 =====
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
        with open(java_file_path, 'r', encoding='iso-8859-1') as file:  # otherwise, try 'iso-8859-1' or 'cp1252'
            content = file.read()
    return content

def class_write(java_file_path, content):
    with open(java_file_path, 'w', encoding='utf-8', errors='ignore') as outfile:
        outfile.write(content)
    outfile.close()

# 提取方法起始和结束行
def extract_method_start_end_index(java_file_path, function_head, method_length):
    content = class_read(java_file_path)
    lines = content.split('\n')
    pattern_lines = function_head.split('\n')

    start_char_idx = content.find(function_head)
    if start_char_idx != -1:
        start_line_idx = content[:start_char_idx].count('\n')
        return [start_line_idx, start_line_idx + method_length]

    for i in range(len(lines)):
        if lines[i].split(')')[0].strip() == pattern_lines[0].strip():
            if len(pattern_lines) == 1:
                return [i, i + method_length]
            for j in range(len(pattern_lines))[1:]:
                if lines[i + j].split(')')[0].strip() != pattern_lines[j].strip():
                    break
            return [i, i + method_length]   
        
    return None

# 方法替换
def replace_file(java_file_path, replace_index, fixed_method):
    content = class_read(java_file_path)
    class_lines = content.split('\n')
    fixed_method_lines = fixed_method.split('\n')
    fixed_method_lines[-1] = fixed_method_lines[-1].split('@Override')[0] # remove redundant '@Override' at the end of the method
    class_lines[replace_index[0]:replace_index[1]] = fixed_method_lines
    code = '\n'.join(class_lines)
    class_write(java_file_path, code)

# 恢复原始java文件
def restore_file(file_path, bug_id):
    try:
        # Using git restore command to revert the file to the last commit state
        os.chdir('defects4j/' + bug_id + '_buggy')
        cmd = 'git checkout -- ' + file_path.replace('defects4j/' + bug_id + '_buggy/', '')
        os.system(cmd)
        os.chdir('../../')
    except (RuntimeError, TypeError, NameError,FileNotFoundError) as e:
        print(f"An error occurred while restoring changes to the file: {e}")