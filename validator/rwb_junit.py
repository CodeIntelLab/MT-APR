import os
import re
import subprocess
import logging

RWB_BASE = "RWB"
RESULT_LOG_DIR = "result/rwb"

os.makedirs(RESULT_LOG_DIR, exist_ok=True)


def class_read(java_file_path):
    """
    读取 Java 文件，尝试 utf-8，如果失败则 iso-8859-1
    """
    try:
        with open(java_file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(java_file_path, "r", encoding="iso-8859-1") as f:
            return f.read()


def get_method_name(function_head):
    """
    提取方法名
    """
    match = re.search(r"([a-zA-Z0-9_]+)\s*\(", function_head)
    if match:
        return match.group(1)
    return None


def extract_method_start_end_index(java_file_path, function_head):
    """
    定位方法在文件中的起止行
    返回 [start_line, end_line]，从0开始索引
    """
    content = class_read(java_file_path)
    lines = content.split("\n")

    method_name = get_method_name(function_head)
    if not method_name:
        return None

    # 辅助函数：将方法头规范化为核心签名（方法名 + 参数简单类型列表）
    def normalize_signature(header):
        # 去除注解行
        lines = [line.strip() for line in header.split('\n') if line.strip() and not line.strip().startswith('@')]
        sig = ' '.join(lines)
        # 去除修饰符（public、static、final等）
        sig = re.sub(r'\b(public|protected|private|static|abstract|final|synchronized|native|strictfp)\s+', '', sig)
        # 去除 throws 子句
        sig = re.split(r'\bthrows\b', sig)[0].rstrip()
        
        # 提取方法名和参数列表
        # 匹配模式：可能还有返回类型，但只关注方法名和括号内的参数
        match = re.match(r'(?:\w+(?:\.\w+)*\s+)?(\w+)\s*\(([^)]*)\)', sig, re.DOTALL)
        if not match:
            return ''
        m_name = match.group(1)
        params = match.group(2).strip()
        
        # 解析参数列表，提取每个参数的简单类型名
        param_simple = []
        if params:
            # 按逗号分割参数（这里简化处理，不考虑泛型嵌套中的逗号）
            for p in params.split(','):
                p = p.strip()
                if not p:
                    continue
                # 去除 final 修饰符
                p = re.sub(r'\bfinal\s+', '', p)
                # 取第一个单词作为类型（可能包含包名和泛型）
                type_part = p.split()[0] if p else ''
                # 去除泛型部分（<...>）
                type_part = re.sub(r'<.*>', '', type_part)
                # 取简单类名（最后一个点之后）
                simple = type_part.split('.')[-1]
                param_simple.append(simple)
        
        # 返回规范化签名：方法名(类型1,类型2,...)
        return m_name + '(' + ','.join(param_simple) + ')'

    target_core = normalize_signature(function_head)

    candidate_start = None
    # 遍历所有可能包含方法名的行
    for i, line in enumerate(lines):
        if re.search(r'\b' + re.escape(method_name) + r'\s*\(', line):
            # 向前包含注解和空行
            start_idx = i
            while start_idx > 0:
                prev_line = lines[start_idx - 1].strip()
                if prev_line == "" or prev_line.startswith("@"):
                    start_idx -= 1
                else:
                    break

            # 收集从 start_idx 到第一个 '{' 之前的行
            collected = []
            for j in range(start_idx, len(lines)):
                collected.append(lines[j])
                if '{' in lines[j]:
                    break

            # 提取到第一个 '{' 之前的部分作为候选方法头
            candidate_block = '\n'.join(collected)
            brace_pos = candidate_block.find('{')
            if brace_pos != -1:
                candidate_head = candidate_block[:brace_pos]
            else:
                candidate_head = candidate_block

            candidate_core = normalize_signature(candidate_head)

            if candidate_core == target_core:   # 完全相等匹配
                candidate_start = start_idx
                break

    if candidate_start is None:
        return None

    # 括号匹配找到方法结束
    brace_count = 0
    method_started = False
    for j in range(candidate_start, len(lines)):
        brace_count += lines[j].count("{")
        brace_count -= lines[j].count("}")

        if "{" in lines[j]:
            method_started = True

        if method_started and brace_count == 0:
            return [candidate_start, j + 1]

    return None


def replace_file(java_file_path, replace_index, fixed_method):
    """
    替换文件中指定行范围的内容为 fixed_method
    保留 patch 内部所有换行和转义，不拆行
    """
    content = class_read(java_file_path)
    class_lines = content.split("\n")

    # 直接替换指定行范围为整个 fixed_method（不按行拆）
    start, end = replace_index[0], replace_index[1]
    new_content = "\n".join(class_lines[:start]) + "\n" + fixed_method + "\n" + "\n".join(class_lines[end:])

    with open(java_file_path, "w", encoding="utf-8", errors="ignore") as f:
        f.write(new_content)


def run_JUnit_RWB(bug_id, test_config=None):
    """
    执行 Maven test
    """
    if test_config is None:
        test_config = {"time_out": 600}

    try:
        project, bug = bug_id.split("-")
        repo_dir = os.path.join(RWB_BASE, project, f"{bug}f")

        if not os.path.exists(repo_dir):
            return False, f"Repo not found: {repo_dir}", 0, []

        # ===== compile =====
        compile_proc = subprocess.run(
            ["mvn", "compile", "-Drat.skip=true"],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=test_config["time_out"],
        )

        compile_output = compile_proc.stdout.decode()

        if compile_proc.returncode != 0:
            log_file = os.path.join(RESULT_LOG_DIR, f"{bug_id}_compile.log")
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(compile_output)
            return False, compile_output, 0, []

        # ===== run test =====
        # 基础测试命令
        cmd = ["mvn", "test", "-Drat.skip=true"]
        
        # 如果是 Jsoup 项目，排除 ProxyTest 类（避免环境问题）
        if project == "Jsoup":
            # 使用全限定类名确保准确排除
            cmd.append("-Dtest=!org.jsoup.integration.ProxyTest")
            # 如果希望排除多个类，可以用逗号分隔：!Class1,!Class2

        test_proc = subprocess.run(
            cmd,
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=test_config["time_out"],
        )

        output = test_proc.stdout.decode()
        log_file = os.path.join(RESULT_LOG_DIR, f"{bug_id}_test.log")
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(output)

        pattern = re.compile(
            r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)"
        )
        matches = pattern.findall(output)

        if not matches:
            return False, output, 0, []

        failures = int(matches[-1][1])
        errors = int(matches[-1][2])
        failing_count = failures + errors

        reward = failing_count == 0
        return reward, output, failing_count, []

    except subprocess.TimeoutExpired:
        return False, "Timeout", 0, []

    except Exception as e:
        logging.error(f"RWB run_JUnit error: {str(e)}")
        return False, str(e), 0, []