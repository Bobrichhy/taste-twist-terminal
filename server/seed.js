const bcrypt = require("bcryptjs");
const { pool } = require("./db");

function slug(s) {
  return String(s).toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "item";
}

const BRANCHES = ["Aguda (Surulere)", "Kilo", "Arepo"];

const USERS = [
  { username: "master", password: "admin123", role: "master", branch: null },
  { username: "staff", password: "1234", role: "staff", branch: "Aguda (Surulere)" },
  { username: "staff_kilo", password: "1234", role: "staff", branch: "Kilo" },
  { username: "staff_arepo", password: "1234", role: "staff", branch: "Arepo" },
];

const ITEMS = [
  ["shawarma-wrap", "Shawarma Wrap", "piece", 20, null],
  ["chicken", "Chicken", "kg", 5, null],
  ["beef", "Beef", "kg", 5, null],
  ["spices", "Spices", "pack", 3, null],
  ["bread", "Bread", "loaf", 15, null],
  ["vegetables", "Vegetables", "kg", 8, null],
  ["oil", "Oil", "liter", 10, null],
  ["sausage", "Hotdog", "piece", 20, null],
  ["mayonnaise", "Mayonnaise", "bottle", 3, null],
  ["ketchup", "Ketchup", "bottle", 3, null],
  ["condensed-milk", "Condensed Milk", "tin", 5, null],
  ["salad-cream", "Salad Cream", "bottle", 3, null],
  ["hollandia-milk", "Hollandia Milk", "carton", 3, null],
  ["pepper", "Pepper", "kg", 2, null],
  ["serviette", "Serviette", "pack", 5, null],
  ["cabbage", "Cabbage", "kg", 3, null],
  ["soap", "Soap", "piece", 3, null],
  ["wrapping-paper", "Wrapping Paper", "pack", 3, null],
  ["onga", "Onga", "pack", 3, null],
  ["ginger-garlic", "Ginger & Garlic", "kg", 1, null],
  ["thyme", "Thyme", "pack", 2, null],
  ["maggi", "Maggi", "pack", 3, null],
  ["curry", "Curry", "pack", 2, null],
  ["salt", "Salt", "kg", 2, null],
  ["nylon", "Nylon", "pack", 3, null],
  ["foil-paper", "Foil Paper", "roll", 3, null],
  ["windowline", "Windowline", "bottle", 2, null],
  ["soy-sauce", "Soy Sauce", "bottle", 3, null],
  ["hair-net", "Hair Net", "pack", 2, null],
  ["hand-gloves", "Hand Gloves", "pack", 3, null],
];

const MENU_ITEMS = [
  ["chicken-plain", "Chicken Plain (No Sausage)", 3000, [{ itemId: "shawarma-wrap", qty: 1 }, { itemId: "chicken", qty: 0.15 }, { itemId: "spices", qty: 0.05 }]],
  ["chicken-regular-saus", "Chicken Regular Saus (1 Sausage)", 3600, [{ itemId: "shawarma-wrap", qty: 1 }, { itemId: "chicken", qty: 0.15 }, { itemId: "spices", qty: 0.05 }, { itemId: "sausage", qty: 1 }]],
  ["chicken-double-saus", "Chicken Double Saus (2 Sausages)", 4000, [{ itemId: "shawarma-wrap", qty: 1 }, { itemId: "chicken", qty: 0.15 }, { itemId: "spices", qty: 0.05 }, { itemId: "sausage", qty: 2 }]],
  ["extra-chicken", "Extra Chicken", 1800, [{ itemId: "chicken", qty: 0.15 }]],
];

const PAYMENT_METHODS = ["Cash", "Moniepoint", "Payforce", "Nomba", "GTB", "Others"];

async function seedIfEmpty() {
  const { rows } = await pool.query("SELECT COUNT(*)::int AS c FROM users");
  if (rows[0].c > 0) return; // already seeded

  for (const b of BRANCHES) {
    await pool.query("INSERT INTO branches (id, name) VALUES ($1,$2) ON CONFLICT DO NOTHING", [slug(b), b]);
  }
  for (const u of USERS) {
    const hash = await bcrypt.hash(u.password, 10);
    await pool.query(
      "INSERT INTO users (id, username, password_hash, role, branch) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
      [slug(u.username), u.username, hash, u.role, u.branch]
    );
  }
  for (const [id, name, unit, minStock] of ITEMS) {
    await pool.query(
      "INSERT INTO items (id, name, unit, min_stock) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
      [id, name, unit, minStock]
    );
    for (const b of BRANCHES) {
      await pool.query(
        "INSERT INTO stock (branch, item_id, qty) VALUES ($1,$2,0) ON CONFLICT DO NOTHING",
        [slug(b), id]
      );
    }
  }
  for (const [id, name, price, recipe] of MENU_ITEMS) {
    await pool.query(
      "INSERT INTO menu_items (id, name, price, recipe) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
      [id, name, price, JSON.stringify(recipe)]
    );
  }
  for (let i = 0; i < PAYMENT_METHODS.length; i++) {
    await pool.query(
      "INSERT INTO payment_methods (id, name, ord) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
      [slug(PAYMENT_METHODS[i]), PAYMENT_METHODS[i], i]
    );
  }
  console.log("Seeded initial Taste Twist data.");
}

module.exports = { seedIfEmpty };
