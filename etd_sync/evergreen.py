"""Evergreen queries, isolated per worker and sharing one browser per batch."""
import asyncio
from bs4 import BeautifulSoup

from .dates import parse_date

URL = 'https://ct.shipmentlink.com/servlet/TDB1_CargoTracking.do'


def extract_etd(html):
    soup = BeautifulSoup(html, 'html.parser')
    candidates = []
    def expand(row):
        values = []
        for cell in row.find_all(['td', 'th'], recursive=False):
            if int(cell.get('rowspan', 1)) != 1:
                raise ValueError('官网存在跨行表格，需要人工核对，未写回')
            values.extend([cell.get_text(' ', strip=True)] * int(cell.get('colspan', 1)))
        return values

    for cell in soup.find_all(['td', 'th']):
        if cell.find('table') or cell.get_text(' ', strip=True).lower() != 'port of loading':
            continue
        row = cell.find_parent('tr')
        table = row.find_parent('table')
        headers = [expand(r) for r in table.find_all('tr')
                   if r.find_parent('table') == table and any(
                       c.get_text(' ', strip=True) == 'Estimated Departure Date'
                       for c in r.find_all(['td', 'th'], recursive=False))]
        if len(headers) != 1 or headers[0].count('Estimated Departure Date') != 1:
            raise ValueError('无法唯一定位 Estimated Departure Date 表头，未写回')
        cells = expand(row)
        if len(cells) != len(headers[0]) or len(cells) < 2 or cells[0] != 'Port of Loading':
            raise ValueError('装货港行与表头不匹配，需要人工核对官网，未写回')
        raw = cells[headers[0].index('Estimated Departure Date')]
        latest = parse_date(raw)
        if latest is None:
            raise ValueError('官网装货港 ETD 为空，未写回')
        candidates.append({'etd': latest, 'raw': raw, 'pol': cells[1]})
    if len(candidates) != 1:
        raise ValueError('没有唯一的装货港 ETD，可能无数据或官网结构变化，未写回')
    return candidates[0]


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
