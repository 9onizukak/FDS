"""Run update I/O off the Tk thread and install only between hospital jobs."""
import json
import queue
import threading
from tkinter import messagebox, ttk

from app_version import APP_VERSION
from runtime_paths import DATA_DIR
import software_update as updater


class UpdateController:
    INTERVAL_MS = 60 * 60 * 1000

    def __init__(self, app, parent):
        import tkinter as tk
        self.app = app
        self.root = app.root
        self.events = queue.Queue()
        self.active = False
        self.pending = None
        self.closed = False
        self.timers = set()
        self.settings_path = DATA_DIR / "update-settings.json"
        enabled = True
        try:
            enabled = json.loads(self.settings_path.read_text(encoding="utf-8")).get("auto_update", True) is not False
        except (OSError, ValueError, AttributeError):
            pass
        self.automatic = tk.BooleanVar(master=self.root, value=enabled)
        self.status = tk.StringVar(master=self.root, value=f"FDH {APP_VERSION}")
        ttk.Label(parent, textvariable=self.status).pack(side="left", padx=(0, 12))
        self.button = ttk.Button(parent, text="ตรวจสอบอัปเดต", command=lambda: self.check(manual=True))
        self.button.pack(side="right")
        ttk.Checkbutton(parent, text="อัปเดตอัตโนมัติ", variable=self.automatic,
                        command=self.save_settings).pack(side="right", padx=12)
        self.root.bind("<Destroy>", self.on_destroy, add="+")
        self.schedule(250, self.poll)
        # Source checkouts do not contact GitHub during startup or tests.
        if updater.can_install():
            self.schedule(3000, self.periodic_check)

    def schedule(self, delay, callback):
        def run():
            self.timers.discard(timer)
            if not self.closed:
                callback()
        timer = self.root.after(delay, run)
        self.timers.add(timer)

    def on_destroy(self, event):
        if event.widget != self.root:
            return
        self.closed = True
        for timer in self.timers:
            self.root.after_cancel(timer)
        self.timers.clear()

    def save_settings(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"auto_update": self.automatic.get()}), encoding="utf-8")
            temporary.replace(self.settings_path)
        except OSError as error:
            messagebox.showerror("FDH Update", f"บันทึกการตั้งค่าอัปเดตไม่ได้: {error}", parent=self.root)

    def periodic_check(self):
        if self.automatic.get():
            self.check()
        self.schedule(self.INTERVAL_MS, self.periodic_check)

    def check(self, manual=False):
        if self.active:
            return
        self.active = True
        self.button.config(state="disabled")
        self.status.set(f"FDH {APP_VERSION} · กำลังตรวจสอบอัปเดต...")

        def worker():
            try:
                self.events.put(("release", updater.check_latest(), manual))
            except Exception as error:
                self.events.put(("error", str(error), manual))
        threading.Thread(target=worker, daemon=True).start()

    def reset(self):
        self.active = False
        self.button.config(state="normal")

    def handle(self, kind, value, manual):
        if kind == "error":
            self.pending = None
            self.status.set(f"FDH {APP_VERSION} · ตรวจสอบ/อัปเดตไม่สำเร็จ")
            self.reset()
            if manual:
                messagebox.showerror("FDH Update", value, parent=self.root)
        elif kind == "release":
            if value is None:
                self.status.set(f"FDH {APP_VERSION} · เป็นรุ่นล่าสุดแล้ว")
                self.reset()
                if manual:
                    messagebox.showinfo("FDH Update", "โปรแกรมเป็นรุ่นล่าสุดแล้ว", parent=self.root)
            elif not updater.can_install():
                self.status.set(f"มีรุ่นใหม่ {value.version}")
                self.reset()
                messagebox.showinfo("FDH Update", f"มีรุ่น {value.version}\n"
                                    "ติดตั้งอัตโนมัติได้เฉพาะโปรแกรม Windows ที่แพ็กแล้ว\n"
                                    + updater.RELEASES_URL, parent=self.root)
            elif not manual and not self.automatic.get():
                self.status.set(f"มีรุ่นใหม่ {value.version}")
                self.reset()
            elif manual and not messagebox.askyesno("FDH Update", f"อัปเดตเป็นรุ่น {value.version}?\n"
                    "โปรแกรมจะติดตั้งและเปิดใหม่เมื่องานปัจจุบันเสร็จ\n"
                    "การตั้งค่าและประวัติการส่งจะยังอยู่", parent=self.root):
                self.status.set(f"มีรุ่นใหม่ {value.version}")
                self.reset()
            else:
                self.status.set(f"กำลังดาวน์โหลด FDH {value.version}...")

                def worker():
                    try:
                        path = updater.download_installer(value, DATA_DIR / "updates")
                        self.events.put(("ready", path, manual))
                    except Exception as error:
                        self.events.put(("error", str(error), manual))
                threading.Thread(target=worker, daemon=True).start()
        elif kind == "ready":
            self.pending = (value, manual)
            self.status.set("ดาวน์โหลดแล้ว · รอให้งานปัจจุบันเสร็จก่อนอัปเดต")

    def install_when_idle(self):
        if self.pending is None:
            return False
        path, manual = self.pending
        if not manual and not self.automatic.get():
            self.pending = None
            self.reset()
            self.status.set(f"FDH {APP_VERSION} · ปิดอัปเดตอัตโนมัติ")
            return False
        if self.app._api_busy():
            return False
        # Keep unsaved settings open for the user to save or close first.
        window = getattr(self.app, "settings_window", None)
        if window is not None and window.winfo_exists():
            return False
        self.app.updating = True
        try:
            updater.start_installer(path, DATA_DIR / "updates")
        except Exception as error:
            self.app.updating = False
            self.handle("error", str(error), True)
            return False
        self.pending = None
        self.root.destroy()
        return True

    def poll(self):
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        if not self.install_when_idle():
            self.schedule(250, self.poll)
