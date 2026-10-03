# Embedding the chat widget on a school website

Paste this snippet into the school website's HTML (ideally just before `</body>`):

```html
<script
  src="https://<app-host>/embed/wms-chatbot.js"
  data-api-base="https://<app-host>"
  data-school="wells"
  async
></script>
```

This injects a fixed-position widget in the bottom-right corner of the page,
pointing at an iframe of the chat UI (`GET /chatbox`). Because the widget runs
in an iframe, it can't leak CSS to or from the host page, and the host page
can't reach into it (or vice versa).

## Attributes

| Attribute        | Required | Description |
|-------------------|----------|-------------|
| `data-api-base`   | Yes      | Origin of the deployed bot (scheme + host, no trailing slash). The script loads `/chatbox` from this origin inside the iframe. |
| `data-school`     | No       | School identifier (e.g. `wells`, `dhs` — see `data/schools/`), forwarded to the chatbox as a `?school=` query param and from there to every `/chat` request. Omitting it falls back to `DEFAULT_SCHOOL_ID` server-side. |

`<app-host>` is the same origin that serves `/chat` and `/chatbox` — currently
wherever the FastAPI app is deployed (e.g. an ngrok tunnel or a hosted URL).

## Local testing

With the app running locally (`python main.py`), create a plain HTML file
anywhere and open it directly in a browser:

```html
<!DOCTYPE html>
<html>
<body>
  <h1>Test host page</h1>
  <script
    src="http://localhost:8000/embed/wms-chatbot.js"
    data-api-base="http://localhost:8000"
    data-school="wells"
    async
  ></script>
</body>
</html>
```

The chat widget should appear in the bottom-right corner. Sending a message
should round-trip through `/chat` and render a Markdown-formatted reply.

## Current hosting

`/embed/wms-chatbot.js` and `/chatbox` are served directly by the FastAPI app
as an interim measure. Sprint 1.7 (#10) will host both as static assets behind
a CDN, at which point `data-api-base` should point at the app's own backend
and the script `src` should point at the CDN URL instead.
