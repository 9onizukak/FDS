@echo off
rem ดับเบิลคลิกไฟล์นี้เพื่อเปิดโปรแกรมส่ง FDH (ไม่มีหน้าต่าง console)
cd /d "%~dp0"
start "" pythonw send_gui.py
