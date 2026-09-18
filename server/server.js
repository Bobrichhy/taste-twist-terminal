require("dotenv").config();
const express = require("express");
const cors = require("cors");
const bcrypt = require("bcryptjs");
const path = require("path");
const { pool, initSchema } = require("./db");

const app = express();
app.use(cors());
app.use(express.json());

// Some Postgres-compatible engines (and this was verified against one during testing)
// don't reliably support `= ANY($1)` array binding — an explicit IN (...) list with one
// placeholder per value works everywhere and is just as safe against injection.
function inClause(values, startAt) {
  const placeholders = values.map((_, i) => `$${startAt + i}`).join(",");
  return { sql: `(${placeholders || "NULL"})`, values };
}

function slug(s) {
  return String(s).toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "item";
}
function stockId(branch, itemId) {
  return slug(branch) + "__" + itemId;
}

// ---------------------------------------------------------------- SSE bus --
const sseClients = new Set();
function broadcastChange() {
  for (const res of sseClients) res.write("data: changed\n\n");
}
app.get("/api/events", (req, res) => {
  res.set({
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  res.flushHeaders();
  res.write("data: connected\n\n");
  sseClients.add(res);
  req.on("close", () => sseClients.delete(res));
});

// ------------------------------------------------------------------ state --
// One shot snapshot of everything the frontend needs on boot / after any change.
app.get("/api/state", async (req, res) => {
  try {
    const [branches, users, items, stock, menuItems, sales, suppliers, purchases, transfers, paymentMethods] =
      await Promise.all([
        pool.query("SELECT * FROM branches ORDER BY name"),
        pool.query("SELECT id, username, role, branch FROM users ORDER BY username"),
        pool.query("SELECT * FROM items ORDER BY name"),
        pool.query("SELECT * FROM stock"),
        pool.query("SELECT * FROM menu_items ORDER BY name"),
        pool.query("SELECT * FROM sales WHERE ts >= now() - interval '30 days' ORDER BY ts DESC LIMIT 500"),
        pool.query("SELECT * FROM suppliers ORDER BY name"),
        pool.query("SELECT * FROM purchases ORDER BY ts DESC LIMIT 200"),
        pool.query("SELECT * FROM transfers ORDER BY requested_at DESC LIMIT 100"),
        pool.query("SELECT * FROM payment_methods ORDER BY ord"),
      ]);
    res.json({
      branches: branches.rows,
      users: users.rows,
      items: items.rows.map(rowToItem),
      stock: stock.rows.map(rowToStock),
      menuItems: menuItems.rows.map(rowToMenuItem),
      sales: sales.rows.map(rowToSale),
      suppliers: suppliers.rows,
      purchases: purchases.rows.map(rowToPurchase),
      transfers: transfers.rows.map(rowToTransfer),
      paymentMethods: paymentMethods.rows,
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Could not load state" });
  }
});

// Reports needs true historical range (not just the last 30 days /api/state keeps live) —
// fetched on demand, per query, rather than held in the always-on state payload.
app.get("/api/sales-range", async (req, res) => {
  const { from, to, branch } = req.query;
  if (!from || !to) return res.status(400).json({ error: "from and to dates are required" });
  try {
    const params = [from, to + " 23:59:59"];
    let sql = "SELECT * FROM sales WHERE ts >= $1 AND ts <= $2";
    if (branch && branch !== "All") {
      params.push(branch);
      sql += ` AND branch = $${params.length}`;
    }
    sql += " ORDER BY ts DESC LIMIT 5000";
    const result = await pool.query(sql, params);
    res.json(result.rows.map(rowToSale));
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Could not load sales history" });
  }
});

function rowToItem(r) {
  return { id: r.id, name: r.name, unit: r.unit, minStock: num(r.min_stock), maxStock: num(r.max_stock), piecesPerPack: num(r.pieces_per_pack), costPrice: num(r.cost_price) };
}
function rowToStock(r) {
  return { branch: r.branch, itemId: r.item_id, qty: num(r.qty) };
}
function rowToMenuItem(r) {
  return { id: r.id, name: r.name, price: num(r.price), recipe: r.recipe || [] };
}
function rowToSale(r) {
  return {
    id: r.id, branch: r.branch, cashier: r.cashier, items: r.items, total: num(r.total),
    ts: r.ts.toISOString(), mode: r.mode, payments: r.payments || [], paidTotal: num(r.paid_total),
    change: num(r.change), voided: r.voided, voidedBy: r.voided_by, voidReason: r.void_reason,
    consumption: r.consumption || null,
  };
}
function rowToPurchase(r) {
  return { id: r.id, branch: r.branch, supplierId: r.supplier_id, supplierName: r.supplier_name, items: r.items, total: num(r.total), ts: r.ts.toISOString(), recordedBy: r.recorded_by };
}
function rowToTransfer(r) {
  return { id: r.id, srcBranch: r.src_branch, dstBranch: r.dst_branch, itemId: r.item_id, itemName: r.item_name, qty: num(r.qty), status: r.status, requestedBy: r.requested_by, requestedAt: r.requested_at.toISOString(), decidedAt: r.decided_at ? r.decided_at.toISOString() : null };
}
function num(v) { return v === null || v === undefined ? null : Number(v); }

// -------------------------------------------------------------------- auth --
app.post("/api/login", async (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: "Username and password required" });
  const r = await pool.query("SELECT * FROM users WHERE id = $1", [slug(username)]);
  const user = r.rows[0];
  if (!user) return res.status(401).json({ error: "Invalid username or password" });
  const ok = await bcrypt.compare(password, user.password_hash);
  if (!ok) return res.status(401).json({ error: "Invalid username or password" });
  res.json({ username: user.username, role: user.role, branch: user.branch });
});

// --------------------------------------------------------------- branches --
app.post("/api/branches", async (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "Name required" });
  const id = slug(name);
  const exists = await pool.query("SELECT id FROM branches WHERE id=$1", [id]);
  if (exists.rows.length) return res.status(409).json({ error: "That branch already exists" });
  await pool.query("INSERT INTO branches (id, name) VALUES ($1,$2)", [id, name]);
  broadcastChange();
  res.json({ id, name });
});
app.delete("/api/branches/:id", async (req, res) => {
  await pool.query("DELETE FROM branches WHERE id=$1", [req.params.id]);
  broadcastChange();
  res.json({ ok: true });
});

