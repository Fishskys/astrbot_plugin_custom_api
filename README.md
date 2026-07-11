# 🌟 AstrBot 自定义API插件
# astrbot-plugin-custom-api
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-Plugin-ff69b4?style=for-the-badge)](https://github.com/AstrBotDevs/AstrBot)

支持多样化的外部API接口调用，可处理文本、图片、语音和视频类型API，支持自定义参数配置，关键词触发调用

## ❓ 能做什么

这是一个通用的API接入插件，不管是文字、图片、语音、还是视频类型的API，都可以通过这个插件接入Astrbot，接入后可以通过自定义命令快捷触发API


## 🌟 功能特性
- ✅ **多类型响应支持**
  支持文本、图片、音频、视频，自动转换输出

- ✅ **动态多参数配置**
  支持常见的API请求参数配置，请求头、请求体均可自定义配置

- ✅ **双重触发模式**
  支持关键词触发 / 仅 @机器人触发两种方式，且可不同API单独配置

- ✅ **频率限制**
  支持用户级 / API 级调用频率限制，防止滥用

- ✅ **随机 API 负载**
  同一个API指令支持配置多个API URL，均衡负载
  
- ✅ **UI界面配置**

  适配Astrbot官方UI接口，可以一览配置与调用详情

- ✅ **API在线调用测试**

  UI界面可以快速测试API可用性

## 🚀 快速使用
### ~~方式1：通过AstrBot插件市场安装（推荐）~~ 当前插件暂未被收录（已提交issue）
~~在插件市场搜索astrbot-plugin-custom-api并安装~~

### 方式2：手动安装
下载本项目压缩包astrbot_plugin_custom_api.zip，在webui上传即可



## 📖 使用说明
### 指令触发
| 指令         | 权限     | 说明           |
| ------------ | -------- | -------------- |
| `/apihelp`   | 全体成员 | 项目使用帮助   |
| `/apilist`   | 全体成员 | api列表        |
| `/api配置`   | 管理员   | api配置json    |
| `/{command}` | 全体成员 | 配置的触发命令 |

## ⚙️ 配置示例

| 配置项   | 类型 | 默认值      | 说明        |
| -------- | ---- | ----------- | ----------- |
| 触发命令 | str  | default_api | api触发命令 |

> [!TIP]
>当你需要给一个API配置多个触发命令时，可以用空格隔开，例如“搜索 搜”，发送“搜索”或者“搜”均可触发

当多条API配置的触发命令相同时，触发时会随机选择一个触发，但并不推荐这样设置，如果你需要随机触发，请在单条API设置中配置多个url。

| 配置项         | 类型 | 默认值 | 说明                                           |
| -------------- | ---- | ------ | ---------------------------------------------- |
| 返回值解析路径 | str  | 空     | 当api响应是json时，要提取内容的路径，以"."隔开 |

采用dpath提取字典内容。例如：某个api响应如下
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

采用dpath嵌套字典取值：支持以下写法，返回值总是列表，未提取到指定内容时返回空列表

1.精确取值：details.data.urlList.0

2.模糊取值：details.*.urlList.0

3.多层通配符：**.urlList，如果不可用，请用单层通配符写法

> [!NOTE]
>当提取的元素是图片地址，且当前API配置为图片类型，则插件会直接发送图片，而不是图片地址，如果需要发送图片地址，请设置文本类型API。

| 配置项                 | 类型 | 默认值 | 说明       |
| ---------------------- | ---- | ------ | ---------- |
| API请求参数列表/params | dict | 空     | 键值对参数 |

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

## 插件截图

![ui-1](https://github.com/user-attachments/assets/d8a00b8b-44c8-47a2-bb34-0f166e368ab7)

![ui-2](https://github.com/user-attachments/assets/0efbae7c-8a1a-4d8c-892a-b5726abbe076")

![ui-3](https://github.com/user-attachments/assets/c0586622-23f5-4bd4-9df5-c0afcea532ac)


## Todo List
- [ ]定时任务
- [ ]访问控制


## 📄 许可证
本项目基于 [MIT License](LICENSE) 开源 - 详见 LICENSE 文件
