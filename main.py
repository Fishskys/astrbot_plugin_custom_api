import random
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
import os
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from pathlib import Path
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


from .core.RateLimiter import RateLimiter
from .core.response_handle import (
    process_select,
    process_text_response,
    process_img_response,
    process_audio_response,
    process_video_response,
)
from .core.client import call_api
from .core.params import params_handle
from .core.page_api import PageAPI
from .core.stats_tracker import StatsTracker


@register(
    "astrbot_plugin_custom_api",
    "Fishskys",
    "支持多样化的外部API调用，可处理文本、图片、语音和视频类型API，支持自定义参数配置，关键词触发调用",
    "0.3.1",
)
class CustomAPIManager(Star):
    def __init__(self, context: Context, config: Dict[str, Any]):
        super().__init__(context)
        self.config = config
        self.global_timeout = config.get("global_default_timeout", 15)
        self.rate_limiter = RateLimiter()
        self.command_list = self._build_command_list()
        self.api_map = self._build_api_map()
        self.plugin_data_path = (
            Path(get_astrbot_data_path()) / "plugin_data" / self.name
        )
        os.makedirs(self.plugin_data_path, exist_ok=True)
        # 调用统计
        self.stats_tracker = StatsTracker(self.plugin_data_path)
        # 注册 Pages Web API（逻辑在 core/page_api.py）
        self.page_api = PageAPI(self)
        self.page_api.register()
        # 媒体类型映射
        self.media_type_handlers = {
            "text": process_text_response,
            "img": process_img_response,
            "audio": process_audio_response,
            "video": process_video_response,
            "default": process_text_response,
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

        return self.rate_limiter._rate_limit(user_id, api_key, rate_limit)

    # ── 聊天命令处理 ──────────────────────────────────────────────

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
        # 记录调用统计
        user_id = event.get_sender_id()
        api_config_for_stats = selected_api.get("config", {})
        api_name = f"{api_config_for_stats.get('api_name', '')}_{selected_api.get('type', '')}"
        self.stats_tracker.record(api_name, user_id)
        # 参数处理
        err_msg, api_config = params_handle(
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
            response_data, content_type, media_type = await call_api(
                api_config, global_timeout=self.global_timeout
            )
            if response_data is None:
                yield event.plain_result(f"⚠️ 未获取到有效内容，具体请查看日志")
                return
            # 根据检测到的媒体类型调用对应的处理函数
            # 对于json类型，根据api类型处理
            # 其它类型，根据content_type获取的media_type处理
            process_err, handler = process_select(
                self.media_type_handlers, media_type=media_type, api_type=api_type
            )
            if process_err:
                yield event.plain_result(process_err)
                return
            async for result in handler(
                response_data, api_config, event, self.plugin_data_path
            ):
                yield result

        except Exception as e:
            logger.error(f"API调用出错: {str(e)}", exc_info=True)
            yield event.plain_result(f"❌ API调用失败: {str(e)}")

        # 停止事件传播，防止其他插件处理
        event.stop_event()
