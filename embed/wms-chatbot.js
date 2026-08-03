(function () {
  var scriptEl = document.currentScript;
  if (!scriptEl) return;

  var apiBase = scriptEl.getAttribute("data-api-base");
  if (!apiBase) {
    console.error("[wms-chatbot] Missing required data-api-base attribute on the embed <script> tag.");
    return;
  }
  apiBase = apiBase.replace(/\/+$/, "");

  var school = scriptEl.getAttribute("data-school");
  var chatboxUrl = apiBase + "/chatbox";
  if (school) {
    chatboxUrl += "?school=" + encodeURIComponent(school);
  }

  var iframe = document.createElement("iframe");
  iframe.src = chatboxUrl;
  iframe.title = "Wells Middle School Chat";
  iframe.loading = "lazy";
  iframe.style.cssText = [
    "position: fixed",
    "bottom: 16px",
    "right: 16px",
    "width: 380px",
    "height: 600px",
    "max-width: calc(100vw - 32px)",
    "max-height: calc(100vh - 32px)",
    "border: none",
    "border-radius: 12px",
    "box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2)",
    "z-index: 2147483647",
    "background: #fff",
  ].join("; ");

  document.body.appendChild(iframe);
})();
