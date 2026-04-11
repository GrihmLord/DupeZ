"""Unelevated WebEngine child process for the embedded iZurvive map.

Chromium's GPU process refuses to initialize under the admin token
DupeZ needs for WinDivert, which forces software rasterization and
makes the iZurvive map unusably choppy. This subpackage splits the
WebEngine into a separate, unelevated child process (launched via
Explorer COM ``ShellExecute`` so it inherits Explorer's medium
integrity token instead of our admin token) and embeds its native
HWND back into the Qt window via ``QWindow.fromWinId`` +
``QWidget.createWindowContainer``.

Entry points:
  * ``host`` — child process main (standalone PyQt6 app, one view).
  * ``launcher`` — parent-side IPC + spawn logic used by DayZMapGUI.
"""
