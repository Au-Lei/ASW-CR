"""Evergreen queries, isolated per worker and sharing one browser per batch."""
import asyncio
import re
from bs4 import BeautifulSoup

from .dates import parse_date

URL = 'https://ct.shipmentlink.com/servlet/TDB1_CargoTracking.do'


def _port_name(raw):
    """Remove only a trailing country-code suffix, retaining meaningful parentheses."""
    name = re.sub(r'\s*[（(][A-Z]{2}[）)]\s*$', '', raw).strip()
    # Strip an explicit country name only when it agrees with the trailing code.
    country = re.search(r'[（(]([A-Z]{2})[）)]\s*$', raw)
    names = {'CN': 'CHINA', 'MY': 'MALAYSIA', 'TH': 'THAILAND', 'IN': 'INDIA', 'DE': 'GERMANY'}
    if country and country.group(1) in names:
        name = re.sub(r',\s*' + names[country.group(1)] + r'$', '', name).strip()
    return name or None


def _expand_row(row):
    values = []
    for cell in row.find_all(['td', 'th'], recursive=False):
        try:
            rowspan, colspan = int(cell.get('rowspan', 1)), int(cell.get('colspan', 1))
        except (ValueError, TypeError):
            raise ValueError('官网表格合并单元格格式异常，未写回') from None
        if rowspan != 1 or not 1 <= colspan <= 64:
            raise ValueError('官网存在不支持的合并单元格，需要人工核对，未写回')
        if cell.find('table'):
            raise ValueError('官网业务行存在嵌套表格，需要人工核对，未写回')
        values.extend([' '.join(cell.get_text(' ', strip=True).split())] * colspan)
    return values


def _label(value):
    return ' '.join(value.split()).casefold()


def extract_etd(html):
    """Extract loading ETD and both ports from one unambiguous result table.

    Missing ports are None with warnings, never a replacement empty string.
    Ambiguous rows or column structure fail the entire result before any writes.
    Existing callers retain the etd/raw/pol keys; pod and raw ports are additive.
    """
    soup = BeautifulSoup(html, 'html.parser')
    loading_rows = []
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'], recursive=False)
        if cells and not cells[0].find('table') and _label(cells[0].get_text(' ', strip=True)) == 'port of loading':
            loading_rows.append(row)
    if len(loading_rows) != 1:
        raise ValueError('没有唯一的装货港 ETD，可能无数据或官网结构变化，未写回')
    loading = loading_rows[0]
    table = loading.find_parent('table')
    if table is None:
        raise ValueError('装货港不在有效表格内，未写回')
    rows = [row for row in table.find_all('tr') if row.find_parent('table') == table]
    headers = []
    for row in rows:
        cells = row.find_all(['td', 'th'], recursive=False)
        if any(not cell.find('table') and _label(cell.get_text(' ', strip=True)) ==
               'estimated departure date' for cell in cells):
            headers.append(_expand_row(row))
    if len(headers) != 1:
        raise ValueError('无法唯一定位 Estimated Departure Date 表头，未写回')
    header = [_label(value) for value in headers[0]]
    if header.count('estimated departure date') != 1:
        raise ValueError('无法唯一定位 Estimated Departure Date 表头，未写回')
    etd_column = header.index('estimated departure date')
    if etd_column < 2:
        raise ValueError('官网 ETD 列与港口列重叠，未写回')

    def port_cells(row, *, merged_name=False):
        direct = row.find_all(['td', 'th'], recursive=False)
        cells = _expand_row(row)
        # Discharge names legitimately span the blank VGM/cut-off columns.
        # Keep the label separate and never let the name cover arrival/departure dates.
        arrival = header.index('estimated arrival date') if header.count('estimated arrival date') == 1 else 2
        max_name_span = min(arrival, etd_column) - 1 if merged_name else 1
        if (len(direct) < 2 or int(direct[0].get('colspan', 1)) != 1 or
                not 1 <= int(direct[1].get('colspan', 1)) <= max_name_span or
                len(cells) != len(header)):
            raise ValueError('港口行与表头不匹配，需要人工核对官网，未写回')
        return cells

    cells = port_cells(loading)
    raw = cells[etd_column]
    latest = parse_date(raw)
    if latest is None:
        raise ValueError('官网装货港 ETD 为空，未写回')
    unloading = []
    for row in rows:
        direct = row.find_all(['td', 'th'], recursive=False)
        if direct and not direct[0].find('table') and _label(direct[0].get_text(' ', strip=True)) == 'port of discharge':
            unloading.append(row)
    if len(unloading) > 1:
        raise ValueError('没有唯一的卸货港，需要人工核对官网，未写回')
    pol_raw = cells[1]
    pod_raw = port_cells(unloading[0], merged_name=True)[1] if unloading else None
    pol, pod = _port_name(pol_raw), _port_name(pod_raw) if pod_raw is not None else None
    warnings = []
    if pol is None:
        warnings.append('官网起运港为空，保留表格原值')
    if pod is None:
        warnings.append('官网目的港为空或缺失，保留表格原值')
    return {'etd': latest, 'raw': raw, 'pol': pol, 'pod': pod,
            'pol_raw': pol_raw, 'pod_raw': pod_raw, 'warnings': warnings}


class EvergreenClient:
    def __init__(self, headless=True, number_type='booking'):
        if number_type not in ('booking', 'bl'):
            raise ValueError('EVERGREEN_NUMBER_TYPE 必须是 booking 或 bl')
        self.headless, self.number_type = headless, number_type

    def fetch(self, number):
        async def single():
            async with self.session(1) as session:
                return await session.fetch(number, 0)
        return asyncio.run(single())

    def session(self, concurrency=2):
        return EvergreenSession(self, concurrency)


class EvergreenSession:
    def __init__(self, client, concurrency):
        self.client, self.concurrency = client, concurrency
        self.playwright = self.browser = None
        self.pages, self.consent_checked = [], set()

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=self.client.headless)
            for _ in range(self.concurrency):
                context = await self.browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(15000)
                async def resource_filter(route):
                    if route.request.resource_type in {'image', 'font', 'media'}:
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route('**/*', resource_filter)
                self.pages.append(page)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.playwright:
                await self.playwright.stop()

    async def fetch(self, number, lane):
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        page = self.pages[lane]
        # Navigation replaces the previous result page before filling this order.
        await page.goto(URL, wait_until='domcontentloaded', timeout=30000)
        consent = page.locator('#btn_cookie_essential_only')
        if lane not in self.consent_checked:
            try:
                await consent.wait_for(state='visible', timeout=8000)
            except PlaywrightTimeout:
                pass
            else:
                await consent.click()
                await page.locator('#modal_cookie_alert').wait_for(state='hidden')
                self.consent_checked.add(lane)
        elif await consent.is_visible():
            await consent.click()
            await page.locator('#modal_cookie_alert').wait_for(state='hidden')
        await page.locator('#s_bk' if self.client.number_type == 'booking' else '#s_bl').check()
        form = page.locator('#nav-quick')
        await form.locator("input[type='text']:visible").first.fill(number)
        await form.locator("input[value='Submit'], input[type='submit']").first.click()
        await page.get_by_text('Basic Information', exact=False).first.wait_for()
        return extract_etd(await page.content())
