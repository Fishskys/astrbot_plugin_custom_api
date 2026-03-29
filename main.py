import random
import time
import json
import re
import mimetypes
import copy
import tempfile
import dpath

from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import urllib.parse

import aiohttp
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp


class RateLimiter:
    def __init__(self):
        self.user_calls = defaultdict(list)  # 用户全局调用记录
        self.api_calls = defaultdict(lambda: defaultdict(list))  # API维度调用记录
        self.expire_seconds = 60  # 统计窗口 60 秒
        self._cleanup_task = None  # 不在 __init__ 创建异步任务

    def _start_cleanup_task(self):
        """
        惰性启动：只有在需要时才创建后台任务
        任何框架、任何环境都不会报错
        """
        try:
            # 只启动一次
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            pass

    async def _periodic_cleanup(self):
        while True:
            await asyncio.sleep(120)
            try:
                self._clean_all_expired()
            except Exception as e:
                logger.error(f"[限流清理任务] 执行异常: {str(e)}", exc_info=True)

    def _clean_all_expired(self):
        """主动清理所有用户的过期记录"""
        now = time.time()
        cutoff = now - self.expire_seconds

        # 清理 user_calls
        for user_id in list(self.user_calls.keys()):
            # 只保留 60s 内的记录
            self.user_calls[user_id] = [
                t for t in self.user_calls[user_id] if t > cutoff
            ]
            # 如果用户没有任何记录了，直接删除键，释放内存
            if not self.user_calls[user_id]:
                del self.user_calls[user_id]

        # 清理 api_calls
        for api_key in list(self.api_calls.keys()):
            for user_id in list(self.api_calls[api_key].keys()):
                self.api_calls[api_key][user_id] = [
                    t for t in self.api_calls[api_key][user_id] if t > cutoff
                ]
                if not self.api_calls[api_key][user_id]:
                    del self.api_calls[api_key][user_id]
            # 如果 API 没有任何用户记录，删除 API 键
            if not self.api_calls[api_key]:
                del self.api_calls[api_key]

    def _rate_limit(self, user_id: str, api_key: str, limit: int) -> bool:
        # 自动启动清理任务
        self._start_cleanup_task()

        if limit <= 0:
            return False

        now = time.time()
        cutoff = now - self.expire_seconds
        # 惰性清理
        self.user_calls[user_id] = [t for t in self.user_calls[user_id] if t > cutoff]
        self.api_calls[api_key][user_id] = [
            t for t in self.api_calls[api_key][user_id] if t > cutoff
        ]

        # 判断是否超限
        if len(self.user_calls[user_id]) >= limit:
            return True
        if len(self.api_calls[api_key][user_id]) >= limit:
            return True

        # 添加新记录
        self.user_calls[user_id].append(now)
        self.api_calls[api_key][user_id].append(now)
        return False


