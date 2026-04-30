import re
import urllib.parse
import copy
import random
from typing import Dict, List, Any, Tuple


def if_url_has_placeholders(url: str) -> bool:
    # 判断url是否有待传参数
    return bool(re.search(r"\{(\w+)\}", url))


def get_placeholders(url: str) -> Any:
    # 返回url待传参数及数量
    key_list = re.findall(r"\{(\w+)\}", url)
    key_len = len(key_list)
    return key_list, key_len


def if_params_has_emptyvalues(params: dict) -> bool:
    # 判断params是否有空值
    if not params:
        return False
    empty_keys = [k for k, v in params.items() if v == ""]
    return bool(empty_keys)


def get_params_empty(params: dict) -> Any:
    # 返回参数列表空值
    empty_keys = [k for k, v in params.items() if v == ""]
    empty_keys_len = len(empty_keys)
    return empty_keys, empty_keys_len


def replace_url_params(url: str, args_list: list):
    """
    按顺序填充URL中的占位符（已做URL编码）
    """
    try:
        parts = url.split("{")
        result = parts[0]

        for i in range(1, len(parts)):
            key_part, rest = parts[i].split("}", 1)
            if i - 1 < len(args_list):
                # 对参数做URL编码，防止路径穿越/参数污染/SSRF
                param_value = urllib.parse.quote(str(args_list[i - 1]), safe="")
                result += param_value + rest
            else:
                result += "{" + key_part + "}" + rest
        return result
    except Exception as e:
        raise Exception(f"❌ 在处理url占位符时发生错误: {str(e)}")


def replace_params(args_list: list, params: dict) -> list:
    """
    按顺序将用户输入的参数填充到值为空的参数字典中
    """
    empty_keys = [k for k, v in params.items() if v == ""]
    for key, value in zip(empty_keys, args_list):
        params[key] = value
    return params



def params_handle(command: str, parts: list, selected_api: dict):
    """
    根据输入参数对url或params进行处理
    """
    # 对params参数操作，copy一份，避免影响原来的配置
    api_config = copy.deepcopy(selected_api["config"])
    params = api_config.get("params", {})
    # 从url列表中随机选择一个
    api_url_list = api_config.get("api_url", [])
    if not isinstance(api_url_list, list):
        api_url = api_url_list
    else:
        if not api_url_list:
            err_msg = f"❌ 未配置 API 地址"
            return err_msg, api_config
        api_url = random.choice(api_url_list)
    api_config["api_url"] = api_url

    if len(parts) > 1:
        args_list = parts[1:]
        args_len = len(args_list)
    else:
        args_list = []
        args_len = 0
    # url有占位符情况
    if if_url_has_placeholders(url=api_url):
        key_list, key_len = get_placeholders(url=api_url)
        if args_len != key_len:
            param_placeholders = f"/{command} " + " ".join(
                [f"{{{p}}}" for p in key_list]
            )
            err_msg = f"❌ 参数数量不匹配，url占位符需要{key_len}个值，实际传递了{args_len}个，用法：{param_placeholders}"
            return err_msg, api_config
        else:
            api_config["api_url"] = replace_url_params(url=api_url, args_list=args_list)
            return None, api_config
    # params有空值情况
    elif if_params_has_emptyvalues(api_config.get("params", {})):
        key_list, key_len = get_params_empty(api_config.get("params", {}))
        if args_len != key_len:
            param_placeholders = f"/{command} " + " ".join(
                [f"{{{p}}}" for p in key_list]
            )
            err_msg = f"❌ 参数数量不匹配，params需要{key_len}个参数值，实际传递了{args_len}个，用法：{param_placeholders}"
            return err_msg, api_config
        else:
            api_config["params"] = replace_params(params=params, args_list=args_list)
            return None, api_config
    elif args_len != 0:
        err_msg = f"❌ 该API请求无需额外参数"
        return err_msg, api_config
    else:
        return None, api_config
