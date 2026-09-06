/**
 * 滴答清单 To-Do 卡片 (v2)
 * - 通过 HA websocket (todo/item/list + todo/item/subscribe) 获取任务，适配 HA 2026.x 新架构
 * - 支持创建/完成/取消完成/删除任务
 * - 界面中文，适配 HA 明暗主题
 */
const LitElement = globalThis.customElements.get("ha-panel-lovelace")
  ? Object.getPrototypeOf(customElements.get("hui-view"))
  : Object.getPrototypeOf(customElements.get("hui-masonry-view"));
const html = LitElement.prototype.html;
const css = LitElement.prototype.css;

class TickTickCard extends LitElement {
  static get properties() {
    return {
      _hass: {},
      _config: {},
      _items: { type: Array },
      _error: { type: String },
      _unsub: {},
      _newTaskTitle: { type: String },
      _newTaskDue: { type: String },
    };
  }

  static getConfigElement() {
    return document.createElement("ticktick-card-editor");
  }

  static getStubConfig() {
    return { entity: "", show_completed: true, show_add: true };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("请配置一个 todo 实体");
    }
    this._config = config;
    this._items = null;
    this._error = "";
    this._newTaskTitle = "";
    this._newTaskDue = "";
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (this._items === null) {
      this._loadItems();
    }
    this._subscribe();
  }

  async _loadItems() {
    if (!this._hass || !this._config) return;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "todo/item/list",
        entity_id: this._config.entity,
      });
      this._items = result.items || [];
    } catch (e) {
      this._error = "无法加载任务: " + e.message;
      this._items = [];
    }
  }

  _subscribe() {
    if (this._unsub || !this._hass || !this._config) return;
    this._hass.connection
      .subscribeMessage(
        (msg) => {
          this._items = msg.items || [];
        },
        { type: "todo/item/subscribe", entity_id: this._config.entity }
      )
      .then((unsub) => {
        this._unsub = unsub;
      })
      .catch(() => {
        // 订阅失败不影响一次性拉取
      });
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _toggleTask(item) {
    if (!this._hass || !item.uid) return;
    const status = item.status === "completed" ? "needs_action" : "completed";
    this._hass.callService(
      "todo",
      "update_item",
      { item: item.uid, status },
      { entity_id: this._config.entity }
    );
  }

  _addTask() {
    const title = (this._newTaskTitle || "").trim();
    if (!title || !this._hass) return;
    const data = { item: title };
    if (this._newTaskDue) {
      data.due_datetime = this._newTaskDue;
    }
    this._hass.callService(
      "todo",
      "create_item",
      data,
      { entity_id: this._config.entity }
    );
    this._newTaskTitle = "";
    this._newTaskDue = "";
  }

  _deleteTask(item) {
    if (!this._hass || !item.uid) return;
    this._hass.callService(
      "todo",
      "delete_item",
      { item: item.uid },
      { entity_id: this._config.entity }
    );
  }

  _onTitleInput(ev) {
    this._newTaskTitle = ev.target.value;
  }

  _onDueInput(ev) {
    this._newTaskDue = ev.target.value;
  }

  _onTitleKeydown(ev) {
    if (ev.key === "Enter") {
      this._addTask();
    }
  }

  _formatDue(due) {
    if (!due) return "";
    const d = new Date(due);
    if (isNaN(d.getTime())) return "";
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const d0 = new Date(d);
    d0.setHours(0, 0, 0, 0);
    const sameDay = (a, b) => a.getTime() === b.getTime();
    if (sameDay(d0, today)) return "今天";
    if (sameDay(d0, tomorrow)) return "明天";
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  _isOverdue(due) {
    if (!due) return false;
    const d = new Date(due);
    if (isNaN(d.getTime())) return false;
    return d.getTime() < Date.now();
  }

  render() {
    const config = this._config || {};
    const showCompleted = config.show_completed !== false;
    const showAdd = config.show_add !== false;
    const items = this._items || [];
    const activeItems = items.filter((i) => i.status !== "completed");
    const completedItems = items.filter((i) => i.status === "completed");
    const displayItems = showCompleted
      ? [...activeItems, ...completedItems]
      : activeItems;

    const stateObj = this._hass ? this._hass.states[config.entity] : null;
    const title = stateObj ? stateObj.attributes.friendly_name : config.entity;

    return html`
      <ha-card class="ticktick-card">
        <div class="card-header">
          <div class="title">${title}</div>
          <div class="count">${activeItems.length} 项待办</div>
        </div>
        ${this._error
          ? html`<div class="error">${this._error}</div>`
          : ""}
        <div class="task-list">
          ${displayItems.length === 0
            ? html`<div class="empty">暂无任务</div>`
            : displayItems.map(
                (item) => html`
                  <div class="task ${item.status === "completed" ? "done" : ""}">
                    <ha-checkbox
                      .checked=${item.status === "completed"}
                      @change=${() => this._toggleTask(item)}
                    ></ha-checkbox>
                    <div class="task-content">
                      <div class="task-summary">${item.summary || ""}</div>
                      ${item.due
                        ? html`<div class="task-due ${this._isOverdue(item.due) && item.status !== "completed" ? "overdue" : ""}">
                            ${this._formatDue(item.due)}
                          </div>`
                        : ""}
                    </div>
                    <ha-icon-button
                      class="delete-btn"
                      label="删除"
                      @click=${() => this._deleteTask(item)}
                    >
                      <ha-icon icon="mdi:close"></ha-icon>
                    </ha-icon-button>
                  </div>
                `
              )}
        </div>
        ${showAdd
          ? html`<div class="add-row">
              <input
                class="add-input"
                type="text"
                placeholder="添加任务，按回车确认"
                .value=${this._newTaskTitle || ""}
                @input=${this._onTitleInput}
                @keydown=${this._onTitleKeydown}
              />
              <input
                class="add-date"
                type="datetime-local"
                .value=${this._newTaskDue || ""}
                @input=${this._onDueInput}
              />
              <ha-button class="add-btn" @click=${this._addTask}>
                添加
              </ha-button>
            </div>`
          : ""}
      </ha-card>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .ticktick-card {
        padding: 12px;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      }
      .title {
        font-size: 16px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .count {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .error {
        color: var(--error-color, #db4437);
        font-size: 13px;
        padding: 8px;
        background: var(--error-background-color, rgba(219, 68, 55, 0.1));
        border-radius: 4px;
        margin-bottom: 8px;
      }
      .task-list {
        max-height: 400px;
        overflow-y: auto;
      }
      .task {
        display: flex;
        align-items: center;
        padding: 6px 4px;
        border-radius: 4px;
        gap: 8px;
      }
      .task:hover {
        background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
      }
      .task.done .task-summary {
        text-decoration: line-through;
        color: var(--disabled-text-color, #999);
      }
      .task-content {
        flex: 1;
        min-width: 0;
      }
      .task-summary {
        font-size: 14px;
        color: var(--primary-text-color);
        word-break: break-word;
      }
      .task-due {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-top: 2px;
      }
      .task-due.overdue {
        color: var(--error-color, #db4437);
      }
      .delete-btn {
        color: var(--secondary-text-color);
        opacity: 0;
        transition: opacity 0.15s;
      }
      .task:hover .delete-btn {
        opacity: 1;
      }
      .empty {
        text-align: center;
        color: var(--secondary-text-color);
        padding: 16px 0;
        font-size: 13px;
      }
      .add-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
        padding-top: 10px;
        border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      }
      .add-input {
        flex: 1;
        min-width: 0;
        padding: 6px 8px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 4px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        font-size: 14px;
      }
      .add-date {
        padding: 5px 6px;
        border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
        border-radius: 4px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        font-size: 12px;
        width: 150px;
      }
      .add-btn {
        --mdc-theme-primary: var(--primary-color);
      }
    `;
  }
}

class TickTickCardEditor extends LitElement {
  static get properties() {
    return { _hass: {}, _config: {} };
  }

  setConfig(config) {
    this._config = config;
  }

  get _entity() {
    return this._config.entity || "";
  }

  render() {
    return html`
      <div style="margin-bottom: 16px">
        <ha-entity-picker
          .hass=${this._hass}
          .value=${this._entity}
          .includeEntities=${["todo.*"]}
          @value-changed=${this._valueChanged}
        ></ha-entity-picker>
        <div style="margin-top: 12px; font-size: 13px; color: var(--secondary-text-color)">
          卡片通过 websocket 实时同步任务数据。
        </div>
      </div>
    `;
  }

  _valueChanged(ev) {
    this._config = { ...this._config, entity: ev.detail.value };
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: this._config },
        bubbles: true,
        composed: true,
      })
    );
  }
}

customElements.define("ticktick-card", TickTickCard);
customElements.define("ticktick-card-editor", TickTickCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ticktick-card",
  name: "滴答清单 To-Do",
  description: "滴答清单任务卡片，支持添加/完成/删除任务",
  preview: true,
});
