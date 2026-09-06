from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN

class TickTickOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """处理标准 OAuth2 配置流程。"""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        """返回日志记录器。"""
        return logging.getLogger(__name__)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """处理用户发起的配置流程。"""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        return await super().async_step_user(user_input)

    async def async_step_reauth(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """处理重新授权流程。"""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        return await super().async_step_reauth(user_input)
