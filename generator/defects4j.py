from utils.chat_remote import RemoteChat
from utils.chat_local import LocalChat
from prompt.defects4j import *
from validator.junit import *
from utils.patch_apply_mul import *
from generator.debug_mul import debug_mul  # 从 debug_mul.py 导入 debug_mul 函数
from generator.debug import debug
from generator.debug_rwb import debug_rwb
from generator.template_predictor import predict_template
from generator.template_func_predictor import predict_func_template
from generator.template_predictor_mul import predict_func_template_mul
import argparse
import os
import logging
from datetime import datetime
# 日志配置
log_dir = "result/defects4j/logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "debug.log")
logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
#sk-d2b85b3987a54fafb5b5d1bf917c7a3c
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--api_key', default="sk-t6jGG7ua2VJlqhY78J2gOgoWSPcXzHeD28YmchEADvfczoTd", type=str)
    parser.add_argument('--cp_path', default="~/.cache/huggingface/hub", type=str)
    parser.add_argument('--local_model_dir', default="/home/wtf/deepseek-coder/models/deepseek-coder-6.7b", type=str,
                        help="本地模型所在父目录，可指定不同模型")
    parser.add_argument('--chat_mode', default="remote", type=str)
    parser.add_argument('--remote_model', default="deepseek-v3.2", type=str)
    parser.add_argument('--local_model', default='deepseek-coder-6.7b', type=str)
    parser.add_argument('--data_path', default="data/single_function_v1.2.csv", type=str)
    parser.add_argument('--msg_path', default="data/defects4j_artifact.csv", type=str)
    parser.add_argument('--result_path', default="result/defects4j/pred", type=str)
    parser.add_argument('--eval_path', default="result/defects4j/eval", type=str)
    parser.add_argument('--remote_proxy', default='YUNWU', type=str)
    parser.add_argument('--local_proxy', default='batch', type=str)
    parser.add_argument('--mode', default='agent', type=str)
    parser.add_argument('--shot', default=1, type=int)#控制few shot的数量。
    parser.add_argument('--max_try', default=5, type=int)
    parser.add_argument('--max_iter', default=2, type=int,help="迭代次数，用于带反馈的多轮修复")
    parser.add_argument('--temperature', default=1.0, type=float)
    parser.add_argument('--ablation', default='full', type=str)#控制做消融实验，源代码见D盘A800
    parser.add_argument('--check', action='store_true')#控制是否跳过成功的bug，源代码见D盘A800
    parser.add_argument('--no-check', dest='check', action='store_false')
    parser.set_defaults(check=False)
    parser.add_argument('--early_stop', default=False, type=bool)
    parser.add_argument('--template_csv', default="data/bug_templates_unique.csv", type=str,
                        help="每个 bug 对应的模板 CSV")
    args = parser.parse_args()

    # ========= 构造参数标签 =========
    param_tag = f"try{args.max_try}_iter{args.max_iter}"
    temp_tag = "default" if args.temperature is None else args.temperature

    # ========= 构造输出 CSV 路径 =========
    result_elements = [args.result_path, args.ablation, str(args.shot)]
    eval_elements = [args.eval_path, args.ablation, str(args.shot)]

    remote_mode_alias = args.remote_model.split('/')[-1]
    local_mode_alias = args.local_model.split('/')[-1]

    # 建议：日期即可；如果你以后想更稳，可以换成 %Y%m%d_%H%M%S
    date_str = datetime.now().strftime("%Y%m%d")

    if args.chat_mode == 'remote':
        args.result_path = '_'.join(elem for elem in result_elements if elem != '') \
            + f'_{param_tag}_{args.mode}_shot_{remote_mode_alias}_temp={temp_tag}_{date_str}.csv'
        args.eval_path = '_'.join(elem for elem in eval_elements if elem != '') \
            + f'_{param_tag}_{args.mode}_shot_{remote_mode_alias}_temp={temp_tag}_{date_str}.csv'

    elif args.chat_mode == 'local':
        args.result_path = '_'.join(elem for elem in result_elements if elem != '') \
            + f'_{param_tag}_{args.mode}_shot_{local_mode_alias}_temp={temp_tag}_{date_str}.csv'
        args.eval_path = '_'.join(elem for elem in eval_elements if elem != '') \
            + f'_{param_tag}_{args.mode}_shot_{local_mode_alias}_temp={temp_tag}_{date_str}.csv'

    else:
        raise ValueError("chat_mode must be 'remote' or 'local'")


    # 初始化 debugger
    if args.chat_mode == "remote":
        debugger = RemoteChat(args.api_key, args.remote_model, args.remote_proxy)
    elif args.chat_mode == "local":
        debugger = LocalChat(args.local_model_dir, args.local_model, args.local_proxy)
    else:
        raise ValueError("chat_mode must be 'remote' or 'local'")

    # 将 debugger 放入 args，以便 debug.py 使用
    args.debugger = debugger

    # 调用 debug
    #predict_template(args)
    #predict_func_template(args)
    #predict_func_template_mul(args)
    #debug_mul(args)
    debug(args)
    #generate_patches(args)