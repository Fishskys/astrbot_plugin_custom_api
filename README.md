# 🌟 AstrBot 自定义API插件
# astrbot-plugin-custom-api
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-ff69b4?style=for-the-badge)](https://github.com/AstrBotDevs/AstrBot)


支持多样化的外部API接口调用，可处理文本、图片、语音和视频类型API，支持自定义参数配置，关键词触发调用


## 🌟 功能特性
- ✅ **多类型响应支持**
自动识别文本、图片、音频、视频，JSON 响应自动提取媒体 URL
- ✅ **动态多参数配置**
支持 URL嵌入参数和params，请求头 / 请求体均可替换
- ✅ **双重触发模式**
全局 + 单 API 配置：直接触发 / 仅 @机器人触发
- ✅ **频率限制**
支持用户级 / API 级调用频率限制，防止滥用
- ✅ **随机 API 负载**

<!-- 这是注释内容，不会显示在渲染结果中 

## 🚀 快速使用
### 方式1：通过AstrBot插件市场安装（推荐）
在插件市场搜索astrbot-plugin-custom-api

### 方式2：手动安装
下载本项目压缩包astrbot_plugin_custom_api.zip，在webui上传即可

-->

## 🚀 快速使用
### 手动安装
下载本项目压缩包astrbot_plugin_custom_api.zip，在webui上传即可

## 📖 使用说明
### 指令触发
| 指令 | 权限 | 说明 |
| -- | -- | -- |
| `/apihelp`| 全体成员 | 项目使用帮助 |
| `/apilist`| 全体成员 | api列表 |
| `/api配置` | 管理员  | api配置json|
| `/{command}` | 全体成员  | 配置的触发命令|

## ⚙️ 配置示例

| 配置项 | 类型 | 默认值 | 说明 |
| ------ | ---- | ------ | ---- |
| 触发命令 | str | default_api | api触发命令|

当多条API配置的触发命令相同时，触发时会随机选择一个触发，但并不推荐这样设置，如果你需要随机触发，请在单条API设置中配置多个url。

| 配置项 | 类型 | 默认值 | 说明 |
| ------ | ---- | ------ | ---- |
| 返回值解析路径 | str | 空 | 当api响应是json时，要提取内容的路径，以"."隔开|

例如：某个api响应如下
```
{
  "status": "200",
  "details": {
    "data":{
        "urlList":["url1","url2"]
    },
    "name":"astrbot"
  },
  "message": "example."
}
```
当需要提取出url1时，可以将返回值解析路径配置为"details.data.urlList.0"。

要提取的列表有多个元素时，若未指定下标，则默认为0，例如在这个例子中，"details.data.urlList.0"和"details.data.urlList"效果是等同的。当路径有多个列表时，混着写也是可以兼容的，但并不推荐。
> [!NOTE]
>当提取的元素是图片地址，且当前API配置为图片类型，则插件会直接发送图片，而不是图片地址，如果需要发送图片地址，请设置文本类型API。

| 配置项   | 类型 | 默认值      | 说明        |
| -------- | ---- | ----------- | ----------- |
| API请求参数列表 | dict  | 空 | 键值对参数 |

> [!TIP]
>当你需要配置带参数的API时，可以在api_url中配置占位符或者在params中设置**空值**的键值对，但**不要同时配置**。

例如，某API触发命令设置为“搜索”，api_url=http://example.api?{key1}&{key2}，或者将params配置为
```
{
    "key1": "",
    "key2": "",
}
```
此时发送“/搜索 北京 天气”，插件会自动将key1和key2的值分别设置为北京、天气。


## Todo List
- [ ]定时触发


## 📄 许可证
本项目基于 [MIT License](LICENSE) 开源 - 详见 LICENSE 文件
