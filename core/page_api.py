import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any, Dict

from astrbot.api import logger
from astrbot.api.web import error_response, file_response, json_response, request
from astrbot.core.star.config import update_config

from .client import call_api


class PageAPI:
    """负责 AstrBot Pages 相关 Web API 的注册与处理。

    将 Pages 后端逻辑从 main.py 中剥离，方便维护与扩展。
    """

    def __init__(self, plugin):
        """plugin: CustomAPIManager 实例，用于访问 config / rate_limiter 等状态。"""
        self.plugin = plugin
        self.context = plugin.context
        self.name = plugin.name
        self._registered_routes: set[str] = set()

    def register(self) -> None:
        """注册所有 Pages Web API 路由，并在冲突时跳过。"""
        routes = [
            (f"/{self.name}/overview/data", self._overview_data, ["GET"], "API 总览数据"),
            (f"/{self.name}/config/list", self._config_list, ["GET"], "API 配置列表"),
            (f"/{self.name}/config/add", self._config_add, ["POST"], "新增 API"),
            (f"/{self.name}/config/update", self._config_update, ["POST"], "更新 API"),
            (f"/{self.name}/config/delete", self._config_delete, ["POST"], "删除 API"),
            (f"/{self.name}/config/global", self._config_global, ["GET"], "全局配置"),
            (
                f"/{self.name}/config/save-global",
                self._config_save_global,
                ["POST"],
                "保存全局配置",
            ),
            (f"/{self.name}/config/export", self._config_export, ["GET"], "导出配置"),
            (f"/{self.name}/config/import", self._config_import, ["POST"], "导入配置"),
            (f"/{self.name}/config/test", self._config_test, ["POST"], "API 测试请求"),
            (f"/{self.name}/stats/summary", self._stats_summary, ["GET"], "统计摘要"),
            (f"/{self.name}/stats/top-apis", self._stats_top_apis, ["GET"], "热门 API 排行"),
            (f"/{self.name}/stats/top-users", self._stats_top_users, ["GET"], "用户调用排行"),
            (f"/{self.name}/stats/trend", self._stats_trend, ["GET"], "月度趋势"),
        ]

        for route, handler, methods, desc in routes:
            if route in self._registered_routes:
                logger.warning(f"[PageAPI] 路由已注册，跳过: {route}")
                continue
            try:
                self.context.register_web_api(route, handler, methods, desc)
                self._registered_routes.add(route)
                logger.info(f"[PageAPI] 注册路由: {route}")
            except Exception as e:
                logger.error(f"[PageAPI] 注册路由失败 {route}: {e}")

    # ── 内部工具 ──────────────────────────────────────────────

    def _save_config(self) -> None:
        """持久化 custom_apis 配置到 AstrBot 配置文件。"""
        try:
            update_config(self.name, "custom_apis", self.plugin.config.get("custom_apis", []))
        except Exception as e:
            logger.error(f"[PageAPI] 保存配置失败: {e}")

    def _save_global_config(self) -> None:
        """持久化全局配置。"""
        try:
            for key in [
                "global_default_timeout",
                "global_rate_limit",
                "default_trigger_type",
            ]:
                val = self.plugin.config.get(key)
                if val is not None:
                    update_config(self.name, key, val)
        except Exception as e:
            logger.error(f"[PageAPI] 保存全局配置失败: {e}")

    def _rebuild_maps(self) -> None:
        """配置变更后重建指令映射。"""
        self.plugin.command_list = self.plugin._build_command_list()
        self.plugin.api_map = self.plugin._build_api_map()

    def _validate_config_item(self, item: Dict[str, Any]) -> Any:
        """对单个 API 配置项做基础校验，返回 error_response 或 None。"""
        api_name = item.get("api_name", "").strip()
        if not api_name:
            return error_response("api_name 不能为空", status_code=400)
        api_url = item.get("api_url")
        if not api_url or (isinstance(api_url, list) and not any(api_url)):
            return error_response("api_url 不能为空", status_code=400)
        method = item.get("method", "GET")
        if method not in ("GET", "POST"):
            return error_response("method 必须为 GET 或 POST", status_code=400)
        template_key = item.get("__template_key", "")
        if template_key not in ("text_type", "img_type", "audio_type", "video_type"):
            item["__template_key"] = "text_type"
        timeout = item.get("timeout", 0)
        if not isinstance(timeout, (int, float)) or timeout < 0 or timeout > 300:
            item["timeout"] = 0
        rate = item.get("api_rate_limit", 0)
        if not isinstance(rate, (int, float)) or rate < 0:
            item["api_rate_limit"] = 0
        trigger_type = item.get("trigger_type", "global")
        if trigger_type not in ("global", "direct", "mention_only"):
            item["trigger_type"] = "global"
        return None

    # ── 路由处理器 ──────────────────────────────────────────────

    async def _overview_data(self):
        """返回已配置 API 总览数据。"""
        return json_response({"custom_apis": self.plugin.config.get("custom_apis", [])})

    async def _config_list(self):
        """返回 API 配置列表。"""
        return json_response(self.plugin.config.get("custom_apis", []))

    async def _config_global(self):
        """返回全局配置。"""
        return json_response(
            {
                "global_default_timeout": self.plugin.config.get(
                    "global_default_timeout", 15
                ),
                "global_rate_limit": self.plugin.config.get("global_rate_limit", 0),
                "global_retry_count": self.plugin.config.get("global_retry_count", 0),
                "default_trigger_type": self.plugin.config.get(
                    "default_trigger_type", "mention_only"
                ),
            }
        )

    async def _config_save_global(self):
        """保存全局配置（按官方文档建议做输入校验）。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象", status_code=400)

        timeout = payload.get("global_default_timeout")
        rate_limit = payload.get("global_rate_limit")
        retry_count = payload.get("global_retry_count")
        trigger_type = payload.get("default_trigger_type")

        if timeout is not None:
            if not isinstance(timeout, (int, float)) or timeout < 1 or timeout > 120:
                return error_response(
                    "global_default_timeout 必须是 1-120 的整数", status_code=400
                )
            self.plugin.config["global_default_timeout"] = int(timeout)
            self.plugin.global_timeout = int(timeout)

        if rate_limit is not None:
            if not isinstance(rate_limit, (int, float)) or rate_limit < 0:
                return error_response(
                    "global_rate_limit 必须是非负整数", status_code=400
                )
            self.plugin.config["global_rate_limit"] = int(rate_limit)

        if retry_count is not None:
            if not isinstance(retry_count, (int, float)) or retry_count < 0 or retry_count > 10:
                return error_response(
                    "global_retry_count 必须是 0-10 的整数", status_code=400
                )
            self.plugin.config["global_retry_count"] = int(retry_count)
            self.plugin.global_retry_count = int(retry_count)

        if trigger_type is not None:
            if trigger_type not in ("direct", "mention_only"):
                return error_response(
                    "default_trigger_type 必须是 direct 或 mention_only",
                    status_code=400,
                )
            self.plugin.config["default_trigger_type"] = trigger_type

        self._save_global_config()
        return json_response({"ok": True})

    async def _config_add(self):
        """新增 API 配置（按官方文档建议做输入校验）。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象", status_code=400)

        config_item = payload.get("config", {})
        if not isinstance(config_item, dict):
            return error_response("config 必须为对象", status_code=400)

        err = self._validate_config_item(config_item)
        if err:
            return err

        api_name = config_item["api_name"].strip()
        custom_apis = self.plugin.config.get("custom_apis", [])
        custom_apis.append(config_item)
        self.plugin.config["custom_apis"] = custom_apis
        self._save_config()
        self._rebuild_maps()
        logger.info(f"[PageAPI] 新增 API: {api_name}")
        return json_response({"ok": True})

    async def _config_update(self):
        """更新 API 配置。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象", status_code=400)

        index = payload.get("index")
        config_item = payload.get("config", {})

        if index is None or not isinstance(index, int):
            return error_response("index 无效", status_code=400)

        custom_apis = self.plugin.config.get("custom_apis", [])
        if index < 0 or index >= len(custom_apis):
            return error_response(f"index {index} 超出范围", status_code=400)

        if not isinstance(config_item, dict):
            return error_response("config 必须为对象", status_code=400)

        err = self._validate_config_item(config_item)
        if err:
            return err

        custom_apis[index] = config_item
        self.plugin.config["custom_apis"] = custom_apis
        self._save_config()
        self._rebuild_maps()
        logger.info(f"[PageAPI] 更新 API 配置 index={index}: {config_item['api_name']}")
        return json_response({"ok": True})

    async def _config_delete(self):
        """删除 API 配置。"""
        payload = await request.json(default={})
        if not isinstance(payload, dict):
            return error_response("请求体必须为 JSON 对象", status_code=400)

        index = payload.get("index")
        if index is None or not isinstance(index, int):
            return error_response("index 无效", status_code=400)

        custom_apis = self.plugin.config.get("custom_apis", [])
        if index < 0 or index >= len(custom_apis):
            return error_response(f"index {index} 超出范围", status_code=400)

        removed = custom_apis.pop(index)
        self.plugin.config["custom_apis"] = custom_apis
        self._save_config()
        self._rebuild_maps()
        logger.info(f"[PageAPI] 删除 API: {removed.get('api_name')}")
        return json_response({"ok": True})

    async def _config_export(self):
        """导出 API 配置为 JSON 文件下载（使用官方 file_response）。"""
        export_path = Path(self.plugin.plugin_data_path) / "api_config_export.json"
        data = self.plugin.config.get("custom_apis", [])
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return file_response(
            str(export_path),
            filename="api_config.json",
            content_type="application/json",
        )

    async def _config_import(self):
        """从 JSON 导入 API 配置，会覆盖现有配置。"""
        try:
            files = await request.files()
            file_field = files.get("file") if files else None
            if not file_field:
                return error_response("未上传文件", status_code=400)
            content = file_field.read()
            if asyncio.iscoroutine(content):
                content = await content
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            imported = json.loads(content)
            if not isinstance(imported, list):
                return error_response("文件内容必须是 API 配置数组", status_code=400)
            for item in imported:
                if not isinstance(item, dict):
                    return error_response("数组每项必须是对象", status_code=400)
                err = self._validate_config_item(item)
                if err:
                    return err
            self.plugin.config["custom_apis"] = imported
            self._save_config()
            self._rebuild_maps()
            logger.info(f"[PageAPI] 导入配置，共 {len(imported)} 个 API")
            return json_response({"ok": True, "count": len(imported)})
        except json.JSONDecodeError as e:
            return error_response(f"JSON 解析失败: {e}", status_code=400)
        except Exception as e:
            logger.error(f"[PageAPI] 导入配置失败: {e}")
            return error_response(f"导入失败: {e}", status_code=500)

    async def _config_test(self):
        """实际发起一次 API 测试请求，不保存配置。"""
        try:
            payload = await request.json(default={})
            if not isinstance(payload, dict):
                return error_response("请求体必须为 JSON 对象", status_code=400)

            config_item = payload.get("config", {})
            if not isinstance(config_item, dict):
                return error_response("config 必须为对象", status_code=400)

            api_url = config_item.get("api_url")
            if not api_url or (isinstance(api_url, list) and not any(api_url)):
                return error_response("api_url 不能为空", status_code=400)

            method = config_item.get("method", "GET").upper()
            if method not in ("GET", "POST"):
                return error_response("method 必须为 GET 或 POST", status_code=400)

            # 统一成列表，但测试时只取第一个地址
            urls = api_url if isinstance(api_url, list) else [api_url]
            urls = [u for u in urls if u]
            if not urls:
                return error_response("api_url 不能为空", status_code=400)

            test_config = {
                **config_item,
                "api_url": urls[0],  # 测试时只使用第一个 URL
                "method": method,
                "params": config_item.get("params", {}) or {},
                "headers": config_item.get("headers", {}) or {},
                "body": config_item.get("body", {}) or {},
                "timeout": config_item.get("timeout", 0),
                "max_size": config_item.get("max_size", 0),
            }

            t0 = time.perf_counter()
            response_data, content_type, media_type, status_code = await call_api(
                test_config,
                global_timeout=self.plugin.global_timeout,
                retry_count=self.plugin.global_retry_count,
            )

            if media_type == "img" and isinstance(response_data, bytes):
                b64 = base64.b64encode(response_data).decode("utf-8")
                response_data = f"data:{content_type or 'image/png'};base64,{b64}"

            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            return json_response({
                "http_code": status_code,
                "content_type": content_type,
                "media_type": media_type,
                "response_data": response_data,
                "elapsed_ms": elapsed_ms,
            })
        except Exception as e:
            logger.error(f"[PageAPI] API 测试失败: {e}")
            return error_response(f"测试失败: {e}", status_code=500)

    async def _stats_summary(self):
        """返回 Dashboard 概览统计。"""
        if not hasattr(self.plugin, "stats_tracker") or self.plugin.stats_tracker is None:
            return json_response({
                "total_calls": 0, "total_users": 0,
                "today_calls": 0, "today_users": 0,
                "top_apis": [], "api_trend": [], "user_trend": [],
            })
        return json_response(self.plugin.stats_tracker.get_summary())

    async def _stats_top_apis(self):
        """返回热门 API 排行榜。"""
        if not hasattr(self.plugin, "stats_tracker") or self.plugin.stats_tracker is None:
            return json_response({"range": "today", "items": []})
        range_type = request.query.get("range", "today") if hasattr(request, "query") else "today"
        if range_type not in ("today", "month", "total"):
            range_type = "today"
        items = self.plugin.stats_tracker.get_top_apis(range_type, limit=10)
        return json_response({"range": range_type, "items": items})

    async def _stats_top_users(self):
        """返回用户调用次数排行榜。"""
        if not hasattr(self.plugin, "stats_tracker") or self.plugin.stats_tracker is None:
            return json_response({"range": "today", "items": []})
        range_type = request.query.get("range", "today") if hasattr(request, "query") else "today"
        if range_type not in ("today", "month", "total"):
            range_type = "today"
        items = self.plugin.stats_tracker.get_top_users(range_type, limit=10)
        return json_response({"range": range_type, "items": items})

    async def _stats_trend(self):
        """返回指定月份的趋势数据。"""
        if not hasattr(self.plugin, "stats_tracker") or self.plugin.stats_tracker is None:
            return json_response({"type": "calls", "month": time.strftime("%Y-%m"), "data": []})
        trend_type = request.query.get("type", "calls") if hasattr(request, "query") else "calls"
        month = request.query.get("month", time.strftime("%Y-%m")) if hasattr(request, "query") else time.strftime("%Y-%m")
        if trend_type not in ("calls", "users"):
            trend_type = "calls"
        if not month or len(month) != 7 or "-" not in month:
            month = time.strftime("%Y-%m")
        data = self.plugin.stats_tracker.get_trend(trend_type, month)
        return json_response({
            "type": trend_type,
            "month": month,
            "data": data,
            "debug": {
                "query_type": request.query.get("type") if hasattr(request, "query") else None,
                "query_month": request.query.get("month") if hasattr(request, "query") else None,
                "row_count": len(data),
            }
        })
