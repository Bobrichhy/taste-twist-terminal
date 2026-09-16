#!/usr/bin/env python3
"""
taste_twist_stock_manager.py - COMPLETE FINAL VERSION
"""

import sys
import datetime
import sqlite3
from pathlib import Path

import ttkbootstrap as tb
from ttkbootstrap.constants import LEFT, RIGHT, BOTH, X
from tkinter import messagebox, filedialog

import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import pandas as pd

THEME_NAME = "united-dark"

# --------------------------------------------------------------------------- #
# DATABASE
# --------------------------------------------------------------------------- #

DB_PATH = Path(__file__).parent / "inventory.db"

BRANCHES = ["Aguda (Surulere)", "Kilo", "Arepo"]
STAFF_USERNAMES = {
    "Aguda (Surulere)": "staff",
    "Kilo": "staff_kilo",
    "Arepo": "staff_arepo",
}


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as con:
        cur = con.cursor()

        # Users
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT CHECK(role IN ('master', 'staff')) NOT NULL,
                branch TEXT
            )
        """)
        cur.execute("INSERT OR IGNORE INTO users VALUES (NULL, 'master', 'admin123', 'master', NULL)")
        for branch, uname in STAFF_USERNAMES.items():
            cur.execute("INSERT OR IGNORE INTO users VALUES (NULL, ?, '1234', 'staff', ?)", (uname, branch))

        # Branches
        cur.execute("""
            CREATE TABLE IF NOT EXISTS branches (name TEXT PRIMARY KEY, display_name TEXT)
        """)
        for b in BRANCHES:
            cur.execute("INSERT OR IGNORE INTO branches VALUES (?, ?)", (b, b))

        # Items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                primary_unit TEXT NOT NULL,
                pieces_per_pack INTEGER DEFAULT 0,
                min_stock REAL NOT NULL DEFAULT 10.0
            )
        """)
        cur.execute("SELECT COUNT(*) FROM items")
        if cur.fetchone()[0] == 0:
            defaults = [
                ("Shawarma Wrap", "piece", 0, 20), ("Chicken", "kg", 0, 5),
                ("Beef", "kg", 0, 5), ("Spices", "pack", 10, 3),
                ("Bread", "loaf", 0, 15), ("Vegetables", "kg", 0, 8),
                ("Oil", "liter", 0, 10)
            ]
            cur.executemany("INSERT INTO items (name, primary_unit, pieces_per_pack, min_stock) VALUES (?,?,?,?)", defaults)

        # Stock
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                entry_date TEXT NOT NULL,
                opening_qty REAL DEFAULT 0,
                stock_in REAL DEFAULT 0,
                used REAL DEFAULT 0,
                closing_qty REAL DEFAULT 0,
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        """)
        # Drop pre-existing duplicate rows (same branch/item/date) before enforcing uniqueness,
        # keeping the most recently written one.
        cur.execute("""
            DELETE FROM stock WHERE id NOT IN (
                SELECT MAX(id) FROM stock GROUP BY branch, item_id, entry_date
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_branch_item_date
            ON stock(branch, item_id, entry_date)
        """)

        # Sales
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                sale_date TEXT NOT NULL,
                qty_sold REAL NOT NULL,
                price_per_unit REAL NOT NULL,
                revenue REAL NOT NULL
            )
        """)
        cur.execute("""
            DELETE FROM sales WHERE id NOT IN (
                SELECT MAX(id) FROM sales GROUP BY branch, item_id, sale_date
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_branch_item_date
            ON sales(branch, item_id, sale_date)
        """)

        # Transfers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_branch TEXT NOT NULL,
                dst_branch TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                qty REAL NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                requestor_id INTEGER NOT NULL,
                request_date TEXT DEFAULT (date('now')),
                FOREIGN KEY(item_id) REFERENCES items(id),
                FOREIGN KEY(requestor_id) REFERENCES users(id)
            )
        """)

        con.commit()


# --------------------------------------------------------------------------- #
# SESSION
# --------------------------------------------------------------------------- #

class Session:
    def __init__(self, user_id, username, role, branch=None):
        self.user_id = user_id
        self.username = username
        self.role = role
        self.branch = branch


def authenticate(username, password):
    with get_conn() as con:
        cur = con.cursor()
        cur.execute("SELECT id, username, role, branch FROM users WHERE username=? AND password=?", (username, password))
        row = cur.fetchone()
        if row:
            return Session(*row)
    return None


# --------------------------------------------------------------------------- #
# MAIN APP
# --------------------------------------------------------------------------- #

class TasteTwistApp:
    def __init__(self, root):
        self.root = root
        self.style = root.style
        self.colors = self.style.colors
        self.logged_user = None

        init_db()
        self.notebook = tb.Notebook(root, bootstyle="primary")
   
        self.build_login_screen()

    def build_login_screen(self):
        f = tb.Frame(self.notebook)
        self.notebook.add(f, text="Login")

        tb.Label(f, text="Taste Twist Stock Manager", font=("Helvetica", 26, "bold"),
                 bootstyle="primary").pack(pady=(50, 5))
        tb.Label(f, text="Stock, sales & branch transfer management",
                 font=("Helvetica", 12)).pack(pady=(0, 30))

        hint_box = tb.Labelframe(f, text="Demo Credentials", bootstyle="secondary", padding=20)
        hint_box.pack(pady=10)
        hint = (
            "Master Login:\nusername: master    password: admin123\n\n"
            "Staff Login (password: 1234):\n"
            + "\n".join(f"{branch}: {uname}" for branch, uname in STAFF_USERNAMES.items())
        )
        tb.Label(hint_box, text=hint, font=("Courier", 11), justify="left").pack()

        form = tb.Frame(f)
        form.pack(pady=25)

        tb.Label(form, text="Username", font=("Helvetica", 10, "bold")).pack()
        self.un = tb.Entry(form, width=35, font=("Arial", 11))
        self.un.pack(pady=(2, 14))
        tb.Label(form, text="Password", font=("Helvetica", 10, "bold")).pack()
        self.pw = tb.Entry(form, show="*", width=35, font=("Arial", 11))
        self.pw.pack(pady=(2, 14))

        self.un.bind("<Return>", lambda e: self.attempt_login())
        self.pw.bind("<Return>", lambda e: self.attempt_login())
        self.un.focus_set()

        tb.Button(form, text="LOGIN", command=self.attempt_login, bootstyle="success",
                  width=22, padding=12).pack(pady=15)

    def attempt_login(self):
        sess = authenticate(self.un.get().strip(), self.pw.get())
        if sess:
            self.logged_user = sess
            for w in self.notebook.winfo_children():
                w.destroy()
            if sess.role == "master":
                self.build_master_screens()
            else:
                self.build_staff_screens()
        else:
            messagebox.showerror("Failed", "Invalid username or password")

    # ====================== STAFF ======================
    def build_staff_screens(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text=f"Staff - {self.logged_user.branch}")
        tb.Label(tab, text=f"Welcome {self.logged_user.username}!",
                 font=("Helvetica", 20, "bold")).pack(pady=40)

        tb.Button(tab, text="Daily Stock & Sales Entry", command=self._add_daily_entry_tab,
                  width=35, padding=12, bootstyle="info").pack(pady=10)
        tb.Button(tab, text="Request Stock Transfer", command=self._add_transfer_tab,
                  width=35, padding=12, bootstyle="warning").pack(pady=10)
        tb.Button(tab, text="Logout", command=self.logout,
                  width=20, padding=10, bootstyle="danger").pack(pady=30)

    # ====================== MASTER ======================
    def build_master_screens(self):
        self._build_dashboard()
        self._add_items_manager_tab()
        self._add_daily_entry_tab()
        self._add_transfer_tab()
        self._add_reports_tab()
        self._add_settings_tab()

    # ====================== DASHBOARD WITH CHARTS ======================
    def _build_dashboard(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Dashboard")

        tb.Label(tab, text="Master Dashboard", font=("Helvetica", 22, "bold")).pack(pady=15)

        top = tb.Frame(tab)
        top.pack(fill=X, padx=20, pady=5)
        self.bell_label = tb.Label(top, text="Checking stock levels...", font=("Helvetica", 15, "bold"),
                                    bootstyle="secondary-inverse", padding=(20, 12))
        self.bell_label.pack(side=LEFT)

        chart_frame = tb.Frame(tab)
        chart_frame.pack(fill=BOTH, expand=True, padx=20, pady=10)

        # Sales Trend
        sales_f = tb.Labelframe(chart_frame, text="Sales Revenue Trend (Last 7 Days)", padding=5)
        sales_f.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        self.fig_sales = Figure(figsize=(7, 4.5), dpi=100)
        self.ax_sales = self.fig_sales.add_subplot(111)
        self.canvas_sales = FigureCanvasTkAgg(self.fig_sales, sales_f)
        self.canvas_sales.get_tk_widget().pack(fill=BOTH, expand=True)

        # Stock Levels
        stock_f = tb.Labelframe(chart_frame, text="Current Stock Levels (Today)", padding=5)
        stock_f.pack(side=RIGHT, fill=BOTH, expand=True, padx=(10, 0))
        self.fig_stock = Figure(figsize=(7, 4.5), dpi=100)
        self.ax_stock = self.fig_stock.add_subplot(111)
        self.canvas_stock = FigureCanvasTkAgg(self.fig_stock, stock_f)
        self.canvas_stock.get_tk_widget().pack(fill=BOTH, expand=True)

        tb.Button(tab, text="Refresh Charts", command=self.refresh_dashboard,
                  bootstyle="secondary", padding=8).pack(pady=10)
        self.refresh_dashboard()

    def _style_axes(self, ax, fig):
        c = self.colors
        fig.set_facecolor(c.bg)
        ax.set_facecolor(c.bg)
        ax.tick_params(colors=c.fg)
        ax.xaxis.label.set_color(c.fg)
        ax.yaxis.label.set_color(c.fg)
        ax.title.set_color(c.fg)
        for spine in ax.spines.values():
            spine.set_color(c.border)

    def refresh_dashboard(self):
        # Low-stock alert badge (today's entries only)
        with get_conn() as con:
            low = con.execute("""
                SELECT COUNT(*) FROM stock s JOIN items i ON s.item_id=i.id
                WHERE s.closing_qty < i.min_stock AND s.entry_date = date('now')
            """).fetchone()[0] or 0
        if low:
            self.bell_label.config(text=f"🔔  {low} item(s) low on stock today", bootstyle="danger-inverse")
        else:
            self.bell_label.config(text="✅  All stock levels OK today", bootstyle="success-inverse")

        # Sales Chart
        self.ax_sales.clear()
        self._style_axes(self.ax_sales, self.fig_sales)
        with get_conn() as con:
            df = pd.read_sql("SELECT sale_date, SUM(revenue) as revenue FROM sales WHERE sale_date >= date('now','-7 days') GROUP BY sale_date ORDER BY sale_date", con)
        if not df.empty:
            self.ax_sales.plot(df['sale_date'], df['revenue'], marker='o', color=self.colors.success, linewidth=2.5)
            self.ax_sales.set_title("Daily Revenue")
            self.ax_sales.set_ylabel("₦")
            self.ax_sales.grid(True, alpha=0.2, color=self.colors.fg)
            self.fig_sales.autofmt_xdate(rotation=30)
        else:
            self.ax_sales.text(0.5, 0.5, "No sales data yet", ha='center', va='center',
                                transform=self.ax_sales.transAxes, fontsize=12, color=self.colors.fg)

        # Stock Chart
        self.ax_stock.clear()
        self._style_axes(self.ax_stock, self.fig_stock)
        with get_conn() as con:
            df = pd.read_sql("""
                SELECT i.name, MAX(s.closing_qty) as qty
                FROM stock s JOIN items i ON s.item_id=i.id
                WHERE s.entry_date = date('now')
                GROUP BY i.name ORDER BY qty DESC LIMIT 8
            """, con)
        if not df.empty:
            self.ax_stock.barh(df['name'], df['qty'], color=self.colors.primary)
            self.ax_stock.set_xlabel("Closing Quantity")
            self.ax_stock.set_title("Stock Levels Today")
        else:
            self.ax_stock.text(0.5, 0.5, "No stock entered for today yet", ha='center', va='center',
                                transform=self.ax_stock.transAxes, fontsize=12, color=self.colors.fg)

        self.canvas_sales.draw()
        self.canvas_stock.draw()

        self.root.after(300000, self.refresh_dashboard)

    # ====================== ITEMS MANAGER ======================
    def _add_items_manager_tab(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Items Manager")

        tb.Label(tab, text="Items Management", font=("Helvetica", 18, "bold")).pack(pady=10)
        tb.Label(tab, text="Unit is free text (e.g. kg, piece, loaf) — keep it consistent across items",
                 font=("Arial", 9, "italic")).pack(anchor="w", padx=15)

        toolbar = tb.Frame(tab)
        toolbar.pack(fill=X, padx=15, pady=8)
        tb.Button(toolbar, text="Add New Item", command=self.add_new_item, bootstyle="success", padding=8).pack(side=LEFT, padx=5)
        tb.Button(toolbar, text="Edit Selected", command=self.edit_selected_item, bootstyle="warning", padding=8).pack(side=LEFT, padx=5)
        tb.Button(toolbar, text="Delete Selected", command=self.delete_selected_item, bootstyle="danger", padding=8).pack(side=LEFT, padx=5)
        tb.Button(toolbar, text="Refresh", command=self.load_items, bootstyle="secondary", padding=8).pack(side=LEFT, padx=5)

        cols = ("id", "name", "unit", "pack", "min")
        self.items_tree = tb.Treeview(tab, columns=cols, show="headings", height=18, bootstyle="primary")
        for txt, c, w in zip(["ID", "Item Name", "Unit", "Pieces/Pack", "Min Stock"], cols, [60, 300, 100, 120, 100]):
            self.items_tree.heading(c, text=txt)
            self.items_tree.column(c, width=w)
        self.items_tree.pack(fill=BOTH, expand=True, padx=15, pady=10)

        self.load_items()

    def load_items(self):
        for i in self.items_tree.get_children():
            self.items_tree.delete(i)
        with get_conn() as con:
            for row in con.execute("SELECT id, name, primary_unit, pieces_per_pack, min_stock FROM items ORDER BY name"):
                self.items_tree.insert("", "end", values=row)

    def add_new_item(self):
        self.show_item_form()

    def edit_selected_item(self):
        sel = self.items_tree.selection()
        if not sel:
            return messagebox.showwarning("Warning", "Select an item")
        item_id = self.items_tree.item(sel[0], "values")[0]
        self.show_item_form(int(item_id))

    def delete_selected_item(self):
        sel = self.items_tree.selection()
        if not sel:
            return
        values = self.items_tree.item(sel[0], "values")
        if messagebox.askyesno("Delete", f"Delete {values[1]}?"):
            with get_conn() as con:
                con.execute("DELETE FROM items WHERE id=?", (values[0],))
                con.commit()
            self.load_items()

    def show_item_form(self, item_id=None):
        win = tb.Toplevel(title="Add Item" if not item_id else "Edit Item", size=(460, 420), resizable=(False, False))
        win.grab_set()

        tb.Label(win, text="Item Name:", font=("Helvetica", 10, "bold")).pack(pady=(20, 5), anchor="w", padx=40)
        name_e = tb.Entry(win, width=40, font=("Arial", 11))
        name_e.pack(pady=5, padx=40)

        tb.Label(win, text="Unit:", font=("Helvetica", 10, "bold")).pack(pady=(15, 5), anchor="w", padx=40)
        unit_e = tb.Entry(win, width=40, font=("Arial", 11))
        unit_e.pack(pady=5, padx=40)

        tb.Label(win, text="Pieces per Pack:", font=("Helvetica", 10, "bold")).pack(pady=(15, 5), anchor="w", padx=40)
        pack_e = tb.Entry(win, width=40, font=("Arial", 11))
        pack_e.pack(pady=5, padx=40)

        tb.Label(win, text="Minimum Stock:", font=("Helvetica", 10, "bold")).pack(pady=(15, 5), anchor="w", padx=40)
        min_e = tb.Entry(win, width=40, font=("Arial", 11))
        min_e.pack(pady=5, padx=40)

        if item_id:
            with get_conn() as con:
                data = con.execute("SELECT name, primary_unit, pieces_per_pack, min_stock FROM items WHERE id=?", (item_id,)).fetchone()
                if data:
                    name_e.insert(0, data[0])
                    unit_e.insert(0, data[1])
                    pack_e.insert(0, data[2])
                    min_e.insert(0, data[3])

        def save():
            try:
                with get_conn() as con:
                    if item_id:
                        con.execute("UPDATE items SET name=?, primary_unit=?, pieces_per_pack=?, min_stock=? WHERE id=?",
                                    (name_e.get().strip(), unit_e.get().strip(), int(pack_e.get() or 0), float(min_e.get() or 10), item_id))
                    else:
                        con.execute("INSERT INTO items (name, primary_unit, pieces_per_pack, min_stock) VALUES (?,?,?,?)",
                                    (name_e.get().strip(), unit_e.get().strip(), int(pack_e.get() or 0), float(min_e.get() or 10)))
                win.destroy()
                self.load_items()
                messagebox.showinfo("Success", "Item saved")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        tb.Button(win, text="Save", command=save, bootstyle="success", width=15, padding=10).pack(pady=25)

    # ====================== DAILY ENTRY ======================
    def _add_daily_entry_tab(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Daily Stock & Sales")

        tb.Label(tab, text="Daily Stock & Sales Entry", font=("Helvetica", 16, "bold")).pack(pady=10)

        top = tb.Frame(tab)
        top.pack(fill=X, padx=15, pady=8)

        tb.Label(top, text="Date:", font=("Helvetica", 10, "bold")).pack(side=LEFT)
        self.date_e = tb.Entry(top, width=15)
        self.date_e.insert(0, datetime.date.today().isoformat())
        self.date_e.pack(side=LEFT, padx=10)

        tb.Label(top, text="Branch:", font=("Helvetica", 10, "bold")).pack(side=LEFT, padx=(20, 5))
        self.branch_cb = tb.Combobox(top, values=BRANCHES, state="readonly")
        self.branch_cb.set(self.logged_user.branch or BRANCHES[0])
        if self.logged_user.role == "staff":
            self.branch_cb.config(state="disabled")
        self.branch_cb.pack(side=LEFT)

        tb.Label(tab, text="Columns marked with ✎ are editable — double-click a cell to edit it",
                 font=("Arial", 9, "italic")).pack(anchor="w", padx=15)

        # Treeview
        cols = ("id", "name", "unit", "open", "in", "used", "close", "price", "rev")
        self.daily_tree = tb.Treeview(tab, columns=cols, show="headings", height=16, bootstyle="primary")
        headings = ["ID", "Item", "Unit", "Opening ✎", "Stock In ✎", "Used ✎", "Closing", "Price ✎", "Revenue"]
        widths = [50, 200, 70, 90, 90, 90, 90, 90, 100]
        for c, h, w in zip(cols, headings, widths):
            self.daily_tree.heading(c, text=h)
            self.daily_tree.column(c, width=w)
        self.daily_tree.pack(fill=BOTH, expand=True, padx=15, pady=10)

        self.daily_tree.bind("<Double-1>", self.edit_daily_cell)

        self.daily_status = tb.Label(tab, text="", font=("Arial", 10, "bold"))
        self.daily_status.pack(pady=(0, 5))

        btns = tb.Frame(tab)
        btns.pack(pady=8)
        tb.Button(btns, text="Load Items", command=self.load_daily_items, bootstyle="info", padding=10).pack(side=LEFT, padx=5)
        tb.Button(btns, text="Save Entry", command=self.save_daily_entry, bootstyle="success", padding=10).pack(side=LEFT, padx=5)

        self.load_daily_items()

    def load_daily_items(self):
        for i in self.daily_tree.get_children():
            self.daily_tree.delete(i)
        branch = self.branch_cb.get()
        date = self.date_e.get()
        with get_conn() as con:
            cur = con.cursor()
            for item in cur.execute("SELECT id, name, primary_unit FROM items"):
                rec = con.execute("SELECT opening_qty, stock_in, used, closing_qty FROM stock WHERE branch=? AND item_id=? AND entry_date=?",
                                  (branch, item[0], date)).fetchone() or (0,0,0,0)
                self.daily_tree.insert("", "end", values=(item[0], item[1], item[2], *rec, 0, 0))

    def edit_daily_cell(self, event):
        item = self.daily_tree.selection()[0]
        col = int(self.daily_tree.identify_column(event.x)[1:]) - 1
        if col not in [3,4,5,7]: return   # editable columns: opening, in, used, price

        bbox = self.daily_tree.bbox(item, column=col+1)
        entry = tb.Entry(self.daily_tree)
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, self.daily_tree.item(item, "values")[col])
        entry.focus()
        entry.select_range(0, "end")

        def save_edit(e=None):
            try:
                val = float(entry.get())
                vals = list(self.daily_tree.item(item, "values"))
                vals[col] = val
                if col in [3,4,5]:
                    vals[6] = round(float(vals[3]) + float(vals[4]) - float(vals[5]), 2)
                if col == 7:
                    vals[8] = round(float(vals[5]) * val, 2)
                self.daily_tree.item(item, values=vals)
                self.daily_status.config(text="", bootstyle="default")
            except ValueError:
                self.daily_status.config(text=f"'{entry.get()}' is not a number — edit discarded", bootstyle="danger")
            entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)

    def save_daily_entry(self):
        branch = self.branch_cb.get()
        date = self.date_e.get()
        with get_conn() as con:
            cur = con.cursor()
            for child in self.daily_tree.get_children():
                v = self.daily_tree.item(child, "values")
                item_id = int(v[0])
                opening = float(v[3])
                stock_in = float(v[4])
                used = float(v[5])
                closing = float(v[6])
                price = float(v[7])
                revenue = float(v[8])

                if closing < 0:
                    return messagebox.showerror("Error", f"Negative closing for {v[1]}")

                cur.execute("""INSERT INTO stock
                    (branch, item_id, entry_date, opening_qty, stock_in, used, closing_qty)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(branch, item_id, entry_date) DO UPDATE SET
                        opening_qty=excluded.opening_qty, stock_in=excluded.stock_in,
                        used=excluded.used, closing_qty=excluded.closing_qty""",
                    (branch, item_id, date, opening, stock_in, used, closing))

                cur.execute("DELETE FROM sales WHERE branch=? AND item_id=? AND sale_date=?",
                            (branch, item_id, date))
                if used > 0 and price > 0:
                    cur.execute("""INSERT INTO sales
                        (branch, item_id, sale_date, qty_sold, price_per_unit, revenue)
                        VALUES (?,?,?,?,?,?)""",
                        (branch, item_id, date, used, price, revenue))
            con.commit()
        messagebox.showinfo("Success", "Daily entry saved!")
        self.load_daily_items()

    # ====================== TRANSFERS ======================
    def _add_transfer_tab(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Stock Transfers")

        tb.Label(tab, text="Stock Transfer Management", font=("Helvetica", 18, "bold")).pack(pady=10)

        # Request form
        lf = tb.Labelframe(tab, text="Request Transfer", bootstyle="primary", padding=15)
        lf.pack(fill=X, padx=15, pady=10)

        f = tb.Frame(lf)
        f.pack(pady=10)

        tb.Label(f, text="From:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, padx=5, sticky="w")
        self.src_cb = tb.Combobox(f, values=BRANCHES, state="readonly", width=25)
        self.src_cb.grid(row=0, column=1, padx=5)
        self.src_cb.set(self.logged_user.branch or BRANCHES[0])
        self.src_cb.bind("<<ComboboxSelected>>", lambda e: self._sync_dst_options())

        tb.Label(f, text="To:", font=("Helvetica", 10, "bold")).grid(row=1, column=0, padx=5, sticky="w", pady=6)
        self.dst_cb = tb.Combobox(f, state="readonly", width=25)
        self.dst_cb.grid(row=1, column=1, padx=5, pady=6)
        self._sync_dst_options()

        tb.Label(f, text="Item:", font=("Helvetica", 10, "bold")).grid(row=2, column=0, padx=5, sticky="w", pady=6)
        self.item_cb = tb.Combobox(f, state="readonly", width=40)
        self.item_cb.grid(row=2, column=1, padx=5, pady=6)
        self.load_item_combo()

        tb.Label(f, text="Qty:", font=("Helvetica", 10, "bold")).grid(row=3, column=0, padx=5, sticky="w", pady=6)
        self.transfer_qty = tb.Entry(f, width=15)
        self.transfer_qty.grid(row=3, column=1, padx=5, pady=6, sticky="w")

        tb.Button(f, text="Submit Request", command=self.submit_transfer, bootstyle="warning", padding=10).grid(row=4, column=1, pady=12, sticky="w")

        # List
        tb.Label(tab, text="Transfer History", font=("Helvetica", 13, "bold")).pack(anchor="w", padx=15, pady=(10,5))

        cols = ("id", "date", "src", "dst", "item", "qty", "status")
        self.trans_tree = tb.Treeview(tab, columns=cols, show="headings", height=14, bootstyle="primary")
        for h, c, w in zip(["ID","Date","From","To","Item","Qty","Status"], cols, [50,100,140,140,220,80,100]):
            self.trans_tree.heading(c, text=h)
            self.trans_tree.column(c, width=w)
        self.trans_tree.pack(fill=BOTH, expand=True, padx=15, pady=5)

        bf = tb.Frame(tab)
        bf.pack(pady=8)
        tb.Button(bf, text="Refresh", command=self.load_transfers, bootstyle="secondary", padding=8).pack(side=LEFT, padx=5)
        if self.logged_user.role == "master":
            tb.Button(bf, text="Approve", command=self.approve_transfer, bootstyle="success", padding=8).pack(side=LEFT, padx=5)
            tb.Button(bf, text="Reject", command=self.reject_transfer, bootstyle="danger", padding=8).pack(side=LEFT, padx=5)

        self.load_transfers()

    def _sync_dst_options(self):
        remaining = [b for b in BRANCHES if b != self.src_cb.get()]
        self.dst_cb['values'] = remaining
        if self.dst_cb.get() not in remaining and remaining:
            self.dst_cb.set(remaining[0])

    def load_item_combo(self):
        with get_conn() as con:
            items = [r[0] for r in con.execute("SELECT name FROM items ORDER BY name")]
        self.item_cb['values'] = items
        if items: self.item_cb.set(items[0])

    def submit_transfer(self):
        src = self.src_cb.get()
        dst = self.dst_cb.get()
        item_name = self.item_cb.get()
        try:
            qty = float(self.transfer_qty.get())
        except:
            return messagebox.showerror("Error", "Invalid quantity")

        if src == dst:
            return messagebox.showerror("Error", "Cannot transfer to same branch")

        with get_conn() as con:
            item_id = con.execute("SELECT id FROM items WHERE name=?", (item_name,)).fetchone()[0]
            con.execute("INSERT INTO transfers (src_branch, dst_branch, item_id, qty, requestor_id) VALUES (?,?,?,?,?)",
                        (src, dst, item_id, qty, self.logged_user.user_id))
            con.commit()

        messagebox.showinfo("Success", "Transfer request submitted")
        self.load_transfers()
        self.transfer_qty.delete(0, "end")

    def load_transfers(self):
        for i in self.trans_tree.get_children():
            self.trans_tree.delete(i)
        with get_conn() as con:
            for row in con.execute("""
                SELECT t.id, t.request_date, t.src_branch, t.dst_branch, i.name, t.qty, t.status
                FROM transfers t JOIN items i ON t.item_id=i.id ORDER BY t.id DESC
            """):
                self.trans_tree.insert("", "end", values=row)

    def approve_transfer(self):
        if self.logged_user.role != "master":
            return messagebox.showwarning("Denied", "Only Master can approve")
        sel = self.trans_tree.selection()
        if not sel: return
        tid = self.trans_tree.item(sel[0], "values")[0]
        today = datetime.date.today().isoformat()

        with get_conn() as con:
            cur = con.cursor()
            row = cur.execute("SELECT src_branch, dst_branch, item_id, qty FROM transfers WHERE id=? AND status='pending'", (tid,)).fetchone()
            if not row:
                return messagebox.showwarning("Warning", "Transfer already processed")
            src, dst, item_id, qty = row

            def today_or_carried_forward(branch):
                r = cur.execute("SELECT opening_qty, stock_in, used FROM stock WHERE branch=? AND item_id=? AND entry_date=?",
                                 (branch, item_id, today)).fetchone()
                if r:
                    return r
                prev = cur.execute("SELECT closing_qty FROM stock WHERE branch=? AND item_id=? ORDER BY entry_date DESC, id DESC LIMIT 1",
                                    (branch, item_id)).fetchone()
                return (prev[0] if prev else 0, 0, 0)

            def upsert_stock(branch, opening, stock_in, used):
                closing = opening + stock_in - used
                cur.execute("""INSERT INTO stock (branch, item_id, entry_date, opening_qty, stock_in, used, closing_qty)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(branch, item_id, entry_date) DO UPDATE SET
                        stock_in=excluded.stock_in, used=excluded.used, closing_qty=excluded.closing_qty""",
                    (branch, item_id, today, opening, stock_in, used, closing))
                return closing

            src_opening, src_in, src_used = today_or_carried_forward(src)
            new_src_closing = src_opening + src_in - (src_used + qty)
            if new_src_closing < 0:
                return messagebox.showerror("Error", "Insufficient stock at source branch for this transfer")

            dst_opening, dst_in, dst_used = today_or_carried_forward(dst)

            upsert_stock(src, src_opening, src_in, src_used + qty)
            upsert_stock(dst, dst_opening, dst_in + qty, dst_used)

            cur.execute("UPDATE transfers SET status='approved' WHERE id=?", (tid,))
            con.commit()
        messagebox.showinfo("Approved", "Transfer completed")
        self.load_transfers()

    def reject_transfer(self):
        if self.logged_user.role != "master":
            return messagebox.showwarning("Denied", "Only Master can reject")
        sel = self.trans_tree.selection()
        if not sel: return
        tid = self.trans_tree.item(sel[0], "values")[0]
        if messagebox.askyesno("Reject", "Reject this request?"):
            with get_conn() as con:
                con.execute("UPDATE transfers SET status='rejected' WHERE id=?", (tid,))
                con.commit()
            self.load_transfers()

    # ====================== REPORTS ======================
    def _add_reports_tab(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Reports")

        tb.Label(tab, text="Reports & Export", font=("Helvetica", 18, "bold")).pack(pady=12)

        ctrl = tb.Frame(tab)
        ctrl.pack(fill=X, padx=20, pady=8)

        tb.Label(ctrl, text="Type:", font=("Helvetica", 10, "bold")).pack(side=LEFT)
        self.rep_type = tb.Combobox(ctrl, values=["Daily", "Weekly", "Monthly"], state="readonly", width=12)
        self.rep_type.set("Daily")
        self.rep_type.bind("<<ComboboxSelected>>", lambda e: self.load_report())
        self.rep_type.pack(side=LEFT, padx=10)

        tb.Label(ctrl, text="From:", font=("Helvetica", 10, "bold")).pack(side=LEFT, padx=(20,5))
        self.from_e = tb.Entry(ctrl, width=12)
        self.from_e.insert(0, (datetime.date.today() - datetime.timedelta(days=30)).isoformat())
        self.from_e.pack(side=LEFT)

        tb.Label(ctrl, text="To:", font=("Helvetica", 10, "bold")).pack(side=LEFT, padx=(10,5))
        self.to_e = tb.Entry(ctrl, width=12)
        self.to_e.insert(0, datetime.date.today().isoformat())
        self.to_e.pack(side=LEFT)

        tb.Button(ctrl, text="Load", command=self.load_report, bootstyle="info", padding=8).pack(side=LEFT, padx=15)
        tb.Button(ctrl, text="Export PDF (Coming Soon)", state="disabled", bootstyle="secondary", padding=8).pack(side=LEFT, padx=5)
        tb.Button(ctrl, text="Export Excel", command=self.export_excel, bootstyle="info", padding=8).pack(side=LEFT, padx=5)

        cols = ("date", "branch", "item", "sold", "revenue", "stock_in", "closing")
        self.rep_tree = tb.Treeview(tab, columns=cols, show="headings", height=18, bootstyle="primary")
        for h, c, w in zip(["Date","Branch","Item","Qty Sold","Revenue","Stock In","Closing"], cols, [100,120,220,90,110,90,90]):
            self.rep_tree.heading(c, text=h)
            self.rep_tree.column(c, width=w)
        self.rep_tree.pack(fill=BOTH, expand=True, padx=15, pady=15)

        self.load_report()

    def load_report(self):
        for i in self.rep_tree.get_children():
            self.rep_tree.delete(i)

        period_sql, period_label = {
            "Daily": ("s.sale_date", "Date"),
            "Weekly": ("strftime('%Y-W%W', s.sale_date)", "Week"),
            "Monthly": ("strftime('%Y-%m', s.sale_date)", "Month"),
        }[self.rep_type.get()]
        self.rep_tree.heading("date", text=period_label)

        with get_conn() as con:
            df = pd.read_sql(f"""
                SELECT {period_sql} as period, s.branch, i.name, SUM(s.qty_sold) as sold, SUM(s.revenue) as revenue,
                       COALESCE(SUM(st.stock_in),0) as stock_in, AVG(st.closing_qty) as closing
                FROM sales s
                JOIN items i ON s.item_id = i.id
                LEFT JOIN stock st ON st.branch = s.branch AND st.item_id = s.item_id AND st.entry_date = s.sale_date
                WHERE s.sale_date BETWEEN ? AND ?
                GROUP BY period, s.branch, i.name
                ORDER BY period DESC
            """, con, params=(self.from_e.get(), self.to_e.get()))
        for _, row in df.iterrows():
            self.rep_tree.insert("", "end", values=tuple(row))

    def export_excel(self):
        if not self.rep_tree.get_children():
            return messagebox.showwarning("Empty", "No data")
        file = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel Files", "*.xlsx")])
        if not file: return

        data = [self.rep_tree.item(child)["values"] for child in self.rep_tree.get_children()]
        cols = [self.rep_tree.heading(c)["text"] for c in self.rep_tree["columns"]]
        pd.DataFrame(data, columns=cols).to_excel(file, index=False)
        messagebox.showinfo("Success", f"Exported to {file}")

    # ====================== SETTINGS ======================
    def _add_settings_tab(self):
        tab = tb.Frame(self.notebook)
        self.notebook.add(tab, text="Settings")
        tb.Label(tab, text="Settings", font=("Helvetica", 18, "bold")).pack(pady=(120, 10))
        tb.Label(tab, text="Change password, backup, etc. — coming in a future update",
                 font=("Helvetica", 12)).pack()

    def logout(self):
        if messagebox.askokcancel("Logout", "Exit application?"):
            self.root.destroy()
            sys.exit()


def main():
    matplotlib.use("TkAgg")
    root = tb.Window(title="Taste Twist Stock Manager", themename=THEME_NAME,
                      size=(1380, 860), minsize=(1100, 700))
    TasteTwistApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
