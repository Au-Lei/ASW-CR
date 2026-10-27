"""Local desktop configuration; never included in a distributable."""
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values

from .wps import WpsClient

DEFAULTS = {
    'WPS_WEBHOOK_URL': '', 'WPS_API_TOKEN': '', 'WPS_SHEET_NAME': '工作表1',
    'EVERGREEN_NUMBER_TYPE': 'booking', 'QUERY_CONCURRENCY': '2',
    'QUERY_INTERVAL_SECONDS': '1', 'HEADLESS': 'true',
}


def read_config(path):
    year = str(datetime.now(timezone(timedelta(hours=8))).year)
    return {**DEFAULTS, 'DATE_YEAR': year,
            **{key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None}}


def validate_config(values):
    config = {key: str(value).strip() for key, value in values.items()}
    if any(any(char in value for char in '\r\n\0') for value in config.values()):
        raise ValueError('配置值不能包含换行或空字符')
    WpsClient(config.get('WPS_WEBHOOK_URL', ''), config.get('WPS_API_TOKEN', ''),
              config.get('WPS_SHEET_NAME', ''))
    if config.get('EVERGREEN_NUMBER_TYPE') not in ('booking', 'bl'):
        raise ValueError('请选择订舱号或提单号')
    try:
        year = config.get('DATE_YEAR', '')
        if year and not 1900 <= int(year) <= 9999:
            raise ValueError()
    except ValueError:
        raise ValueError('年份须为 1900–9999 的整数，或留空') from None
    try:
        interval = float(config.get('QUERY_INTERVAL_SECONDS', '1'))
        concurrency = int(config.get('QUERY_CONCURRENCY', '2'))
        if not math.isfinite(interval) or interval < 0 or not 1 <= concurrency <= 3:
            raise ValueError()
    except ValueError:
        raise ValueError('查询间隔须为非负有限数，并发数须为 1–3') from None
    return config


def save_config(path, values):
    config = validate_config(values)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.settings-', delete=False) as handle:
            temporary = Path(handle.name)
            for key, value in config.items():
                if not key.replace('_', '').isalnum() or not key[0].isalpha():
                    raise ValueError('配置项名称无效')
                handle.write(key + '=' + json.dumps(value, ensure_ascii=False) + '\n')
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return config


def configure(root, path):
    """Blocking modal wizard; call only from the Tk main thread."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    values = read_config(path)
    result = None
    window = tk.Toplevel(root)
    window.title('长荣货物追踪 · WPS 配置')
    window.resizable(False, False)
    window.protocol('WM_DELETE_WINDOW', window.destroy)
    panel = ttk.Frame(window, padding=24)
    panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='首次填写一次，之后双击程序即可使用。').grid(
        row=0, column=0, columnspan=2, sticky='w', pady=(0, 16))
    fields = [
        ('WPS_WEBHOOK_URL', '同步 webhook（/sync_task）'),
        ('WPS_API_TOKEN', '脚本 Token'), ('WPS_SHEET_NAME', '工作表标签名称'),
        ('EVERGREEN_NUMBER_TYPE', '单号类型'), ('DATE_YEAR', '旧版月日文本的年份'),
    ]
    entries = {}
    for index, (key, label) in enumerate(fields, 1):
        ttk.Label(panel, text=label).grid(row=index, column=0, sticky='w', padx=(0, 14), pady=6)
        variable = tk.StringVar(value=values.get(key, ''))
        entries[key] = variable
        if key == 'EVERGREEN_NUMBER_TYPE':
            field = ttk.Combobox(panel, textvariable=variable, values=('booking', 'bl'),
                                 state='readonly', width=47)
        else:
            field = ttk.Entry(panel, textvariable=variable, width=50,
                              show='*' if key == 'WPS_API_TOKEN' else '')
        field.grid(row=index, column=1, sticky='ew', pady=6)
    ttk.Label(panel, text='booking = 订舱号；bl = 提单号。配置保存不会读取或修改 WPS。').grid(
        row=6, column=0, columnspan=2, sticky='w', pady=(12, 4))
    ttk.Label(panel, text='WPS 脚本需使用项目最新版，并包含 Valid to 和当前状态列。').grid(
        row=7, column=0, columnspan=2, sticky='w')

    def save():
        nonlocal result
        try:
            result = save_config(path, {**values, **{key: value.get() for key, value in entries.items()}})
        except (ValueError, OSError):
            # Never echo input or exception text that might contain a secret.
            messagebox.showerror('配置未保存', '请检查 webhook、Token、工作表名、单号类型和年份；也请确认数据目录可写。', parent=window)
            return
        window.destroy()

    buttons = ttk.Frame(panel)
    buttons.grid(row=8, column=0, columnspan=2, sticky='e', pady=(20, 0))
    ttk.Button(buttons, text='取消', command=window.destroy).pack(side='left', padx=8)
    ttk.Button(buttons, text='保存配置', command=save).pack(side='left')
    window.update_idletasks()
    window.grab_set()
    window.focus_force()
    root.wait_window(window)
    return result
