import os
import json
import logging
import shutil

ROOT_DIR = "result/patch"
CLEAN_NAME = "patches_clean.json"
FINAL_NAME = "patches.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)


def has_valid_patches(clean_json_path: str) -> bool:
    """判断 patches_clean.json 中是否有有效补丁"""
    try:
        with open(clean_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        patches = data.get("patches", [])
        return isinstance(patches, list) and len(patches) > 0
    except Exception as e:
        logging.warning(f"无法解析 {clean_json_path}: {e}")
        return False


def process_template_dir(template_dir: str):
    clean_path = os.path.join(template_dir, CLEAN_NAME)
    final_path = os.path.join(template_dir, FINAL_NAME)

    # 情况 1：没有 patches_clean.json → 删除模板目录
    if not os.path.exists(clean_path):
        logging.info(f"✘ 无清洗补丁，删除模板目录: {template_dir}")
        shutil.rmtree(template_dir)
        return

    # 情况 2：patches_clean.json 存在但没有有效补丁
    if not has_valid_patches(clean_path):
        logging.info(f"✘ 空补丁模板，删除模板目录: {template_dir}")
        shutil.rmtree(template_dir)
        return

    # 情况 3：有有效补丁 → 替换 patches.json
    if os.path.exists(final_path):
        os.remove(final_path)

    os.rename(clean_path, final_path)
    logging.info(f"✔ 保留模板并更新补丁: {template_dir}")


def main():
    for bug_id in os.listdir(ROOT_DIR):
        bug_dir = os.path.join(ROOT_DIR, bug_id)
        if not os.path.isdir(bug_dir):
            continue

        for template in os.listdir(bug_dir):
            template_dir = os.path.join(bug_dir, template)
            if not os.path.isdir(template_dir):
                continue

            process_template_dir(template_dir)


if __name__ == "__main__":
    main()
