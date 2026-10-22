import os
import subprocess
import signal
import logging
import time
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# =========================
# 超时控制
# =========================
def _timeout_handler(signum, frame):
    raise TimeoutError("Test timed out")

def set_timeout(seconds: int):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(seconds)

def reset_timeout():
    signal.alarm(0)

# =========================
# defects4j 测试
# =========================
def run_JUnit(bug_id: str, timeout: int = 600):
    """
    执行 defects4j test，并返回:
    reward: True/False
    output: 原始 stdout
    failing_count: 失败用例数
    failing_tests: 失败用例列表
    """
    project_dir = os.path.join(PROJECT_ROOT, 'defects4j_buggy', f'{bug_id}_buggy')

    try:
        set_timeout(timeout)
        process = subprocess.Popen(
            'defects4j test',
            shell=True,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        output_bytes, _ = process.communicate()
        reset_timeout()
        output = output_bytes.decode('utf-8', errors='ignore')

        # 检查 cwd 错误或配置错误
        if 'Cannot open config file' in output or 'is not a valid working directory' in output:
            logging.error(f"[{bug_id}] defects4j working directory invalid")
            return False, output, 0, []

        # 检查编译失败
        if 'BUILD FAILED' in output or 'javac' in output:
            logging.error(f"[{bug_id}] Compilation failed")
            return False, output, 0, []

        # 获取失败用例
        failing_tests = []
        m = re.search(r'Failing tests:\s*(\d+)', output)
        failing_count = int(m.group(1)) if m else 0

        for line in output.splitlines():
            line = line.strip()
            if line.startswith('- '):
                failing_tests.append(line[2:])

        reward = failing_count == 0
        return reward, output, failing_count, failing_tests

    except TimeoutError:
        logging.error(f"[{bug_id}] defects4j test timeout")
        return False, "Timeout", 0, []
    except Exception as e:
        logging.exception(f"[{bug_id}] defects4j test exception")
        return False, str(e), 0, []
    finally:
        reset_timeout()

# =========================
# 单个测试类 JUnitCore 调试
# =========================
def run_junitcore(test_class: str, bug_id: str):
    project_dir = os.path.join(PROJECT_ROOT, 'defects4j_buggy', f'{bug_id}_buggy')
    cmd = (
        'java -cp "$(defects4j export -p cp.test)" '
        f'org.junit.runner.JUnitCore {test_class}'
    )
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            cwd=project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        output_bytes, _ = process.communicate()
        output = output_bytes.decode('utf-8', errors='ignore')
        return output
    except Exception as e:
        return f"JUnitCore failed: {str(e)}"

# =========================
# 补丁修改行数统计
# =========================
def calculate_patch_lines(original_code: str, patched_code: str) -> int:
    orig_lines = [l for l in original_code.splitlines() if l.strip()]
    patch_lines = [l for l in patched_code.splitlines() if l.strip()]

    import difflib
    diff = difflib.SequenceMatcher(None, orig_lines, patch_lines)
    changed_lines = 0
    for tag, i1, i2, j1, j2 in diff.get_opcodes():
        if tag != 'equal':
            changed_lines += max(i2 - i1, j2 - j1)
    return changed_lines

# =========================
# 文件读写工具
# =========================
def class_read(java_file_path: str) -> str:
    try:
        with open(java_file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        with open(java_file_path, 'r', encoding='iso-8859-1') as f:
            return f.read()

def class_write(java_file_path: str, content: str):
    with open(java_file_path, 'w', encoding='utf-8', errors='ignore') as f:
        f.write(content)

# =========================
# 文件回滚
# =========================
def restore_file(file_path: str, bug_id: str):
    project_dir = os.path.join(PROJECT_ROOT, 'defects4j_buggy', f'{bug_id}_buggy')
    if file_path.startswith(project_dir):
        rel_path = os.path.relpath(file_path, project_dir)
    else:
        rel_path = file_path
    subprocess.run(
        f'git checkout -- {rel_path}',
        shell=True,
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
