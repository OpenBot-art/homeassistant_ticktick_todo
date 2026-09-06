import datetime
import json
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, API_BASE_URL

_LOGGER = logging.getLogger(__name__)

_UNIQUE_ID_PREFIX = "ticktick_s_"

async def async_setup_entry(hass, entry, async_add_entities):
    """设置开关平台：为每个"今天到期"任务创建一个可操作的开关实体。"""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    manager = TaskSwitchManager(hass, coordinator, entry.entry_id, async_add_entities)
    manager.start()

class TaskSwitchManager:
    """动态管理开关实体。

    数据源为滴答清单"今天到期"的任务（未完成且到期日 == 今天）。
    实体 ID 固定为 task1/task2/task3...（槽位序号，持久化、不随任务标题变化），
    显示名称始终是任务的中文标题。以注册表为准进行同步：
    每次刷新都会清理不属于当前任务集的孤儿实体，避免残留"不可用"实体。
    """

    def __init__(self, hass, coordinator, entry_id, async_add_entities):
        self._hass = hass
        self._coordinator = coordinator
        self._entry_id = entry_id
        self._async_add_entities = async_add_entities
        self._entities = {}   # 任务 uid -> TickTickTaskSwitch（本次运行已加载的）
        self._slots = {}      # 任务 uid -> 槽位序号（持久化）
        self._slot_file = hass.config.path("ticktick_todo_slots.json")
        self._load_slots()

    def _unique_id(self, uid):
        """生成注册表唯一 ID。"""
        return f"{_UNIQUE_ID_PREFIX}{uid}_{self._entry_id}"

    def _uid_from_unique_id(self, unique_id):
        """从注册表唯一 ID 反向提取任务 uid。"""
        if not unique_id or not unique_id.startswith(_UNIQUE_ID_PREFIX):
            return None
        suffix = f"_{self._entry_id}"
        if not unique_id.endswith(suffix):
            return None
        return unique_id[len(_UNIQUE_ID_PREFIX):-len(suffix)]

    def _load_slots(self):
        """从磁盘加载槽位映射，保证重启后序号不变化。"""
        try:
            with open(self._slot_file, encoding="utf-8") as f:
                self._slots = json.load(f)
        except (OSError, ValueError):
            self._slots = {}

    def _save_slots(self):
        """保存槽位映射到磁盘。"""
        try:
            with open(self._slot_file, "w", encoding="utf-8") as f:
                json.dump(self._slots, f, ensure_ascii=False)
        except OSError as err:
            _LOGGER.warning("无法保存槽位映射: %s", err)

    def _assign_slot(self, uid):
        """为任务分配固定槽位：优先复用空闲槽位，否则取下一个新槽位。"""
        if uid in self._slots:
            return self._slots[uid]
        used = set(self._slots.values())
        slot = 1
        while slot in used:
            slot += 1
        self._slots[uid] = slot
        return slot

    def start(self):
        """监听 coordinator 数据变化，同步开关实体。"""
        self._coordinator.async_add_listener(self._sync)
        self._sync()

    def _today_tasks(self):
        """从 coordinator 缓存中取出"今天到期"的任务（未完成且到期日 == 今天）。"""
        tasks = []
        for project_id, info in self._coordinator.data.items():
            data = info.get("tasks", {})
            for task in data.get("tasks", []):
                if self._is_today_task(task):
                    tasks.append(task)
        return tasks

    @staticmethod
    def _is_today_task(task):
        """判断任务是否属于"今天到期"：未完成且到期日 == 今天。

        注意：滴答清单 API 的 dueDate 统一为 UTC（全天任务也是 UTC 日期），
        必须转成本地时区再比较，否则跨时区边界（如 UTC 23:59 = 本地次日）
        会误判日期。
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
                # 纯日期/无时区，直接按日期比较（全天任务）
                due_date = parsed.date()
            else:
                due_date = dt_util.as_local(parsed).date()
        except Exception:
            return False
        return due_date == dt_util.now().date()

    def _sync(self):
        """以注册表为准同步开关实体，清理孤儿实体并固定 taskN 实体 ID。"""
        reg = er.async_get(self._hass)
        current_uids = {task["id"] for task in self._today_tasks()}

        # 扫描本集成本条目在注册表中的所有开关实体
        registered = {}
        for reg_entry in reg.entities.values():
            if reg_entry.domain != DOMAIN or reg_entry.platform != Platform.SWITCH:
                continue
            uid = self._uid_from_unique_id(reg_entry.unique_id)
            if uid is not None:
                registered[uid] = reg_entry

        slots_changed = False

        # 1) 清理：移除不属于当前任务集的实体（含旧版本残留的孤儿实体）
        for uid, reg_entry in registered.items():
            if uid not in current_uids:
                entity = self._entities.pop(uid, None)
                if entity is not None:
                    self._hass.async_create_task(entity.async_remove())
                reg.async_remove(reg_entry.entity_id)
                if uid in self._slots:
                    del self._slots[uid]
                    slots_changed = True

        # 2) 补齐：为当前任务集创建实体，并把实体 ID 固定为 task{slot}
        to_add = current_uids - set(registered)
        for uid in to_add:
            if uid in self._slots:
                slot = self._slots[uid]
            else:
                slot = self._assign_slot(uid)
                slots_changed = True

            entity = TickTickTaskSwitch(self._coordinator, uid, self._entry_id)
            reg_entry = reg.async_get_or_create(
                Platform.SWITCH,
                DOMAIN,
                unique_id=entity.unique_id,
                suggested_object_id=f"task{slot}",
            )
            # 若此前已注册为拼音等其它 ID，强制改成固定序号（switch.taskN）
            expected = f"switch.task{slot}"
            if reg_entry.entity_id != expected:
                try:
                    reg.async_update_entity(reg_entry.entity_id, new_entity_id=expected)
                    reg_entry = reg.async_get(expected)
                except ValueError:
                    _LOGGER.warning("实体 ID %s 已被占用，保持原 ID。", expected)
            entity.entity_id = reg_entry.entity_id if reg_entry else expected
            self._entities[uid] = entity

        if to_add:
            self._async_add_entities([self._entities[uid] for uid in to_add], True)

        if slots_changed:
            self._hass.async_add_executor_job(self._save_slots)

class TickTickTaskSwitch(CoordinatorEntity, SwitchEntity):
    """一个任务对应一个开关实体：开 = 已完成，关 = 未完成。"""

    def __init__(self, coordinator, task_uid, entry_id):
        super().__init__(coordinator)
        self.task_uid = task_uid
        self._entry_id = entry_id
        self._attr_unique_id = f"{_UNIQUE_ID_PREFIX}{task_uid}_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="滴答清单账户",
            manufacturer="滴答清单",
            model="API 集成",
        )

    def _find_task(self):
        """在 coordinator 缓存中查找本开关对应的任务。"""
        for project_id, info in self.coordinator.data.items():
            data = info.get("tasks", {})
            for task in data.get("tasks", []) + data.get("completed", []):
                if task["id"] == self.task_uid:
                    return task, project_id
        return None, None

    @property
    def name(self):
        """开关名称 = 任务标题。"""
        task, _ = self._find_task()
        return task["title"] if task else "已删除任务"

    @property
    def is_on(self):
        """开 = 任务已完成。"""
        task, _ = self._find_task()
        if task is None:
            return False
        return task.get("status", 0) in (2, -1)

    async def async_turn_on(self):
        """打开开关 = 完成任务。"""
        await self._set_completed(True)

    async def async_turn_off(self):
        """关闭开关 = 取消完成。"""
        await self._set_completed(False)

    async def _set_completed(self, completed: bool):
        """调用滴答清单 API 完成或取消完成任务。"""
        task, project_id = self._find_task()
        if task is None:
            raise HomeAssistantError("任务不存在，可能已被删除")

        session = self.hass.data[DOMAIN][self.coordinator.config_entry.entry_id]["session"]
        await session.async_ensure_token_valid()
        headers = {
            "Authorization": f"Bearer {session.token['access_token']}",
            "Content-Type": "application/json",
        }
        client = async_get_clientsession(self.hass)

        if completed:
            # 完成任务
            url = f"{API_BASE_URL}/project/{project_id}/task/{self.task_uid}/complete"
            async with client.post(url, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("完成任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法完成任务 (HTTP {resp.status})"
                    )
        else:
            # 取消完成
            url = f"{API_BASE_URL}/task/{self.task_uid}"
            payload = {
                "id": self.task_uid,
                "projectId": project_id,
                "title": task["title"],
                "status": 0,
            }
            async with client.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    _LOGGER.error("更新任务失败: %s", await resp.text())
                    raise HomeAssistantError(
                        f"滴答清单无法更新任务 (HTTP {resp.status})"
                    )

        # 通知 Coordinator：数据已变更，重新加载所有数据
        await self.coordinator.async_request_refresh()
