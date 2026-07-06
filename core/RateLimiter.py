import time
import asyncio
from collections import defaultdict
from astrbot.api import logger


class RateLimiter:
    def __init__(self):
        self.user_calls = defaultdict(list)  # 用户全局调用记录
        self.api_calls = defaultdict(lambda: defaultdict(list))  # API维度调用记录
        self.expire_seconds = 60  # 统计窗口 60 秒
        self._cleanup_task = None  # 不在 __init__ 创建异步任务
        self._shutdown_event = asyncio.Event()  # 关闭信号

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

    async def shutdown(self):
        """优雅关闭：取消后台清理任务"""
        self._shutdown_event.set()
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._clean_all_expired()  # 最后一次清理

    async def _periodic_cleanup(self):
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=120)
                break  # shutdown 信号
            except asyncio.TimeoutError:
                pass  # 120s 超时，执行清理
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
