"""Exercise the actual static site in Chromium; save review screenshots locally."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / '.verification'
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:4173', wait_until='networkidle')
    page.wait_for_function("document.querySelector('.sidebar-meta code').textContent !== '—'")
    page.screenshot(path=str(OUT / 'overview-desktop.png'), full_page=True, animations='disabled')
    assert page.locator('.node').count() == 12
    page.locator('.node[data-value="brain"]').click()
    assert page.locator('dialog').is_visible()
    page.locator('#tab-internals').click()
    assert page.locator('.internal-step').count() == 4
    page.locator('[data-action="file"][data-value="declaw/brain/loop.py"]').click()
    assert 'build_agent_graph' in page.locator('.source-code').inner_text()
    page.screenshot(path=str(OUT / 'source-desktop.png'), full_page=True)
    page.keyboard.press('Escape')
    assert page.locator('dialog').count() == 0
    for lang, title in [('fr','Tout le système.'),('vi','Toàn bộ hệ thống.'),('en','The whole system.')]:
        page.select_option('#language',lang)
        assert page.locator('html').get_attribute('lang') == lang
        assert title in page.locator('h1').inner_text()
    page.locator('[data-action="level"][data-value="context"]').click()
    assert page.locator('.node').count() == 6
    page.locator('.node[data-value="core"]').click()
    assert page.locator('.node').count() == 12
    page.locator('[data-action="view"][data-value="flows"]').click()
    for journey in ['chat','read','write','index','search']:
        page.locator(f'[data-action="journey"][data-value="{journey}"]').click()
        count=page.locator('.step').count()
        for i in range(count):
            page.locator(f'[data-action="step"][data-value="{i}"]').click()
            assert page.locator('.node.illuminated').count() == 2
            assert page.locator('.wire.live').count() == 1
        page.locator('.step-contract [data-action="edge"]').click()
        assert page.locator('.contract-fields').is_visible()
        page.keyboard.press('Escape')
    page.locator('[data-action="journey"][data-value="read"]').click()
    page.locator('[data-action="play"]').click()
    page.wait_for_timeout(4400)
    assert page.locator('.step.active').get_attribute('data-value') == '1'
    page.locator('[data-action="play"]').click()
    page.screenshot(path=str(OUT / 'journey-desktop.png'), full_page=True)
    page.locator('[data-action="view"][data-value="directory"]').click()
    page.locator('#search').fill('loop.py')
    assert page.locator('.component-card').count() == 1
    page.locator('#search').fill('no-module-exists-with-this-name')
    assert page.locator('.empty').is_visible()
    page.locator('#search').fill('')
    assert page.locator('.component-card').count() == 12
    page.goto('http://127.0.0.1:4173/#view=overview&lang=fr&node=tools',wait_until='networkidle')
    assert page.locator('dialog').is_visible()
    assert 'Registre' in page.locator('#detail-title').inner_text()
    page.locator('#tab-internals').click()
    assert page.locator('.internal-flow.branching').is_visible()
    page.keyboard.press('Escape')
    page.set_viewport_size({'width':390,'height':844})
    page.select_option('#language','vi')
    page.screenshot(path=str(OUT / 'overview-mobile.png'),full_page=True, animations='disabled')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('[data-action="view"][data-value="directory"]').click()
    page.locator('[data-action="node"][data-value="documents"]').click()
    page.screenshot(path=str(OUT / 'detail-mobile.png'),full_page=True)
    assert page.locator('dialog').bounding_box()['width'] <= 390
    page.keyboard.press('Escape')
    page.emulate_media(reduced_motion='reduce')
    page.locator('[data-action="view"][data-value="flows"]').click()
    assert page.locator('.wire.live').evaluate('(el)=>getComputedStyle(el).animationName') == 'none'
    page.locator('[data-action="theme"]').click()
    assert page.locator('html').get_attribute('data-theme') == 'dark'
    page.screenshot(path=str(OUT / 'journey-mobile-dark.png'),full_page=True)
    assert errors == [], errors
    print('Browser checks passed: all journeys, source drilldown, translations, search, deep links, mobile bounds, themes and reduced motion.')
    browser.close()
