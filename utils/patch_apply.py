import re
import sys
import os

project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_dir)
#rwb

def extract_code(s: str):
    """
    从字符串 s 中提取被 Markdown ``` 包裹的代码块。
    自动去掉首行注解（如 @Override），返回纯净 Java 代码列表。
    """
    pattern = r"```(?:java)?\s*\n(.*?)```"
    codeblocks = re.findall(pattern, s, flags=re.DOTALL | re.IGNORECASE)
    cleaned_blocks = []

    for block in codeblocks:
        lines = block.strip().split('\n')
        # 如果第一行是注解（以@开头），删除它
        if lines and lines[0].strip().startswith('@'):
            lines = lines[1:]
        cleaned_blocks.append('\n'.join(lines).strip())

    return cleaned_blocks



def find_hunk_range(code, chunk):
    A_raw = code.split("\n")
    B_raw = chunk.split("\n")
    len_A = len(A_raw)
    len_B = len(B_raw)
    A = A_raw.copy()
    B = B_raw.copy()

    for i in range(len_A):
        A[i] = A[i].strip()
    for i in range(len_B):
        B[i] = B[i].strip()

    if len_A < len_B:
        return -1, -1

    for i in range(len_A):
        if A[i].strip() == B[0].strip(): 
            if len_A - i < len_B: 
                return -1, -1
            match = True
            for j in range(len_B):
                if A[i+j].strip() != B[j].strip(): 
                    match = False
                    break
            if match:
                l = len('\n'.join(A_raw[:i])) + 1
                r = len('\n'.join(A_raw[:i+len_B]))
                return l, r
    return -1, -1
    

def apply_diff_to_program(code, diff):
    diff_lines = diff.split("\n")
    
    bug_chunks = []
    fix_chunks = []

    for diff_line in diff_lines:
        if diff_line.startswith(("diff", "index", "---", "+++")):
            continue
        elif diff_line.startswith("@@"):
            bug_chunks.append([])
            fix_chunks.append([])
            if len(bug_chunks) > 1:
                bug_chunks[-2] = "\n".join(bug_chunks[-2])
                fix_chunks[-2] = "\n".join(fix_chunks[-2])
                l, r = find_hunk_range(code, bug_chunks[-2])
                if l == -1 or r == -1:
                    raise Exception("Hunk not found")
                code = code[:l] + fix_chunks[-2] + code[r:]
        elif diff_line.strip() == "":
            bug_chunks[-1].append(diff_line)
            fix_chunks[-1].append(diff_line)
        elif diff_line.startswith("-"):
            line = diff_line[1:]
            bug_chunks[-1].append(line)
        elif diff_line.startswith("+"):
            line = diff_line[1:]
            fix_chunks[-1].append(line)
        else:
            bug_chunks[-1].append(diff_line[1:])
            fix_chunks[-1].append(diff_line[1:])

    bug_chunks[-1] = "\n".join(bug_chunks[-1])
    fix_chunks[-1] = "\n".join(fix_chunks[-1])
    l, r = find_hunk_range(code, bug_chunks[-1])
    if l == -1 or r == -1:
        raise Exception("Hunk not found")
    code = code[:l] + fix_chunks[-1] + code[r:]
    
    bug_chunks = ["\n".join(chunk) for chunk in bug_chunks]
    fix_chunks = ["\n".join(chunk) for chunk in fix_chunks]

    return code


if __name__ == '__main__':

    PATCH = extract_code(PATCH)[0]
    print(PATCH)
    MERGE = apply_diff_to_program(SOURCE.strip(), PATCH.strip()).strip()
    print(MERGE)
    FIX = extract_code(FIX)[0].strip()
    print(FIX)
    print(MERGE == FIX)
    MIX_DIFF, MIX_FIX = extract_code(MIX)
    print(MIX_DIFF)
    print(MIX_FIX)

