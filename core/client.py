from typing import Dict, List, Any, Tuple
import json
import asyncio
import aiohttp
from astrbot.api import logger

from .response_handle import detect_media_type


async def call_api(api_config: Dict[str, Any], global_timeout) -> Tuple[Any, str, str]:
    """
    调用API并返回结果
    返回: (响应数据, Content-Type, 媒体类型)
    保证：任何情况下都返回稳定的三元组，不会出现未定义变量 / None
    """
    response_data = None
    content_type = ""
    media_type = ""

    api_url = api_config.get("api_url", "")
    method = api_config.get("method", "GET").upper()
    params = api_config.get("params", {})
    headers = api_config.get("headers", {})
    body = api_config.get("body", {})
    timeout = api_config.get("timeout", global_timeout)
    # timeout 在配置文件中只能配置为int类型，这里仅检测是否为负数
    if timeout < 0:
        timeout = 30

    try:
        timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 2. 统一请求参数（GET/POST 只在这里区分）
            req_kwargs = {"headers": headers, "params": params}
            if method == "POST":
                req_kwargs["json"] = body

            if method == "GET":
                req_func = session.get
            elif method == "POST":
                req_func = session.post
            else:
                raise Exception(f"❌ 不支持的请求方法: {method}")

            async with req_func(api_url, **req_kwargs) as response:
                response_data = None
                content_type = ""
                media_type = ""

                # api响应只处理200
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "").split(";")[
                        0
                    ]
                    media_type = detect_media_type(content_type, api_url)

                    # 统一读取数据逻辑
                    if media_type in ["json", "text"]:
                        try:
                            response_data = await response.json()
                        except (json.JSONDecodeError, aiohttp.ContentTypeError):
                            response_data = await response.text()
                    else:
                        response_data = await response.read()
                else:
                    logger.error(f"❌ API请求失败，状态码: {response.status}")

                # 统一返回
                return response_data, content_type, media_type

    except asyncio.TimeoutError:
        logger.warning(f"⚠️ 请求超时")
        return response_data, content_type, media_type

    except Exception as e:
        logger.error(f"❌ API调用失败: {str(e)}")
        return response_data, content_type, media_type
