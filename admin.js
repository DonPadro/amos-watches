const loginView = document.getElementById("login-view");
const adminView = document.getElementById("admin-view");
let catalog = { categories: [], products: [] };

async function api(url, options = {}) {
  const res = await fetch(url, { credentials: "include", ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "שגיאה");
  return data;
}

function fillCategories() {
  const select = document.querySelector("#product-form [name=category_id]");
  select.replaceChildren();
  catalog.categories.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = c.name;
    select.append(opt);
  });
}

function renderLists() {
  const cats = document.getElementById("category-list");
  const products = document.getElementById("product-list");
  cats.replaceChildren();
  products.replaceChildren();
  catalog.categories.forEach((c) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<div></div><div><strong></strong><p></p></div><menu></menu>`;
    row.querySelector("strong").textContent = c.name;
    row.querySelector("p").textContent = c.slug;
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "עריכה";
    edit.addEventListener("click", () => {
      const form = document.getElementById("category-form");
      form.id.value = c.id;
      form.name.value = c.name;
      form.slug.value = c.slug;
      form.description.value = c.description;
      form.sort_order.value = c.sort_order;
    });
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "מחיקה";
    del.addEventListener("click", async () => {
      if (!confirm("למחוק קטגוריה ואת הפריטים שבה?")) return;
      await api(`/api/admin/categories/${c.id}`, { method: "DELETE" });
      await refresh();
    });
    row.querySelector("menu").append(edit, del);
    cats.append(row);
  });

  catalog.products.forEach((p) => {
    const row = document.createElement("div");
    row.className = "row";
    const img = document.createElement("img");
    img.src = p.image;
    img.alt = p.title;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = p.title;
    const meta = document.createElement("p");
    meta.textContent = `${p.category} · ${p.price_label}${p.featured ? " · נבחר" : ""}`;
    info.append(title, meta);
    const menu = document.createElement("menu");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "עריכה";
    edit.addEventListener("click", () => {
      const form = document.getElementById("product-form");
      form.id.value = p.id;
      form.category_id.value = p.category_id;
      form.title.value = p.title;
      form.price.value = p.price;
      form.description.value = p.description;
      form.image_url.value = p.image.startsWith("/uploads/") ? "" : p.image;
      form.featured.checked = p.featured;
    });
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "מחיקה";
    del.addEventListener("click", async () => {
      if (!confirm("למחוק פריט?")) return;
      await api(`/api/admin/products/${p.id}`, { method: "DELETE" });
      await refresh();
    });
    menu.append(edit, del);
    row.append(img, info, menu);
    products.append(row);
  });
}

async function refresh() {
  catalog = await api("/api/catalog");
  const stats = await api("/api/admin/stats");
  document.getElementById("admin-online").textContent = stats.online;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><span>פריטים</span><b>${stats.products}</b></div>
    <div class="stat"><span>קטגוריות</span><b>${stats.categories}</b></div>
    <div class="stat"><span>הזמנות</span><b>${stats.orders || 0}</b></div>
    <div class="stat"><span>שולמו</span><b>${stats.paid || 0}</b></div>
    <div class="stat"><span>אונליין</span><b>${stats.online}</b></div>
  `;
  fillCategories();
  renderLists();
  await renderOps();
}

async function showAdmin() {
  loginView.hidden = true;
  adminView.hidden = false;
  await refresh();
}

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.getElementById("login-error");
  error.hidden = true;
  try {
    await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        password: event.target.password.value,
        email: event.target.email.value || "owner@amos",
      }),
    });
    await showAdmin();
  } catch (err) {
    error.hidden = false;
    error.textContent = err.message;
  }
});

document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

document.getElementById("category-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = {
    name: form.name.value,
    slug: form.slug.value,
    description: form.description.value,
    sort_order: Number(form.sort_order.value || 0),
  };
  const id = form.id.value;
  await api(id ? `/api/admin/categories/${id}` : "/api/admin/categories", {
    method: id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  form.reset();
  form.id.value = "";
  await refresh();
});

document.getElementById("product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  data.set("featured", form.featured.checked ? "1" : "0");
  const id = form.id.value;
  data.delete("id");
  await api(id ? `/api/admin/products/${id}` : "/api/admin/products", {
    method: id ? "PUT" : "POST",
    body: data,
  });
  form.reset();
  form.id.value = "";
  await refresh();
});

api("/api/me").then((me) => {
  if (me.admin) showAdmin();
});

async function renderOps() {
  const ordersBox = document.getElementById("order-list");
  const orders = await api("/api/admin/orders");
  ordersBox.replaceChildren();
  (orders.orders || []).forEach((order) => {
    const row = document.createElement("div");
    row.className = "row";
    const info = document.createElement("div");
    info.innerHTML = "<strong></strong><p></p>";
    info.querySelector("strong").textContent = `${order.public_id} · ${order.status} · ₪${order.total}`;
    const ship = [order.address, order.city, order.zip].filter(Boolean).join(" · ");
    info.querySelector("p").textContent = `${order.customer_name} · ${order.phone} · ${order.email}${ship ? " · " + ship : ""}`;
    const menu = document.createElement("menu");
    const actions = [
      ["קבלה", "/api/send-order-receipt"],
      ["וואטסאפ", "/api/notify-order"],
      ["אישור ידני", "/api/mark-order-paid-manual"],
      ["סגירה", "/api/finalize-order"],
    ];
    actions.forEach(([label, url]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      btn.addEventListener("click", async () => {
        await api(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order: order.public_id }),
        });
        await refresh();
      });
      menu.append(btn);
    });
    row.append(document.createElement("div"), info, menu);
    ordersBox.append(row);
  });

  try {
    const users = await api("/api/admin/users");
    const box = document.getElementById("user-list");
    box.replaceChildren();
    users.users.forEach((u) => {
      const p = document.createElement("p");
      p.textContent = `${u.email} · ${u.role}`;
      box.append(p);
    });
  } catch {
    document.getElementById("user-list").textContent = "הרשאות: לבעלים בלבד.";
  }

  try {
    const sec = await api("/api/admin/security");
    const box = document.getElementById("sec-list");
    box.replaceChildren();
    sec.events.forEach((e) => {
      const p = document.createElement("p");
      p.textContent = `${e.kind}: ${e.message}`;
      box.append(p);
    });
  } catch {
    /* staff */
  }
}

document.getElementById("admin-ai-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = document.getElementById("admin-ai-input").value.trim();
  const data = await api("/api/admin-ai-assistant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  document.getElementById("admin-ai-out").textContent = data.reply;
});

document.getElementById("role-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = await api("/api/assign-admin-role", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: form.email.value,
      password: form.password.value,
      role: form.role.value,
    }),
  });
  alert(data.temporary_password ? `סיסמה זמנית: ${data.temporary_password}` : "התפקיד עודכן");
  await refresh();
});

document.getElementById("sec-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/notify-admin-security", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "manual", message: event.target.message.value }),
  });
  event.target.reset();
  await refresh();
});
