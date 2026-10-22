import os
from datetime import datetime

def wrap_java_code(response: str) -> str:
    """
    确保 response 中的 Java 代码被 ```java 包裹。
    如果已经有了，就不动；如果没有，就统一包裹。
    """
    if "```java" in response:
        return response.strip()
    return f"```java\n{response.strip()}\n```"

def write_bug_log(bug_id, mode, prompt, response, candidate_codes):
    """
    每个 bug 的详细日志，包含 mode、prompt、response、候选代码
    """
    log_dir = "log/defect/information"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{bug_id}.log")

    with open(log_path, "a", encoding="utf-8") as f:
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"\n==== [{mode}] Time: {time_str} ====\n")
        f.write("Prompt:\n")
        for p in prompt:
            f.write(f"{p['role']}: {p['content']}\n")
        f.write("\nResponse:\n")
        f.write(f"{response}\n\n")
        f.write("Candidate Codes:\n")
        for idx, code in enumerate(candidate_codes, 1):
            f.write(f"--- Candidate {idx} ---\n{code}\n\n")