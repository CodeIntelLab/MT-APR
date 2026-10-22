import os
import logging
import re
from typing import List, Tuple, Optional, Dict
from validator.junit_mul import restore_file

# =========================
# 文件读写
# =========================
def class_read(java_file_path: str) -> str:
    try:
        with open(java_file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        with open(java_file_path, 'r', encoding='iso-8859-1') as f:
            return f.read()

def class_write(java_file_path: str, content: str):
    with open(java_file_path, 'w', encoding='utf-8') as f:
        f.write(content)

# =========================
# 方法签名解析（方法名 + 参数类型）
# =========================
def parse_method_signature(buggy_code: str) -> Optional[Tuple[str, List[str]]]:
    header_lines = []
    for line in buggy_code.splitlines():
        header_lines.append(line.strip())
        if '{' in line:
            break
    header = ' '.join(header_lines).split('{')[0]
    m = re.search(r'(\w+)\s*\((.*)\)', header)
    if not m:
        return None
    method_name = m.group(1)
    params = m.group(2).strip()
    param_types = [p.strip().split()[0] for p in params.split(',')] if params else []
    return method_name, param_types

# =========================
# 方法定位（方法名 + 参数类型 + 大括号）
# =========================
def locate_method_by_signature_and_brace(content: str, method_name: str, param_types: List[str]) -> Optional[Tuple[int, int]]:
    lines = content.splitlines()
    n = len(lines)
    for i in range(n):
        if method_name not in lines[i]:
            continue
        sig_lines = []
        for j in range(i, min(i + 10, n)):
            sig_lines.append(lines[j].strip())
            if '{' in lines[j]:
                break
        sig_text = ' '.join(sig_lines)
        m = re.search(r'\((.*?)\)', sig_text)
        if not m:
            continue
        found_types = [p.strip().split()[0] for p in m.group(1).split(',')] if m.group(1).strip() else []
        if found_types != param_types:
            continue
        brace_count = 0
        started = False
        for k in range(i, n):
            brace_count += lines[k].count('{')
            brace_count -= lines[k].count('}')
            if '{' in lines[k]:
                started = True
            if started and brace_count == 0:
                return i, k + 1
    return None

# =========================
# fallback 精确文本匹配
# =========================
def extract_method_start_end_index(content: str, original_method: str) -> Optional[Tuple[int, int]]:
    original_lines_tag = [line.strip() for line in original_method.splitlines() if line.strip()]
    if not original_lines_tag:
        return None
    content_lines = content.splitlines()
    original_lines = original_method.splitlines()
    for i in range(len(content_lines) - len(original_lines) + 1):
        window = [line.strip() for line in content_lines[i:i+len(original_lines)] if line.strip()]
        if window == original_lines_tag:
            return i, i + len(original_lines)
    return None

# =========================
# 单文件多方法替换
# =========================
def replace_file(java_file_path: str, method_replacements: List[Tuple[str, str]]):
    content = class_read(java_file_path)
    class_lines = content.splitlines()
    for original_method, fixed_method in method_replacements:
        current_content = '\n'.join(class_lines)
        locate = None
        sig = parse_method_signature(original_method)
        if sig:
            method_name, param_types = sig
            locate = locate_method_by_signature_and_brace(current_content, method_name, param_types)
        if locate is None:
            locate = extract_method_start_end_index(current_content, original_method)
        if locate is None:
            raise ValueError(f"Locate failed: Could not find method in {java_file_path}")
        start, end = locate
        logging.info(f"Replacing method '{method_name}' in file: {java_file_path}")
        logging.debug(f"Patch content:\n{fixed_method}")
        fixed_lines = fixed_method.splitlines()
        class_lines[start:end] = fixed_lines
        current_content = '\n'.join(class_lines)
        class_lines = current_content.splitlines()
    class_write(java_file_path, '\n'.join(class_lines))

# =========================
# 多补丁应用
# =========================
def apply_multi_patches(patches: List[Dict]):
    """
    patches 中 class_path 直接按 CSV 提供路径，不再假设 source 目录
    """
    touched_files = set()
    # 检查所有文件是否存在
    for p in patches:
        abs_path = os.path.abspath(p['class_path'])
        logging.debug(f"Checking file exists: {abs_path}")
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Target file not found: {abs_path}")
        touched_files.add(abs_path)

    # 构造 file_patch_map
    file_patch_map: Dict[str, List[Tuple[str, str]]] = {}
    for p in patches:
        file_patch_map.setdefault(p['class_path'], []).append((p['buggy_code'], p['patch']))

    # 替换方法
    try:
        for java_file, method_repls in file_patch_map.items():
            replace_file(java_file, method_repls)
    except Exception as e:
        logging.error(f"[apply_multi_patches] ERROR: {e}")
        raise
