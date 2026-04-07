# Playwright MCP Scraping Workflow

How to use the Playwright MCP browser tools to access genealogy sites that require interactive authentication, JavaScript rendering, or CAPTCHA solving. This workflow covers the general pattern and then documents specifics for three major platforms.

## When to Use This Workflow

Use Playwright MCP when a genealogy database:
- Requires login and cannot be accessed via direct HTTP
- Serves records only through JavaScript-rendered interfaces
- Uses CAPTCHAs that block automated requests
- Has useful data in its accessibility tree that can be extracted without parsing HTML

## General Pattern

### 1. Launch and navigate

```
browser_navigate(url)
browser_snapshot()   # always snapshot after navigation to see the page state
```

`browser_snapshot` returns the full accessibility tree as structured YAML: names, labels, links, table cells, and relationships. It is more useful than screenshots for structured data extraction. Use it after every navigation or page change.

### 2. Authenticate interactively

Most genealogy platforms use OAuth or session cookies. The general approach:

1. Navigate to the login page.
2. If the login form is visible in the snapshot, use `browser_fill_form` and `browser_click`.
3. If the login redirects to a third-party OAuth provider (Google, Facebook), ask the user to complete the login in the browser session. The Playwright session persists across your conversation turn; the cookies will be set when the user confirms.
4. After login, extract the session cookie:

```js
// browser_evaluate:
() => document.cookie
```

Save the cookie string to a file (e.g., `.playwright-mcp/{site}_cookies.txt`). Reuse it in subsequent Python HTTP calls for bulk fetching.

### 3. Handle CAPTCHAs

CAPTCHAs cannot be auto-solved. When a CAPTCHA appears:

1. Take a screenshot: `browser_take_screenshot`.
2. Show the screenshot to the user and ask them to read the value.
3. Type the value: `browser_type(selector, value)`.
4. Proceed once the CAPTCHA clears.

After solving, the session is usually valid for the remainder of the browser session. Re-solve only if the CAPTCHA reappears on a new page trigger.

### 4. Extract data from snapshots

The accessibility tree from `browser_snapshot` gives you names, labels, links, table cells, and form fields without parsing HTML. For each record or person page:

1. Navigate to the page.
2. Run `browser_snapshot`.
3. Extract the relevant fields from the YAML output.
4. Follow links to related records and repeat.

### 5. Reuse cookies in Python

For bulk fetching after an interactive session:

```python
import httpx

cookie_str = open(".playwright-mcp/{site}_cookies.txt").read().strip()
cookies = dict(c.strip().split("=", 1) for c in cookie_str.split(";"))

with httpx.Client(cookies=cookies, follow_redirects=True) as client:
    r = client.get("https://example-genealogy-site.com/record/123")
    # parse r.text with BeautifulSoup
```

Note: cookies expire. Re-run the interactive auth step if requests start returning login redirects.

---

## FamilySearch

FamilySearch requires authentication to access record images and the Family Tree. It uses Google OAuth for login.

### Authentication

1. Navigate to the target record URL via `browser_navigate`.
2. FamilySearch redirects to Google OAuth. Ask the user to complete the Google login in the browser.
3. After login, extract cookies:

```js
// browser_evaluate:
() => document.cookie
```

Save to `.playwright-mcp/familysearch_cookies.txt`. The critical cookie is `fssessionid`.

4. Cookies expire after approximately 30 minutes of inactivity. Re-login if requests fail.

Note: The FamilySearch platform API (`/platform/tree/persons/{PID}`) requires a Bearer token, not cookies. It cannot be accessed with session cookies alone. Use browser-based scraping for record images and tree profiles.

### Key URL Patterns

| Purpose | Pattern |
|---|---|
| Individual record (ARK) | `https://www.familysearch.org/ark:/61903/1:1/{ARK_ID}?lang=en` |
| Family Tree person profile | `https://www.familysearch.org/tree/person/details/{PID}` |
| Collection browse | `https://www.familysearch.org/search/collection/{COLLECTION_ID}` |
| Collection search | `https://www.familysearch.org/search/collection/{COLLECTION_ID}?q.surname={SURNAME}` |

### Recursive Traversal

Records are connected by ARK links visible in the snapshot. Each person record lists spouses, children, and parents as links. Follow them:

1. Start from a known record URL.
2. Run `browser_snapshot` and extract all person links (ARK IDs and Family Tree PIDs).
3. Navigate to each linked person and snapshot again.
4. Stop when a profile has no new links not yet visited, or when records have no further sources.

### Confidence Tiers

| Source type | Confidence |
|---|---|
| Indexed civil registration or parish record (ARK ID) | Strong Signal |
| Image-only record (browse, no index) | Moderate Signal |
| User-contributed Family Tree profile (PID) | Speculative |

Family Tree profiles (PIDs like `XXXX-XXX`) are community-edited. Always verify against primary source records (ARK IDs) before relying on tree data.

---

## MyHeritage

MyHeritage family sites can be accessed without authentication if the site owner has made them public. Private trees require login.

### Authentication

MyHeritage uses session cookies (PHPSESSID + perm_id). Log in via the Playwright browser and extract:

```js
// browser_evaluate:
() => document.cookie
```

