"""Check all beat endings, text bounds, and the staged write result."""
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

URL = 'http://127.0.0.1:8776/agent-first/ch01/'


async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('CHROME'))
        page = await browser.new_page(viewport={'width': 1640, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(URL + '?beat=0&t=0')
        durations = await page.evaluate('BEATS.map(b => TIMINGS[b.id].dur)')
        for i, duration in enumerate(durations):
            await page.goto(URL + f'?beat={i}&t={duration}')
            await page.wait_for_timeout(100)
            outside = await page.evaluate('''() => {
              const stage = document.querySelector('#stage').getBoundingClientRect();
              return [...document.querySelectorAll('#scene text')].filter(e => {
                let opacity = 1;
                for (let q = e; q && q.id !== 'stage'; q = q.parentElement)
                  opacity *= Number(getComputedStyle(q).opacity);
                if (opacity < .9) return false;
                const b = e.getBoundingClientRect();
                return b.left < stage.left + 10 || b.right > stage.right - 10 ||
                  b.top < stage.top + 10 || b.bottom > stage.bottom - 10;
              }).map(e => e.textContent);
            }''')
            if outside:
                errors.append({'beat': i, 'outside': outside})
        marks = await page.evaluate('TIMINGS.second.marks')
        for label, t, expected in [('before', marks['write'] - .1, False),
                                   ('after', marks['success'] + 1, True)]:
            await page.goto(URL + f'?beat=5&t={t}')
            visible = await page.evaluate('''() => [...document.querySelectorAll('#scene text')].some(e => {
              if (e.textContent !== 'tool：写入成功') return false;
              let opacity = 1;
              for (let q = e; q && q.id !== 'stage'; q = q.parentElement)
                opacity *= Number(getComputedStyle(q).opacity);
              return opacity > .9;
            })''')
            if visible != expected:
                errors.append({'timing': label, 'visible': visible})
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.goto(URL)
        if await page.evaluate('document.documentElement.scrollWidth > innerWidth'):
            errors.append('mobile horizontal overflow')
        await browser.close()
    result = {'beats': len(durations), 'geometry_and_staged_result_errors': errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    Path('books/agent-first/review/verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


asyncio.run(main())
