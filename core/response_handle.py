import tempfile
import urllib.parse
import mimetypes

from typing import Dict, Any
from astrbot.api import logger
import astrbot.api.message_components as Comp
from .utils import get_nested_value


def process_select(media_type_handlers: dict, media_type: str, api_type: str):
    """
    文本或json类型返回值可能是网url或者含url的字典
    """
    err_msg = ""
    if media_type in ["json", "text"] and api_type in media_type_handlers:
        return err_msg, media_type_handlers[api_type]
    elif media_type in media_type_handlers:
        return err_msg, media_type_handlers[media_type]
    else:
        err_msg = f"不支持的API返回类型"
        return err_msg, media_type_handlers["default"]


def detect_media_type(content_type: str, url: str = "") -> str:
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
        ct in content_type for ct in ["text/", "application/json", "application/xml"]
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


async def process_text_response(data: Any, api_config: Dict[str, Any], event):
    """处理文本类型响应"""
    try:
        data_path = api_config.get("data_path", "")

        if isinstance(data, dict):
            if data_path:
                text_list = get_nested_value(data, data_path)
            else:
                text_list = data
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


async def process_img_response(data: Any, api_config: Dict[str, Any], event):
    """处理图片类型响应"""
    try:
        chain = []
        data_path = api_config.get("data_path", "")

        if data_path and isinstance(data, dict):
            # 从JSON中获取图片URL
            img_content = get_nested_value(data, data_path)
            if not img_content:
                yield event.plain_result("⚠️ 提取路径未找到图片内容")
                return
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
            if img.startswith(("http://", "https://")):
                chain.append(Comp.Image.fromURL(img))
                yield event.chain_result(chain)
                return
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


async def process_audio_response(data: Any, api_config: Dict[str, Any], event):
    """处理语音类型响应"""
    try:
        chain = []
        data_path = api_config.get("data_path", "")

        if data_path and isinstance(data, dict):
            # 从JSON中获取音频URL
            audio_url_list = get_nested_value(data, data_path)
            if audio_url_list:
                for audio_url in audio_url_list:
                    # 构建语音消息链
                    chain.append(Comp.Record(url=audio_url))
                yield event.chain_result(chain)
            else:
                yield event.plain_result("⚠️ 提取路径未找到音频URL")
                return
        elif isinstance(data, str):
            if data.startswith(("http://", "https://")):
                chain.append(Comp.Record.fromURL(data))
                yield event.chain_result(chain)
        elif isinstance(data, bytes):
            # 利用with的自动清理机制
            with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as tmp_file:
                tmp_file.write(data)
                tmp_file.flush()
                tmp_file_path = tmp_file.name
                chain = [Comp.Record(file=tmp_file_path)]
                yield event.chain_result(chain)

    except Exception as e:
        logger.error(f"处理音频响应失败: {str(e)}", exc_info=True)
        yield event.plain_result(f"❌ 音频处理失败: {str(e)}")


async def process_video_response(data: Any, api_config: Dict[str, Any], event):
    """处理视频类型响应"""
    try:
        chain = []
        data_path = api_config.get("data_path", "")

        if data_path and isinstance(data, dict):
            # 从JSON中获取视频URL
            video_url_list = get_nested_value(data, data_path)
            if video_url_list:
                # 构建视频消息链
                for video_url in video_url_list:
                    chain.append(Comp.Video.fromURL(url=video_url))
                yield event.chain_result(chain)
            else:
                yield event.plain_result("⚠️ 提取路径未找到视频URL")
                return
        elif isinstance(data, str):
            if data.startswith(("http://", "https://")):
                chain.append(Comp.Video.fromURL(data))
                yield event.chain_result(chain)
        elif isinstance(data, bytes):
            # 利用with的自动清理机制
            with tempfile.NamedTemporaryFile(delete=True, suffix=".mp4") as tmp_file:
                tmp_file.write(data)
                tmp_file.flush()
                tmp_file_path = tmp_file.name
                chain = [Comp.Video(file=tmp_file_path)]
                yield event.chain_result(chain)

    except Exception as e:
        logger.error(f"处理视频响应失败: {str(e)}", exc_info=True)
        yield event.plain_result(f"❌ 视频处理失败: {str(e)}")
