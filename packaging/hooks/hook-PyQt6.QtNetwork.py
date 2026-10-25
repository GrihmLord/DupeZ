"""Collect Qt Network with Windows Schannel, without ambient OpenSSL probing."""

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

from native_runtime_policy import filter_qt_network_hook_binaries


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = filter_qt_network_hook_binaries(binaries)
# Deliberately omit collect_qtnetwork_files(): its OpenSSL discovery imports
# QSslSocket and searches the build machine's unrelated library directories.
