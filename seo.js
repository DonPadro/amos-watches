(async function applySeo() {
  const path = location.pathname;
  let page = "home";
  let id;
  if (path.startsWith("/item/")) {
    page = "item";
    id = Number(path.split("/")[2]);
  } else if (path.startsWith("/checkout")) page = "checkout";
  else if (path.startsWith("/admin")) page = "admin";
  try {
    const res = await fetch(`/api/seo?page=${encodeURIComponent(page)}${id ? `&id=${id}` : ""}`);
    const data = await res.json();
    if (data.title) document.title = data.title;
    const desc = document.querySelector('meta[name="description"]');
    if (desc && data.description) desc.setAttribute("content", data.description);
    const ogTitle = document.querySelector('meta[property="og:title"]') || document.createElement("meta");
    ogTitle.setAttribute("property", "og:title");
    ogTitle.setAttribute("content", data.title || document.title);
    document.head.append(ogTitle);
    const ogDesc = document.querySelector('meta[property="og:description"]') || document.createElement("meta");
    ogDesc.setAttribute("property", "og:description");
    ogDesc.setAttribute("content", data.description || "");
    document.head.append(ogDesc);
  } catch {
    /* keep static tags */
  }
})();
