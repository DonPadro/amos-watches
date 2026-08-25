const featuredGrid = document.getElementById("featured-grid");
const collectionsRoot = document.getElementById("collections");
const modal = document.getElementById("product-modal");
const inquiryForm = document.getElementById("inquiry-form");
const formNote = document.getElementById("form-note");
const liveCount = document.getElementById("live-count");
const searchPanel = document.getElementById("search-panel");
const wishPanel = document.getElementById("wish-panel");
const drawer = document.getElementById("drawer");
const drawerBackdrop = document.getElementById("drawer-backdrop");
const menuToggle = document.getElementById("menu-toggle");

let catalog = { categories: [], products: [] };
let activeProduct = null;
const wishlist = new Set(JSON.parse(localStorage.getItem("amos-wish") || "[]"));
const cart = JSON.parse(localStorage.getItem("amos-cart") || "[]");

function saveWish() {
  localStorage.setItem("amos-wish", JSON.stringify([...wishlist]));
}

function saveCart() {
  localStorage.setItem("amos-cart", JSON.stringify(cart));
  const count = document.getElementById("cart-count");
  if (count) count.textContent = String(cart.reduce((sum, item) => sum + (item.qty || 1), 0));
}

function formatPrice(value) {
  return `₪${Number(value).toLocaleString("he-IL")}`;
}

function card(product) {
  const button = document.createElement("button");
  button.className = "card";
  button.type = "button";
  const img = document.createElement("img");
  img.src = product.image;
  img.alt = product.title;
  const body = document.createElement("div");
  body.className = "card-body";
  const cat = document.createElement("p");
  cat.className = "eyebrow";
  cat.textContent = product.category;
  const title = document.createElement("h3");
  title.textContent = product.title;
  const price = document.createElement("p");
  price.className = "price";
  price.textContent = product.price_label || formatPrice(product.price);
  body.append(cat, title, price);
  if (product.featured) {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "נבחר";
    body.append(badge);
  }
  button.append(img, body);
  button.addEventListener("click", () => openProduct(product));
  return button;
}

function renderCatalog() {
  featuredGrid.replaceChildren();
  collectionsRoot.replaceChildren();
  catalog.products.filter((p) => p.featured).forEach((p) => featuredGrid.append(card(p)));
  if (!featuredGrid.children.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "סמנו פריטים כמומלצים בפאנל הניהול.";
    featuredGrid.append(empty);
  }

  catalog.categories.forEach((category, index) => {
    const section = document.createElement("section");
    section.className = `collection ${index % 2 ? "collection-alt" : ""}`;
    section.id = `cat-${category.slug}`;
    const head = document.createElement("header");
    head.className = "section-head";
    head.innerHTML = `<p class="eyebrow">Collection</p>`;
    const h2 = document.createElement("h2");
    h2.textContent = category.name;
    const desc = document.createElement("p");
    desc.textContent = category.description;
    head.append(h2, desc);
    const grid = document.createElement("div");
    grid.className = "grid";
    catalog.products
      .filter((p) => p.category_id === category.id)
      .forEach((p) => grid.append(card(p)));
    if (!grid.children.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "אין עדיין פריטים בקטגוריה.";
      grid.append(empty);
    }
    section.append(head, grid);
    collectionsRoot.append(section);
  });
}

function openProduct(product) {
  activeProduct = product;
  document.getElementById("modal-image").src = product.image;
  document.getElementById("modal-image").alt = product.title;
  document.getElementById("modal-cat").textContent = product.category;
  document.getElementById("modal-title").textContent = product.title;
  document.getElementById("modal-desc").textContent = product.description;
  document.getElementById("modal-price").textContent = product.price_label || formatPrice(product.price);
  document.getElementById("modal-wish").textContent = wishlist.has(product.id) ? "הסירו משמורים" : "שמירה";
  modal.showModal();
}

function whatsappUrl(text) {
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}

function setLive(count) {
  liveCount.textContent = String(count);
}

function connectPresence() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  try {
    const socket = new WebSocket(`${proto}://${location.host}/ws/presence`);
    socket.addEventListener("message", (event) => {
      const data = JSON.parse(event.data);
      if (data.count) setLive(data.count);
    });
    setInterval(() => {
      if (socket.readyState === 1) socket.send("ping");
    }, 20000);
    socket.addEventListener("close", () => {
      fetch("/api/presence")
        .then((r) => r.json())
        .then((d) => setLive(d.count))
        .catch(() => {});
    });
  } catch {
    fetch("/api/presence")
      .then((r) => r.json())
      .then((d) => setLive(d.count))
      .catch(() => {});
  }
}

function setMenu(open) {
  drawer.classList.toggle("open", open);
  drawer.hidden = false;
  drawer.setAttribute("aria-hidden", String(!open));
  drawerBackdrop.hidden = !open;
  menuToggle.setAttribute("aria-expanded", String(open));
  document.body.style.overflow = open ? "hidden" : "";
}

menuToggle.addEventListener("click", () => setMenu(!drawer.classList.contains("open")));
drawerBackdrop.addEventListener("click", () => setMenu(false));
drawer.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setMenu(false)));

document.getElementById("modal-cart").addEventListener("click", () => {
  if (!activeProduct) return;
  const found = cart.find((item) => item.id === activeProduct.id);
  if (found) found.qty += 1;
  else cart.push({ id: activeProduct.id, title: activeProduct.title, price: activeProduct.price, price_label: activeProduct.price_label, qty: 1 });
  saveCart();
  document.getElementById("modal-cart").textContent = "בעגלה";
});

