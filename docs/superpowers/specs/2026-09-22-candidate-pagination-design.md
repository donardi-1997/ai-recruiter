# Candidate Pagination Design

## Goal

Paginate the Candidates view server-side with a fixed page size of 20 so the browser no longer loads every candidate record on each visit.

## Behavior

- `GET /api/candidates?page=<n>&page_size=20` returns a paginated object.
- Response shape contains `items`, `total`, `page`, `page_size`, and `pages`.
- Default page is 1 and fixed UI page size is 20.
- The Candidates page shows total profiles, visible range, current page, previous and next controls.
- Previous is disabled on page 1; Next is disabled on the final page.
- After add/delete/reload, if the current page no longer exists the UI moves to the last valid page.
- Existing candidate actions continue to operate on the candidates visible on the current page.

## API response

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20,
  "pages": 0
}
```

## Acceptance criteria

1. At most 20 candidate cards render at once.
2. The backend query uses limit/offset rather than loading all candidates then slicing in React.
3. Total is owner-scoped.
4. UI requests page 1 with page size 20 on initial load.
5. Next/Previous request the expected server page.
6. The UI displays `Página X de Y` and `Mostrando A–B` when candidates exist.
7. Existing actions and modal behavior continue to work.
8. No merge to `main` is performed from this branch without explicit approval.
