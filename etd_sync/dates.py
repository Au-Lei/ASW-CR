import re
from datetime import date, datetime, timedelta


def parse_date(value, year=None):
    """Accept WPS serial dates, ISO dates and Evergreen English dates.

    Legacy month.day input requires an explicit business year; never infer it.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("布尔值不是日期")
    if isinstance(value, (int, float)):
        if value < 10000:
            raise ValueError("数字月日存在歧义，请把单元格改为完整日期或文本")
        return (datetime(1899, 12, 30) + timedelta(days=value)).date()
    text = str(value).strip()
    match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if match:
        return date(*map(int, match.groups()))
    match = re.search(r"\b([A-Za-z]{3})[-\s](\d{1,2})[-,\s]+(\d{4})\b", text)
    if match:
        months = {name: i + 1 for i, name in enumerate(
            ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
        month, day, yr = match.groups()
        if month.lower() in months:
            return date(int(yr), months[month.lower()], int(day))
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if match and year:
        return date(year, *map(int, match.groups()))
    raise ValueError(f"无法识别日期：{text}；请使用 YYYY-MM-DD")


def needs_update(original, saved, latest):
    if original is None or latest is None:
        raise ValueError("原始 ETD 和官网 ETD 不能为空")
    return latest != saved and (latest != original or saved is not None)


def current_status(original, latest, valid_to, today):
    """Business status, independent of whether this sync needs an ETD write."""
    if original is None or latest is None:
        raise ValueError('原始 ETD 和最新 ETD 不能为空')
    if today > latest:
        return '已完成'
    if valid_to is None:
        raise ValueError('Valid to 为空，无法判断当前状态，请填写完整日期')
    if latest > valid_to:
        return '托班到下一批次'
    return 'ETD已变更' if latest != original else 'ETD未变更'