Key cookies: `PHPSESSID` (session), `perm_id` (persistent identity), `LVTS` (login verification). Save to `.playwright-mcp/myheritage_cookies.txt`.

### URL Structure

| Purpose | Pattern |
|---|---|
| Family site home | `https://www.myheritage.com/family-sites/{slug}/{SITE_ID}` |
| People list | `https://www.myheritage.com/people-{SITE_ID}/{slug}` |
| Person profile | `https://www.myheritage.com/person-{SITE_ID}-{PERSON_ID}/{slug}` |
| Pedigree view | `https://www.myheritage.com/pedigree-tree-{SITE_ID}-{PERSON_ID}/{slug}` |
| Fan view | `https://www.myheritage.com/fan-view-{SITE_ID}-{PERSON_ID}/{slug}` |

### Scraping Strategy

1. Navigate to the people list URL (most reliable for bulk extraction).
2. Run `browser_snapshot` — it returns all person cards with names and dates.
3. For each person, navigate to their profile for parents, children, events, and sources.
4. The MyHeritage API (`/FP/API/ClanAPI/GetIndividual`) may also be used with session cookies for structured JSON, but requires reverse-engineering the call parameters for your specific site.

### Confidence Tiers

| Source type | Confidence |
|---|---|
| MyHeritage Record Matches (linked to civil/church records) | Strong Signal |
| Smart Matches (matched to another user's tree) | Moderate Signal |
| User-entered tree data with no attached source | Speculative |

---

## Hemeroteca Digital Brasileira (Biblioteca Nacional)

The Hemeroteca provides full-text OCR search across digitized Brazilian newspapers. It uses the DocReader Pro (Acervus) viewer, which serves images through a session-based cache.

- **Search entry point**: `https://memoria.bn.gov.br/hdb/` — select a title, then search within it.
- **DocReader direct URL**: `https://memoria.bn.gov.br/docreader/DocReader.aspx?bib={BIB_ID}&Pesq={search+term}` — opens a collection with search results pre-loaded.

### CAPTCHA Handling

Since October 2025, a numeric CAPTCHA appears on every new session and on each new page load trigger. The CAPTCHA shows 3 to 4 digits as a distorted image. It must be solved interactively (Playwright can display it but cannot auto-solve). After solving, the session allows page navigation without further CAPTCHAs until the session ends.

### DocReader Internal API (Reverse-Engineered)

The DocReader serves page images via a session-based cache URL:

```
https://memoria.bn.gov.br/docreader/cache/{HiddenID}/I{pagfis:07d}-1-0-{disp_h:06d}-{disp_w:06d}-{full_h:06d}-{full_w:06d}.JPG
```

Parameters:
- `HiddenID`: per-session cache token. Found in the hidden form field `<input id="HiddenID">` on the page. Changes with each new browser session.
- `pagfis`: absolute page number across the entire collection (not the page number within one edition).
- `disp_h`, `disp_w`: display dimensions requested by the browser (set by the `HiddenSize` field, e.g. `1493x814`). The server only serves the image at the exact dimensions already cached; requesting other dimensions returns 404.
- `full_h`, `full_w`: full native scan resolution (e.g. `006857x004288`).

**Resolution note**: the image resolution is locked to the browser viewport size at session time. To get a higher-resolution image, resize the browser window before triggering the page load.

### Step-by-Step Scraping Procedure

1. Navigate to `DocReader.aspx?bib={BIB_ID}&Pesq={SEARCH_TERM}&pagfis={FIRST_MATCH_PAGFIS}`.
2. Solve the CAPTCHA when it appears (screenshot, ask user to read digits, type the value).
3. Extract `HiddenID` from the form:

```js
// browser_evaluate:
() => document.getElementById('HiddenID').value
```

4. Extract the current image URL from the `<img>` tag to confirm the cache key and get `full_h`/`full_w`:

```js
// browser_evaluate:
() => document.querySelector('img[src*="cache"]').src
```

5. For each target page, set the `hPagFis` field and trigger the UpdatePanel postback:

```js
// browser_evaluate:
() => {
  document.getElementById('hPagFis').value = '0001234';
  document.getElementById('CarregaImagemHiddenButton').click();
}
```

6. Wait for the spinner to clear (`browser_wait_for`), then re-read the `<img>` src to get the new image URL.
7. Fetch the image URL with the session cookie to download the JPEG.

### Other Discovered Endpoints

| Endpoint | Notes |
|---|---|
| `DocUpload/Unlock.ashx?id={HiddenID}&bib={BIB}` | Session keepalive (POST) |
| `SessionHeartbeat.ashx` | Called every 15s by the client |
| `addons/captcha.aspx?id={...}&pagfis={...}` | CAPTCHA iframe source |

The OCR text API method name was not found. `DocReader.js` is served empty to direct fetch attempts due to CDN restrictions. Navigation between search matches uses the `>>` Next Match button, which triggers `__doPostBack` with the next `pagfis` embedded in the UpdatePanel response.

### Confidence Tiers

| Source type | Confidence |
|---|---|
| Death/birth/marriage notice in digitized newspaper, text confirmed | Strong Signal |
| Classified ad or public notice mentioning a name | Moderate Signal |
| OCR match without confirmed reading of the full text | Speculative |
