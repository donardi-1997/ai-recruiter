from __future__ import annotations

import asyncio
import json

from . import vacancy_sync


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


async def click_listing_row_with_recovery(browser, cdp, row: dict) -> bool:
    """Open the exact SPA vacancy represented by a listing snapshot.

    Temporary DOM tokens are accepted only while the marked node still matches
    the discovered vacancy. Stable provider identity is authoritative. If a
    reload removes both, a unique title may be recovered even when dynamic
    counters changed; exact duplicate rows fail closed instead of being guessed
    from their vertical position.
    """

    token = str(row.get("clickToken") or "").strip()
    external_job_key = str(row.get("externalJobKey") or "").strip()
    title = _clean_text(row.get("title"))
    row_text = _clean_text(row.get("rowText"))
    scroll_y = max(0, int(row.get("scrollY") or 0))

    await browser._evaluate(cdp, f"window.scrollTo(0, {scroll_y}); true")
    await asyncio.sleep(0.18)

    payload = json.dumps(
        {
            "token": token,
            "externalJobKey": external_job_key,
            "title": title,
            "rowText": row_text,
        },
        ensure_ascii=False,
    )
    script = f"""
(() => {{
  const target = {payload};
  const clean = (v) => String(v || '').replace(/\\s+/g, ' ').trim();
  const identityAttrs = [
    'data-job-id','data-jobid','data-job-key','data-jobkey',
    'data-indeed-job-id','data-indeed-job-key'
  ];
  const rowRoot = (node) => node?.closest?.(
    'tr,[role="row"],[data-testid*="job" i],article,li'
  ) || node;
  const nodeTitle = (node) => clean(
    node?.getAttribute?.('aria-label') || node?.innerText || node?.textContent || ''
  );
  const rootIdentity = (root) => {{
    if (!root) return '';
    for (const attr of identityAttrs) {{
      const direct = clean(root.getAttribute?.(attr));
      if (direct) return direct;
      const nested = root.querySelector?.(`[${{attr}}]`);
      const value = clean(nested?.getAttribute?.(attr));
      if (value) return value;
    }}
    return '';
  }};

  // A virtualized list can recycle the same DOM node while leaving our custom
  // token behind. Never trust the token without revalidating current content.
  const byToken = target.token
    ? document.querySelector(`[data-asiati-vacancy-token="${{CSS.escape(target.token)}}"]`)
    : null;
  if (byToken) {{
    const root = rowRoot(byToken);
    const currentTitle = nodeTitle(byToken);
    const currentText = clean(root?.innerText || root?.textContent || '');
    const currentIdentity = rootIdentity(root);
    const identityMatches = target.externalJobKey
      ? currentIdentity === target.externalJobKey
      : !currentIdentity;
    const pendingSignatureMatches = target.externalJobKey
      ? true
      : (!target.rowText || currentText === target.rowText);
    if (
      currentTitle === target.title
      && identityMatches
      && pendingSignatureMatches
    ) {{
      byToken.click();
      return true;
    }}
  }}

  // Stable provider identity is safe even after arbitrary row reordering.
  if (target.externalJobKey) {{
    for (const attr of identityAttrs) {{
      const escaped = CSS.escape(target.externalJobKey);
      const root = document.querySelector(`[${{attr}}="${{escaped}}"]`);
      if (!root) continue;
      const clickable = root.matches('a,button,[role="link"]')
        ? root
        : root.querySelector('a,button,[role="link"]');
      if (clickable && nodeTitle(clickable) === target.title) {{
        clickable.click();
        return true;
      }}
    }}
  }}

  const titleMatches = Array.from(document.querySelectorAll('a,button,[role="link"]'))
    .filter((node) => nodeTitle(node) === target.title)
    .map((node) => {{
      const root = rowRoot(node);
      return {{
        node,
        text: clean(root?.innerText || root?.textContent || ''),
        identity: rootIdentity(root),
      }};
    }})
    // A row that gained a stable identity different from the discovered one is
    // never a safe fallback candidate.
    .filter((item) => !target.externalJobKey || item.identity === target.externalJobKey);

  // A unique title is deterministic and tolerates live counters/status copy
  // changing between discovery and click.
  if (titleMatches.length === 1) {{
    titleMatches[0].node.click();
    return true;
  }}

  if (titleMatches.length < 2) return false;

  // For duplicate titles, exact row text can disambiguate only when it yields
  // one unique candidate. If identical rows remain, there is no safe identity
  // after token/provider id loss; fail closed instead of guessing by geometry.
  const exactSignature = titleMatches.filter(
    (item) => target.rowText && item.text === target.rowText
  );
  if (exactSignature.length === 1) {{
    exactSignature[0].node.click();
    return true;
  }}
  return false;
}})()
"""
    return bool(await browser._evaluate(cdp, script))


def install_vacancy_click_recovery() -> None:
    vacancy_sync._click_listing_row = click_listing_row_with_recovery
