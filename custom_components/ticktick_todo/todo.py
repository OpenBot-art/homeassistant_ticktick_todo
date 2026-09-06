import logging
import datetime

from homeassistant.components.todo import (
    TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import DOMAIN, API_BASE_URL

_LOGGER = logging.getLogger(__name__)

def _build_task_payload(item: TodoItem, project_id: str) -> dict:
    """构建发送给滴答清单的 JSON 数据包。"""
    payload = {"title": item.summary, "projectId": project_id}
    if item.description:
        payload["content"] = item.description
    if item.due:
        if isinstance(item.due, datetime.datetime):
            utc_due = item.due.astimezone(datetime.timezone.utc)
            payload["dueDate"] = utc_due.strftime("%Y-%m-%dT%H:%M:%S+0000")
            payload["isAllDay"] = False
        else:
            payload["dueDate"] = item.due.strftime("%Y-%m-%dT00:00:00+0000")
            payload["isAllDay"] = True
    return payload

def _task_is_today(task) -> bool:
    """判断任务是否属于"今天到期"：未完成且到期日（本地时区）== 今天。

    注意：滴答清单 API 的 dueDate 统一为 UTC，必须转本地时区再比较日期，
    否则跨时区边界（如 UTC 23:59 = 本地次日）会误判。
    """
    if task.get("status", 0) in (2, -1):
        return False
    due = task.get("dueDate")
    if not due:
        return False
    try:
        d_str = due.replace("+0000", "+00:00")
        parsed = datetime.datetime.fromisoformat(d_str)
        if parsed.tzinfo is None:
            due_date = parsed.date()
        else:
            due_date = dt_util.as_local(parsed).date()
    except Exception:
        return False
    return due_date == dt_util.now().date()

async def async_setup_entry(hass, entry, async_add_entities):
    """设置平台，使用共享的 Coordinator 管理数据。"""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for project_id, project_info in coordinator.data.items():
        entities.append(TickTickTodoList(coordinator, project_info["name"], project_id, entry.entry_id))

    # 额外的"今日任务"列表实体
    entities.append(TickTickTodayTodoList(coordinator, entry.entry_id))

    async_add_entities(entities)

class TickTickTodoList(CoordinatorEntity, TodoListEntity):
    """待办列表实体，数据来自中央 Coordinator。"""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM |
        TodoListEntityFeature.UPDATE_TODO_ITEM |
        TodoListEntityFeature.DELETE_TODO_ITEM |
        TodoListEntityFeature.SET_DUE_DATE_ON_ITEM |
        TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM |
        TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator, name, list_id, entry_id):
        super().__init__(coordinator)
        self._list_id = list_id
        self._attr_name = f"滴答清单 {name}"
        self._attr_unique_id = f"ticktick_l_{list_id}_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="滴答清单账户",
            manufacturer="滴答清单",
            model="API 集成",
        )

    @property
    def todo_items(self):
        """直接从 Coordinator 缓存中快速获取任务项。"""
        data = self.coordinator.data.get(self._list_id, {}).get("tasks", {})
        all_tasks = data.get("tasks", []) + data.get("completed", [])
        
        items = []
        for task in all_tasks:
            due = None
            if task.get("dueDate"):
                try:
                    d_str = task["dueDate"].replace("+0000", "+00:00")
                    parsed = datetime.datetime.fromisoformat(d_str)
                    due = parsed.date() if task.get("isAllDay") else parsed
                except Exception:
                    pass

            items.append(TodoItem(
                summary=task["title"],
                uid=task["id"],
                status=TodoItemStatus.COMPLETED if task.get("status") in (2, -1) else TodoItemStatus.NEEDS_ACTION,
                due=due,
                description=task.get("content") or None,
            ))
        return items

    def _build_task_payload(self, item: TodoItem, project_id: str) -> dict:
        """构建发送给滴答清单的 JSON 数据包。"""
        return _build_task_payload(item, project_id)

    async def async_create_todo_item(self, item: TodoItem) -> TodoItem | None:
        """创建新任务并返回带 uid 的任务项。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}", "Content-Type": "application/json"}
        client = async_get_clientsession(self.hass)
        
        payload = self._build_task_payload(item, self._list_id)
        
        async with client.post(f"{API_BASE_URL}/task", json=payload, headers=headers) as resp:
            if resp.status not in (200, 201):
                _LOGGER.error("创建任务失败: %s", await resp.text())
                raise HomeAssistantError(
                    f"滴答清单无法创建任务 (HTTP {resp.status})"
                )
            created = await resp.json()
        
        # 通知 Coordinator：数据已变更，重新加载所有数据。
        await self.coordinator.async_request_refresh()
        
        return TodoItem(
            summary=item.summary,
            uid=created.get("id"),
            status=item.status,
            due=item.due,
            description=item.description,
        )

    async def async_update_todo_item(self, item):
        """更新任务并刷新 Coordinator。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}", "Content-Type": "application/json"}
        client = async_get_clientsession(self.hass)
        
        # 获取任务的真实项目 ID
        task_map = self.coordinator.data.get(self._list_id, {}).get("task_map", {})
        project_id = task_map.get(item.uid, self._list_id)
        
        if item.status == TodoItemStatus.COMPLETED:
            url = f"{API_BASE_URL}/project/{project_id}/task/{item.uid}/complete"
            async with client.post(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("完成任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法完成任务 (HTTP {resp.status})"
                    )
        else:
            url = f"{API_BASE_URL}/task/{item.uid}"
            payload = self._build_task_payload(item, project_id)
            payload.update({"id": item.uid, "status": 0})
            async with client.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("更新任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法更新任务 (HTTP {resp.status})"
                    )
        
        # 重新同步
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]):
        """删除任务并刷新 Coordinator。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}"}
        client = async_get_clientsession(self.hass)
        
        task_map = self.coordinator.data.get(self._list_id, {}).get("task_map", {})
        
        for uid in uids:
            project_id = task_map.get(uid, self._list_id)
            url = f"{API_BASE_URL}/project/{project_id}/task/{uid}"
            async with client.delete(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("删除任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法删除任务 (HTTP {resp.status})"
                    )
            
        # 重新同步
        await self.coordinator.async_request_refresh()

class TickTickTodayTodoList(CoordinatorEntity, TodoListEntity):
    """"今日任务"列表实体：汇总所有项目中"今天到期"的未完成任务。"""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM |
        TodoListEntityFeature.UPDATE_TODO_ITEM |
        TodoListEntityFeature.DELETE_TODO_ITEM |
        TodoListEntityFeature.SET_DUE_DATE_ON_ITEM |
        TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM |
        TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, coordinator, entry_id):
        super().__init__(coordinator)
        self._attr_name = "滴答清单 今日"
        self._attr_unique_id = f"ticktick_today_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="滴答清单账户",
            manufacturer="滴答清单",
            model="API 集成",
        )

    def _global_task_map(self) -> dict:
        """合并所有项目的任务映射（任务 ID → 真实项目 ID）。"""
        task_map = {}
        for project_data in self.coordinator.data.values():
            task_map.update(project_data.get("task_map", {}))
        return task_map

    def _inbox_id(self) -> str:
        """返回收件箱项目 ID（手动补充的 inbox 或第一个项目）。"""
        if "inbox" in self.coordinator.data:
            return "inbox"
        return next(iter(self.coordinator.data))

    @property
    def todo_items(self):
        """汇总所有项目中今天到期且未完成的任务。"""
        items = []
        for project_data in self.coordinator.data.values():
            all_tasks = project_data.get("tasks", {}).get("tasks", []) + project_data.get("tasks", {}).get("completed", [])
            for task in all_tasks:
                if not _task_is_today(task):
                    continue
                due = None
                if task.get("dueDate"):
                    try:
                        d_str = task["dueDate"].replace("+0000", "+00:00")
                        parsed = datetime.datetime.fromisoformat(d_str)
                        due = parsed.date() if task.get("isAllDay") else parsed
                    except Exception:
                        pass
                items.append(TodoItem(
                    summary=task["title"],
                    uid=task["id"],
                    status=TodoItemStatus.COMPLETED if task.get("status") in (2, -1) else TodoItemStatus.NEEDS_ACTION,
                    due=due,
                    description=task.get("content") or None,
                ))
        return items

    async def async_create_todo_item(self, item: TodoItem) -> TodoItem | None:
        """创建任务到收件箱，并默认设置截止日期为今天。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}", "Content-Type": "application/json"}
        client = async_get_clientsession(self.hass)

        payload = _build_task_payload(item, self._inbox_id())
        if item.due is None:
            today = dt_util.now().date()
            payload["dueDate"] = today.strftime("%Y-%m-%dT00:00:00+0000")
            payload["isAllDay"] = True

        async with client.post(f"{API_BASE_URL}/task", json=payload, headers=headers) as resp:
            if resp.status not in (200, 201):
                _LOGGER.error("创建任务失败: %s", await resp.text())
                raise HomeAssistantError(
                    f"滴答清单无法创建任务 (HTTP {resp.status})"
                )
            created = await resp.json()

        await self.coordinator.async_request_refresh()

        return TodoItem(
            summary=item.summary,
            uid=created.get("id"),
            status=item.status,
            due=item.due or dt_util.now().date(),
            description=item.description,
        )

    async def async_update_todo_item(self, item):
        """更新任务（跨项目，通过全局 task_map 定位真实项目）。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}", "Content-Type": "application/json"}
        client = async_get_clientsession(self.hass)

        project_id = self._global_task_map().get(item.uid, self._inbox_id())

        if item.status == TodoItemStatus.COMPLETED:
            url = f"{API_BASE_URL}/project/{project_id}/task/{item.uid}/complete"
            async with client.post(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("完成任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法完成任务 (HTTP {resp.status})"
                    )
        else:
            url = f"{API_BASE_URL}/task/{item.uid}"
            payload = _build_task_payload(item, project_id)
            payload.update({"id": item.uid, "status": 0})
            async with client.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("更新任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法更新任务 (HTTP {resp.status})"
                    )

        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]):
        """删除任务（跨项目，通过全局 task_map 定位真实项目）。"""
        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {"Authorization": f"Bearer {session.token['access_token']}"}
        client = async_get_clientsession(self.hass)

        task_map = self._global_task_map()

        for uid in uids:
            project_id = task_map.get(uid, self._inbox_id())
            url = f"{API_BASE_URL}/project/{project_id}/task/{uid}"
            async with client.delete(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("删除任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法删除任务 (HTTP {resp.status})"
                    )

        await self.coordinator.async_request_refresh()