// ----------------------------------------------------------- payment methods --
app.post("/api/payment-methods", async (req, res) => {
  const { name } = req.body || {};
  if (!name) return res.status(400).json({ error: "Name required" });
  const id = slug(name);
  const countR = await pool.query("SELECT COUNT(*)::int AS c FROM payment_methods");
  const exists = await pool.query("SELECT id FROM payment_methods WHERE id=$1", [id]);
  if (exists.rows.length) return res.status(409).json({ error: "That payment method already exists" });
  await pool.query("INSERT INTO payment_methods (id, name, ord) VALUES ($1,$2,$3)", [id, name, countR.rows[0].c]);
  broadcastChange();
  res.json({ id, name });
});
app.delete("/api/payment-methods/:id", async (req, res) => {
  await pool.query("DELETE FROM payment_methods WHERE id=$1", [req.params.id]);
  broadcastChange();
  res.json({ ok: true });
});

// --------------------------------------------------------------------- users --
app.post("/api/users", async (req, res) => {
  const { username, password, role, branch } = req.body || {};
  if (!username || !password) return res.status(400).json({ error: "Username and password required" });
  const id = slug(username);
  const hash = await bcrypt.hash(password, 10);
  await pool.query(
    "INSERT INTO users (id, username, password_hash, role, branch) VALUES ($1,$2,$3,$4,$5)",
    [id, username, hash, role, role === "staff" ? branch : null]
  );
  broadcastChange();
  res.json({ id });
});
app.put("/api/users/:id", async (req, res) => {
  const { password, role, branch } = req.body || {};
  const fields = ["role = $2", "branch = $3"];
  const values = [req.params.id, role, role === "staff" ? branch : null];
  if (password) {
    const hash = await bcrypt.hash(password, 10);
    fields.push("password_hash = $" + (values.length + 1));
    values.push(hash);
  }
  await pool.query(`UPDATE users SET ${fields.join(", ")} WHERE id = $1`, values);
  broadcastChange();
  res.json({ ok: true });
});
app.delete("/api/users/:id", async (req, res) => {
  await pool.query("DELETE FROM users WHERE id=$1", [req.params.id]);
  broadcastChange();
  res.json({ ok: true });
});

