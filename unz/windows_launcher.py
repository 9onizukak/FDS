"""Windows executable entry point with a visible startup error."""
import tkinter as tk
from tkinter import messagebox


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        from send_gui import App
        App(root)
        root.deiconify()
        root.mainloop()
    except Exception as error:
        messagebox.showerror("FDH", f"เปิดโปรแกรมไม่สำเร็จ\n{error}", parent=root)
        root.destroy()
        raise


if __name__ == "__main__":
    main()
