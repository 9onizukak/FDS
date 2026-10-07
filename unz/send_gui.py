"""หน้าจอเลือกคนไข้ส่ง FDH (GUI, tkinter — ไม่ต้องลง dependency)

เปิด:  python send_gui.py     (หรือ double-click ไฟล์นี้)

กรอกช่วงวันที่ -> ค้นหา -> ติ๊ก ☐ หน้าคนไข้ที่จะส่ง -> กดส่ง -> ดูคอลัมน์ "สถานะ"
อ่าน DB read-only แล้ว reuse build_payload + import_fdh เหมือน CLI
"""
import calendar
import datetime
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import build_payload
import api_config
import check_fdh
import history
import import_fdh
import send_menu
from runtime_paths import ENV_PATH
from app_version import APP_VERSION
from update_ui import UpdateController

THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


class ThaiDatePicker(ttk.Frame):
    """เลือกวันที่แบบ dropdown: วัน / เดือนไทย / ปี พ.ศ.  -> get() คืน 'YYYY-MM-DD' (ค.ศ.)"""

    def __init__(self, master):
        super().__init__(master, style="Card.TFrame")
        self.d, self.m, self.y = tk.StringVar(), tk.StringVar(), tk.StringVar()
        cy = datetime.date.today().year + 543
        years = [str(cy + o) for o in (1, 0, -1, -2, -3, -4, -5)]
        ttk.Combobox(self, textvariable=self.d, width=3, state="readonly",
                     values=[str(i) for i in range(1, 32)]).pack(side="left", padx=1)
        ttk.Combobox(self, textvariable=self.m, width=6, state="readonly",
                     values=THAI_MONTHS).pack(side="left", padx=1)
        ttk.Combobox(self, textvariable=self.y, width=6, state="readonly",
                     values=years).pack(side="left", padx=1)
        self.set(datetime.date.today())

    def set(self, dt):
        self.d.set(str(dt.day))
        self.m.set(THAI_MONTHS[dt.month - 1])
        self.y.set(str(dt.year + 543))

    def get(self):
        y = int(self.y.get()) - 543
        mo = THAI_MONTHS.index(self.m.get()) + 1
        day = min(int(self.d.get()), calendar.monthrange(y, mo)[1])   # กันวันเกินเดือน
        return f"{y:04d}-{mo:02d}-{day:02d}"


