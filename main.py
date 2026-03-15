import random
import time
import json
import re
import mimetypes
import copy
import tempfile
import os
import base64

from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from urllib.parse import urlparse

import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp


class RateLimiter:
    """频率限制器"""

    def __init__(self):
        self.user_calls = defaultdict(list)
        self.api_calls = defaultdict(lambda: defaultdict(list))

    def is_allowed(self, user_id: str, api_key: str, limit: int) -> bool:
        """检查是否超过频率限制"""
        if limit <= 0:
            return True

        now = time.time()
        one_minute_ago = now - 60

        # 清理过期记录
        self.user_calls[user_id] = [
            t for t in self.user_calls[user_id] if t > one_minute_ago
        ]
        self.api_calls[api_key][user_id] = [
            t for t in self.api_calls[api_key][user_id] if t > one_minute_ago
        ]

        # 检查限制
        if len(self.user_calls[user_id]) >= limit:
            return False
        if len(self.api_calls[api_key][user_id]) >= limit:
            return False

        # 记录调用
        self.user_calls[user_id].append(now)
        self.api_calls[api_key][user_id].append(now)
        return True


class CustomAPIManager(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.rate_limiter = RateLimiter()
        self.api_map = self._build_api_map()

        # 媒体类型映射
        self.media_type_handlers = {
            "text": self._process_text_response,
            "img": self._process_img_response,
            "audio": self._process_audio_response,
            "video": self._process_video_response,
        }

    def _build_api_map(self) -> Dict[str, List[Dict[str, Any]]]:
        """构建指令到API的映射"""
        api_map = defaultdict(list)
        custom_apis = self.config.get("custom_apis", [])

        for api_config in custom_apis:
            template_key = api_config.get("__template_key", "")
            command = api_config.get("api_name", "").lower()

            if command:
                api_info = {
                    "type": template_key.replace(
                        "_type", ""
                    ),  # text, img, audio, video
                    "config": api_config,
                }
                api_map[command].append(api_info)

        return dict(api_map)

    def _get_nested_value(self, data: Any, path: str) -> Any:
        """
        嵌套字典取值
        1.支持数字下标：data.0.urlsList.0.url
        2.默认取列表第一项：data.urlsList.url
        杂交写法也没问题：data.0.urlsList.url
        """
        if not path:
            return data

        keys = path.split(".")
        result = data

        for key in keys:
            if isinstance(result, dict):
                if key in result:
                    result = result[key]
                else:
                    return None

            elif isinstance(result, list):
                if key.isdigit():
                    idx = int(key)
                    if 0 <= idx < len(result):
                        result = result[idx]
                    else:
                        return None
                else:
                    if len(result) == 0:
                        return None
                    result = result[0]
                    if key in result:
                        result = result[key]
            else:
                return None
        return result

    def _if_url_has_placeholders(self, url: str) -> bool:
        # 判断url是否有待传参数
        return bool(re.search(r"\{(\w+)\}", url))

    def _get_placeholders(self, url: str) -> Any:
        # 返回url待传参数及数量
        key_list = re.findall(r"\{(\w+)\}", url)
        key_len = len(key_list)
        return key_list, key_len

    def _get_params_empty_len(self, params: list) -> Any:
        # 返回参数列表空值数量
        if not params:
            return 0
        empty_keys = [k for k, v in params.items() if v == ""]
        empty_keys_len = len(empty_keys)
        return empty_keys, empty_keys_len

    def _replace_url_params(self, url: str, args_list: list):
        """
        按顺序填充URL中的占位符
        """
        # 找到所有占位符
        parts = url.split("{")
        result = parts[0]

        for i in range(1, len(parts)):
            key_part, rest = parts[i].split("}", 1)
            if i - 1 < len(args_list):
                result += str(args_list[i - 1]) + rest
            else:
                result += "{" + key_part + "}" + rest
        return result

    def _replace_params(self, args_list: list, params: dict) -> Any:
        """
        按顺序将用户输入的参数填充到值为空的参数字典中
        """
        empty_keys = [k for k, v in params.items() if v == ""]
        for key, value in zip(empty_keys, args_list):
            params[key] = value
        return params

    def _should_trigger(self, event: AstrMessageEvent, api_config: dict) -> Any:
        """
        判断是否应该触发API
        1. 单个API配置优先
        2. 没有则使用全局配置
        """
        api_trigger_type = api_config.get("trigger_type", "global")
        if api_trigger_type == "global":
            trigger_type = self.config.get("default_trigger_type", "direct")
        else:
            trigger_type = api_trigger_type

        # 判断是否被@
        is_mentioned = event.is_at_or_wake_command
        # 仅@时触发
        if trigger_type == "mention_only":
            return is_mentioned
        # 直接触发
        return True

    def _detect_media_type(self, content_type: str, url: str = "") -> str:
        """
        根据Content-Type和URL检测媒体类型
        返回值: text, img, audio, video, other
        """
        if not content_type:
            # 从URL推断类型
            parsed_url = urlparse(url)
            mime_type, _ = mimetypes.guess_type(parsed_url.path)
            content_type = mime_type or ""

        content_type = content_type.lower()

        # json类型
        if any(ct in content_type for ct in ["application/json", "text/json"]):
            return "json"
        # 文本类型
        elif any(
            ct in content_type
            for ct in ["text/", "application/json", "application/xml"]
        ):
            return "text"
        # 图片类型
        elif any(
            ct in content_type
            for ct in ["image/", "png", "jpg", "jpeg", "gif", "bmp", "webp"]
        ):
            return "img"

        # 音频类型
        elif any(
            ct in content_type for ct in ["audio/", "mp3", "wav", "ogg", "m4a", "amr"]
        ):
            return "audio"

        # 视频类型
        elif any(
            ct in content_type for ct in ["video/", "mp4", "avi", "mov", "flv", "mkv"]
        ):
            return "video"

        # 其他类型
        else:
            return "other"

    async def _call_api(self, api_config: Dict[str, Any]) -> Tuple[Any, str, str]:
        """
        调用API并返回结果
        返回: (响应数据, Content-Type, 媒体类型)
        """
        api_url = api_config.get("api_url", "")
        method = api_config.get("method", "GET")
        params = api_config.get("params", {})
        headers = api_config.get("headers", {})
        body = api_config.get("body", {})
        timeout = api_config.get("timeout", self.config.get("global_timeout", 30))

        try:
            timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method == "GET":
                    async with session.get(
                        api_url, headers=headers, params=params
                    ) as response:
                        if response.status == 200:
                            content_type = response.headers.get(
                                "Content-Type", ""
                            ).split(";")[0]
                            media_type = self._detect_media_type(content_type, api_url)
                            if media_type in ["json", "text"]:
                                try:
                                    response_data = await response.json()
                                except json.JSONDecodeError:
                                    response_data = await response.text()
                            else:
                                response_data = await response.read()
                        else:
                            logger.error(f"❌ API请求失败，状态码: {response.status}")
                        return response_data, content_type, media_type

                elif method == "POST":
                    async with session.post(
                        api_url, headers=headers, params=params, json=body
                    ) as response:
                        if response.status == 200:
                            content_type = response.headers.get(
                                "Content-Type", ""
                            ).split(";")[0]
                            media_type = self._detect_media_type(content_type, api_url)
                            if media_type in ["json", "text"]:
                                try:
                                    response_data = await response.json()
                                except json.JSONDecodeError:
                                    response_data = await response.text()
                            else:
                                response_data = await response.read()
                        else:
                            logger.error(f"❌ API请求失败，状态码: {response.status}")
                        return response_data, content_type, media_type
                else:
                    raise Exception(f"❌ 不支持的请求方法: {method}，请修改后台配置")
        except asyncio.TimeoutError:
            logger.warning(f"请求超时")
        except Exception as e:
            logger.error(f"❌ API调用失败: {str(e)}")
            raise

    # 响应处理
    async def _process_text_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理文本类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if isinstance(data, dict) and data_path:
                text = self._get_nested_value(data, data_path)
            else:
                text = str(data)

            if text and text.strip():
                yield event.plain_result(text.strip())
            else:
                yield event.plain_result("⚠️ API返回空文本")

        except Exception as e:
            logger.error(f"处理文本响应失败: {str(e)}")
            yield event.plain_result(f"❌ 文本处理失败: {str(e)}")

    async def _process_img_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理图片类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if data_path and isinstance(data, dict):
                # 从JSON中获取图片URL
                img_content = self._get_nested_value(data, data_path)
                if not img_content:
                    yield event.plain_result("⚠️ 未找到图片内容")
                    return

                img_content = str(img_content).strip()
                # URL
                if img_content.startswith(("http://", "https://")):
                    yield event.image_result(img_content)
                    return
                # json中有base64
                try:
                    if "base64," in img_content:
                        img_content = img_content.split(",")[1]
                    # ✅ 关键：前面加 base64://
                    yield event.image_result(f"base64://{img_content}")
                    return
                except:
                    yield event.plain_result("❌ Base64 图片格式错误")

            # 二进制图片
            elif isinstance(data, bytes):
                img_bytes = data
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                    f.write(img_bytes)
                yield event.image_result(f.name)
                os.unlink(f.name)
                return

            # 3. 纯字符串 Base64
            elif isinstance(data, str):
                try:
                    if "base64," in data:
                        data = data.split("base64,")[1]
                    img_bytes = base64.b64decode(data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                        f.write(img_bytes)
                    yield event.image_result(f.name)
                    os.unlink(f.name)
                    return
                except:
                    pass
            else:
                yield event.plain_result(f"❌ 不支持的图片格式")
        except Exception as e:
            logger.error(f"处理图片响应失败: {str(e)}")
            yield event.plain_result(f"❌ 图片处理失败: {str(e)}")

    async def _process_audio_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理语音类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if data_path and isinstance(data, dict):
                # 从JSON中获取音频URL
                audio_url = self._get_nested_value(data, data_path)
                if audio_url:
                    # 构建语音消息链
                    chain = [Comp.Record(url=audio_url)]
                    yield event.chain_result(chain)
                else:
                    yield event.plain_result("⚠️ 未找到音频URL")
            else:
                # 处理音频二进制数据
                # 保存音频到临时文件
                import tempfile
                import os

                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".mp3"
                ) as tmp_file:
                    tmp_file.write(data)
                    tmp_file_path = tmp_file.name

                # 发送音频（根据AstrBot API调整）
                chain = [Comp.Record(file=tmp_file_path)]
                yield event.chain_result(chain)

                # 清理临时文件
                os.unlink(tmp_file_path)

        except Exception as e:
            logger.error(f"处理音频响应失败: {str(e)}")
            yield event.plain_result(f"❌ 音频处理失败: {str(e)}")

    async def _process_video_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理视频类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if data_path and isinstance(data, dict):
                # 从JSON中获取视频URL
                video_url = self._get_nested_value(data, data_path)
                if video_url:
                    # 构建视频消息链
                    chain = [Comp.Video.fromURL(url=video_url)]
                    yield event.chain_result(chain)
                else:
                    yield event.plain_result("⚠️ 未找到视频URL")
            else:
                # 处理视频二进制数据
                # 保存视频到临时文件
                import tempfile
                import os

                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".mp4"
                ) as tmp_file:
                    tmp_file.write(data)
                    tmp_file_path = tmp_file.name

                # 发送视频（根据AstrBot API调整）
                chain = [Comp.Video(file=tmp_file_path)]
                yield event.chain_result(chain)

                # 清理临时文件
                os.unlink(tmp_file_path)

        except Exception as e:
            logger.error(f"处理视频响应失败: {str(e)}")
            yield event.plain_result(f"❌ 视频处理失败: {str(e)}")

    @filter.command("apihelp", alias={"api帮助", "APIHELP"})
    async def api_help(self, event: AstrMessageEvent):
        """显示API帮助信息"""
        help_text = """自定义API管理插件帮助
                    📋 可用指令：
                    • /apihelp 或 /api帮助- 显示此帮助信息
                    • /apilist 或 /api列表 - 显示所有可用的API指令

                    🔧 使用方法：
                    直接输入配置的触发指令即可调用对应的API。
                    如果一个指令配置了多个API或多个url，系统会随机选择一个调用。
                    """
        yield event.plain_result(help_text)

    @filter.command("apilist", alias={"api列表", "APILIST"})
    async def api_list(self, event: AstrMessageEvent):
        """显示所有可用的API列表"""
        if not self.api_map:
            yield event.plain_result("暂无配置的API")
            return

        list_text = "可用API列表：\n\n"

        for command, apis in self.api_map.items():
            api_types = [api["type"] for api in apis]
            type_str = "/".join(api_types)
            list_text += f"• /{command} ({type_str}) - {len(apis)}个API\n"

        list_text += "\n💡 提示：直接输入指令即可调用对应的API"
        yield event.plain_result(list_text)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("api配置")
    async def api_conf(self, event: AstrMessageEvent):
        yield event.plain_result(str(self.config))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_all_messages(self, event: AstrMessageEvent):
        """处理所有消息，检查是否匹配API指令"""
        message = event.message_str.strip()

        # 1. 去掉开头 / 并按空格分割所有参数（支持无限个）
        parts = message.lstrip("/").split()
        if not parts:
            return

        # 2. 拆分指令 + 参数列表
        command = parts[0].lower()
        if command not in self.api_map:
            return

        # 检查是否匹配API指令
        # 随机选择一个API
        api_list = self.api_map[command]
        selected_api = random.choice(api_list)

        api_type = selected_api["type"]
        # 对params参数操作，copy一份，避免影响原来的配置
        api_config = copy.deepcopy(selected_api["config"])
        # 从url列表中随机选择一个
        api_url_list = api_config.get("api_url", "")
        api_url = random.choice(api_url_list)
        api_config["api_url"] = api_url
        params = api_config.get("params", "")

        if not self._should_trigger(event, api_config):
            return

        # 参数替换，将用户传递的参数替换到url或者params中
        if len(parts) > 1:
            args_list = parts[1:]
            args_len = len(args_list)
        else:
            args_len = 0
        if self._if_url_has_placeholders(url=api_url):
            key_list, key_len = self._get_placeholders(url=api_url)
            # yield event.plain_result(f"keylen={str(key_len)}")
            if args_len != key_len:
                param_placeholders = f"/{command} " + " ".join(
                    [f"{{{p}}}" for p in key_list]
                )
                yield event.plain_result(
                    f"❌ 参数数量不匹配，需要{key_len}个，实际传递了{args_len}个，用法：{param_placeholders}"
                )
                return
            else:
                api_config["api_url"] = self._replace_url_params(
                    url=api_url, args_list=args_list
                )
        elif self._get_params_empty_len(api_config.get("params", "")) != 0:
            key_list, key_len = self._get_params_empty_len(api_config.get("params", ""))
            # yield event.plain_result(f"paramslen={str(key_len)}")
            if args_len != key_len:
                param_placeholders = f"/{command} " + " ".join(
                    [f"{{{p}}}" for p in key_list]
                )
                yield event.plain_result(
                    f"❌ 参数数量不匹配，需要{key_len}个，实际传递了{args_len}个，用法：{param_placeholders}"
                )
                return
            else:
                api_config["params"] = self._replace_params(
                    params=params, args_list=args_list
                )
        elif args_len != 0:
            event.plain_result(f"❌ 该API请求无需额外参数")
            return

        # 检查频率限制
        user_id = event.get_sender_id()
        api_key = f"{command}_{api_type}"
        rate_limit = api_config.get("rate_limit", 0)
        if rate_limit == 0:
            rate_limit = self.config.get("global_rate_limit", 0)

        if not self.rate_limiter.is_allowed(user_id, api_key, rate_limit):
            yield event.plain_result("⚠️ 调用过于频繁，请稍后再试")
            event.stop_event()
            return

        try:
            # 调用API并获取响应
            response_data, content_type, media_type = await self._call_api(api_config)

            # 根据检测到的媒体类型调用对应的处理函数
            # 对于json类型，根据api类型处理
            # 其它类型，根据content_type获取的media_type处理
            if media_type == "json":
                handler = self.media_type_handlers[api_type]
                async for result in handler(response_data, api_config, event):
                    yield result
            elif media_type in self.media_type_handlers:
                handler = self.media_type_handlers[media_type]
                async for result in handler(response_data, api_config, event):
                    yield result
            else:
                yield event.plain_result(f"⚠️ 不支持的响应类型: {content_type}")

        except Exception as e:
            logger.error(f"API调用出错: {str(e)}")
            yield event.plain_result(f"❌ API调用失败: {str(e)}")

        # 停止事件传播，防止其他插件处理
        event.stop_event()
