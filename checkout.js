const cart = JSON.parse(localStorage.getItem("amos-cart") || "[]");
const box = document.getElementById("cart-box");
const note = document.getElementById("checkout-note");
const payHint = document.getElementById("pay-hint");
const submitBtn = document.querySelector("#checkout-form button[type=submit]");

function draw() {
  box.replaceChildren();
  if (!cart.length) {
    box.textContent = "העגלה ריקה.";
    return;
  }
  cart.forEach((item) => {
    const p = document.createElement("p");
    p.textContent = `${item.title} × ${item.qty} — ${item.price_label || "₪" + item.price}`;
    box.append(p);
  });
  const subtotal = cart.reduce((sum, item) => sum + Number(item.price || 0) * (item.qty || 1), 0);
  const ship = document.createElement("p");
  ship.className = "ship-line";
  ship.textContent = "משלוח עד הבית — עלינו · ₪0";
  box.append(ship);
  const total = document.createElement("p");
  total.className = "cart-total";
  total.textContent = `לתשלום בכרטיס אשראי: ₪${subtotal.toLocaleString("he-IL")}`;
  box.append(total);
}

fetch("/api/checkout-info")
  .then((r) => r.json())
  .then((info) => {
    if (!payHint) return;
    payHint.textContent = info.pay_ready
      ? "אחרי השליחה תועברו לדף סליקה מאובטח לתשלום בכרטיס אשראי. המשלוח עד הבית על חשבוננו."
      : "הכתובת נשמרת למשלוח עד הבית (עלינו). לסליקה באשראי חסר עדיין מספר מסוף (Masof) אצל יעד.";
    if (submitBtn && info.pay_ready) submitBtn.textContent = "לתשלום בכרטיס אשראי";
  })
  .catch(() => {});

document.getElementById("checkout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!cart.length) return;
  const form = event.target;
  note.hidden = true;
  try {
    const order = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.name.value,
        phone: form.phone.value,
        email: form.email.value,
        address: form.address.value,
        city: form.city.value,
        zip: form.zip.value,
        notes: form.notes.value,
        items: cart.map((item) => ({ product_id: item.id, qty: item.qty || 1 })),
      }),
    }).then((r) => r.json().then((d) => (r.ok ? d : Promise.reject(d))));
    const pay = await fetch("/api/yaad-create-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order: order.public_id }),
    }).then((r) => r.json().then((d) => (r.ok ? d : Promise.reject(d))));
    localStorage.removeItem("amos-cart");
    location.href = pay.pay_url;
  } catch (err) {
    note.hidden = false;
    note.textContent = err.detail || "לא ניתן לפתוח סליקה כרגע.";
  }
});

draw();
