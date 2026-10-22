import re
import sys
import os

project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_dir)


def extract_code(s: str):
    """
    从字符串 s 中提取被 Markdown ``` 包裹的代码块。
    自动去掉首行注解（如 @Override），返回纯净 Java 代码列表。
    """
    pattern = r"```(?:java)?\s*\n(.*?)```"
    codeblocks = re.findall(pattern, s, flags=re.DOTALL | re.IGNORECASE)
    if not codeblocks:
        return [s.strip()]  # fallback: 没有 Markdown 时返回原文

    cleaned_blocks = []
    for block in codeblocks:
        lines = block.strip().split('\n')
        # 如果第一行是注解（以@开头），删除它
        if lines and lines[0].strip().startswith('@'):
            lines = lines[1:]
        cleaned_blocks.append('\n'.join(lines).strip())

    return cleaned_blocks


def find_hunk_range(code, chunk):
    """
    根据 diff chunk 找在原代码中的字符范围
    """
    A_raw = code.split("\n")
    B_raw = chunk.split("\n")
    len_A = len(A_raw)
    len_B = len(B_raw)
    A = [line.strip() for line in A_raw]
    B = [line.strip() for line in B_raw]

    if len_A < len_B:
        return -1, -1

    for i in range(len_A):
        if A[i] == B[0]:
            if len_A - i < len_B:
                return -1, -1
            match = all(A[i + j] == B[j] for j in range(len_B))
            if match:
                l = len('\n'.join(A_raw[:i])) + (1 if i > 0 else 0)
                r = len('\n'.join(A_raw[:i + len_B]))
                return l, r
    return -1, -1


def apply_diff_to_program(code, diff):
    """
    将 diff 应用到源码 code 中
    """
    diff_lines = diff.split("\n")
    bug_chunks = []
    fix_chunks = []

    for diff_line in diff_lines:
        if diff_line.startswith(("diff", "index", "---", "+++")):
            continue
        elif diff_line.startswith("@@"):
            bug_chunks.append([])
            fix_chunks.append([])
        elif diff_line.strip() == "":
            bug_chunks[-1].append(diff_line + "\n")
            fix_chunks[-1].append(diff_line + "\n")
        elif diff_line.startswith("-"):
            bug_chunks[-1].append(diff_line[1:] + "\n")
        elif diff_line.startswith("+"):
            fix_chunks[-1].append(diff_line[1:] + "\n")
        else:
            bug_chunks[-1].append(diff_line[1:] + "\n")
            fix_chunks[-1].append(diff_line[1:] + "\n")

    # 最后一个 chunk 应用
    if bug_chunks and fix_chunks:
        bug_chunks[-1] = ''.join(bug_chunks[-1])
        fix_chunks[-1] = ''.join(fix_chunks[-1])
        l, r = find_hunk_range(code, bug_chunks[-1])
        if l == -1 or r == -1:
            raise Exception("Hunk not found")
        code = code[:l] + fix_chunks[-1] + code[r:]

    return code