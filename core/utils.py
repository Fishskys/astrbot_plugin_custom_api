import dpath
import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_nested_value(data: Any, path: str) -> list:
    """
    采用dpath嵌套字典取值
    1.精确取值：data.0.urlsList.0.url
    2.模糊取值：data.*.urlsList.*.url
    3.多层通配符：**.url，如果不可用，请用单层通配符写法
    返回: list
    """
    if not path:
        return data if isinstance(data, list) else [data]
    try:
        result = dpath.values(data, path, separator=".")
        return result
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"dpath取值失败: path={path}, error={str(e)}")
        return []