@register(
    "astrbot_plugin_custom_api",
    "Fishskys",
    "支持多样化的外部API调用，可处理文本、图片、语音和视频类型API，支持自定义参数配置，关键词触发调用",
    "0.2.1",
)
class CustomAPIManager(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.global_timeout = config.get("global_timeout", 30)
        self.rate_limiter = RateLimiter()
        self.command_list = self._build_command_list()
        self.api_map = self._build_api_map()

        # 媒体类型映射
        self.media_type_handlers = {
            "text": self._process_text_response,
            "img": self._process_img_response,
            "audio": self._process_audio_response,
            "video": self._process_video_response,
        }

    def _build_command_list(self):
        """扁平化指令列表，面向用户"""
        command_list = defaultdict(list)
        custom_apis = self.config.get("custom_apis", [])

        for api_config in custom_apis:
            template_key = api_config.get("__template_key", "")
            api_name = api_config.get("api_name", "").lower()
            commands = api_name.split()

            if commands:
                for command in commands:
                    api_info = {
                        "type": template_key.replace(
                            "_type", ""
                        ),  # text, img, audio, video
                        "api_url": api_config.get("api_url", []),
                    }
                    command_list[command].append(api_info)

        return dict(command_list)

    def _build_api_map(self) -> Dict[str, List[Dict[str, Any]]]:
        """构建指令到API的映射，程序用"""
        api_map = defaultdict(list)
        custom_apis = self.config.get("custom_apis", [])

        for api_config in custom_apis:
            template_key = api_config.get("__template_key", "")
            api_name = api_config.get("api_name", "").lower()
            commands = api_name.split()

            if commands:
                for command in commands:
                    api_info = {
                        "type": template_key.replace(
                            "_type", ""
                        ),  # text, img, audio, video
                        "config": api_config,
                    }
                    api_map[command].append(api_info)

        return dict(api_map)

    @staticmethod
    def _get_nested_value(data: Any, path: str) -> list:
        """
        采用dpath嵌套字典取值
        1.精确取值：data.0.urlsList.0.url
        2.模糊取值：data.*.urlsList.*.url
        3.多层通配符：**.url，如果不可用，请用单层通配符写法
        """
        if not path:
            return data
        result = dpath.values(data, path, separator=".")
        return result

    @staticmethod
    def _if_url_has_placeholders(url: str) -> bool:
        # 判断url是否有待传参数
        return bool(re.search(r"\{(\w+)\}", url))

    @staticmethod
    def _get_placeholders(url: str) -> Any:
        # 返回url待传参数及数量
        key_list = re.findall(r"\{(\w+)\}", url)
        key_len = len(key_list)
        return key_list, key_len

    @staticmethod
    def _if_params_has_emptyvalues(params: dict) -> bool:
        # 判断params是否有空值
        if not params:
            return False
        empty_keys = [k for k, v in params.items() if v == ""]
        if not empty_keys:
            return False
        else:
            return True

    @staticmethod
    def _get_params_empty(params: dict) -> Any:
        # 返回参数列表空值
        empty_keys = [k for k, v in params.items() if v == ""]
        empty_keys_len = len(empty_keys)
        return empty_keys, empty_keys_len

    @staticmethod
    def _replace_url_params(url: str, args_list: list):
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
            logger.error(f"❌ 在处理url占位符时发生错误: {str(e)}")
            raise

    @staticmethod
    def _replace_params(args_list: list, params: dict) -> list:
        """
        按顺序将用户输入的参数填充到值为空的参数字典中
        """
        empty_keys = [k for k, v in params.items() if v == ""]
        for key, value in zip(empty_keys, args_list):
            params[key] = value
        return params

    def _should_trigger(self, event: AstrMessageEvent, selected_api: dict) -> bool:
        """
        判断是否应该触发API
        1. 单个API配置优先
        2. 没有则使用全局配置
        """
        api_config = selected_api.get("config", {})
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

    def _is_rate_limit(self, event: AstrMessageEvent, selected_api: dict) -> bool:
        """
        返回True代表达到速率限制
        """
        user_id = event.get_sender_id()
        api_config = selected_api.get("config", {})
        command = api_config.get("api_name", "")
        api_type = selected_api.get("type", "")
        api_key = f"{command}_{api_type}"
        rate_limit = api_config.get("api_rate_limit", 0)
        if rate_limit == 0:
            rate_limit = self.config.get("global_rate_limit", 0)

        if self.rate_limiter._rate_limit(user_id, api_key, rate_limit):
            return True
        else:
            return False

    def _params_handle(self, command: str, parts: list, selected_api: dict):
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
                # raise Exception(f"❌ 未配置 API 地址")
            api_url = random.choice(api_url_list)
        api_config["api_url"] = api_url

        if len(parts) > 1:
            args_list = parts[1:]
            args_len = len(args_list)
        else:
            args_list = []
            args_len = 0
        # url有占位符情况
        if self._if_url_has_placeholders(url=api_url):
            key_list, key_len = self._get_placeholders(url=api_url)
            if args_len != key_len:
                param_placeholders = f"/{command} " + " ".join(
                    [f"{{{p}}}" for p in key_list]
                )
                err_msg = f"❌ 参数数量不匹配，url占位符需要{key_len}个值，实际传递了{args_len}个，用法：{param_placeholders}"
                return err_msg, api_config
            else:
                api_config["api_url"] = self._replace_url_params(
                    url=api_url, args_list=args_list
                )
                return None, api_config
        # params有空值情况
        elif self._if_params_has_emptyvalues(api_config.get("params", {})):
            key_list, key_len = self._get_params_empty(api_config.get("params", {}))
            if args_len != key_len:
                param_placeholders = f"/{command} " + " ".join(
                    [f"{{{p}}}" for p in key_list]
                )
                err_msg = f"❌ 参数数量不匹配，params需要{key_len}个参数值，实际传递了{args_len}个，用法：{param_placeholders}"
                return err_msg, api_config
            else:
                api_config["params"] = self._replace_params(
                    params=params, args_list=args_list
                )
                return None, api_config
        elif args_len != 0:
            err_msg = f"❌ 该API请求无需额外参数"
            return err_msg, api_config
            # raise Exception(f"❌ 该API请求无需额外参数")
        else:
            return None, api_config

    def _detect_media_type(self, content_type: str, url: str = "") -> str:
        """
        根据Content-Type和URL检测媒体类型
        返回值: text, img, audio, video, other
        """
        if not content_type:
            # 从URL推断类型
            parsed_url = urllib.parse.urlparse(url)
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
        global_timeout = self.config.get("global_timeout", 30)
        timeout = api_config.get("timeout", global_timeout)
        # timeout 在配置文件中只能配置为int类型，这里仅检测是否为负数
        if timeout < 0:
            timeout = 30

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
                                    # 捕获完整JSON异常
                                    response_data = await response.json()
                                except (json.JSONDecodeError, aiohttp.ContentTypeError):
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
                                    # 捕获完整JSON异常
                                    response_data = await response.json()
                                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                                    response_data = await response.text()
                            else:
                                response_data = await response.read()
                        else:
                            logger.error(f"❌ API请求失败，状态码: {response.status}")
                        return response_data, content_type, media_type
                else:
                    raise Exception(f"❌ 不支持的请求方法: {method}，请修改后台配置")

        except asyncio.TimeoutError:
            logger.warning(f"⚠️ 请求超时")
            return response_data, content_type, media_type

        except Exception as e:
            logger.error(f"❌ API调用失败: {str(e)}")
            return response_data, content_type, media_type

    # 响应处理
    async def _process_text_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理文本类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if isinstance(data, dict) and data_path:
                text_list = self._get_nested_value(data, data_path)
            elif isinstance(data, str):
                text_list = [data.strip()]
            else:
                yield event.plain_result("⚠️ API返回了不支持的文本类型")
                return

            if text_list:
                for text in text_list:
                    if isinstance(text, str):
                        yield event.plain_result(text.strip())
                return
            else:
                yield event.plain_result("⚠️ API返回空文本或提取路径错误")
                return

        except Exception as e:
            logger.error(f"处理文本响应失败: {str(e)}", exc_info=True)
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
                    yield event.plain_result("⚠️ 提取路径未找到图片内容")
                    return
                chain = []
                try:
                    for img in img_content:
                        if img.startswith(("http://", "https://")):
                            chain.append(Comp.Image.fromURL(img))
                        # json中有base64 str
                        elif "base64," in img:
                            img = img.split(",")[1]
                            chain.append(Comp.Image.fromBase64(img))
                    yield event.chain_result(chain)
                    return
                except Exception as e:
                    yield event.plain_result("❌ 尝试从JSON中提取并发送图片时失败")
                    logger.error(
                        f"尝试从JSON中提取并发送图片时失败: {str(e)}", exc_info=True
                    )
                    return

            # 二进制图片
            elif isinstance(data, bytes):
                try:
                    img_bytes = data
                    chain = [Comp.Image.fromBytes(img_bytes)]
                    yield event.chain_result(chain)
                    return
                except Exception as e:
                    yield event.plain_result("❌ 尝试发送二进制格式图片失败")
                    logger.error(f"尝试发送二进制格式图片失败: {str(e)}", exc_info=True)
                    return

            # 3. 纯字符串 Base64
            elif isinstance(data, str):
                try:
                    if "base64," in data:
                        data = data.split("base64,")[1]
                    chain = [Comp.Image.fromBase64(data)]
                    yield event.chain_result(chain)
                    return
                except Exception as e:
                    yield event.plain_result("❌ 尝试发送base64格式图片失败")
                    logger.error(f"尝试发送base64格式图片失败: {str(e)}", exc_info=True)
                    return
            else:
                yield event.plain_result(f"❌ 不支持的图片格式")
                return
        except Exception as e:
            logger.error(f"处理图片响应失败: {str(e)}", exc_info=True)
            yield event.plain_result(f"❌ 图片处理失败: {str(e)}")

    async def _process_audio_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理语音类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if data_path and isinstance(data, dict):
                # 从JSON中获取音频URL
                audio_url_list = self._get_nested_value(data, data_path)
                if audio_url_list:
                    chain = []
                    for audio_url in audio_url_list:
                        # 构建语音消息链
                        chain.append(Comp.Record(url=audio_url))
                    yield event.chain_result(chain)
                else:
                    yield event.plain_result("⚠️ 提取路径未找到音频URL")
                    return
            else:
                # 处理音频二进制数据
                # 保存音频到临时文件
                # 利用with的自动清理机制
                with tempfile.NamedTemporaryFile(
                    delete=True, suffix=".mp3"
                ) as tmp_file:
                    tmp_file.write(data)
                    tmp_file.flush()
                    tmp_file_path = tmp_file.name
                    chain = [Comp.Record(file=tmp_file_path)]
                    yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"处理音频响应失败: {str(e)}", exc_info=True)
            yield event.plain_result(f"❌ 音频处理失败: {str(e)}")

    async def _process_video_response(
        self, data: Any, api_config: Dict[str, Any], event: AstrMessageEvent
    ):
        """处理视频类型响应"""
        try:
            data_path = api_config.get("data_path", "")

            if data_path and isinstance(data, dict):
                # 从JSON中获取视频URL
                video_url_list = self._get_nested_value(data, data_path)
                if video_url_list:
                    # 构建视频消息链
                    chain = []
                    for video_url in video_url_list:
                        chain.append(Comp.Video.fromURL(url=video_url))
                    yield event.chain_result(chain)
                else:
                    yield event.plain_result("⚠️ 提取路径未找到视频URL")
                    return
            else:
                # 处理视频二进制数据
                # 保存视频到临时文件
                # 利用with的自动清理机制
                with tempfile.NamedTemporaryFile(
                    delete=True, suffix=".mp4"
                ) as tmp_file:
                    tmp_file.write(data)
                    tmp_file.flush()
                    tmp_file_path = tmp_file.name
                    chain = [Comp.Video(file=tmp_file_path)]
                    yield event.chain_result(chain)

        except Exception as e:
            logger.error(f"处理视频响应失败: {str(e)}", exc_info=True)
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
        if not self.command_list:
            yield event.plain_result("暂无配置的API")
            return

        list_text = "可用API列表：\n\n"

        for command, apis in self.command_list.items():
            if apis:
                api_num = len(apis)
                api_type = apis[0].get("type", "")
                # url_num = [len(api.get("api_url", [])) for api in apis]
                # url_text = "、".join([f"{{p}}" for p in url_num])
                list_text += f"• /{command} ({api_type}) - {api_num}个api\n"

        list_text += "\n💡 提示：直接输入指令即可调用对应的API"
        yield event.plain_result(list_text)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("api配置")
    async def api_conf(self, event: AstrMessageEvent):
        yield event.plain_result(str(self.command_list))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_all_messages(self, event: AstrMessageEvent):
        """处理所有消息，检查是否匹配API指令"""
        message = event.message_str.strip()

        # 去掉开头 / 并按空格分割所有参数（支持无限个），以支持可配置的上下文自动触发，设置中可关闭自动触发
        parts = message.lstrip("/").split()
        if not parts:
            return

        # 指令匹配检测
        command = parts[0].lower()
        if command not in self.command_list:
            return

        # 检查是否匹配API指令
        # 随机选择一个API
        api_list = self.api_map.get(command, [])
        if not api_list:
            yield event.plain_result("❌ 未配置 API 地址")
            return

        selected_api = random.choice(api_list)
        api_type = selected_api.get("type", "text")

        # 触发条件检测
        if not self._should_trigger(event=event, selected_api=selected_api):
            return
        # 速率检测
        if self._is_rate_limit(event=event, selected_api=selected_api):
            yield event.plain_result("⚠️ 调用过于频繁，请稍后再试")
            event.stop_event()
            return
        # 参数处理
        err_msg, api_config = self._params_handle(
            command=command, parts=parts, selected_api=selected_api
        )
        if err_msg:
            yield event.plain_result(err_msg)
            event.stop_event()
            return
        if not api_config:
            event.stop_event()
            return

        try:
            # 调用API并获取响应
            response_data, content_type, media_type = await self._call_api(api_config)
            if response_data is None:
                yield event.plain_result(f"⚠️ 未获取到有效内容")
                return
            # 根据检测到的媒体类型调用对应的处理函数
            # 对于json类型，根据api类型处理
            # 其它类型，根据content_type获取的media_type处理
            if media_type == "json" and api_type in self.media_type_handlers:
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
            logger.error(f"API调用出错: {str(e)}", exc_info=True)
            yield event.plain_result(f"❌ API调用失败: {str(e)}")

        # 停止事件传播，防止其他插件处理
        event.stop_event()
