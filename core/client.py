from typing import Dict, Any, Tuple
import json
import asyncio
import aiohttp
from astrbot.api import logger

from .response_handle import detect_media_type

# 可重试的异常类型
_RETRYABLE_EXCEPTIONS = (
    asyncio.TimeoutError,
    aiohttp.ClientConnectionError,
    aiohttp.ServerTimeoutError,
)

# 二进制响应的硬性安全上限（MB）。
# 即使配置 max_size=0（不限）也套用该上限，防止异常/恶意响应耗尽内存。
_HARD_MAX_SIZE_MB = 500

# 流式读取响应体时的分块大小
_CHUNK_SIZE = 64 * 1024


async def _read_body_limited(
    response: aiohttp.ClientResponse, limit_bytes: int
) -> Tuple[Any, int]:
    """流式读取响应体，累计超过 limit_bytes 立即中止。

    返回: (完整字节, 已接收字节数)；超限时返回 (None, 已接收字节数)。
    不依赖 Content-Length，对 chunked/缺失头部的响应同样有效。
    """
    chunks = []
    received = 0
    async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
        received += len(chunk)
        if received > limit_bytes:
            return None, received
        chunks.append(chunk)
    return b"".join(chunks), received


async def _do_request(
    session: aiohttp.ClientSession,
    method: str,
    api_url: str,
    api_config: Dict[str, Any],
    req_kwargs: Dict[str, Any],
) -> Tuple[Any, str, str, int]:
    """执行单次 HTTP 请求并解析响应。

    返回: (响应数据, Content-Type 前缀, 媒体类型, HTTP 状态码)
    """
    if method == "GET":
        req_func = session.get
    elif method == "POST":
        req_func = session.post
    else:
        raise Exception(f"❌ 不支持的请求方法: {method}")

    async with req_func(api_url, **req_kwargs) as response:
        if response.status == 200:
            content_type = response.headers.get("Content-Type", "").split(";")[0]
            media_type = detect_media_type(content_type, api_url)

            if media_type in ("json", "text"):
                try:
                    response_data = await response.json(content_type=None)
                    logger.info(f"json 格式响应: {response_data}")
                except json.JSONDecodeError:
                    response_data = await response.text()
                    logger.info(f"文本格式响应: {response_data}")
            else:
                # 解析大小限制：优先单 API 配置的 max_size，0 时套用硬性安全上限
                max_size = api_config.get("max_size", 0)
                if not isinstance(max_size, (int, float)) or max_size < 0:
                    max_size = 0
                limit_mb = max_size if max_size > 0 else _HARD_MAX_SIZE_MB
                limit_bytes = int(limit_mb * 1024 * 1024)

                # 快速路径：有 Content-Length 且已超限，不下载直接拒收
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > limit_bytes:
                            logger.warning(
                                f"⚠️ 响应大小 {content_length} Bytes 超过限制 {limit_mb} MB"
                            )
                            return None, content_type, media_type, response.status
                    except ValueError:
                        pass  # 非法 Content-Length 头，交由流式读取兜底

                # 流式读取：无 Content-Length（chunked）时也能在超限瞬间中止
                response_data, received = await _read_body_limited(
                    response, limit_bytes
                )
                if response_data is None:
                    logger.warning(
                        f"⚠️ 响应超过 {limit_mb} MB 限制，已接收 {received} Bytes，中止下载"
                    )
                    return None, content_type, media_type, response.status
                logger.info(f"二进制响应，大小 {received} Bytes")
        else:
            logger.error(f"❌ API 请求失败，状态码: {response.status}")
            response_data = None
            content_type = ""
            media_type = ""

        return response_data, content_type, media_type, response.status


async def call_api(
    api_config: Dict[str, Any],
    global_timeout: int,
    retry_count: int = 0,
) -> Tuple[Any, str, str, int]:
    """调用 API 并返回结果（含指数退避重试）。

    参数:
        api_config:   单个 API 的配置字典
        global_timeout: 全局超时秒数
        retry_count:  最大重试次数（0 = 不重试）
    返回:
        (响应数据, Content-Type 前缀, 媒体类型, HTTP 状态码)
    保证:
        - 任何情况下都返回稳定的四元组
        - 仅网络超时/连接错误重试；HTTP 4xx/5xx 不重试
    """
    response_data = None
    content_type = ""
    media_type = ""
    status_code = 0

    api_url = api_config.get("api_url", "")
    method = api_config.get("method", "GET").upper()
    params = api_config.get("params", {})
    headers = api_config.get("headers", {})
    body = api_config.get("body", {})
    # 配置为0时继承全局
    timeout_sec = api_config.get("timeout") or global_timeout
    if not isinstance(timeout_sec, (int, float)) or timeout_sec <= 0:
        timeout_sec = 20

    total_attempts = max(0, retry_count) + 1
    last_error: str = ""

    for attempt in range(1, total_attempts + 1):
        try:
            client_timeout = aiohttp.ClientTimeout(total=timeout_sec)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                req_kwargs = {"headers": headers, "params": params}
                if method == "POST":
                    req_kwargs["json"] = body

                result = await _do_request(
                    session, method, api_url, api_config, req_kwargs
                )
                response_data, content_type, media_type, status_code = result

                # HTTP 层面成功了（200 或 非 200 都算请求完成），直接返回
                return response_data, content_type, media_type, status_code

        except _RETRYABLE_EXCEPTIONS as e:
            last_error = str(e)
            if attempt < total_attempts:
                delay = 2 ** (attempt - 1) * 0.5  # 0.5s → 1s → 2s → 4s
                logger.warning(
                    f"⚠️ 第 {attempt} 次请求失败 ({last_error})，"
                    f"{delay:.1f}s 后重试 ({attempt}/{retry_count})"
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(f"⚠️ 请求超时（已重试 {retry_count} 次）: {last_error}")

        except Exception as e:
            last_error = str(e)
            logger.error(f"❌ API 调用失败（不可重试）: {last_error}")
            # 不可重试的错误直接退出
            break

    return response_data, content_type, media_type, status_code
