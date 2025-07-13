import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger(__name__)

class WebResearchManager:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.current_session: Dict[str, Any] = {"query": "", "results": [], "lastUpdated": ""}
        self.screenshots_dir: str = tempfile.mkdtemp(prefix="mcp-screenshots-")

    async def ensure_browser(self) -> Page:
        if not self.browser or not self.browser.is_connected():
            self.browser = await async_playwright().start().chromium.launch(headless=True)
            self.page = await self.browser.new_page()
        elif not self.page or self.page.is_closed():
            self.page = await self.browser.new_page()
        return self.page

    async def cleanup(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.page = None
        if os.path.exists(self.screenshots_dir):
            shutil.rmtree(self.screenshots_dir)

    async def _with_retry(self, operation, retries=3, delay=1000):
        last_error = None
        for i in range(retries):
            try:
                return await operation()
            except Exception as e:
                last_error = e
                logger.error(f"Attempt {i + 1} failed, retrying in {delay}ms: {e}")
                await asyncio.sleep(delay / 1000)
        raise last_error

    def _add_result(self, result: Dict[str, Any]):
        if not self.current_session["query"]:
            self.current_session["query"] = "Research Session"
        self.current_session["results"].append(result)
        if len(self.current_session["results"]) > 100: # MAX_RESULTS_PER_SESSION
            self.current_session["results"].pop(0)
        self.current_session["lastUpdated"] = self.get_current_timestamp()

    def get_current_timestamp(self) -> str:
        import datetime
        return datetime.datetime.now().isoformat()

    async def _dismiss_google_consent(self, page: Page):
        regions = [
            '.google.de', '.google.fr', '.google.co.uk',
            '.google.it', '.google.es', '.google.nl',
            '.google.pl', '.google.ie', '.google.dk',
            '.google.no', '.google.se', '.google.fi',
            '.google.at', '.google.ch', '.google.be',
            '.google.pt', '.google.gr', '.google.com.tr',
            '.google.co.id', '.google.com.sg', '.google.co.th',
            '.google.com.my', '.google.com.ph', '.google.com.au',
            '.google.co.nz', '.google.com.vn',
            '.google.com', '.google.co'
        ]
        try:
            current_url = page.url
            if not any(domain in current_url for domain in regions):
                return

            has_consent = await page.evaluate("""
                () => {
                    const selectors = [
                        'form:has(button[aria-label])',
                        'div[aria-modal="true"]',
                        'div[role="dialog"]',
                        'div[role="alertdialog"]',
                        'div[class*="consent"]',
                        'div[id*="consent"]',
                        'div[class*="cookie"]',
                        'div[id*="cookie"]',
                        'div[class*="modal"]:has(button)',
                        'div[class*="popup"]:has(button)',
                        'div[class*="banner"]:has(button)',
                        'div[id*="banner"]:has(button)'
                    ];
                    return selectors.some(selector => document.querySelector(selector));
                }
            """)
            if not has_consent:
                return

            await page.evaluate("""
                () => {
                    const consentPatterns = {
                        text: [
                            'accept all', 'agree', 'consent',
                            'alle akzeptieren', 'ich stimme zu', 'zustimmen',
                            'tout accepter', 'j\'accepte',
                            'aceptar todo', 'acepto',
                            'accetta tutto', 'accetto',
                            'aceitar tudo', 'concordo',
                            'alles accepteren', 'akkoord',
                            'zaakceptuj wszystko', 'zgadzam się',
                            'godkänn alla', 'godkänn',
                            'accepter alle', 'accepter',
                            'godta alle', 'godta',
                            'hyväksy kaikki', 'hyväksy',
                            'terima semua', 'setuju', 'saya setuju',
                            'terima semua', 'setuju',
                            'ยอมรับทั้งหมด', 'ยอมรับ',
                            'chấp nhận tất cả', 'đồng ý',
                            'tanggapin lahat', 'sumang-ayon',
                            'すべて同意する', '同意する',
                            '모두 동의', '동의'
                        ],
                        ariaLabels: [
                            'consent', 'accept', 'agree',
                            'cookie', 'privacy', 'terms',
                            'persetujuan', 'setuju',
                            'ยอมรับ',
                            'đồng ý',
                            '同意'
                        ]
                    };

                    const findAcceptButton = () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        return buttons.find(button => {
                            const text = button.textContent?.toLowerCase() || '';
                            const label = button.getAttribute('aria-label')?.toLowerCase() || '';
                            const hasMatchingText = consentPatterns.text.some(pattern => text.includes(pattern));
                            const hasMatchingLabel = consentPatterns.ariaLabels.some(pattern => label.includes(pattern));
                            return hasMatchingText || hasMatchingLabel;
                        });
                    };
                    const acceptButton = findAcceptButton();
                    if (acceptButton) {
                        acceptButton.click();
                    }
                }
            """)
        except Exception as e:
            logger.warning(f"Consent handling failed: {e}")

    async def _safe_page_navigation(self, page: Page, url: str):
        try:
            await page.context.add_cookies([{
                'name': 'CONSENT',
                'value': 'YES+',
                'domain': '.google.com',
                'path': '/'
            }])

            response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if not response:
                raise Exception('Navigation failed: no response received')

            status = response.status
            if status >= 400:
                raise Exception(f"HTTP {status}: {response.status_text}")

            await page.wait_for_load_state("networkidle", timeout=5000)

            validation = await page.evaluate("""
                () => {
                    const botProtectionExists = [
                        '#challenge-running',
                        '#cf-challenge-running',
                        '#px-captcha',
                        '#ddos-protection',
                        '#waf-challenge-html'
                    ].some(selector => document.querySelector(selector));

                    const suspiciousTitle = [
                        'security check',
                        'ddos protection',
                        'please wait',
                        'just a moment',
                        'attention required'
                    ].some(phrase => document.title.toLowerCase().includes(phrase));

                    const bodyText = document.body.innerText || '';
                    const words = bodyText.trim().split(/\s+/).length;

                    return {
                        wordCount: words,
                        botProtection: botProtectionExists,
                        suspiciousTitle: suspiciousTitle,
                        title: document.title
                    };
                }
            """)

            if validation["botProtection"]:
                raise Exception('Bot protection detected')
            if validation["suspiciousTitle"]:
                raise Exception(f"Suspicious page title detected: \"{validation['title']}\"")
            if validation["wordCount"] < 10:
                raise Exception('Page contains insufficient content')

        except Exception as e:
            raise Exception(f"Navigation to {url} failed: {e}")

    async def _take_screenshot_with_size_limit(self, page: Page) -> str:
        MAX_SIZE = 5 * 1024 * 1024
        MAX_DIMENSION = 1920
        MIN_DIMENSION = 800

        await page.set_viewport_size({"width": 1600, "height": 900})
        screenshot_bytes = await page.screenshot(type="png", full_page=False)

        buffer = screenshot_bytes
        attempts = 0
        MAX_ATTEMPTS = 3

        while len(buffer) > MAX_SIZE and attempts < MAX_ATTEMPTS:
            viewport = page.viewport_size
            if not viewport: continue

            scale_factor = (0.75)**(attempts + 1)
            new_width = round(viewport["width"] * scale_factor)
            new_height = round(viewport["height"] * scale_factor)

            new_width = max(MIN_DIMENSION, min(MAX_DIMENSION, new_width))
            new_height = max(MIN_DIMENSION, min(MAX_DIMENSION, new_height))

            await page.set_viewport_size({"width": new_width, "height": new_height})
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            buffer = screenshot_bytes
            attempts += 1

        if len(buffer) > MAX_SIZE:
            await page.set_viewport_size({"width": MIN_DIMENSION, "height": MIN_DIMENSION})
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            buffer = screenshot_bytes
            if len(buffer) > MAX_SIZE:
                raise Exception("Failed to reduce screenshot to under 5MB even with minimum settings")

        return buffer.base64().decode('utf-8')

    async def _save_screenshot(self, screenshot_base64: str, title: str) -> str:
        buffer = screenshot_base64.encode('utf-8') # Already base64 encoded
        MAX_SIZE = 5 * 1024 * 1024
        if len(buffer) > MAX_SIZE:
            raise Exception(f"Screenshot too large: {round(len(buffer) / (1024 * 1024))}MB exceeds {MAX_SIZE / (1024 * 1024)}MB limit")

        timestamp = self.get_current_timestamp()
        safe_title = re.sub(r'[^a-z0-9]', '_', title.lower())
        filename = f"{safe_title}-{timestamp}.png"
        filepath = os.path.join(self.screenshots_dir, filename)

        with open(filepath, "wb") as f:
            f.write(buffer) # Write bytes directly
        return filepath

    def _is_valid_url(self, url_string: str) -> bool:
        try:
            result = urlparse(url_string)
            return result.scheme in ['http', 'https']
        except ValueError:
            return False

    async def search_google(self, query: str) -> Dict[str, Any]:
        page = await self.ensure_browser()
        try:
            results = await self._with_retry(async def():
                await self._safe_page_navigation(page, 'https://www.google.com')
                await self._dismiss_google_consent(page)

                await self._with_retry(async def():
                    await page.wait_for_selector('input[name="q"], textarea[name="q"], input[type="text"]', timeout=5000)
                    search_input = await page.query_selector('input[name="q"]') or \
                                   await page.query_selector('textarea[name="q"]') or \
                                   await page.query_selector('input[type="text"]')
                    if not search_input:
                        raise Exception('Search input element not found after waiting')
                    await search_input.click(click_count=3)
                    await search_input.press('Backspace')
                    await search_input.type(query)
                , retries=3, delay=2000)

                await self._with_retry(async def():
                    await asyncio.gather(
                        page.keyboard.press('Enter'),
                        page.wait_for_load_state('networkidle', timeout=15000),
                    )
                })

                search_results = await self._with_retry(async def():
                    elements = await page.query_selector_all('div.g')
                    if not elements:
                        raise Exception('No search results found')

                    results_list = []
                    for el in elements:
                        title_el = await el.query_selector('h3')
                        link_el = await el.query_selector('a')
                        snippet_el = await el.query_selector('div.VwiC3b')

                        if title_el and link_el and snippet_el:
                            title = await title_el.text_content()
                            url = await link_el.get_attribute('href')
                            snippet = await snippet_el.text_content()
                            results_list.append({"title": title, "url": url, "snippet": snippet})
                    if not results_list:
                        raise Exception('No valid search results found')
                    return results_list
                })

                for result in search_results:
                    self._add_result({
                        "url": result["url"],
                        "title": result["title"],
                        "content": result["snippet"],
                        "timestamp": self.get_current_timestamp(),
                    })
                return search_results
            })
            return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Failed to perform search: {e}"}], "isError": True}

    async def visit_page(self, url: str, takeScreenshot: bool = False) -> Dict[str, Any]:
        if not self._is_valid_url(url):
            return {"content": [{"type": "text", "text": f"Invalid URL: {url}. Only http and https protocols are supported."}], "isError": True}

        page = await self.ensure_browser()
        try:
            result = await self._with_retry(async def():
                await self._safe_page_navigation(page, url)
                title = await page.title()

                content = await self._with_retry(async def():
                    extracted_content = await self._extract_content_as_markdown(page)
                    if not extracted_content:
                        raise Exception('Failed to extract content')
                    return extracted_content
                })

                page_result = {
                    "url": url,
                    "title": title,
                    "content": content,
                    "timestamp": self.get_current_timestamp(),
                }

                screenshot_uri = None
                if takeScreenshot:
                    screenshot_base64 = await self._take_screenshot_with_size_limit(page)
                    page_result["screenshotPath"] = await self._save_screenshot(screenshot_base64, title)
                    screenshot_uri = f"research://screenshots/{len(self.current_session['results'])}"
                    # TODO: Notify clients about new screenshot resource

                self._add_result(page_result)
                return {"pageResult": page_result, "screenshotUri": screenshot_uri}
            })
            return {"content": [{"type": "text", "text": json.dumps({
                "url": result["pageResult"]["url"],
                "title": result["pageResult"]["title"],
                "content": result["pageResult"]["content"],
                "timestamp": result["pageResult"]["timestamp"],
                "screenshot": f"View screenshot via *MCP Resources* (Paperclip icon) @ URI: {result['screenshotUri']}" if result['screenshotUri'] else None
            }, indent=2)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Failed to visit page: {e}"}], "isError": True}

    async def take_screenshot(self) -> Dict[str, Any]:
        page = await self.ensure_browser()
        try:
            screenshot_base64 = await self._with_retry(async def():
                return await self._take_screenshot_with_size_limit(page)
            })

            if not self.current_session["query"]:
                self.current_session = {"query": "Screenshot Session", "results": [], "lastUpdated": self.get_current_timestamp()}

            page_url = page.url
            page_title = await page.title()

            screenshot_path = await self._save_screenshot(screenshot_base64, page_title or 'untitled')

            result_index = len(self.current_session['results'])
            self._add_result({
                "url": page_url,
                "title": page_title or "Untitled Page",
                "content": "Screenshot taken",
                "timestamp": self.get_current_timestamp(),
                "screenshotPath": screenshot_path
            })

            screenshot_uri = f"research://screenshots/{result_index}"
            # TODO: Notify clients about new screenshot resource

            return {"content": [{"type": "text", "text": f"Screenshot taken successfully. You can view it via *MCP Resources* (Paperclip icon) @ URI: {screenshot_uri}"}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Failed to take screenshot: {e}"}], "isError": True}

    async def _extract_content_as_markdown(self, page: Page, selector: Optional[str] = None) -> str:
        html = await page.evaluate(f"""
            (sel) => {
                if (sel) {
                    const element = document.querySelector(sel);
                    return element ? element.outerHTML : '';
                }
                const contentSelectors = [
                    'main', 'article', '[role="main"]', '#content', '.content', '.main', '.post', '.article',
                ];
                for (const contentSelector of contentSelectors) {
                    const element = document.querySelector(contentSelector);
                    if (element) {
                        return element.outerHTML;
                    }
                }
                const body = document.body;
                const elementsToRemove = [
                    'header', 'footer', 'nav', '[role="navigation"]',
                    'aside', '.sidebar', '[role="complementary"]',
                    '.nav', '.menu',
                    '.header', '.footer',
                    '.advertisement', '.ads', '.cookie-notice',
                ];
                elementsToRemove.forEach(sel => {
                    body.querySelectorAll(sel).forEach(el => el.remove());
                });
                return body.outerHTML;
            }
        """, selector)

        if not html:
            return ''

        # This part would require a Python HTML to Markdown converter
        # For now, returning raw HTML or a simplified version
        # You would typically use a library like `markdownify` or `html2text` here
        return html # Placeholder

    def get_current_session_summary(self) -> Dict[str, Any]:
        return {
            "query": self.current_session["query"],
            "resultCount": len(self.current_session["results"]),
            "lastUpdated": self.current_session["lastUpdated"],
            "results": [
                {
                    "title": r["title"],
                    "url": r["url"],
                    "timestamp": r["timestamp"],
                    "screenshotPath": r.get("screenshotPath")
                }
                for r in self.current_session["results"]
            ]
        }

    def get_screenshot_data(self, index: int) -> bytes:
        if not self.current_session or index < 0 or index >= len(self.current_session["results"]):
            raise ValueError("Invalid screenshot index or no active session")
        result = self.current_session["results"][index]
        if not result.get("screenshotPath"):
            raise ValueError("No screenshot available at this index")
        with open(result["screenshotPath"], "rb") as f:
            return f.read()
