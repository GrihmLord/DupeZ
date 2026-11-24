"""Unelevated WebEngine child process for the embedded iZurvive map.

Chromium's GPU process refuses to initialize under the admin token
DupeZ needs for WinDivert, which forces software rasterization and
makes the iZurvive map unusably choppy. This subpackage splits the
WebEngine into a separate, unelevated child process launched with the
interactive shell's token and embeds its native HWND back into the Qt
window via ``QWindow.fromWinId`` + ``QWidget.createWindowContainer``.
The PID returned by process creation is retained and must match the
accepted Windows TCP peer, the child's claim, and the Windows HWND owner.
A per-launch random nonce adds session correlation but is not the
process-identity trust boundary.
The child-process path is experimental and source/development-only;
frozen builds deliberately use the in-process map fallback.

Entry points:
  * ``host`` — child process main (standalone PyQt6 app, one view).
  * ``launcher`` — parent-side IPC + spawn logic used by DayZMapGUI.
"""