document.getElementById("cart-open").addEventListener("click", () => {
  location.href = "/checkout";
});

document.getElementById("modal-ask").addEventListener("click", () => {
  if (!activeProduct) return;
  const text = `שלום AMOS, מתעניין/ת בפריט: ${activeProduct.title} (${activeProduct.price_label})`;
  window.open(whatsappUrl(text), "_blank", "noopener");
});

document.getElementById("modal-wish").addEventListener("click", () => {
  if (!activeProduct) return;
  if (wishlist.has(activeProduct.id)) wishlist.delete(activeProduct.id);
  else wishlist.add(activeProduct.id);
  saveWish();
  document.getElementById("modal-wish").textContent = wishlist.has(activeProduct.id)
    ? "הסירו משמורים"
    : "שמירה";
});

document.querySelector(".modal-close").addEventListener("click", () => modal.close());
modal.addEventListener("click", (event) => {
  if (event.target === modal) modal.close();
});

inquiryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(inquiryForm);
  const text = [
    "פנייה מאתר AMOS",
    `שם: ${data.get("name")}`,
    `טלפון: ${data.get("phone")}`,
    `הודעה: ${data.get("message") || "—"}`,
  ].join("\n");
  window.open(whatsappUrl(text), "_blank", "noopener");
  formNote.hidden = false;
  formNote.textContent = "נפתח וואטסאפ עם ההודעה. אם זה לא קרה, כתבו באינסטגרם @amos_watches_il";
});

document.getElementById("search-open").addEventListener("click", () => {
  wishPanel.hidden = true;
  searchPanel.hidden = !searchPanel.hidden;
  if (!searchPanel.hidden) document.getElementById("search-input").focus();
});

document.getElementById("search-input").addEventListener("input", (event) => {
  const q = event.target.value.trim().toLowerCase();
  const box = document.getElementById("search-results");
  box.replaceChildren();
  if (!q) return;
  catalog.products
    .filter((p) => `${p.title} ${p.description} ${p.category}`.toLowerCase().includes(q))
    .slice(0, 8)
    .forEach((p) => {
      const btn = document.createElement("button");
      btn.className = "search-hit";
      btn.type = "button";
      btn.textContent = `${p.title} · ${p.price_label}`;
      btn.addEventListener("click", () => {
        searchPanel.hidden = true;
        openProduct(p);
      });
      box.append(btn);
    });
});

document.getElementById("wish-open").addEventListener("click", () => {
  searchPanel.hidden = true;
  wishPanel.hidden = !wishPanel.hidden;
  const box = document.getElementById("wish-list");
  box.replaceChildren();
  const items = catalog.products.filter((p) => wishlist.has(p.id));
  if (!items.length) {
    box.textContent = "עדיין אין פריטים שמורים.";
    return;
  }
  items.forEach((p) => {
    const btn = document.createElement("button");
    btn.className = "wish-item";
    btn.type = "button";
    btn.textContent = `${p.title} · ${p.price_label}`;
    btn.addEventListener("click", () => openProduct(p));
    box.append(btn);
  });
});

const aiPanel = document.getElementById("ai-panel");
const aiLog = document.getElementById("ai-log");
document.getElementById("ai-launch").addEventListener("click", () => {
  aiPanel.hidden = !aiPanel.hidden;
});
document.getElementById("ai-close").addEventListener("click", () => {
  aiPanel.hidden = true;
});

function addAi(role, text) {
  const p = document.createElement("p");
  p.className = `ai-msg ${role}`;
  p.textContent = text;
  aiLog.append(p);
  aiLog.scrollTop = aiLog.scrollHeight;
}

addAi("bot", "שלום, אני העוזר של AMOS. אפשר לשאול על שעונים, תכשיטים, תקציב או איך להזמין.");

document.getElementById("ai-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("ai-input");
  const message = input.value.trim();
  if (!message) return;
  addAi("user", message);
  input.value = "";
  try {
    const res = await fetch("/api/ai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    addAi("bot", data.reply);
  } catch {
    addAi("bot", "הרגע לא הצלחתי להתחבר. נסו שוב או כתבו באינסטגרם.");
  }
});

window.addEventListener("scroll", () => {
  const max = document.documentElement.scrollHeight - window.innerHeight;
  document.getElementById("progress").style.width = `${max > 0 ? (window.scrollY / max) * 100 : 0}%`;
});

async function boot() {
  const res = await fetch("/api/catalog");
  catalog = await res.json();
  renderCatalog();
  saveCart();
  connectPresence();
  const reviews = await fetch("/api/google-reviews").then((r) => r.json()).catch(() => ({ reviews: [] }));
  const grid = document.getElementById("reviews-grid");
  if (grid) {
    if (!reviews.reviews || !reviews.reviews.length) {
      grid.textContent = reviews.configured
        ? "אין ביקורות להצגה כרגע."
        : "חברו GOOGLE_PLACES_API_KEY ו-GOOGLE_PLACE_ID כדי למשוך ביקורות.";
    } else {
      reviews.reviews.forEach((review) => {
        const article = document.createElement("article");
        article.className = "card-body";
        article.style.border = "1px solid var(--line)";
        const h = document.createElement("h3");
        h.textContent = `${review.author} · ${"★".repeat(review.rating || 0)}`;
        const p = document.createElement("p");
        p.textContent = review.body;
        article.append(h, p);
        grid.append(article);
      });
    }
  }
}

boot();
