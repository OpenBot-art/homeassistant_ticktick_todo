![Version](https://img.shields.io/github/v/release/OpenBot-art/homeassistant_ticktick_todo?style=for-the-badge)
![Downloads](https://img.shields.io/github/downloads/OpenBot-art/homeassistant_ticktick_todo/total?style=for-the-badge)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
<br>
<p align="center">
  <img src="images/logo.jpg" width="100" height="100" alt="滴答清单 Logo">
</p>

# 滴答清单（Dida365）Home Assistant 集成

非官方的 Home Assistant 集成，对接**国内版滴答清单（Dida365）**。基于原生 `todo` 平台，把任务直接带入你的智能家居仪表盘，还附带专属自定义卡片。

## ✨ 功能特性

- **自动发现**：自动发现并添加所有滴答清单项目（含收件箱）为独立待办实体
- **今日任务列表**：汇总所有项目中"今天到期"的任务，随日期自动滚动
- **每任务开关**：每个今日任务生成一个开关实体（`switch.task1`、`switch.task2`…），标题变化开关名称跟随
- **完整任务管理**：创建、完成、取消完成、重命名、永久删除任务
- **截止日期**：完整支持日期与具体时间
- **已完成任务**：在 HA 界面直接查看已完成任务
- **自定义卡片**：`ticktick-card`，支持勾选、添加、删除任务（集成加载时自动注册，无需手动添加资源）
- **设备分组**：所有列表统一归入"滴答清单账户"设备
- **全中文界面**：实体、设备、日志、异常提示全部中文化

---

## 🛠️ 准备工作

需要你自己的 Dida365 开发者凭据，免费注册，约 2 分钟：

1. 登录 [滴答清单开发者中心](https://developer.dida365.com/)
2. 点击 **Manage Apps**，创建一个新应用（Web App）
3. **OAuth 回调地址** 填写：
   `https://my.home-assistant.io/redirect/oauth`
4. 保存应用，获取 **Client ID** 和 **Client Secret**

> ⚠️ 注意：请使用**国内版** `developer.dida365.com` 创建的应用，国际版 `developer.ticktick.com` 的凭据不通用。

---

## 📦 安装（HACS）

1. 打开 HACS → 右上角三个点 → **自定义仓库**
2. 粘贴本仓库地址，类别选择 **集成**：
   `https://github.com/OpenBot-art/homeassistant_ticktick_todo`
3. 在 HACS 中搜索 **滴答清单**，点击 **下载**
4. **重启** Home Assistant

---

## ⚙️ 配置

1. 进入 **设置 → 设备与服务**
2. 右上角三个点 → **应用凭据**
3. 点击 **添加应用凭据**，选择 **滴答清单**
4. 输入名称（如 "Dida365 API"），粘贴 **Client ID** 和 **Client Secret**
5. 返回 *设备与服务*，点击 **添加集成**，搜索 **滴答清单**
6. 按提示完成 OAuth 授权（在浏览器中登录滴答清单）

配置完成后会生成：

| 实体 | 说明 |
|---|---|
| `todo.滴答清单账户_滴答清单_收件箱` | 收件箱全部任务 |
| `todo.滴答清单账户_滴答清单_今日` | 今天到期的任务（跨项目汇总） |
| `switch.task1`…`switch.taskN` | 每项今日任务一个开关，勾选即完成/取消完成 |

---

## 🃏 自定义卡片

卡片资源由集成**自动注册**，无需手动添加。浏览器强制刷新（Ctrl+F5）后在仪表盘添加卡片：

```yaml
type: custom:ticktick-card
entity: todo.滴答清单账户_滴答清单_今日   # 或收件箱实体
show_completed: true                     # 可选：显示已完成
show_add: true                           # 可选：显示添加栏
```

功能：
- 显示任务列表（未完成在前，已完成置灰划线）
- 勾选/取消完成任务
- 添加任务（标题 + 日期，回车或点"添加"）
- 悬停显示删除按钮
- 逾期任务日期标红
- 顶部显示剩余任务数

---

## 📝 许可证

本项目基于 MIT 许可证开源，详见 [LICENSE](LICENSE) 文件。

*声明：本项目与滴答清单官方无关，未经官方认可。*
