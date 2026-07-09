import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from astrbot.api import logger


class StatsTracker:
    """基于 SQLite 的 API 调用统计，按「日期 + API + 用户」做每日汇总。"""

    def __init__(self, data_path: Path):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_path / "stats.db"
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ── 数据库生命周期 ──────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取或创建数据库连接（延迟初始化）。"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def _init_db(self):
        """初始化表结构与索引。"""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                date     TEXT NOT NULL,
                api_name TEXT NOT NULL,
                user_id  TEXT NOT NULL,
                call_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (date, api_name, user_id)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calls_date ON calls(date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calls_api ON calls(api_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_calls_user ON calls(user_id)"
        )
        conn.commit()

    def shutdown(self):
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _range_clause(self, range_type: str) -> Tuple[str, Tuple[str, ...]]:
        """根据范围类型生成 WHERE 子句与参数。"""
        today = time.strftime("%Y-%m-%d")
        if range_type == "today":
            return "date = ?", (today,)
        if range_type == "month":
            month = today[:7]
            return "date LIKE ?", (f"{month}%",)
        return "", ()

    # ── 公共接口 ────────────────────────────────────────────────

    def record(self, api_name: str, user_id: str):
        """记录一次 API 调用。"""
        today = time.strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO calls (date, api_name, user_id, call_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(date, api_name, user_id) DO UPDATE SET
                call_count = call_count + 1
            """, (today, api_name, user_id))
            conn.commit()
        except Exception as e:
            logger.error(f"[StatsTracker] record 失败: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """获取 Dashboard 概览统计。"""
        today = time.strftime("%Y-%m-%d")
        conn = self._get_conn()

        total_calls = conn.execute(
            "SELECT COALESCE(SUM(call_count), 0) FROM calls"
        ).fetchone()[0]

        total_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM calls"
        ).fetchone()[0]

        today_calls = conn.execute(
            "SELECT COALESCE(SUM(call_count), 0) FROM calls WHERE date = ?",
            (today,),
        ).fetchone()[0]

        today_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM calls WHERE date = ?",
            (today,),
        ).fetchone()[0]

        top_apis = self.get_top_apis("today", 4)

        thirty_days_ago = time.strftime(
            "%Y-%m-%d", time.localtime(time.time() - 29 * 86400)
        )

        api_rows = conn.execute(
            "SELECT date, SUM(call_count) FROM calls "
            "WHERE date >= ? GROUP BY date ORDER BY date",
            (thirty_days_ago,),
        ).fetchall()
        api_map: Dict[str, int] = {r[0]: r[1] for r in api_rows}

        user_rows = conn.execute(
            "SELECT date, COUNT(DISTINCT user_id) FROM calls "
            "WHERE date >= ? GROUP BY date ORDER BY date",
            (thirty_days_ago,),
        ).fetchall()
        user_map: Dict[str, int] = {r[0]: r[1] for r in user_rows}

        api_trend = []
        user_trend = []
        for i in range(30):
            d = time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - (29 - i) * 86400)
            )
            api_trend.append({"date": d, "count": api_map.get(d, 0)})
            user_trend.append({"date": d, "count": user_map.get(d, 0)})

        return {
            "total_calls": total_calls,
            "total_users": total_users,
            "today_calls": today_calls,
            "today_users": today_users,
            "top_apis": top_apis,
            "api_trend": api_trend,
            "user_trend": user_trend,
        }

    def get_top_apis(self, range_type: str = "today", limit: int = 4) -> List[Dict[str, Any]]:
        """获取热门 API 排行榜。"""
        range_type = range_type if range_type in ("today", "month", "total") else "today"
        where_clause, params = self._range_clause(range_type)
        sql = (
            "SELECT api_name, SUM(call_count) AS total FROM calls "
            + (("WHERE " + where_clause) if where_clause else "")
            + " GROUP BY api_name ORDER BY total DESC LIMIT ?"
        )
        rows = self._get_conn().execute(sql, params + (limit,)).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows]

    def get_top_users(self, range_type: str = "today", limit: int = 10) -> List[Dict[str, Any]]:
        """获取用户调用次数排行榜。"""
        range_type = range_type if range_type in ("today", "month", "total") else "today"
        where_clause, params = self._range_clause(range_type)
        sql = (
            "SELECT user_id, SUM(call_count) AS total FROM calls "
            + (("WHERE " + where_clause) if where_clause else "")
            + " GROUP BY user_id ORDER BY total DESC LIMIT ?"
        )
        rows = self._get_conn().execute(sql, params + (limit,)).fetchall()
        return [{"user_id": r[0], "count": r[1]} for r in rows]

    def get_trend(self, trend_type: str = "calls", month: str = "") -> List[Dict[str, Any]]:
        """获取指定月份的趋势数据。"""
        if trend_type not in ("calls", "users"):
            trend_type = "calls"
        if not month or len(month) != 7 or "-" not in month:
            month = time.strftime("%Y-%m")

        conn = self._get_conn()
        if trend_type == "calls":
            rows = conn.execute(
                "SELECT date, SUM(call_count) FROM calls "
                "WHERE date LIKE ? GROUP BY date ORDER BY date",
                (f"{month}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT date, COUNT(DISTINCT user_id) FROM calls "
                "WHERE date LIKE ? GROUP BY date ORDER BY date",
                (f"{month}%",),
            ).fetchall()

        data_map = {r[0]: r[1] for r in rows}

        year, mon = map(int, month.split("-"))
        days_in_month = self._days_in_month(year, mon)
        result = []
        for day in range(1, days_in_month + 1):
            d = f"{year:04d}-{mon:02d}-{day:02d}"
            result.append({"date": d, "count": data_map.get(d, 0)})
        return result

    @staticmethod
    def _days_in_month(year: int, month: int) -> int:
        """返回某年某月的天数。"""
        if month == 12:
            next_month = f"{year + 1}-01-01"
        else:
            next_month = f"{year}-{month + 1:02d}-01"
        ts1 = time.mktime(time.strptime(f"{year}-{month:02d}-01", "%Y-%m-%d"))
        ts2 = time.mktime(time.strptime(next_month, "%Y-%m-%d"))
        return int((ts2 - ts1) / 86400)
