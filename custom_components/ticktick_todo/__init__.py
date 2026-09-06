import logging
from datetime import timedelta

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config import ConfigType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, API_BASE_URL

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.TODO, Platform.SWITCH]

# 前端卡片资源的 URL 路径（由集成内部注册静态路径，兼容 HACS 与手动安装）
FRONTEND_CARD_URL = "/ticktick_todo_card.js"

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """设置滴答清单集成，注册前端卡片静态资源。"""
    # /ticktick_todo_card.js → custom_components/ticktick_todo/frontend/ticktick-card.js
    card_path = hass.config.path(
        "custom_components", DOMAIN, "frontend", "ticktick-card.js"
    )
    await hass.http.async_register_static_paths(
        [StaticPathConfig(url_path=FRONTEND_CARD_URL, path=card_path)]
    )
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """从配置条目设置滴答清单集成。"""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    hass.data.setdefault(DOMAIN, {})

    # 统一的中央 Coordinator：todo 平台与 switch 平台共用，避免重复拉取数据
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="滴答清单任务",
        update_method=async_update_data(hass, session),
        update_interval=timedelta(seconds=60),
    )
    # 在创建实体前先完成首次刷新，避免重启时出现"不可用"状态
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "session": session,
        "coordinator": coordinator,
    }

    # 自动注册前端卡片资源，无需手动在资源列表中添加
    frontend.add_extra_js_url(hass, FRONTEND_CARD_URL)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目。"""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

def async_update_data(hass: HomeAssistant, session):
    """统一获取所有列表的数据。"""
    async def update():
        try:
            await session.async_ensure_token_valid()
            access_token = session.token["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}
            client = async_get_clientsession(hass)

            # 1. 获取所有项目
            async with client.get(f"{API_BASE_URL}/project", headers=headers) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"无法加载项目列表: {resp.status}")
                projects = await resp.json()

            # 收件箱（Inbox）手动补充，防止 API 未返回
            if not any(p["id"] == "inbox" for p in projects):
                projects.append({"id": "inbox", "name": "收件箱"})

            # 2. 获取每个项目的任务数据
            full_data = {}
            for project in projects:
                p_id = project["id"]
                url = f"{API_BASE_URL}/project/{p_id}/data"
                async with client.get(url, headers=headers) as p_resp:
                    if p_resp.status == 200:
                        data = await p_resp.json()

                        # 记录每个任务的真实项目 ID
                        task_map = {}
                        all_tasks = data.get("tasks", []) + data.get("completed", [])
                        for task in all_tasks:
                            task_map[task["id"]] = task.get("projectId", p_id)

                        full_data[p_id] = {
                            "name": project["name"],
                            "tasks": data,
                            "task_map": task_map,
                        }
                    else:
                        _LOGGER.warning("无法加载项目 %s 的数据。", p_id)
            return full_data
        except Exception as err:
            raise UpdateFailed(f"与滴答清单通信失败: {err}")
    return update