// ------------------------------------------------------------------- items --
app.post("/api/items", async (req, res) => {
  const { name, unit, minStock, maxStock, piecesPerPack } = req.body || {};
  if (!name) return res.status(400).json({ error: "Name required" });
  const id = slug(name);
  await pool.query(
    "INSERT INTO items (id, name, unit, min_stock, max_stock, pieces_per_pack) VALUES ($1,$2,$3,$4,$5,$6)",
    [id, name, unit || "", minStock || 0, maxStock || null, piecesPerPack || null]
  );
  const branches = await pool.query("SELECT id FROM branches");
  await Promise.all(branches.rows.map((b) =>
    pool.query("INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,0) ON CONFLICT DO NOTHING", [b.id, id])
  ));
  broadcastChange();
  res.json({ id });
});
app.put("/api/items/:id", async (req, res) => {
  const { unit, minStock, maxStock, piecesPerPack, costPrice } = req.body || {};
  await pool.query(
    "UPDATE items SET unit=$2, min_stock=$3, max_stock=$4, pieces_per_pack=$5, cost_price=COALESCE($6, cost_price) WHERE id=$1",
    [req.params.id, unit || "", minStock || 0, maxStock || null, piecesPerPack || null, costPrice || null]
  );
  broadcastChange();
  res.json({ ok: true });
});
app.delete("/api/items/:id", async (req, res) => {
  await pool.query("DELETE FROM items WHERE id=$1", [req.params.id]);
  broadcastChange();
  res.json({ ok: true });
});

// ------------------------------------------------------------------- stock --
app.put("/api/stock/:branch/:itemId", async (req, res) => {
  const { qty } = req.body || {};
  await pool.query(
    "INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,$3) ON CONFLICT (branch,item_id) DO UPDATE SET qty=$3",
    [req.params.branch, req.params.itemId, qty]
  );
  broadcastChange();
  res.json({ ok: true });
});

// -------------------------------------------------------------- menu items --
app.post("/api/menu-items", async (req, res) => {
  const { name, price, recipe } = req.body || {};
  if (!name || !recipe || !recipe.length) return res.status(400).json({ error: "Name and at least one recipe line required" });
  const id = slug(name) + "-" + Date.now().toString(36);
  await pool.query("INSERT INTO menu_items (id, name, price, recipe) VALUES ($1,$2,$3,$4)", [id, name, price || 0, JSON.stringify(recipe)]);
  broadcastChange();
  res.json({ id });
});
app.put("/api/menu-items/:id", async (req, res) => {
  const { name, price, recipe } = req.body || {};
  await pool.query("UPDATE menu_items SET name=$2, price=$3, recipe=$4 WHERE id=$1", [req.params.id, name, price || 0, JSON.stringify(recipe)]);
  broadcastChange();
  res.json({ ok: true });
});
app.delete("/api/menu-items/:id", async (req, res) => {
  await pool.query("DELETE FROM menu_items WHERE id=$1", [req.params.id]);
  broadcastChange();
  res.json({ ok: true });
});

