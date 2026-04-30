import dpath
from typing import Dict, List, Any, Tuple


def get_nested_value(data: Any, path: str) -> list:
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