class App:
    # ---------- ธีมสี ----------
    BG, CARD, PRIMARY, PRIMARY_D = "#f7f9f8", "#ffffff", "#087443", "#065a34"
    NAVY, TEXT, MUTED = "#18382b", "#293d34", "#6c7b73"
    OKC, FAILC, WARN, STRIPE, LINE = "#087443", "#c2414b", "#a87623", "#fafcfb", "#e3e9e5"

    def __init__(self, root):
        self.root = root
        self.rows = []
        self.sending = False
        self.searching = False
        self.checking = False
        self.resending = False
        self.updating = False
        self.api_config = api_config.load()
        self.checked = set()       # iid (str = index แถวจริง) ที่ติ๊กไว้ — ข้ามหน้าได้
        self.rowstatus = {}        # idx -> (ข้อความสถานะเครื่องนี้, tag)
        self.fdhstatus = {}        # idx -> ข้อความสถานะจากเซิร์ฟเวอร์ FDH
        self.view = []             # ลำดับ index ที่จะแสดง (หลังกรอง/เรียง)
        self.page = 0
        self.PAGE = 200            # แถวต่อหน้า
        self.sort_col = None
        self.sort_desc = False
        root.title(f"{build_payload.HOSPITAL_NAME} · FDH {APP_VERSION}")
        root.geometry("1280x820")
        root.minsize(1040, 680)
        root.configure(bg=self.BG)
        self._setup_style()

        # ชื่อโรงพยาบาลเป็นหัวเรื่องระดับ H1 ของหน้าจอ tkinter
        hdr = tk.Frame(root, bg=self.CARD, height=112)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        brand = tk.Frame(hdr, bg=self.CARD)
        brand.pack(side="left", fill="y", padx=(28, 0))
        self.moph_logo = tk.PhotoImage(master=root,
                                      file=Path(__file__).resolve().parent / "assets" / "moph-logo.png")
        root.iconphoto(True, self.moph_logo)
        tk.Label(brand, image=self.moph_logo, bg=self.CARD,
                 borderwidth=0).pack(side="left", pady=20)
        brand_text = tk.Frame(brand, bg=self.CARD)
        brand_text.pack(side="left", padx=14, pady=15)
        tk.Label(brand_text, text=build_payload.HOSPITAL_NAME, bg=self.CARD, fg=self.NAVY,
                 font=self.H1_FONT, anchor="w").pack(fill="x")
        tk.Label(brand_text, text=f"ระบบส่งข้อมูล FDH  ·  รหัสหน่วยบริการ {build_payload.HCODE}",
                 bg=self.CARD, fg=self.MUTED, font=(self.FONT, 10), anchor="w").pack(fill="x", pady=(4, 0))

        controls = tk.Frame(hdr, bg=self.CARD)
        controls.pack(side="right", padx=28, pady=14)
        self.lbl_environment = tk.Label(controls, bg="#f5f8f6", padx=12, pady=6,
                                        font=(self.FONT, 10, "bold"))
        self.lbl_environment.pack(anchor="e")
        self._update_environment_badge()
        ttk.Button(controls, text="ตั้งค่า API / การเชื่อมต่อ",
                   command=self.open_settings).pack(anchor="e", pady=(6, 0))
        tk.Frame(root, bg=self.LINE, height=1).pack(fill="x")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=24, pady=(18, 22))
        opd = ttk.Frame(nb, style="Page.TFrame")
        ipd = ttk.Frame(nb, style="Page.TFrame")
        nb.add(opd, text="   ผู้ป่วยนอก OPD   ")
        nb.add(ipd, text="   ผู้ป่วยใน IPD   ")
        self._build_opd(opd)
        self._build_ipd(ipd)
        update_bar = ttk.Frame(root, style="Page.TFrame")
        update_bar.pack(fill="x", padx=24, pady=(0, 10))
        self.updater = UpdateController(self, update_bar)

    def open_settings(self):
        if self._api_busy():
            messagebox.showinfo("กำลังประมวลผล", "รอให้งานปัจจุบันเสร็จก่อนเปลี่ยนการตั้งค่า API", parent=self.root)
            return
        if hasattr(self, "settings_window") and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = self.settings_window = tk.Toplevel(self.root)
        win.title("ตั้งค่า API / การเชื่อมต่อ")
        win.geometry("780x560")
        win.resizable(False, False)
        win.configure(bg=self.CARD)
        win.transient(self.root)
        body = tk.Frame(win, bg=self.CARD, padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="ตั้งค่า API", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 18, "bold")).pack(anchor="w")
        tk.Label(body, text="เลือกปลายทางสำหรับส่งข้อมูลและตรวจสถานะ FDH",
                 bg=self.CARD, fg=self.MUTED, font=(self.FONT, 10)).pack(anchor="w", pady=(2, 14))
        form = tk.Frame(body, bg=self.CARD)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        environment = tk.StringVar(value=self.api_config.environment)
        uat_url = tk.StringVar(value=self.api_config.uat_url)
        production_url = tk.StringVar(value=self.api_config.production_url)
        token_url = tk.StringVar(value=self.api_config.token_url)
        for row, label in enumerate(("โหมดใช้งาน", "UAT Base URL", "Production Base URL", "Token URL")):
            tk.Label(form, text=label, bg=self.CARD, fg=self.TEXT,
                     font=(self.FONT, 10)).grid(row=row, column=0, sticky="w", padx=(0, 18), pady=7)
        mode = ttk.Combobox(form, textvariable=environment, values=("UAT", "PRODUCTION"),
                            state="readonly", width=20)
        mode.grid(row=0, column=1, sticky="w", pady=7)
        for row, variable in enumerate((uat_url, production_url, token_url), start=1):
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=7)
        preview = tk.Label(body, bg="#f5f8f6", fg=self.TEXT, font=(self.FONT, 10),
                           anchor="w", justify="left", padx=12, pady=12, wraplength=700)
        preview.pack(fill="x", pady=(14, 0))

        def update_preview(*args):
            base = (production_url.get() if environment.get() == "PRODUCTION" else uat_url.get()).rstrip("/")
            label = "PRODUCTION · ส่งข้อมูลจริง" if environment.get() == "PRODUCTION" else "UAT · พื้นที่ทดสอบ"
            try:
                dataset = api_config.dataset_base_url(base)
                preview.config(text=f"{label}\nส่งข้อมูล: {dataset}/import\n"
                                    f"ตรวจสถานะ: {dataset}/get_data")
            except ValueError:
                preview.config(text="กรุณาตรวจสอบรูปแบบ URL")

        for variable in (environment, uat_url, production_url):
            variable.trace_add("write", update_preview)
        update_preview()
        tk.Label(body, text="บัญชี FDH และฐานข้อมูล HOSxP", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 11, "bold")).pack(anchor="w", pady=(18, 6))
        ttk.Button(body, text="แก้ไขบัญชี / รหัสผ่าน / ฐานข้อมูล",
                   command=self.open_connection_file).pack(anchor="w")
        tk.Label(body, text="Base URL ใช้โดเมนหรือ URL ถึง dataset ได้ · โหมด API มีผลทันทีหลังบันทึก", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9)).pack(anchor="w", pady=(10, 0))
        actions = tk.Frame(body, bg=self.CARD)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(actions, text="บันทึก", style="Accent.TButton",
                   command=lambda: self._save_api_settings(win, environment, uat_url,
                                                           production_url, token_url)).pack(side="right")
        ttk.Button(actions, text="ยกเลิก", command=win.destroy).pack(side="right", padx=8)

    def _api_busy(self):
        return self.sending or self.searching or self.checking or self.resending or self.updating

    def _update_environment_badge(self):
        production = self.api_config.environment == "PRODUCTION"
        self.lbl_environment.config(text="● PRODUCTION · ส่งจริง" if production else "● UAT · พื้นที่ทดสอบ",
                                    fg=self.PRIMARY if production else self.WARN)

    def _save_api_settings(self, win, environment, uat_url, production_url, token_url):
        if self._api_busy():
            messagebox.showinfo("กำลังประมวลผล", "รอให้งานปัจจุบันเสร็จก่อนเปลี่ยนการตั้งค่า API", parent=win)
            return
        try:
            config = api_config.APIConfig(environment.get(), uat_url.get().strip(),
                                          production_url.get().strip(), token_url.get().strip())
            sent = history.sent_vns(config.environment)
            api_config.save(config)
        except Exception as error:
            messagebox.showerror("บันทึกไม่สำเร็จ", str(error), parent=win)
            return
        self.api_config = config
        self._update_environment_badge()
        self._apply_opd_search(self.rows, sent)
        self.lbl_status.config(text=f"ใช้งาน {config.environment} · {config.base_url}")
        win.destroy()

    def open_connection_file(self):
        import subprocess
        subprocess.Popen(["notepad.exe", str(ENV_PATH)])
        messagebox.showinfo("ตั้งค่าการเชื่อมต่อ",
                            "เติมค่าการเชื่อมต่อในไฟล์ที่เปิด แล้วบันทึก\n"
                            "ปิดและเปิดโปรแกรมใหม่หลังแก้ไขค่าการเชื่อมต่อ", parent=self.root)

    def _setup_style(self):
        # เลือกฟอนต์ไทยสวย ๆ ที่มีในเครื่อง (Leelawadee UI มากับ Windows)
        import tkinter.font as tkfont
        fams = set(tkfont.families())
        fam = next((f for f in ("Leelawadee UI", "Sarabun", "TH Sarabun New", "Tahoma") if f in fams),
                   "Tahoma")
        self.FONT = fam
        self.H1_FONT = (fam, 24, "bold")
        base = (fam, 10)
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", font=base, background=self.BG, foreground=self.TEXT)
        s.configure("TFrame", background=self.BG)
        s.configure("Page.TFrame", background=self.BG)
        s.configure("Card.TFrame", background=self.CARD)
        s.configure("TLabel", background=self.CARD, foreground=self.TEXT)
        s.configure("Muted.TLabel", background=self.CARD, foreground=self.MUTED)
        s.configure("PageTitle.TLabel", background=self.BG, foreground=self.NAVY,
                    font=(fam, 16, "bold"))
        s.configure("PageSub.TLabel", background=self.BG, foreground=self.MUTED,
                    font=(fam, 10))
        s.configure("TCheckbutton", background=self.CARD, font=base)
        s.configure("TButton", padding=(13, 8), font=(fam, 10), background="#eef3f0", borderwidth=0,
                    focuscolor=self.CARD)
        s.map("TButton", background=[("active", "#e1eae4"), ("disabled", "#f3f5f4")],
              foreground=[("disabled", "#98a59e")])
        s.configure("Accent.TButton", padding=(18, 9), font=(fam, 10, "bold"),
                    background=self.PRIMARY, foreground="white", borderwidth=0)
        s.map("Accent.TButton", background=[("active", self.PRIMARY_D), ("disabled", "#aacabc")])
        s.configure("Treeview", rowheight=38, font=(fam, 10), background=self.CARD,
                    fieldbackground=self.CARD, borderwidth=0, relief="flat")
        s.map("Treeview", background=[("selected", "#e2f1e8")], foreground=[("selected", self.NAVY)])
        s.configure("Treeview.Heading", font=(fam, 9, "bold"), background="#f0f4f1",
                    foreground=self.TEXT, padding=(8, 10), relief="flat")
        s.map("Treeview.Heading", background=[("active", "#e3ebe6")])
        s.configure("TNotebook", background=self.BG, borderwidth=0, tabmargins=(0, 0, 0, 14))
        s.configure("TNotebook.Tab", padding=(22, 11), font=(fam, 10, "bold"),
                    background=self.BG, foreground=self.MUTED, borderwidth=0)
        s.map("TNotebook.Tab", background=[("selected", self.CARD), ("active", "#edf3ef")],
              foreground=[("selected", self.PRIMARY)])
        s.configure("TEntry", padding=6, fieldbackground="white", bordercolor=self.LINE)
        s.configure("TCombobox", padding=6, fieldbackground="white", bordercolor=self.LINE)
        s.configure("Horizontal.TProgressbar", background=self.PRIMARY,
                    troughcolor="#eaf0ec", borderwidth=0, lightcolor=self.PRIMARY,
                    darkcolor=self.PRIMARY)

    # ---------- แท็บ OPD ----------
    def _build_opd(self, root):
        title = ttk.Frame(root, style="Page.TFrame")
        title.pack(fill="x", pady=(4, 14))
        title_text = ttk.Frame(title, style="Page.TFrame")
        title_text.pack(side="left")
        ttk.Label(title_text, text="ส่งข้อมูลผู้ป่วยนอก", style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(title_text, text="ค้นหา ตรวจสอบ และส่งข้อมูลการรับบริการไปยัง Financial Data Hub",
                  style="PageSub.TLabel").pack(anchor="w", pady=(2, 0))
        self.lbl_count = ttk.Label(title, text="พร้อมค้นหารายการ", style="PageSub.TLabel")
        self.lbl_count.pack(side="right", pady=(18, 0))

        self.opd_search_progress = ttk.Progressbar(root, mode="indeterminate")
        search_card = tk.Frame(root, bg=self.CARD, highlightbackground=self.LINE,
                               highlightthickness=1, padx=18, pady=14)
        self.opd_search_card = search_card
        search_card.pack(fill="x")
        search_top = tk.Frame(search_card, bg=self.CARD)
        search_top.pack(fill="x")
        tk.Label(search_top, text="ช่วงวันที่รับบริการ", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 10, "bold")).pack(side="left", padx=(0, 10))
        self.e_from = ThaiDatePicker(search_top)
        self.e_from.pack(side="left")
        tk.Label(search_top, text="ถึง", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 10)).pack(side="left", padx=8)
        self.e_to = ThaiDatePicker(search_top)
        self.e_to.pack(side="left")
        self.btn_search = ttk.Button(search_top, text="ค้นหารายการ", style="Accent.TButton",
                                     command=self.search)
        self.btn_search.pack(side="left", padx=(14, 0))
        # Keep the primary action next to search controls so it remains visible
        # even when the visit table fills the available vertical space.
        self.btn_send = ttk.Button(search_top, text="ส่งรายการที่เลือก  →",
                                   style="Accent.TButton", command=self.send)
        self.btn_send.pack(side="left", padx=(10, 0))
        self.select_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search_top, text="เลือกรายการทั้งหมดที่พบ", variable=self.select_all_var,
                        command=self.toggle_select_all).pack(side="left", padx=(12, 0))

        self.filter_var = tk.StringVar(value="ทั้งหมด")
        cb = ttk.Combobox(search_top, textvariable=self.filter_var, width=14, state="readonly",
                          values=("ทั้งหมด", "ส่งแล้ว", "ยังไม่ส่ง"))
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())
        tk.Label(search_top, text="สถานะ", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9)).pack(side="right", padx=(0, 8))

        divider = tk.Frame(search_card, bg=self.LINE, height=1)
        divider.pack(fill="x", pady=(13, 10))
        top2 = tk.Frame(search_card, bg=self.CARD)
        top2.pack(fill="x")
        tk.Label(top2, text="ตัวกรองความพร้อมข้อมูล", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9, "bold")).pack(side="left", padx=(0, 8))
        self.f_an = tk.BooleanVar(value=True)
        self.f_low = tk.BooleanVar(value=True)
        self.f_dx = tk.BooleanVar(value=True)
        ttk.Checkbutton(top2, text="ตัดรายที่มี AN", variable=self.f_an).pack(side="left", padx=7)
        ttk.Checkbutton(top2, text="ตัดยอด 0 / 50 บาท", variable=self.f_low).pack(side="left", padx=7)
        ttk.Checkbutton(top2, text="ต้องมี PDX ที่พร้อมส่ง", variable=self.f_dx).pack(side="left", padx=7)
        tk.Label(top2, text="ใช้เมื่อค้นหาครั้งถัดไป", bg=self.CARD, fg="#8da0b2",
                 font=(self.FONT, 9)).pack(side="right")

        stats = tk.Frame(root, bg=self.BG)
        stats.pack(fill="x", pady=12)
        self.stat_total = self._metric(stats, "รายการที่พบ", "0", "ราย", self.NAVY)
        self.stat_sent = self._metric(stats, "ส่งสำเร็จ", "0", "ราย", self.OKC)
        self.stat_selected = self._metric(stats, "กำลังเลือก", "0", "ราย", self.PRIMARY)
        self.stat_amount = self._metric(stats, "มูลค่ารวม", "0.00", "บาท", self.NAVY)

        self.lbl_send_progress = ttk.Label(root, text="ยังไม่ได้เริ่มส่ง", style="PageSub.TLabel")
        self.lbl_send_progress.pack(fill="x", pady=(0, 4))
        self.send_progress = ttk.Progressbar(root, mode="determinate", maximum=1)
        self.send_progress.pack(fill="x", pady=(0, 10))

        table_card = tk.Frame(root, bg=self.CARD, highlightbackground=self.LINE,
                              highlightthickness=1)
        table_card.pack(fill="both", expand=True)
        table_head = tk.Frame(table_card, bg=self.CARD, padx=16, pady=11)
        table_head.pack(fill="x")
        tk.Label(table_head, text="รายการผู้รับบริการ", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 11, "bold")).pack(side="left")
        tk.Label(table_head, text="คลิกช่องเลือก · ดับเบิลคลิกเพื่อดูรายละเอียด",
                 bg=self.CARD, fg=self.MUTED, font=(self.FONT, 9)).pack(side="left", padx=12)
        self.lbl_page = tk.Label(table_head, text="ยังไม่มีข้อมูล", bg=self.CARD, fg=self.MUTED,
                                 font=(self.FONT, 9))
        self.lbl_page.pack(side="right")

        mid = ttk.Frame(table_card, style="Card.TFrame")
        mid.pack(fill="both", expand=True, padx=1)
        cols = ("chk", "date", "time", "hn", "an", "name", "total", "status", "fdh")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="none")
        for c, t, w, anc in (("chk", "เลือก", 55, "center"), ("date", "วันที่รับบริการ", 105, "center"),
                             ("time", "เวลา", 62, "center"), ("hn", "HN", 86, "center"),
                             ("an", "AN", 82, "center"),
                             ("name", "ชื่อผู้รับบริการ", 230, "w"), ("total", "ยอด (บาท)", 100, "e"),
                             ("status", "สถานะการส่ง", 130, "w"),
                             ("fdh", "ผลตรวจ FDH", 135, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=anc)
        self.tree.heading("total", command=lambda: self.sort_by("total", numeric=True))
        self.tree.heading("status", command=lambda: self.sort_by("status"))
        self.tree.tag_configure("ok", foreground=self.OKC)
        self.tree.tag_configure("fail", foreground=self.FAILC)
        self.tree.tag_configure("muted", foreground="#8294a6")
        self.tree.tag_configure("evenrow", background=self.CARD)
        self.tree.tag_configure("oddrow", background=self.STRIPE)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-1>", self.show_detail)

        nav = tk.Frame(table_card, bg=self.CARD, padx=14, pady=9)
        nav.pack(side="bottom", fill="x", before=mid)
        self.btn_prev = ttk.Button(nav, text="‹  ก่อนหน้า", command=lambda: self.go_page(-1))
        self.btn_prev.pack(side="left")
        self.btn_next = ttk.Button(nav, text="ถัดไป  ›", command=lambda: self.go_page(1))
        self.btn_next.pack(side="left", padx=4)

        bot = tk.Frame(root, bg=self.CARD, highlightbackground=self.LINE,
                       highlightthickness=1, padx=18, pady=12)
        bot.pack(side="bottom", fill="x", pady=(12, 0), before=table_card)
        self.lbl_status = tk.Label(bot, text="เลือกช่วงวันที่ แล้วค้นหารายการเพื่อเริ่มต้น",
                                   bg=self.CARD, fg=self.MUTED, font=(self.FONT, 10), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        ttk.Button(bot, text="เลือกทั้งหน้านี้", command=self.check_page).pack(side="left", padx=4)
        ttk.Button(bot, text="ล้างที่เลือก", command=self.clear_checks).pack(side="left", padx=4)
        self.btn_check = ttk.Button(bot, text="ตรวจสถานะ FDH", command=self.check)
        self.btn_check.pack(side="left", padx=(12, 4))
        ttk.Button(bot, text="ประวัติ", command=self.show_history).pack(side="left", padx=4)

    def _metric(self, master, label, value, suffix, color):
        card = tk.Frame(master, bg=self.CARD, highlightbackground=self.LINE,
                        highlightthickness=1, padx=16, pady=10)
        card.pack(side="left", fill="x", expand=True, padx=(0, 8))
        body = tk.Frame(card, bg=self.CARD)
        body.pack(side="left", fill="x", expand=True)
        tk.Label(body, text=label, bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9)).pack(anchor="w")
        row = tk.Frame(body, bg=self.CARD)
        row.pack(anchor="w")
        number = tk.Label(row, text=value, bg=self.CARD, fg=color,
                          font=(self.FONT, 17, "bold"))
        number.pack(side="left")
        tk.Label(row, text="  " + suffix, bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9)).pack(side="left", pady=(6, 0))
        return number

    # ---------- แท็บ IPD (วางแผน — ยังไม่ส่ง) ----------
    def _build_ipd(self, root):
        title = ttk.Frame(root, style="Page.TFrame")
        title.pack(fill="x", pady=(4, 14))
        title_text = ttk.Frame(title, style="Page.TFrame")
        title_text.pack(side="left")
        ttk.Label(title_text, text="วางแผนข้อมูลผู้ป่วยใน", style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(title_text, text="ตรวจรายการผู้ป่วย UCS ที่จำหน่ายแล้ว เพื่อเตรียมความพร้อมสำหรับ IPD",
                  style="PageSub.TLabel").pack(anchor="w", pady=(2, 0))
        self.ipd_count = ttk.Label(title, text="พร้อมค้นหารายการ", style="PageSub.TLabel")
        self.ipd_count.pack(side="right", pady=(18, 0))

        self.ipd_search_progress = ttk.Progressbar(root, mode="indeterminate")
        search_card = tk.Frame(root, bg=self.CARD, highlightbackground=self.LINE,
                               highlightthickness=1, padx=18, pady=14)
        self.ipd_search_card = search_card
        search_card.pack(fill="x")
        top = tk.Frame(search_card, bg=self.CARD)
        top.pack(fill="x")
        tk.Label(top, text="ช่วงวันที่จำหน่าย", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 10, "bold")).pack(side="left", padx=(0, 10))
        self.ipd_from = ThaiDatePicker(top)
        self.ipd_from.pack(side="left")
        tk.Label(top, text="ถึง", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 10)).pack(side="left", padx=8)
        self.ipd_to = ThaiDatePicker(top)
        self.ipd_to.pack(side="left")
        self.btn_ipd_search = ttk.Button(top, text="ค้นหารายการ", style="Accent.TButton",
                                         command=self.ipd_search)
        self.btn_ipd_search.pack(side="left", padx=(14, 0))

        banner = tk.Frame(root, bg="#fff8e6", highlightbackground="#f4d58d",
                          highlightthickness=1, padx=14, pady=10)
        banner.pack(fill="x", pady=12)
        tk.Label(banner, text="i", bg="#d69e2e", fg="white", width=2,
                 font=(self.FONT, 10, "bold")).pack(side="left")
        tk.Label(banner, text="  หน้านี้เป็นมุมมองสำหรับวางแผนเท่านั้น ยังไม่รองรับการส่งข้อมูล IPD ไปยัง FDH",
                 bg="#fff8e6", fg="#8b641c", font=(self.FONT, 10), anchor="w").pack(side="left")

        table_card = tk.Frame(root, bg=self.CARD, highlightbackground=self.LINE,
                              highlightthickness=1)
        table_card.pack(fill="both", expand=True)
        table_head = tk.Frame(table_card, bg=self.CARD, padx=16, pady=12)
        table_head.pack(fill="x")
        tk.Label(table_head, text="ผู้ป่วยในที่จำหน่ายแล้ว", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 11, "bold")).pack(side="left")
        mid = ttk.Frame(table_card, style="Card.TFrame")
        mid.pack(fill="both", expand=True, padx=1, pady=(0, 1))
        cols = ("dchdate", "an", "hn", "name", "ward", "los", "total")
        self.ipd_tree = ttk.Treeview(mid, columns=cols, show="headings")
        for c, t, w, anc in (("dchdate", "วันที่จำหน่าย", 115, "center"), ("an", "AN", 100, "center"),
                             ("hn", "HN", 86, "center"), ("name", "ชื่อ-สกุล", 230, "w"),
                             ("ward", "หอผู้ป่วย", 240, "w"), ("los", "จำนวนวันนอน", 95, "center"),
                             ("total", "ยอด (บาท)", 110, "e")):
            self.ipd_tree.heading(c, text=t)
            self.ipd_tree.column(c, width=w, anchor=anc)
        self.ipd_tree.tag_configure("evenrow", background=self.CARD)
        self.ipd_tree.tag_configure("oddrow", background=self.STRIPE)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.ipd_tree.yview)
        self.ipd_tree.configure(yscrollcommand=sb.set)
        self.ipd_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")

    def ipd_search(self):
        if self._api_busy():
            return
        try:
            date_from, date_to = self.ipd_from.get().strip(), self.ipd_to.get().strip()
        except Exception as e:
            messagebox.showerror("ค้นหาไม่สำเร็จ", str(e))
            return
        self._start_search("ipd", lambda: send_menu.list_discharged(date_from, date_to))

    def _apply_ipd_search(self, rows):
        self.ipd_tree.delete(*self.ipd_tree.get_children())
        total = 0.0
        for i, r in enumerate(rows):
            name = f"{r['pname']}{r['fname']} {r['lname']}"
            tot = float(r["tot"] or 0)
            total += tot
            self.ipd_tree.insert("", "end", tags=("evenrow" if i % 2 == 0 else "oddrow",),
                                 values=(r["dchdate"], r["an"], r["hn"], name, r["wardname"] or "",
                                         r["los"], f"{tot:.2f}"))
        self.ipd_count.config(text=f"จำหน่าย {len(rows):,} ราย · รวม {total:,.2f} บาท")

    # ---------- ช่องติ๊ก ----------
    def _set_chk(self, idx, on):
        (self.checked.add if on else self.checked.discard)(str(idx))
        if self.tree.exists(str(idx)):
            self.tree.set(str(idx), "chk", "☑" if on else "☐")
        self._sync_select_all()
        self._update_metrics()

    def on_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell" \
                and self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            if iid:
                self._set_chk(int(iid), iid not in self.checked)

    def check_page(self):
        """ติ๊กเฉพาะแถวในหน้าปัจจุบัน (สูงสุด 200)"""
        start = self.page * self.PAGE
        for idx in self.view[start:start + self.PAGE]:
            self.checked.add(str(idx))
        self._sync_select_all()
        self._render_page()

    def toggle_select_all(self):
        """เลือกหรือล้างทุกผลลัพธ์จากการค้นหา รวมรายการนอกหน้าปัจจุบัน."""
        if self.select_all_var.get():
            self.checked = {str(idx) for idx in range(len(self.rows))}
        else:
            self.checked.clear()
        self._render_page()

    def _sync_select_all(self):
        """ทำให้ checkbox สะท้อนว่าเลือกผลลัพธ์จากการค้นหาครบทุกแถวหรือไม่."""
        if hasattr(self, "select_all_var"):
            self.select_all_var.set(bool(self.rows) and len(self.checked) == len(self.rows))

    def clear_checks(self):
        """ล้างติ๊กทั้งหมด (ทุกหน้า)"""
        self.checked.clear()
        self._sync_select_all()
        self._render_page()

    def _update_metrics(self):
        """อัปเดตภาพรวมให้สะท้อนรายการที่กรองและรายการที่ผู้ใช้เลือก"""
        if not hasattr(self, "stat_total"):
            return
        visible = self.view
        sent = sum(1 for i in visible if self.rowstatus.get(i, ("", ""))[1] == "ok")
        amount = sum(float(self.rows[i]["tot"] or 0) for i in visible)
        self.stat_total.config(text=f"{len(visible):,}")
        self.stat_sent.config(text=f"{sent:,}")
        self.stat_selected.config(text=f"{len(self.checked):,}")
        self.stat_amount.config(text=f"{amount:,.2f}")

    # ---------- ค้นหา ----------
    def search(self):
        if self._api_busy():
            return
        try:
            date_from, date_to = self.e_from.get().strip(), self.e_to.get().strip()
            filters = dict(exclude_an=self.f_an.get(), exclude_low=self.f_low.get(),
                           require_dx=self.f_dx.get())
        except Exception as e:
            messagebox.showerror("ค้นหาไม่สำเร็จ", str(e))
            return

        def query_visits():
            rows = send_menu.list_visits(date_from, date_to, **filters)
            return rows, history.sent_vns(environment)

        environment = self.api_config.environment
        self._start_search("opd", query_visits)

    def _start_search(self, kind, query):
        """Run DB work off the UI thread; process results only in Tk's event loop."""
        self.searching = True
        count = self.lbl_count if kind == "opd" else self.ipd_count
        progress = self.opd_search_progress if kind == "opd" else self.ipd_search_progress
        card = self.opd_search_card if kind == "opd" else self.ipd_search_card
        count.config(text="กำลังค้นหารายการ…")
        if kind == "opd":
            self.lbl_status.config(text="กำลังประมวลผล กรุณารอสักครู่…")
        buttons = (self.btn_search, self.btn_ipd_search, self.btn_send, self.btn_check)
        previous_states = [(button, button.cget("state")) for button in buttons]
        for button in buttons:
            button.config(state="disabled")
        progress.pack(fill="x", pady=(0, 10), before=card)
        progress.start(12)
        results = queue.Queue()

        def worker():
            try:
                results.put((True, query()))
            except Exception as error:
                results.put((False, str(error)))

        def poll():
            try:
                success, result = results.get_nowait()
            except queue.Empty:
                self.root.after(50, poll)
                return
            try:
                if not success:
                    raise RuntimeError(result)
                if kind == "opd":
                    self._apply_opd_search(*result)
                else:
                    self._apply_ipd_search(result)
            except Exception as error:
                count.config(text="ค้นหาไม่สำเร็จ")
                if kind == "opd":
                    self.lbl_status.config(text="ค้นหาไม่สำเร็จ กรุณาตรวจสอบการเชื่อมต่อแล้วลองใหม่")
                messagebox.showerror("ค้นหาไม่สำเร็จ", str(error), parent=self.root)
            finally:
                progress.stop()
                progress.pack_forget()
                self.searching = False
                for button, state in previous_states:
                    button.config(state=state)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, poll)

    def _apply_opd_search(self, rows, sent):
        self.rows = rows
        self.checked.clear()
        self._sync_select_all()
        self.filter_var.set("ทั้งหมด")
        self.sort_col = None
        self.rowstatus = {i: (("✓ ส่งแล้ว", "ok") if str(r["vn"]) in sent else ("ยังไม่ส่ง", "muted"))
                          for i, r in enumerate(self.rows)}
        self.fdhstatus = {i: "— ยังไม่ตรวจ" for i in range(len(self.rows))}  # ยืนยันจากเซิร์ฟเวอร์
        n_sent = sum(1 for v in self.rowstatus.values() if v[1] == "ok")
        self.lbl_count.config(text=f"พบ {len(self.rows):,} ราย · ส่งแล้ว {n_sent:,} ราย")
        self.lbl_status.config(text="เลือกรายการที่พร้อมส่ง หรือดับเบิลคลิกเพื่อตรวจรายละเอียด")
        self.page = 0
        self._build_view()
        self._render_page()

    # ---------- กรอง / เรียง / แบ่งหน้า ----------
    def _build_view(self):
        want = self.filter_var.get()

        def keep(idx):
            is_sent = self.rowstatus[idx][1] == "ok"
            return want == "ทั้งหมด" or (want == "ส่งแล้ว" and is_sent) \
                or (want == "ยังไม่ส่ง" and not is_sent)
        self.view = [i for i in range(len(self.rows)) if keep(i)]
        if self.sort_col == "total":
            self.view.sort(key=lambda i: float(self.rows[i]["tot"] or 0), reverse=self.sort_desc)
        elif self.sort_col == "status":
            self.view.sort(key=lambda i: self.rowstatus[i][0], reverse=self.sort_desc)

    def _render_page(self):
        self.tree.delete(*self.tree.get_children())
        total = len(self.view)
        pages = max(1, (total + self.PAGE - 1) // self.PAGE)
        self.page = max(0, min(self.page, pages - 1))
        start = self.page * self.PAGE
        end = min(start + self.PAGE, total)
        for pos, idx in enumerate(self.view[start:end]):
            r = self.rows[idx]
            name = f"{r['pname']}{r['fname']} {r['lname']}"
            text, tag = self.rowstatus[idx]
            stripe = "oddrow" if pos % 2 else "evenrow"
            self.tree.insert("", "end", iid=str(idx), tags=(stripe,) + ((tag,) if tag else ()),
                             values=("☑" if str(idx) in self.checked else "☐",
                                     r["vstdate"], r["vsttime"], r["hn"], r["an"] or "", name,
                                     f"{float(r['tot'] or 0):.2f}", text, self.fdhstatus.get(idx, "—")))
        self.lbl_page.config(text=f"หน้า {self.page + 1}/{pages}   "
                                  f"(แถว {start + 1 if total else 0}-{end} จาก {total})")
        self.btn_prev.config(state="normal" if self.page > 0 else "disabled")
        self.btn_next.config(state="normal" if self.page < pages - 1 else "disabled")
        self._update_metrics()

    def go_page(self, step):
        self.page += step
        self._render_page()

    def _refresh_row(self, idx):
        """อัปเดตแถวเดียวบนจอ (ถ้าอยู่หน้าปัจจุบัน)"""
        iid = str(idx)
        if not self.tree.exists(iid):
            return
        text, tag = self.rowstatus[idx]
        self.tree.set(iid, "status", text)
        self.tree.set(iid, "fdh", self.fdhstatus.get(idx, "—"))
        self.tree.set(iid, "chk", "☑" if iid in self.checked else "☐")
        stripe = "oddrow" if self.tree.index(iid) % 2 else "evenrow"
        self.tree.item(iid, tags=(stripe,) + ((tag,) if tag else ()))

    def sort_by(self, col, numeric=False):
        self.sort_desc = not self.sort_desc if self.sort_col == col else True
        self.sort_col = col
        self._build_view()
        self.page = 0
        self._render_page()
        for c, base in (("total", "ยอด(บาท)"), ("status", "สถานะ")):
            self.tree.heading(c, text=base + ((" ▼" if self.sort_desc else " ▲") if c == col else ""))

    def apply_filter(self):
        self.page = 0
        self._build_view()
        self._render_page()

    # ---------- ส่ง ----------
    def send(self):
        if self._api_busy():
            return
        sel = sorted(int(i) for i in self.checked)
        if not sel:
            messagebox.showinfo("ยังไม่ได้เลือก", "ติ๊ก ☐ หน้าคนไข้อย่างน้อย 1 รายก่อน")
            return
        config = self.api_config
        if not messagebox.askyesno("ยืนยันส่ง", f"ส่งข้อมูล {len(sel)} ราย เข้า FDH ({config.environment})?\n{config.base_url}"):
            return
        self.btn_send.config(state="disabled")
        self.sending = True
        self._send_progress(len(sel), 0, 0, "กำลังขอ token...")
        threading.Thread(target=self._send_worker, args=(sel, config), daemon=True).start()

    def _send_progress(self, total, done, ok, phase):
        """Called on the UI thread; count completed attempts, including failures."""
        failed = done - ok
        percent = done * 100 / total if total else 0
        self.send_progress.config(maximum=max(total, 1), value=done)
        self.lbl_send_progress.config(text=(
            f"{phase} · ดำเนินการแล้ว {done}/{total} ({percent:.0f}%)"
            f" · สำเร็จ {ok} · ไม่สำเร็จ {failed} · เหลือ {total - done}"))
        self._update_metrics()

    def _finish_sending(self):
        self.sending = False
        self.btn_send.config(state="normal")

    def _status(self, idx, text, tag=""):
        def apply():
            self.rowstatus[idx] = (text, tag)
            self._refresh_row(idx)
            self._update_metrics()
        self.root.after(0, apply)

    def _send_worker(self, sel, config):
        done, ok = 0, 0
        try:
            self.root.after(0, lambda: self.lbl_status.config(text="กำลังขอ token..."))
            token = import_fdh.get_access_token(config=config)
            batch = datetime.datetime.now().isoformat(timespec="microseconds")  # id ก้อนนี้
            for n, idx in enumerate(sel, 1):
                r = self.rows[idx]
                name = f"{r['pname']}{r['fname']} {r['lname']}"
                self._status(idx, "⏳ กำลังส่ง...")
                self.root.after(0, lambda n=n: self.lbl_status.config(
                    text=f"กำลังส่ง {n}/{len(sel)}..."))
                self.root.after(0, lambda n=n, done=done, ok=ok: self._send_progress(
                    len(sel), done, ok, f"กำลังส่งรายที่ {n}/{len(sel)}"))
                txid = ""
                try:
                    payload, _ = build_payload.make_payload(r["vn"])
                    txid = payload["transactionId"]
                    st, txt = import_fdh.send(payload, token, config=config)
                    good = st == 200 and '"success"' in txt
                except Exception as e:
                    good, st, txt = False, "-", str(e)[:80]
                ok += good
                done += 1
                self._status(idx, ("✓ ส่งแล้ว" if good else f"❌ {st}: {txt[:40]}"),
                             "ok" if good else "fail")
                self.root.after(0, lambda done=done, ok=ok: self._send_progress(
                    len(sel), done, ok, "กำลังส่ง" if done < len(sel) else "ส่งครบแล้ว"))
                history.log({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                             "batch": batch, "batch_size": len(sel),
                             "environment": config.environment,
                             "transactionId": txid, "vn": r["vn"], "hn": r["hn"], "name": name,
                             "http": st, "status": "submitted" if good else "failed"})
            n, fail = len(sel), len(sel) - ok
            self.root.after(0, lambda: self.lbl_status.config(text=f"เสร็จ: สำเร็จ {ok}/{n} ราย"))
            self.root.after(0, lambda: (
                messagebox.showinfo("ส่งครบแล้ว", f"ส่งครบ {n} ราย\nสำเร็จ {ok} ราย ✅")
                if fail == 0 else
                messagebox.showwarning("ส่งเสร็จ (มีไม่สำเร็จ)",
                                       f"ส่งครบ {n} ราย\nสำเร็จ {ok} ราย\nไม่สำเร็จ {fail} ราย ❌")))
        except Exception as e:
            error = str(e)[:120]
            self.root.after(0, lambda done=done, ok=ok: self._send_progress(
                len(sel), done, ok, "หยุดส่งก่อนครบ"))
            self.root.after(0, lambda error=error: self.lbl_status.config(text=f"ส่งหยุดลง: {error}"))
        finally:
            self.root.after(0, self._finish_sending)

    # ---------- ดับเบิลคลิก: รายละเอียดที่ส่ง FDH ----------
    def show_detail(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        r = self.rows[int(iid)]
        self.lbl_status.config(text="กำลังโหลดรายละเอียด...")
        self.root.update_idletasks()
        try:
            payload, _ = build_payload.make_payload(r["vn"])
        except Exception as e:
            messagebox.showerror("โหลดรายละเอียดไม่ได้", str(e))
            return
        finally:
            self.lbl_status.config(text="")
        self._detail_window(payload)

    def _detail_window(self, payload):
        v = payload["data"][0]
        p, opd, b = v["patient"], v["encounter"]["opd"], v["benefits"]
        cl, ad = b["claim"], p.get("address", {})
        win = tk.Toplevel(self.root)
        win.title(f"รายละเอียดที่ส่ง FDH — {p['name']['line']}")
        win.geometry("920x680")
        win.minsize(760, 560)
        win.configure(bg=self.BG)
        win.transient(self.root)

        head = (f"{p['name']['line']}    HN {p['hn']}    CID {p.get('id', '-')}\n"
                f"VN {opd['seq']}    {opd['dateTime']}\n"
                f"transactionId {payload['transactionId']}    hcode {payload['hcode']}")
        modal_head = tk.Frame(win, bg=self.CARD, padx=20, pady=15)
        modal_head.pack(side="top", fill="x")
        tk.Label(modal_head, text="รายละเอียดข้อมูลก่อนส่ง", bg=self.CARD, fg=self.MUTED,
                 font=(self.FONT, 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(modal_head, text=head, bg=self.CARD, fg=self.TEXT, justify="left", anchor="w",
                 font=(self.FONT, 11), pady=5).pack(fill="x")
        tk.Label(win, text=f"ยอดรวมทั้งสิ้น   {b['cht'][0]['total']:,.2f}  บาท",
                 bg=self.CARD, fg=self.PRIMARY, font=(self.FONT, 14, "bold"),
                 anchor="e", padx=18, pady=12).pack(
                     side="bottom", fill="x")

        mid = ttk.Frame(win, style="Card.TFrame")
        mid.pack(side="top", fill="both", expand=True, padx=16, pady=16)
        t = ttk.Treeview(mid, columns=("code", "qty", "unit", "amt"), show="tree headings")
        t.heading("#0", text="รายการ")
        t.column("#0", width=360)
        for c, h, w in (("code", "รหัสที่ส่ง", 170), ("qty", "จำนวน", 70),
                        ("unit", "ราคา/หน่วย", 90), ("amt", "รวม", 90)):
            t.heading(c, text=h)
            t.column(c, width=w, anchor="w" if c == "code" else "e")
        sb = ttk.Scrollbar(mid, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        sb.pack(side="left", fill="y", pady=6)

        def row(parent, label, code):
            t.insert(parent, "end", text="   " + label, values=(code or "-", "", "", ""))

        # รหัสคนไข้ + สิทธิ ที่ส่งไป
        gp = t.insert("", "end", text="รหัสคนไข้ & สิทธิ", open=True)
        row(gp, "เพศ (gender)", p.get("gender"))
        row(gp, "idType", p.get("idType"))
        row(gp, "สัญชาติ (nationality)", p.get("nationality"))
        row(gp, "สถานภาพ (maritalStatus)", p.get("maritalStatus"))
        row(gp, "อาชีพ (occupation)", p.get("occupation"))
        row(gp, "จังหวัด/อำเภอ/ตำบล", f"{ad.get('state','-')}/{ad.get('city','-')}/{ad.get('district','-')}")
        row(gp, "คลินิก (clinic)", opd.get("clinic"))
        row(gp, "สิทธิ (inscl)", cl.get("inscl"))
        row(gp, "hmain / hsub", f"{cl.get('hmain','-')} / {cl.get('hsub','-')}")
        row(gp, "uuc", cl.get("uuc"))
        row(gp, "permitNo", cl.get("permitNo"))

        dx = v["encounter"]["diagnosisIcd10"]
        gp = t.insert("", "end", text=f"การวินิจฉัย ({len(dx)} รายการ)", open=True)
        for d in dx:
            t.insert(gp, "end", text=f"   diagType {d['diagType']}  หมอ {d.get('professionId', '')}",
                     values=(d["icd10"], "", "", ""))

        cat = {"DRUG": "ยา", "SERVICE": "บริการ", "IMAGING": "รังสี", "LAB": "แล็บ",
               "PROC": "หัตถการ", "SUPPLY": "อุปกรณ์"}
        for c in b["cha"]:
            it0 = c["items"][0]
            gp = t.insert("", "end", open=True, values=("", "", "", f"{c['amount']:.2f}"),
                          text=f"หมวด {c['chrgItem']} {cat.get(it0.get('itemCat'), '')} "
                               f"({c['itemCount']} รายการ)")
            for it in c["items"]:
                code = f"{it.get('localCode', '')} ({it.get('codeSys', '')})"
                t.insert(gp, "end", text=f"   {it['descript']}",
                         values=(code, f"{it['qty']:.0f}", f"{it['unitPrice']:.2f}",
                                 f"{it['chargeAmt']:.2f}"))

    # ---------- ประวัติการส่ง (รายก้อน) ----------
    def show_history(self):
        environment = self.api_config.environment
        entries = history.load(environment)
        # จัดกลุ่มเป็นก้อนตาม batch (ของเก่าที่ไม่มี batch ใช้ ts เป็นก้อนเดี่ยว)
        batches = {}
        for i, e in enumerate(entries):
            batches.setdefault(e.get("batch") or f"_{i}", []).append(e)
        order = list(batches)   # เรียงตามการเกิดจริง

        win = tk.Toplevel(self.root)
        win.title(f"ประวัติการส่ง FDH · {environment}")
        win.geometry("960x600")
        win.minsize(780, 500)
        win.configure(bg=self.BG)
        win.transient(self.root)
        top = tk.Frame(win, bg=self.CARD, padx=18, pady=14)
        top.pack(fill="x")
        heading = tk.Frame(top, bg=self.CARD)
        heading.pack(side="left")
        tk.Label(heading, text=f"ประวัติการส่งข้อมูล · {environment}", bg=self.CARD, fg=self.NAVY,
                 font=(self.FONT, 15, "bold"), anchor="w").pack(fill="x")
        tk.Label(heading, text=f"ทั้งหมด {len(order):,} ชุด · {len(entries):,} ราย  "
                               "ดับเบิลคลิกชุดข้อมูลเพื่อดูรายชื่อ",
                 bg=self.CARD, fg=self.MUTED, font=(self.FONT, 9), anchor="w").pack(fill="x")

        mid = ttk.Frame(win, style="Card.TFrame")
        mid.pack(fill="both", expand=True, padx=16, pady=16)
        t = ttk.Treeview(mid, columns=("info", "http", "status"), show="tree headings")
        t.heading("#0", text="ก้อน / รายชื่อ")
        t.column("#0", width=420)
        for c, h, w in (("info", "จำนวน / transaction_id", 280), ("http", "http", 60),
                        ("status", "สถานะ", 110)):
            t.heading(c, text=h)
            t.column(c, width=w)
        t.tag_configure("ok", foreground="green")
        t.tag_configure("fail", foreground="red")
        sb = ttk.Scrollbar(mid, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        sb.pack(side="left", fill="y", pady=6)

        for bi in range(len(order) - 1, -1, -1):   # ก้อนใหม่สุดอยู่บน
            grp = batches[order[bi]]
            ok = sum(1 for e in grp if e.get("status") == "submitted")
            ts = grp[0].get("ts", "")
            bp = t.insert("", "end", iid=f"b{bi}", open=False,
                          text=f"ก้อนที่ {bi + 1}   {ts}",
                          values=(f"{len(grp)} คน  (สำเร็จ {ok}/{len(grp)})", "",
                                  "✅" if ok == len(grp) else f"{ok}/{len(grp)}"),
                          tags=("ok" if ok == len(grp) else "fail",))
            for e in grp:
                ei = entries.index(e)
                t.insert(bp, "end", iid=f"e{ei}", text=f"   {e.get('name', '')}",
                         values=(e.get("transactionId", ""), e.get("http", ""),
                                 e.get("status", "")),
                         tags=("ok" if e.get("status") == "submitted" else "fail",))

        def resend():
            if self._api_busy():
                return
            s = t.selection()
            if not s or not s[0].startswith("e"):
                messagebox.showinfo("ส่งซ้ำ", "เลือก 'รายชื่อคน' (กางก้อนออกก่อน) ที่จะส่งซ้ำ")
                return
            e = entries[int(s[0][1:])]
            config = self.api_config
            if e.get("environment", "UAT") != config.environment:
                messagebox.showinfo("โหมด API เปลี่ยนแล้ว", "เปิดประวัติใหม่สำหรับโหมด API ปัจจุบัน", parent=win)
                return
            if messagebox.askyesno("ส่งซ้ำ", f"ส่งซ้ำ {e.get('name')} (vn {e.get('vn')})\n"
                                           f"FDH {config.environment} · {config.base_url} ?"):
                self.resending = True
                threading.Thread(target=self._resend_worker, args=(e, config), daemon=True).start()
        ttk.Button(top, text="ส่งซ้ำรายที่เลือก", command=resend).pack(side="right")

    def _resend_worker(self, e, config):
        txid = ""
        try:
            token = import_fdh.get_access_token(config=config)
            payload, _ = build_payload.make_payload(e["vn"])
            txid = payload["transactionId"]
            st, txt = import_fdh.send(payload, token, config=config)
            good = st == 200 and '"success"' in txt
        except Exception as ex:
            good, st, txt = False, "-", str(ex)[:80]
        now = datetime.datetime.now().isoformat(timespec="microseconds")
        try:
            history.log({"ts": now[:19], "batch": now, "batch_size": 1,
                         "environment": config.environment,
                         "transactionId": txid, "vn": e["vn"], "hn": e.get("hn"), "name": e.get("name"),
                         "http": st, "status": "submitted" if good else "failed"})
        finally:
            self.root.after(0, lambda: setattr(self, "resending", False))
        self.root.after(0, lambda: messagebox.showinfo(
            "ผลส่งซ้ำ", f"FDH {config.environment}\n{e.get('name')}\nHTTP {st}: {txt}\n\n(เปิดประวัติใหม่เพื่อดูรายการล่าสุด)"))

    # ---------- ตรวจสถานะจาก FDH ----------
    def check(self):
        if self._api_busy():
            return
        # มีติ๊กไว้ -> ตรวจเฉพาะที่ติ๊ก, ไม่งั้นตรวจทุกแถวที่กรองไว้
        sel = sorted(int(i) for i in self.checked) or list(self.view)
        self._run_check(sel)

    def _run_check(self, sel):
        if self.checking:
            return
        self.checking = True
        self.btn_check.config(state="disabled")
        threading.Thread(target=self._check_worker, args=(list(sel), self.api_config), daemon=True).start()

    def _check_worker(self, sel, config):
        try:
            self.root.after(0, lambda: self.lbl_status.config(text="กำลังถาม FDH (อาจช้าถ้าข้อมูลเยอะ)..."))
            token = import_fdh.get_access_token(config=config)
            sent = check_fdh.sent_seqs(token, config=config)   # set ของ vn ที่ FDH เก็บแล้ว (ยิงครั้งเดียว)
            if sent is None:
                self.root.after(0, lambda: self.lbl_status.config(text="ตรวจไม่ได้ (FDH error)"))
                return
            matched = sum(1 for idx in sel if str(self.rows[idx]["vn"]) in sent)

            def apply():   # เขียนลงคอลัมน์ FDH ทุกแถวที่ตรวจ (เจอ/ไม่เจอ) แล้ว render หน้าเดียว
                for idx in sel:
                    self.fdhstatus[idx] = ("✓ อยู่ใน FDH" if str(self.rows[idx]["vn"]) in sent
                                           else "✗ ไม่พบ")
                self._render_page()
                self.lbl_status.config(
                    text=f"ตรวจกับ FDH แล้ว — อยู่ใน FDH {matched} ราย (เซิร์ฟเวอร์มีทั้งหมด {len(sent)})")
            self.root.after(0, apply)
        except Exception as e:   # กันค้าง: ทุก error ต้องอัปเดตป้ายสถานะเสมอ
            error = str(e)[:60]
            self.root.after(0, lambda error=error: self.lbl_status.config(text=f"ตรวจไม่ได้: {error}"))
        finally:
            self.root.after(0, self._finish_checking)

    def _finish_checking(self):
        self.checking = False
        self.btn_check.config(state="normal")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
