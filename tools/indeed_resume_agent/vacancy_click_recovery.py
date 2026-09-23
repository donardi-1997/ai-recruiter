from __future__ import annotations

import asyncio
import json

from . import vacancy_sync


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


async def click_listing_row_with_recovery(browser, cdp, row: dict) -> bool:
    """Open the exact SPA vacancy represented by a listing snapshot.

    The temporary DOM token is the preferred identity. If Indeed reloads the
    listing and drops that token before the row is opened, reacquire the row
    using the stable provider id when available. For pending SPA rows without
    an id yet, match the exact visible row signature and use its recorded
    absolute vertical position to disambiguate visually identical vacancies.
    Ambiguous recovery fails closed instead of clicking the first title match.
    """

    token = str(row.get("clickToken") or "").strip()
    external_job_key = str(row.get("externalJobKey") or "").strip()
    title = _clean_text(row.get("title"))
    row_text = _clean_text(row.get("rowText"))
    scroll_y = max(0, int(row.get("scrollY") or 0))
    try:
        row_position = float(row.get("rowPosition"))
    except (TypeError, ValueError):
        row_position = None

    await browser._evaluate(cdp, f"window.scrollTo(0, {scroll_y}); true")
    await asyncio.sleep(0.18)

    payload = json.dumps(
        {
            "token": token,
            "externalJobKey": external_job_key,
            "title": title,
            "rowText": row_text,
            "rowPosition": row_position,
        },
        ensure_ascii=False,
    )
    script = f"""
(() => {{
  const target = {payload};
  const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
  const byToken = target.token
    ? document.querySelector(`[data-asiati-vacancy-token="${{CSS.escape(target.token)}}"]`)
    : null;
  if (byToken) {{ byToken.click(); return true; }}

  const identityAttrs = [
    'data-job-id','data-jobid','data-job-key','data-jobkey',
    'data-indeed-job-id','data-indeed-job-key'
  ];
  for (const attr of identityAttrs) {{
    const escaped = CSS.escape(target.externalJobKey || '');
    const root = escaped ? document.querySelector(`[${{attr}}="${{escaped}}"]`) : null;
    if (!root) continue;
    const clickable = root.matches('a,button,[role="link"]')
      ? root
      : root.querySelector('a,button,[role="link"]');
    if (clickable) {{ clickable.click(); return true; }}
  }}

  const candidates = Array.from(document.querySelectorAll('a,button,[role="link"]'))
    .filter((node) => clean(node.getAttribute?.('aria-label') || node.innerText || node.textContent || '') === target.title)
    .map((node) => {{
      const root = node.closest('tr,[role="row"],[data-testid*="job" i],article,li') || node;
      const text = clean(root.innerText || root.textContent || '');
      const absoluteY = Number((root.getBoundingClientRect?.().top || 0) + window.scrollY);
      return {{node, text, absoluteY}};
    }})
    .filter((item) => !target.rowText || item.text === target.rowText);

  if (candidates.length === 1) {{ candidates[0].node.click(); return true; }}
  if (candidates.length < 2 || !Number.isFinite(target.rowPosition)) return false;

  const ranked = candidates
    .map((item) => ({{...item, distance: Math.abs(item.absoluteY - target.rowPosition)}}))
    .sort((a, b) => a.distance - b.distance);

  if (!ranked.length) return false;
  if (ranked.length > 1 && Math.abs(ranked[0].distance - ranked[1].distance) < 0.5) return false;

  // A global banner/header may move every row slightly after reload. The
  // closest exact-signature row is still deterministic as long as the nearest
  // candidate is unique; do not fall back to the first title match.
  ranked[0].node.click();
  return true;
}})()
"""
    return bool(await browser._evaluate(cdp, script))


def install_vacancy_click_recovery() -> None:
    vacancy_sync._click_listing_row = click_listing_row_with_recovery
