"""Antarmuka Tkinter; seluruh pembaruan widget dilakukan pada thread UI."""

from __future__ import annotations

import gc
import ctypes
import logging
import queue
import sys
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

from repository import CLINICS, LABELS, METHODS, TIMES, ClinicError, ClinicRepository

BG, WHITE, INK, MUTED, TEAL, NAVY = "#F2F6F7", "#FFFFFF", "#18343A", "#60777D", "#087F83", "#16343B"


def money(amount):
    return "Rp " + f"{amount:,}".replace(",", ".")


def label(value):
    return LABELS.get(value, value)


class FormDialog(tk.Toplevel):
    def __init__(self, app, title, fields, operation, success, note="", button="Simpan"):
        super().__init__(app)
        self.app, self.operation, self.success = app, operation, success
        self.busy = False
        self.inputs, self.controls = {}, []
        self.title(title)
        self.configure(bg=WHITE)
        self.resizable(True, True)
        self.transient(app)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.form_canvas = tk.Canvas(self, background=WHITE, highlightthickness=0)
        self.form_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.form_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.form_canvas.configure(yscrollcommand=scrollbar.set)
        panel = ttk.Frame(self.form_canvas, padding=26, style="Card.TFrame")
        panel_id = self.form_canvas.create_window(0, 0, window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _: self.form_canvas.configure(scrollregion=self.form_canvas.bbox("all")))
        self.form_canvas.bind("<Configure>", lambda event: self.form_canvas.itemconfigure(panel_id, width=event.width))
        ttk.Label(panel, text=title, style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        if note:
            ttk.Label(panel, text=note, wraplength=470, style="MutedCard.TLabel").pack(anchor="w", pady=(0, 16))
        for key, caption, kind, options, initial in fields:
            ttk.Label(panel, text=caption, style="Card.TLabel").pack(anchor="w", pady=(7, 4))
            if kind == "text":
                widget = tk.Text(panel, height=3, width=52, font=("Segoe UI", 10), relief="solid", bd=1, wrap="word", padx=8, pady=6)
                widget.insert("1.0", initial)
                getter = lambda w=widget: w.get("1.0", "end-1c")
            else:
                variable = tk.StringVar(self, value=initial)
                if kind == "choice":
                    widget = ttk.Combobox(panel, textvariable=variable, values=options, state="readonly", width=52)
                else:
                    widget = ttk.Entry(panel, textvariable=variable, show="•" if kind == "password" else "", width=54)
                getter = variable.get
            widget.pack(fill="x")
            self.inputs[key] = (widget, getter)
            self.controls.append((widget, kind))
        self.error = tk.StringVar(self)
        ttk.Label(panel, textvariable=self.error, foreground="#B42318", background=WHITE, wraplength=470).pack(anchor="w", pady=12)
        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.pack(fill="x")
        self.cancel_button = ttk.Button(actions, text="Batal", command=self.close)
        self.cancel_button.pack(side="left")
        self.submit_button = ttk.Button(actions, text=button, style="Primary.TButton", command=self.submit)
        self.submit_button.pack(side="right")
        self.button_text = button
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _: self.close())

        def reveal_field(event):
            if event.widget is self:
                return
            canvas = self.form_canvas
            top = event.widget.winfo_rooty() - panel.winfo_rooty()
            bottom = top + event.widget.winfo_height()
            viewport_top = canvas.canvasy(0)
            total = max(1, panel.winfo_height())
            if top < viewport_top:
                canvas.yview_moveto(top / total)
            elif bottom > viewport_top + canvas.winfo_height():
                canvas.yview_moveto((bottom - canvas.winfo_height()) / total)

        def scroll_form(event):
            # Text/Combobox mempertahankan perilaku roda mouse bawaan.
            if event.widget.winfo_class() not in ("Text", "TCombobox"):
                self.form_canvas.yview_scroll(-int(event.delta / 120), "units")

        self.bind("<FocusIn>", reveal_field)
        self.bind("<MouseWheel>", scroll_form)
        self.update_idletasks()
        width = min(panel.winfo_reqwidth() + scrollbar.winfo_reqwidth(), app.winfo_screenwidth() - 80)
        height = min(panel.winfo_reqheight(), app.winfo_screenheight() - 100)
        x = max(0, min(app.winfo_screenwidth() - width - 20, app.winfo_rootx() + (app.winfo_width() - width) // 2))
        y = max(0, min(app.winfo_screenheight() - height - 70, app.winfo_rooty() + (app.winfo_height() - height) // 2))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.grab_set()
        if self.controls:
            self.controls[0][0].focus_set()

    def values(self):
        return {key: getter() for key, (_, getter) in self.inputs.items()}

    def set_busy(self, busy):
        self.busy = busy
        for widget, kind in self.controls:
            widget.configure(state="disabled" if busy else "readonly" if kind == "choice" else "normal")
        self.submit_button.configure(state="disabled" if busy else "normal", text="Menyimpan…" if busy else self.button_text)
        self.cancel_button.configure(state="disabled" if busy else "normal")

    def submit(self):
        if self.busy:
            return
        values = self.values()
        self.error.set("")
        self.set_busy(True)
        self.app.run_task(self, partial(self.operation, values), self._saved, self._failed)

    def _failed(self, error):
        self.set_busy(False)
        self.error.set(self.app.error_message(error))

    def _saved(self, result):
        callback = self.success
        self.set_busy(False)
        self.close()
        callback(result)

    def close(self):
        if self.busy:
            return
        self.grab_release()
        self.destroy()

    def destroy(self):
        super().destroy()
        self.inputs.clear()
        self.controls.clear()
        self.error = None
        self.operation = None
        self.success = None
        gc.collect()


def field(key, caption, kind="entry", options=(), initial=""):
    return key, caption, kind, options, initial


class ClinicApp(tk.Tk):
    def __init__(self, repository: ClinicRepository):
        if sys.platform == "win32":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except OSError:
                pass
        super().__init__()
        self.repository = repository
        self.session = None
        self.pending = 0
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clinic-db")
        self.results = queue.Queue()
        self.jobs = {}
        self.job_number = 0
        self.page = "Beranda"
        self.dialog = None
        self.title("Klinik Sehat — Desktop")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1180, screen_width - 80)}x{min(780, screen_height - 100)}")
        self.minsize(min(960, screen_width - 80), min(680, screen_height - 100))
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self.status = tk.StringVar(self, value="Siap")
        self.status_bar = ttk.Label(self, textvariable=self.status, padding=(18, 8), style="Muted.TLabel")
        self.status_bar.pack(side="bottom", fill="x")
        self.container = ttk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.poll_id = self.after(35, self._poll)
        self.show_login()

    def _style(self):
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), background=WHITE)
        style.configure("Page.TLabel", font=("Segoe UI Semibold", 24))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("MutedCard.TLabel", background=WHITE, foreground=MUTED)
        style.configure("Card.TFrame", background=WHITE)
        style.configure("Card.TLabel", background=WHITE)
        style.configure("Metric.TLabel", background=WHITE, foreground=TEAL, font=("Segoe UI Semibold", 28))
        style.configure("TButton", padding=(14, 9), background="#E6EEEE", borderwidth=0)
        style.map("TButton", background=[("active", "#D7E6E6")])
        style.configure("Primary.TButton", background=TEAL, foreground=WHITE)
        style.map("Primary.TButton", background=[("disabled", "#8BAFB0"), ("active", "#06696D")], foreground=[("disabled", WHITE)])
        style.configure("Nav.TButton", background=NAVY, foreground="#D4E3E5", anchor="w", padding=(20, 13))
        style.map("Nav.TButton", background=[("active", "#24505B")], foreground=[("active", WHITE)])
        style.configure("TEntry", padding=9, fieldbackground=WHITE)
        style.configure("TCombobox", padding=7)
        style.configure("Treeview", rowheight=35, fieldbackground=WHITE, background=WHITE, borderwidth=0)
        style.configure("Treeview.Heading", padding=(8, 12), background="#E5EEEF", font=("Segoe UI Semibold", 10))
        style.map("Treeview", background=[("selected", TEAL)], foreground=[("selected", WHITE)])

    @staticmethod
    def error_message(error):
        if isinstance(error, ClinicError):
            return str(error)
        logging.error("Operasi klinik gagal", exc_info=(type(error), error, error.__traceback__))
        return "Operasi tidak dapat diselesaikan. Periksa akses file/database; rincian tersedia di data/desktop.log."

    def report_callback_exception(self, exc, value, traceback):
        logging.error("Kesalahan antarmuka", exc_info=(exc, value, traceback))
        messagebox.showerror("Operasi gagal", self.error_message(value), parent=self)

    def run_task(self, owner, operation, success, failure=None):
        self.pending += 1
        self.status.set("Memproses…")
        self.job_number += 1
        job_id = self.job_number
        self.jobs[job_id] = (owner, success, failure)
        future = self.executor.submit(operation)
        # Worker hanya membawa ID dan hasil; referensi widget/callback milik thread UI.
        results = self.results
        future.add_done_callback(lambda done: results.put((job_id, done)))

    def _poll(self):
        try:
            while True:
                try:
                    job_id, future = self.results.get_nowait()
                except queue.Empty:
                    break
                self.pending -= 1
                owner, success, failure = self.jobs.pop(job_id)
                try:
                    try:
                        result = future.result()
                    except Exception as error:
                        if owner.winfo_exists():
                            if failure:
                                failure(error)
                            else:
                                message = self.error_message(error)
                                self.status.set(message)
                                messagebox.showerror("Operasi gagal", message, parent=self)
                    else:
                        if owner.winfo_exists():
                            self.status.set("Siap")
                            success(result)
                except Exception:
                    self.report_callback_exception(*sys.exc_info())
        finally:
            if not self.closed:
                self.poll_id = self.after(35, self._poll)

    def clear(self):
        for child in self.container.winfo_children():
            child.destroy()
        gc.collect()

    def show_login(self):
        self.clear()
        self.session = None
        self.repository.logout()
        host = ttk.Frame(self.container)
        host.pack(fill="both", expand=True)
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(host, background=BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)
        stage = ttk.Frame(canvas)
        stage_id = canvas.create_window(0, 0, window=stage, anchor="n")
        ttk.Label(stage, text="+", font=("Segoe UI", 30, "bold"), foreground=TEAL).pack()
        card = ttk.Frame(stage, padding=(36, 20), style="Card.TFrame")
        card.pack(pady=12)
        ttk.Label(card, text="Klinik Sehat", style="Title.TLabel").pack(anchor="w")
        ttk.Label(card, text="Masuk untuk mengelola layanan klinik Anda.", style="MutedCard.TLabel").pack(anchor="w", pady=(6, 12))
        self.login_vars = {"username": tk.StringVar(self), "password": tk.StringVar(self)}
        for key, caption in (("username", "Username"), ("password", "Kata sandi")):
            ttk.Label(card, text=caption, style="Card.TLabel").pack(anchor="w", pady=(8, 4))
            entry = ttk.Entry(card, textvariable=self.login_vars[key], show="•" if key == "password" else "", width=43)
            entry.pack(fill="x")
            entry.bind("<Return>", lambda _: self.login())
        self.login_error = tk.StringVar(self)
        ttk.Label(card, textvariable=self.login_error, foreground="#B42318", background=WHITE, wraplength=350).pack(anchor="w", pady=6)
        self.login_button = ttk.Button(card, text="Masuk", style="Primary.TButton", command=self.login)
        self.login_button.pack(fill="x", pady=(0, 9))
        self.login_owner = card
        if self.repository.has_users():
            ttk.Button(card, text="Daftar sebagai Pasien", command=self.register_patient).pack(fill="x")
        else:
            ttk.Label(card, text="Belum ada data klinik di desktop ini.", style="MutedCard.TLabel").pack(anchor="w", pady=8)
            ttk.Button(card, text="Siapkan Admin Pertama", command=self.setup_admin).pack(fill="x", pady=4)
            ttk.Button(card, text="Impor Database Flutter / Backup", command=self.import_database).pack(fill="x", pady=4)
        ttk.Label(stage, text="Pasien · Dokter · Admin   |   Desktop", style="Muted.TLabel").pack(pady=12)

        def layout(_event=None):
            width, height = canvas.winfo_width(), canvas.winfo_height()
            required = stage.winfo_reqheight()
            canvas.coords(stage_id, width // 2, max(12, (height - required) // 2))
            canvas.configure(scrollregion=(0, 0, width, max(height, required + 24)))
            if required + 24 > height:
                scrollbar.grid()
            else:
                scrollbar.grid_remove()

        canvas.bind("<Configure>", layout)
        stage.bind("<Configure>", layout)
        for widget in (canvas, stage, card, *card.winfo_children()):
            widget.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units"), add="+")
        self.status.set("Database: " + str(self.repository.path))

    def login(self):
        if self.pending:
            return
        username, password = self.login_vars["username"].get(), self.login_vars["password"].get()
        self.login_button.configure(state="disabled", text="Memeriksa…")
        self.login_error.set("")

        def failed(error):
            self.login_button.configure(state="normal", text="Masuk")
            self.login_error.set(self.error_message(error))

        self.run_task(self.login_owner, lambda: self.repository.authenticate(username, password), self.logged_in, failed)

    def logged_in(self, account):
        self.session = account
        self.clear()
        side = tk.Frame(self.container, background=NAVY, width=225)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="+  KLINIK SEHAT", background=NAVY, foreground=WHITE, font=("Segoe UI Semibold", 16)).pack(anchor="w", padx=20, pady=(30, 6))
        tk.Label(side, text="LAYANAN KLINIK DESKTOP", background=NAVY, foreground="#9ABABC", font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 28))
        role = account["role"]
        menus = ["Beranda", "Pendaftaran"]
        if role == "ADMIN":
            menus += ["Pengguna", "Pembayaran"]
        elif role == "DOCTOR":
            menus += ["Rekam Medis", "Resep"]
        else:
            menus += ["Rekam Medis", "Resep", "Pembayaran"]
        for name in menus:
            ttk.Button(side, text=name, style="Nav.TButton", command=lambda p=name: self.show_page(p)).pack(fill="x", padx=10, pady=3)
        ttk.Button(side, text="Keluar dari Akun", style="Nav.TButton", command=self.logout).pack(side="bottom", fill="x", padx=10, pady=20)
        self.main = ttk.Frame(self.container, padding=(28, 24))
        self.main.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(self.main)
        top.pack(fill="x", pady=(0, 20))
        identity = account["full_name"] + (" · " + account["medical_number"] if account["role"] == "PATIENT" else "")
        ttk.Label(top, text=identity, font=("Segoe UI Semibold", 12)).pack(side="left")
        ttk.Label(top, text=label(role) + "  •  " + date.today().strftime("%d/%m/%Y"), style="Muted.TLabel").pack(side="right")
        self.content = ttk.Frame(self.main)
        self.content.pack(fill="both", expand=True)
        self.show_page("Beranda")

    def logout(self):
        if self.pending:
            self.status.set("Tunggu proses selesai sebelum keluar.")
            return
        if messagebox.askyesno("Keluar", "Keluar dari akun sekarang?", parent=self):
            self.show_login()

    def show_page(self, name):
        if self.pending:
            return
        self.page = name
        for child in self.content.winfo_children():
            child.destroy()
        self.page_owner = ttk.Frame(self.content)
        self.page_owner.pack(fill="both", expand=True)
        self.heading = ttk.Frame(self.page_owner)
        self.heading.pack(fill="x", pady=(0, 18))
        ttk.Label(self.heading, text=name, style="Page.TLabel").pack(side="left")
        ttk.Button(self.heading, text="Muat Ulang", command=lambda: self.show_page(name)).pack(side="right")
        self.page_body = ttk.Frame(self.page_owner)
        self.page_body.pack(fill="both", expand=True)
        if name == "Beranda":
            self.dashboard()
        elif name == "Pengguna":
            self.run_task(self.page_owner, self.repository.users, self.render_users)
        elif name == "Pendaftaran":
            self.run_task(self.page_owner, self.repository.registrations, self.render_registrations)
        elif name == "Rekam Medis":
            self.run_task(self.page_owner, self.repository.medical_records, self.render_records)
        elif name == "Resep":
            self.run_task(self.page_owner, self.repository.prescriptions, self.render_prescriptions)
        else:
            self.run_task(self.page_owner, self.repository.payments, self.render_payments)

    def dashboard(self):
        role = self.session["role"]
        repository = self.repository

        def load():
            repository.current_user()
            registrations = repository.registrations()
            payments = repository.payments() if role != "DOCTOR" else []
            users = repository.users() if role == "ADMIN" else []
            return registrations, payments, users

        def render(data):
            registrations, payments, users = data
            card = ttk.Frame(self.page_body, style="Card.TFrame", padding=24)
            card.pack(fill="x", pady=(0, 20))
            ttk.Label(card, text="Selamat datang, " + self.session["full_name"], style="Title.TLabel", wraplength=680).pack(anchor="w")
            ttk.Label(card, text={"ADMIN": "Kelola dokter, antrean kunjungan, dan verifikasi pembayaran.", "DOCTOR": "Periksa antrean Anda dan catat hasil pemeriksaan pasien.", "PATIENT": "Daftarkan kunjungan dan pantau layanan kesehatan Anda."}[role], style="MutedCard.TLabel", wraplength=650).pack(anchor="w", pady=(10, 0))
            stats = ttk.Frame(self.page_body)
            stats.pack(fill="x", pady=(0, 20))
            metrics = [("Total kunjungan", len(registrations)), ("Menunggu pemeriksaan", sum(r["status"] in ("WAITING", "CONFIRMED") for r in registrations)), ("Dokter aktif", sum(u["role"] == "DOCTOR" and u["is_active"] for u in users)) if role == "ADMIN" else ("Kunjungan selesai", sum(r["status"] == "COMPLETED" for r in registrations))]
            for index, (caption, value) in enumerate(metrics):
                stats.columnconfigure(index, weight=1, uniform="metrics")
                metric = ttk.Frame(stats, style="Card.TFrame", padding=18)
                metric.grid(row=0, column=index, sticky="nsew", padx=(0, 12 if index < 2 else 0))
                ttk.Label(metric, text=str(value), style="Metric.TLabel").pack(anchor="w")
                ttk.Label(metric, text=caption, style="MutedCard.TLabel", wraplength=170).pack(anchor="w")
            actions = ttk.Frame(self.page_body, style="Card.TFrame", padding=22)
            actions.pack(fill="x")
            ttk.Label(actions, text="Akses cepat", style="Card.TLabel", font=("Segoe UI Semibold", 14)).pack(anchor="w", pady=(0, 15))
            if role == "ADMIN":
                ttk.Button(actions, text="+ Tambah Dokter", style="Primary.TButton", command=self.add_doctor).pack(anchor="w", pady=4)
                ttk.Button(actions, text="Backup Database", command=self.backup_database).pack(anchor="w", pady=4)
            elif role == "PATIENT":
                ttk.Button(actions, text="+ Daftar Pemeriksaan", style="Primary.TButton", command=self.add_appointment).pack(anchor="w", pady=4)
            else:
                ttk.Button(actions, text="Buka Antrean Saya", style="Primary.TButton", command=lambda: self.show_page("Pendaftaran")).pack(anchor="w", pady=4)
            if role != "DOCTOR":
                remaining = sum(p["amount"] for p in payments if p["status"] != "PAID")
                ttk.Label(actions, text="Tagihan belum lunas: " + money(remaining), style="MutedCard.TLabel").pack(anchor="w", pady=(15, 0))

        self.run_task(self.page_owner, load, render)

    def table(self, rows, columns):
        toolbar = ttk.Frame(self.page_body)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, text="Pilih baris untuk melihat rincian dan melakukan tindakan.", style="Muted.TLabel").pack(anchor="w")
        wrap = ttk.Frame(self.page_body)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=[col[0] for col in columns], show="headings", selectmode="browse", height=9)
        for key, caption, width in columns:
            self.tree.heading(key, text=caption)
            self.tree.column(key, width=width, minwidth=75)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(wrap, command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.rows = {str(row["id"]): row for row in rows}
        for row in rows:
            values = []
            for key, _, _ in columns:
                value = row.get(key, "")
                if key == "is_active":
                    value = "Aktif" if value else "Nonaktif"
                elif key == "amount":
                    value = money(value)
                else:
                    value = label(value) if isinstance(value, str) else value
                values.append(value)
            self.tree.insert("", "end", iid=str(row["id"]), values=values)
        detail_frame = ttk.Frame(self.page_body)
        detail_frame.pack(fill="x", pady=(12, 10))
        self.detail = tk.Text(detail_frame, height=5, font=("Segoe UI", 10), bg=WHITE, fg=INK, relief="flat", padx=14, pady=10, wrap="word", state="disabled")
        self.detail.pack(side="left", fill="x", expand=True)
        detail_scrollbar = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        detail_scrollbar.pack(side="right", fill="y")
        self.detail.configure(yscrollcommand=detail_scrollbar.set)
        self.detail_fields = []
        self.tree.bind("<<TreeviewSelect>>", self.update_detail)
        self.actions = ttk.Frame(self.page_body)
        self.actions.pack(fill="x")
        self.status.set(f"{len(rows)} data ditampilkan" if rows else "Belum ada data.")
        return self.tree

    def selected(self):
        ids = self.tree.selection()
        if not ids:
            raise ClinicError("Pilih satu baris terlebih dahulu.")
        return self.rows[ids[0]]

    def choose(self, callback):
        try:
            callback(self.selected())
        except ClinicError as error:
            messagebox.showinfo("Pilih Data", str(error), parent=self)

    def update_detail(self, _event=None):
        if not self.tree.selection():
            return
        row = self.selected()
        content = "\n".join(f"{caption}: {label(str(row.get(key) or '-'))}" for key, caption in self.detail_fields)
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", content)
        self.detail.configure(state="disabled")

    def action_button(self, text, callback, primary=False):
        ttk.Button(self.actions, text=text, style="Primary.TButton" if primary else "TButton", command=lambda: self.choose(callback)).pack(side="left", padx=(0, 8))

    def refresh_success(self, message):
        self.show_page(self.page)
        self.status.set(message)

    def mutate(self, operation, message):
        if self.pending:
            return
        self.run_task(self.page_owner, operation, lambda _: self.refresh_success(message))

    def render_users(self, rows):
        ttk.Button(self.heading, text="+ Tambah Dokter", style="Primary.TButton", command=self.add_doctor).pack(side="right", padx=10)
        self.table(rows, [("full_name", "Nama", 210), ("username", "Username", 240), ("role", "Role", 100), ("clinic", "Poli", 120), ("is_active", "Status", 90)])
        self.detail_fields = [("full_name", "Nama"), ("medical_number", "Nomor rekam medis"), ("username", "Username"), ("clinic", "Poli")]

        def toggle(row):
            verb = "menonaktifkan" if row["is_active"] else "mengaktifkan"
            if messagebox.askyesno("Status Akun", f"Anda akan {verb} akun {row['full_name']}. Lanjutkan?", parent=self):
                self.mutate(lambda: self.repository.set_user_active(row["id"], not row["is_active"]), "Status akun diperbarui")

        self.action_button("Aktifkan / Nonaktifkan", toggle)

    def render_registrations(self, rows):
        role = self.session["role"]
        if role == "PATIENT":
            ttk.Button(self.heading, text="+ Daftar Pemeriksaan", style="Primary.TButton", command=self.add_appointment).pack(side="right", padx=10)
        self.table(rows, [("queue_number", "Antrean", 85), ("visit_date", "Tanggal", 110), ("visit_time", "Jam", 75), ("patient_name", "Pasien", 165), ("doctor_name", "Dokter", 165), ("status", "Status", 135)])
        self.detail_fields = [("patient_name", "Pasien"), ("medical_number", "Nomor rekam medis"), ("doctor_name", "Dokter"), ("clinic", "Poli"), ("complaint", "Keluhan")]
        if role == "ADMIN":
            self.action_button("Konfirmasi", lambda r: self.mutate(lambda: self.repository.confirm_registration(r["id"]), "Pendaftaran dikonfirmasi"), True)

            def cancel(row):
                if messagebox.askyesno("Batalkan Kunjungan", "Batalkan pendaftaran " + row["queue_number"] + "?", parent=self):
                    self.mutate(lambda: self.repository.cancel_registration(row["id"]), "Pendaftaran dibatalkan")

            self.action_button("Batalkan", cancel)
        elif role == "DOCTOR":
            self.action_button("Isi Hasil Pemeriksaan", self.examine, True)

    def render_records(self, rows):
        self.table(rows, [("visit_date", "Tanggal", 110), ("patient_name", "Pasien", 170), ("doctor_name", "Dokter", 170), ("diagnosis", "Diagnosis", 250)])
        self.detail_fields = [("patient_name", "Pasien"), ("medical_number", "Nomor rekam medis"), ("complaint", "Keluhan"), ("diagnosis", "Diagnosis"), ("treatment", "Tindakan")]

    def render_prescriptions(self, rows):
        for row in rows:
            row["handover_time"] = datetime.fromtimestamp(row["handed_over_at"] / 1000).strftime("%d/%m/%Y %H:%M") if row["handed_over_at"] else "Belum tercatat"
        self.table(rows, [("visit_date", "Tanggal", 110), ("patient_name", "Pasien", 160), ("doctor_name", "Dokter", 160), ("medicines", "Resep obat", 320), ("delivery_status", "Penyerahan obat", 210)])
        self.detail_fields = [("patient_name", "Pasien"), ("medical_number", "Nomor rekam medis"), ("doctor_name", "Dokter"), ("medicines", "Resep"), ("delivery_status", "Status"), ("handover_name", "Diserahkan oleh"), ("handover_time", "Waktu penyerahan")]

        def collect(row):
            if messagebox.askyesno("Penyerahan Obat", f"Pastikan identitas pasien {row['patient_name']} ({row['medical_number']}) dan seluruh obat sesuai resep. Catat bahwa Anda telah menyerahkan obat?", parent=self):
                self.mutate(lambda: self.repository.dispense_prescription(row["id"]), "Petugas dan waktu penyerahan obat tersimpan")

        if self.session["role"] == "DOCTOR":
            self.action_button("Catat Penyerahan Obat", collect, True)

    def render_payments(self, rows):
        self.table(rows, [("patient_name", "Pasien", 170), ("description", "Tagihan", 210), ("amount", "Jumlah", 125), ("status", "Status", 170)])
        self.detail_fields = [("patient_name", "Pasien"), ("medical_number", "Nomor rekam medis"), ("description", "Tagihan"), ("payment_method", "Metode"), ("payment_reference", "Referensi"), ("status", "Status")]
        if self.session["role"] == "PATIENT":
            self.action_button("Kirim Informasi Pembayaran", self.pay, True)
        else:
            def review(row, accepted):
                text = "Verifikasi sebagai lunas?" if accepted else "Tolak informasi pembayaran ini?"
                if messagebox.askyesno("Verifikasi Pembayaran", text, parent=self):
                    self.mutate(lambda: self.repository.review_payment(row["id"], accepted), "Pembayaran diperbarui")

            self.action_button("Verifikasi Lunas", lambda r: review(r, True), True)
            self.action_button("Tolak", lambda r: review(r, False))

    def open_form(self, title, fields, operation, success, note="", button="Simpan"):
        if self.pending:
            return None
        if self.dialog is not None and self.dialog.winfo_exists():
            self.dialog.lift()
            return self.dialog
        self.dialog = FormDialog(self, title, fields, operation, success, note, button)
        return self.dialog

    @staticmethod
    def confirmed_password(values):
        if values["password"] != values["confirmation"]:
            raise ClinicError("Konfirmasi kata sandi tidak sama.")
        return values["password"]

    def account_fields(self):
        return [field("name", "Nama lengkap"), field("username", "Username"), field("password", "Kata sandi (8–72 karakter, huruf dan angka)", "password"), field("confirmation", "Ulangi kata sandi", "password")]

    def setup_admin(self):
        repository = self.repository
        def save(values):
            return repository.create_initial_admin(values["name"], values["username"], ClinicApp.confirmed_password(values))

        def success(account):
            self.show_login()
            self.login_vars["username"].set(account["username"])
            self.status.set("Admin pertama tersimpan. Silakan masuk.")

        return self.open_form("Siapkan Admin Klinik", self.account_fields(), save, success, "Hanya diperlukan sekali pada database kosong.")

    def register_patient(self):
        repository = self.repository
        def save(values):
            return repository.register_patient(values["name"], values["username"], ClinicApp.confirmed_password(values))

        def success(account):
            self.login_vars["username"].set(account["username"])
            self.login_vars["password"].set("")
            self.status.set("Akun pasien tersimpan. Silakan masuk.")

        return self.open_form("Daftar sebagai Pasien", self.account_fields(), save, success)

    def add_doctor(self):
        repository = self.repository
        fields = [field("name", "Nama dokter"), field("username", "Username dokter"), field("password", "Kata sandi awal (8–72 karakter, huruf dan angka)", "password"), field("clinic", "Poli", "choice", tuple(CLINICS), next(iter(CLINICS)))]
        return self.open_form("Tambah Dokter", fields, lambda v: repository.create_doctor(v["name"], v["username"], v["password"], v["clinic"]), lambda _: self.refresh_success("Akun dokter berhasil dibuat"), "Role Dokter ditetapkan oleh sistem. Username harus unik.")

    def add_appointment(self):
        repository = self.repository
        def loaded(doctors):
            if not doctors:
                messagebox.showinfo("Pendaftaran", "Belum ada dokter aktif. Hubungi Admin klinik.", parent=self)
                return
            mapping = {f"{d['full_name']} · {d['clinic']} (ID {d['id']})": d["id"] for d in doctors}
            fields = [field("doctor", "Dokter / Poli", "choice", tuple(mapping), next(iter(mapping))), field("date", "Tanggal kunjungan (YYYY-MM-DD)", initial=date.today().isoformat()), field("time", "Jam", "choice", TIMES, TIMES[0]), field("complaint", "Keluhan utama (3–250 karakter)", "text")]
            self.open_form("Pendaftaran Pemeriksaan", fields, lambda v: repository.register_appointment(mapping[v["doctor"]], v["date"], v["time"], v["complaint"]), lambda r: self.refresh_success("Pendaftaran tersimpan. Antrean: " + r["queue_number"]))

        if not self.pending:
            self.run_task(self.page_owner, self.repository.active_doctors, loaded)

    def examine(self, row):
        repository = self.repository
        fields = [field("diagnosis", "Diagnosis (3–200 karakter)", "text"), field("treatment", "Tindakan (3–300 karakter)", "text"), field("medicines", "Resep obat dan aturan pakai (opsional, maksimal 500 karakter)", "text")]
        return self.open_form("Hasil Pemeriksaan", fields, lambda v: repository.complete_examination(row["id"], v["diagnosis"], v["treatment"], v["medicines"]), lambda _: self.refresh_success("Rekam medis, resep, dan tagihan disimpan"), row["patient_name"] + " — " + row["complaint"])

    def pay(self, row):
        repository = self.repository
        fields = [field("method", "Metode", "choice", METHODS, METHODS[0]), field("reference", "Nomor referensi transaksi (4–40 karakter)")]
        return self.open_form("Informasi Pembayaran", fields, lambda v: repository.submit_payment(row["id"], v["method"], v["reference"]), lambda _: self.refresh_success("Pembayaran menunggu verifikasi Admin"), "Tagihan " + money(row["amount"]) + ". Masukkan referensi transaksi yang telah dilakukan; aplikasi mencatat pembayaran dan tidak mentransfer dana.")

    def backup_database(self):
        destination = filedialog.asksaveasfilename(parent=self, title="Simpan Backup", initialfile="klinik-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db", defaultextension=".db", filetypes=[("SQLite database", "*.db")])
        if destination:
            self.mutate(lambda: self.repository.backup(destination), "Backup database berhasil dibuat")

    def import_database(self):
        if self.pending:
            return
        source = filedialog.askopenfilename(parent=self, title="Pilih Database Flutter / Backup", filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"), ("Semua file", "*.*")])
        if source:
            self.run_task(self.login_owner, lambda: self.repository.import_flutter(source), lambda _: self.show_login())

    def close(self):
        if self.pending:
            self.status.set("Tunggu proses selesai sebelum menutup aplikasi.")
            return
        self.closed = True
        self.after_cancel(self.poll_id)
        self.executor.shutdown(wait=True)
        self.repository.close()
        self.destroy()
        self.jobs.clear()
        self.login_vars.clear()
        self.login_error = None
        self.status = None
        gc.collect()