// ----------------------------------------------------------------- checkout --
// Server-side transaction: validates + decrements ingredient stock and records the
// sale atomically, avoiding the read-then-write race a client-side flow can't fully close.
app.post("/api/sales", async (req, res) => {
  const { branch, cashier, cartLines, mode, payments, customerNote } = req.body || {};
  if (!branch || !cartLines || !cartLines.length) return res.status(400).json({ error: "Nothing to sell" });

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const menuIds = cartLines.map((l) => l.menuItemId);
    const menuIn = inClause(menuIds, 1);
    const miRes = await client.query(`SELECT * FROM menu_items WHERE id IN ${menuIn.sql}`, menuIn.values);
    const menuById = {};
    miRes.rows.forEach((r) => (menuById[r.id] = rowToMenuItem(r)));

    // A sale is never blocked by stock, on purpose (business decision) — items are always
    // orderable, and ingredient stock is allowed to go negative to surface the real shortfall
    // as a Low Stock alert instead of stopping a cashier mid-transaction.
    const consumption = {};
    const lineDocs = [];
    for (const line of cartLines) {
      const mi = menuById[line.menuItemId];
      if (!mi) throw Object.assign(new Error(`${line.name} is not a valid menu item`), { code: "BAD_ITEM" });
      (mi.recipe || []).forEach((r) => { consumption[r.itemId] = (consumption[r.itemId] || 0) + r.qty * line.qty; });
      lineDocs.push({ itemId: line.menuItemId, name: mi.name, qty: line.qty, price: mi.price, subtotal: mi.price * line.qty });
    }

    const ingredientIds = Object.keys(consumption);
    if (ingredientIds.length) {
      const stockIn = inClause(ingredientIds, 2);
      await client.query(`SELECT * FROM stock WHERE branch=$1 AND item_id IN ${stockIn.sql} FOR UPDATE`, [branch, ...stockIn.values]);
      for (const id of ingredientIds) {
        await client.query(
          `INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,$3)
           ON CONFLICT (branch, item_id) DO UPDATE SET qty = stock.qty - $4`,
          [branch, id, -consumption[id], consumption[id]]
        );
      }
    }

    const total = lineDocs.reduce((a, l) => a + l.subtotal, 0);
    const paidTotal = mode === "pay" ? (payments || []).reduce((a, p) => a + p.amount, 0) : null;
    const saleR = await client.query(
      `INSERT INTO sales (branch, cashier, items, total, mode, payments, paid_total, change, consumption)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
      [branch, cashier, JSON.stringify(lineDocs), total, mode,
        JSON.stringify(mode === "pay" ? payments : []),
        paidTotal, mode === "pay" ? paidTotal - total : null,
        JSON.stringify(consumption)]
    );
    await client.query("COMMIT");
    broadcastChange();
    res.json(rowToSale(saleR.rows[0]));
  } catch (err) {
    await client.query("ROLLBACK");
    console.error(err);
    res.status(err.code === "BAD_ITEM" ? 409 : 500).json({ error: err.message || "Could not complete the sale" });
  } finally {
    client.release();
  }
});

app.post("/api/sales/:id/void", async (req, res) => {
  const { reason, voidedBy } = req.body || {};
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const saleR = await client.query("SELECT * FROM sales WHERE id=$1 FOR UPDATE", [req.params.id]);
    const sale = saleR.rows[0];
    if (!sale) throw new Error("Sale not found");
    if (sale.voided) throw new Error("Already voided");
    const consumption = sale.consumption || {};
    for (const itemId of Object.keys(consumption)) {
      await client.query(
        "UPDATE stock SET qty = qty + $3 WHERE branch=$1 AND item_id=$2",
        [sale.branch, itemId, consumption[itemId]]
      );
    }
    await client.query(
      "UPDATE sales SET voided=true, voided_by=$2, voided_at=now(), void_reason=$3 WHERE id=$1",
      [req.params.id, voidedBy, reason || ""]
    );
    await client.query("COMMIT");
    broadcastChange();
    res.json({ ok: true });
  } catch (err) {
    await client.query("ROLLBACK");
    res.status(400).json({ error: err.message });
  } finally {
    client.release();
  }
});

// ---------------------------------------------------------------- suppliers --
app.post("/api/suppliers", async (req, res) => {
  const { name } = req.body || {};
  const id = slug(name);
  await pool.query("INSERT INTO suppliers (id, name) VALUES ($1,$2) ON CONFLICT DO NOTHING", [id, name]);
  broadcastChange();
  res.json({ id });
});

// ---------------------------------------------------------------- purchases --
app.post("/api/purchases", async (req, res) => {
  const { branch, supplierName, lines, recordedBy } = req.body || {};
  if (!branch || !lines || !lines.length) return res.status(400).json({ error: "Nothing to record" });
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const supplierId = slug(supplierName || "walk-in-supplier");
    await client.query("INSERT INTO suppliers (id, name) VALUES ($1,$2) ON CONFLICT DO NOTHING", [supplierId, supplierName || "Walk-in supplier"]);
    for (const l of lines) {
      await client.query(
        "INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,$3) ON CONFLICT (branch,item_id) DO UPDATE SET qty = stock.qty + $3",
        [branch, l.itemId, l.qty]
      );
      await client.query("UPDATE items SET cost_price=$2 WHERE id=$1", [l.itemId, l.cost]);
    }
    const total = lines.reduce((a, l) => a + l.cost * l.qty, 0);
    const poR = await client.query(
      "INSERT INTO purchases (branch, supplier_id, supplier_name, items, total, recorded_by) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
      [branch, supplierId, supplierName || "Walk-in supplier", JSON.stringify(lines), total, recordedBy]
    );
    await client.query("COMMIT");
    broadcastChange();
    res.json(rowToPurchase(poR.rows[0]));
  } catch (err) {
    await client.query("ROLLBACK");
    console.error(err);
    res.status(500).json({ error: "Could not record purchase" });
  } finally {
    client.release();
  }
});

// ---------------------------------------------------------------- transfers --
app.post("/api/transfers", async (req, res) => {
  const { srcBranch, dstBranch, itemId, itemName, qty, requestedBy } = req.body || {};
  await pool.query(
    "INSERT INTO transfers (src_branch, dst_branch, item_id, item_name, qty, requested_by) VALUES ($1,$2,$3,$4,$5,$6)",
    [srcBranch, dstBranch, itemId, itemName, qty, requestedBy]
  );
  broadcastChange();
  res.json({ ok: true });
});
app.post("/api/transfers/:id/decide", async (req, res) => {
  const { approve } = req.body || {};
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const tR = await client.query("SELECT * FROM transfers WHERE id=$1 FOR UPDATE", [req.params.id]);
    const t = tR.rows[0];
    if (!t || t.status !== "pending") throw new Error("Transfer already processed");
    if (!approve) {
      await client.query("UPDATE transfers SET status='rejected', decided_at=now() WHERE id=$1", [req.params.id]);
    } else {
      const srcR = await client.query("SELECT qty FROM stock WHERE branch=$1 AND item_id=$2 FOR UPDATE", [t.src_branch, t.item_id]);
      const srcQty = srcR.rows[0] ? Number(srcR.rows[0].qty) : 0;
      if (srcQty < Number(t.qty)) throw new Error(`${t.src_branch} only has ${srcQty} ${t.item_name} — cannot approve`);
      await client.query("UPDATE stock SET qty = qty - $3 WHERE branch=$1 AND item_id=$2", [t.src_branch, t.item_id, t.qty]);
      await client.query(
        "INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,$3) ON CONFLICT (branch,item_id) DO UPDATE SET qty = stock.qty + $3",
        [t.dst_branch, t.item_id, t.qty]
      );
      await client.query("UPDATE transfers SET status='approved', decided_at=now() WHERE id=$1", [req.params.id]);
    }
    await client.query("COMMIT");
    broadcastChange();
    res.json({ ok: true });
  } catch (err) {
    await client.query("ROLLBACK");
    res.status(400).json({ error: err.message });
  } finally {
    client.release();
  }
});

// ------------------------------------------------------------ stock ledger --
app.get("/api/stock-ledger/:branch/:date", async (req, res) => {
  const id = slug(req.params.branch) + "__" + req.params.date;
  const r = await pool.query("SELECT * FROM stock_ledger WHERE id=$1", [id]);
  res.json(r.rows[0] ? { branch: r.rows[0].branch, date: req.params.date, rows: r.rows[0].rows } : null);
});
app.put("/api/stock-ledger/:branch/:date", async (req, res) => {
  const { rows, recordedBy } = req.body || {};
  const branch = req.params.branch, date = req.params.date;
  const id = slug(branch) + "__" + date;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO stock_ledger (id, branch, date, rows, recorded_by, updated_at) VALUES ($1,$2,$3,$4,$5,now())
       ON CONFLICT (id) DO UPDATE SET rows=$4, recorded_by=$5, updated_at=now()`,
      [id, branch, date, JSON.stringify(rows), recordedBy]
    );
    for (const itemId of Object.keys(rows)) {
      await client.query(
        "INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,$3) ON CONFLICT (branch,item_id) DO UPDATE SET qty=$3",
        [branch, itemId, rows[itemId].closing]
      );
    }
    await client.query("COMMIT");
    broadcastChange();
    res.json({ ok: true });
  } catch (err) {
    await client.query("ROLLBACK");
    console.error(err);
    res.status(500).json({ error: "Could not save the ledger" });
  } finally {
    client.release();
  }
});

// ---------------------------------------------------------------- static UI --
app.use(express.static(path.join(__dirname, "..", "public")));
app.get(/.*/, (req, res) => {
  res.sendFile(path.join(__dirname, "..", "public", "index.html"));
});

const PORT = process.env.PORT || 3000;
initSchema()
  .then(() => require("./seed").seedIfEmpty())
  .then(() => {
    app.listen(PORT, () => console.log(`Taste Twist server listening on :${PORT}`));
  })
  .catch((err) => {
    console.error("Failed to start:", err);
    process.exit(1);
  });
