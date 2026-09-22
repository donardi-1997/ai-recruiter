from __future__ import annotations

from .browser_use_driver import (
    IndeedBrowserUse as _BaseIndeedBrowserUse,
    _CHALLENGE_MARKERS,
    _URL_CHALLENGE_MARKERS,
)


class IndeedBrowserUse(_BaseIndeedBrowserUse):
    """Browser driver with visibility-aware Indeed challenge detection.

    Indeed can keep anti-abuse/challenge iframes mounted in authenticated SPA
    pages. Those background frames must not block vacancy or candidate flows
    unless the frame itself is actually visible to the recruiter.
    """

    async def _page_state(self, cdp) -> dict:
        script = r"""
(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const iframes = Array.from(document.querySelectorAll('iframe'))
    .map((el) => {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const visible = style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number.parseFloat(style.opacity || '1') > 0
        && rect.width > 1
        && rect.height > 1;
      return {
        src: String(el.src || ''),
        visible,
      };
    })
    .filter((item) => item.src)
    .slice(0, 50);
  return {
    url: location.href,
    title: document.title || '',
    body: clean(document.body?.innerText || '').slice(0, 12000),
    iframes,
  };
})()
"""
        value = await self._evaluate(cdp, script)
        return value if isinstance(value, dict) else {}

    async def _requires_human(self, cdp) -> bool:
        state = await self._page_state(cdp)
        url = str(state.get("url") or "").casefold()
        if any(marker in url for marker in _URL_CHALLENGE_MARKERS):
            return True

        for frame in state.get("iframes") or []:
            if isinstance(frame, dict):
                if not bool(frame.get("visible")):
                    continue
                candidate = str(frame.get("src") or "").casefold()
            else:
                # Backwards compatibility for older diagnostic fixtures.
                candidate = str(frame or "").casefold()
            if any(marker in candidate for marker in _URL_CHALLENGE_MARKERS):
                return True

        body = str(state.get("body") or "").casefold()
        return any(marker in body for marker in _CHALLENGE_MARKERS)
