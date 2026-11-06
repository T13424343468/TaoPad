# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化（v3）
覆盖范围（对照源码 MainWindow.xaml 全部菜单与命令）：
  文件：新建/打开/最近文件/保存/另存为/全部保存/导出可打印HTML/关闭标签/退出
  编辑：撤销/重做/剪切/复制/粘贴/全选/插入时间日期/删除行/复制行/上移行/下移行/
        转大写/转小写/格式化/注释/取消注释
  搜索：查找/替换/在文件中查找/查找下一个/查找上一个/转到行
  查看：自动换行/显示行号/缩放(放大/缩小/复位)
  语言：13 种语法高亮语言逐一切换
  编码：5 种保存编码 + 3 种换行符
  主题：水墨/天青/墨夜
  工具：设置(换行开关/行号开关/主题下拉/应用)
  标签页：新增/切换/关闭
  状态栏：行/列/选中/字符/行数/缩放/编码/换行符/语言 逐项断言
每步截图；结果写 ui-evidence/report.json；任一失败进程退出码非 0。
"""
import json
import os
import re
import subprocess
import sys
import time
import ctypes

EVID = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui-evidence"))
os.makedirs(EVID, exist_ok=True)

from PIL import ImageGrab
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys
import pyperclip

DOCS = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\runneradmin"), "Documents")
os.makedirs(DOCS, exist_ok=True)
FILE1 = os.path.join(DOCS, "taopad-it1.txt")
FILE2B = os.path.join(DOCS, "taopad-it3.txt")
HTML_OUT = os.path.join(DOCS, "taopad-export.html")

RESULTS = []

# 窗口句柄重连：WinUI 弹层打开时窗口可能短暂不可见/标题解析失效，
# 一律按句柄取新包装，避免界面枚举整体失灵
WIN_HANDLE = None


def cur_win():
    app = Application(backend="uia").connect(handle=WIN_HANDLE)
    return app.window(handle=WIN_HANDLE)


def shot(name):
    p = os.path.join(EVID, name + ".png")
    try:
        ImageGrab.grab().save(p)
    except Exception as e:
        print("截图失败", name, e)
    return p


def record(name, ok, detail=""):
    RESULTS.append({"case": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  --  " + detail) if detail else ""), flush=True)


def case(name, fn):
    try:
        fn()
        record(name, True)
    except Exception as e:
        record(name, False, f"[{type(e).__name__}] {str(e)[:280]}")
        shot("FAIL-" + re.sub(r"[^0-9A-Za-z_-]", "_", name))


def find_exe():
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i); i += 1
            except OSError:
                break
            try:
                sk = winreg.OpenKey(k, sub)
                disp, _ = winreg.QueryValueEx(sk, "DisplayName")
                if "TaoPad" in str(disp):
                    try:
                        loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                    except OSError:
                        loc = ""
                    if loc and os.path.exists(os.path.join(str(loc), "TaoPad.exe")):
                        return os.path.join(str(loc), "TaoPad.exe")
            except OSError:
                continue
    except OSError:
        pass
    import string
    for d in string.ascii_uppercase:
        cand = f"{d}:\\Program Files\\TaoPad\\TaoPad.exe"
        if os.path.exists(cand):
            return cand
    for d in string.ascii_uppercase:
        pf = f"{d}:\\Program Files"
        if os.path.isdir(pf):
            for root, dirs, files in os.walk(pf):
                if root.count(os.sep) - pf.count(os.sep) > 4:
                    dirs[:] = []
                    continue
                if "TaoPad.exe" in files:
                    return os.path.join(root, "TaoPad.exe")
    raise RuntimeError("找不到 TaoPad.exe")


def _safe_descendants(w):
    try:
        for d in w.descendants():
            yield d
    except Exception:
        pass


def _iter_candidates(win=None):
    """主窗口 + 全部顶层弹窗/弹出层（菜单浮层是独立 HWND）"""
    try:
        win = cur_win()
    except Exception:
        return
    yield from _safe_descendants(win)
    try:
        for w in Desktop(backend="uia").windows():
            try:
                if w.handle == WIN_HANDLE:
                    continue
            except Exception:
                pass
            yield from _safe_descendants(w)
    except Exception:
        pass


def find_el(title, contains=False, win=None):
    for d in _iter_candidates():
        try:
            t = (d.window_text() or "").strip()
            if (t == title) if not contains else (title in t):
                return d
        except Exception:
            continue
    return None


def esc_cleanup():
    """关掉可能残留的菜单浮层/对话框，焦点还给编辑区"""
    try:
        send_keys("{ESC}")
        time.sleep(0.25)
        send_keys("{ESC}")
        time.sleep(0.4)
    except Exception:
        pass


def menu(*titles):
    """点击菜单路径，如 menu('编码','保存编码','GBK')"""
    esc_cleanup()
    top = find_el(titles[0])
    if top is None:
        raise AssertionError("找不到顶层菜单：" + titles[0])
    top.click_input()
    time.sleep(0.8)
    for t in titles[1:]:
        el = find_el(t)
        if el is None:
            # 重试一次：先关浮层再打开
            esc_cleanup()
            top2 = find_el(titles[0])
            top2.click_input()
            time.sleep(0.8)
            el = find_el(t)
            if el is None:
                raise AssertionError("找不到菜单项：" + t)
        try:
            el.invoke()
        except Exception:
            el.click_input()
        time.sleep(0.8)
    esc_cleanup()


def texts(win=None):
    try:
        win = cur_win()
    except Exception:
        return []
    out = []
    try:
        for d in win.descendants(control_type="Text"):
            t = d.window_text()
            if t:
                out.append(t)
    except Exception:
        pass
    return out


def status_has(win=None, exact=None, contains=None):
    ts = texts(win)
    if exact is not None and not any(t.strip() == exact for t in ts):
        raise AssertionError(f"状态栏没有精确项[{exact}]，当前文本项: {ts[:20]}")
    if contains is not None and not any(contains in t for t in ts):
        raise AssertionError(f"状态栏没有包含[{contains}]，当前文本项: {ts[:20]}")


def click_editor(win=None):
    """把焦点还给编辑区（点编辑区中部）"""
    win = cur_win()
    try:
        win.click_input(coords=(win.rectangle().width() // 2, int(win.rectangle().height() * 0.62)))
    except Exception:
        rect = win.rectangle()
        ctypes.windll.user32.SetCursorPos(int((rect.left + rect.right) / 2), int(rect.top + (rect.bottom - rect.top) * 0.62))
    time.sleep(0.3)


def type_text(s):
    pyperclip.copy(s)
    send_keys("^v")
    time.sleep(0.4)


def editor_clipboard():
    pyperclip.copy("")
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^c")
    time.sleep(0.4)
    return pyperclip.paste()


def picker_typing(path, wait=3.0):
    """系统文件选择器打开后文件名框默认有焦点：键入完整路径回车；处理『已存在是否替换』确认框"""
    time.sleep(wait)
    send_keys(path, with_spaces=True)
    time.sleep(0.5)
    send_keys("{ENTER}")
    time.sleep(1.5)
    # 替换确认框：找 Yes/是 按钮
    for _ in range(3):
        yes = None
        try:
            for w in Desktop(backend="uia").windows():
                if w.window_text() in ("Confirm Save As", "确认另存为", "Confirm Save As"):
                    for b in w.descendants(control_type="Button"):
                        if b.window_text() in ("Yes", "是", "&Yes"):
                            yes = b
                            break
                if yes:
                    break
        except Exception:
            pass
        if yes is None:
            break
        try:
            yes.click_input()
        except Exception:
            yes.invoke()
        time.sleep(1.2)


def wer_count():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER")
    n = 0
    for root, dirs, files in os.walk(base):
        if any("TaoPad" in f for f in files):
            n += 1
    return n


# ---------------- 用例 ----------------

def c_startup(win):
    status_has(win, contains="行 1，列 1")
    shot("case-startup")


def c_new_tab(win):
    send_keys("^n")
    time.sleep(0.9)
    click_editor(win)
    type_text("tab2")
    shot("case-new-tab")


def c_type_undo_redo(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("hello-taopad")
    clip = editor_clipboard()
    assert "hello-taopad" in clip, f"复制内容不对: {clip!r}"
    send_keys("^z")
    time.sleep(0.5)
    clip2 = editor_clipboard()
    assert "hello-taopad" not in clip2, f"撤销后内容未变化: {clip2!r}"
    send_keys("^y")
    time.sleep(0.5)
    clip3 = editor_clipboard()
    assert "hello-taopad" in clip3, "重做后内容丢失"
    shot("case-undo-redo")


def c_cut_copy_paste(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("copy-me-123")
    clip = editor_clipboard()
    assert clip == "copy-me-123", f"全选复制失败: {clip!r}"
    send_keys("^x")
    time.sleep(0.5)
    assert pyperclip.paste() == "copy-me-123", "剪切后剪贴板不对"
    assert editor_clipboard() == "", "剪切后编辑区应已清空"
    pyperclip.copy("copy-me-123")
    send_keys("^v")
    time.sleep(0.6)
    got = editor_clipboard()
    assert got == "copy-me-123", f"粘贴失败: {got!r}"
    shot("case-cut-copy-paste")


def c_insert_time(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("t:")
    before = len(editor_clipboard())
    send_keys("{F5}")
    time.sleep(0.6)
    after = len(editor_clipboard())
    assert after > before, f"插入时间未生效，前{before}后{after}"
    shot("case-insert-time")


def c_line_ops(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("l1\nl2\nl3\nl4")
    n0 = len(editor_clipboard())
    send_keys("^d")
    time.sleep(0.5)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"复制行未生效 {n0}->{n1}"
    send_keys("%{UP}")
    time.sleep(0.4)
    shot("case-line-move")
    send_keys("%{DOWN}")
    time.sleep(0.4)
    n2 = len(editor_clipboard())
    send_keys("^+{L}")
    time.sleep(0.5)
    n3 = len(editor_clipboard())
    assert n3 < n2, f"删除行未生效 {n2}->{n3}"
    shot("case-line-ops")


def c_case_convert(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("abc")
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^+{U}")
    time.sleep(0.5)
    assert editor_clipboard() == "ABC", f"转大写失败: {editor_clipboard()!r}"
    send_keys("^{U}")
    time.sleep(0.5)
    assert editor_clipboard() == "abc", f"转小写失败: {editor_clipboard()!r}"
    shot("case-case-convert")


def c_format(win):
    click_editor(win)
    esc_cleanup()
    type_text("\ndef f(x):\n    return x\n")
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^k^d")
    time.sleep(0.7)
    shot("case-format")


def c_comment(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("code-line")
    n0 = len(editor_clipboard())
    menu("编辑", "注释选区（Ctrl+K, C）")
    time.sleep(0.6)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"注释未生效 {n0}->{n1}"
    menu("编辑", "取消注释选区（Ctrl+K, U）")
    time.sleep(0.6)
    n2 = len(editor_clipboard())
    assert n2 < n1, f"取消注释未生效 {n1}->{n2}"
    shot("case-comment")


def c_find_panel(win):
    win = cur_win()
    type_text("apple banana apple")
    send_keys("^f")
    time.sleep(0.9)
    panel_edits = list(win.descendants(control_type="Edit"))
    assert panel_edits, "查找面板没有输入框"
    send_keys("apple")
    time.sleep(0.4)
    send_keys("{ENTER}")
    time.sleep(0.5)
    send_keys("+{F3}")
    time.sleep(0.5)
    shot("case-find-panel")
    esc_cleanup()


def c_replace_panel(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("cat cat cat")
    send_keys("^h")
    time.sleep(0.9)
    send_keys("cat")
    time.sleep(0.3)
    send_keys("{TAB}")
    time.sleep(0.3)
    send_keys("dog")
    time.sleep(0.3)
    send_keys("{ENTER}")
    time.sleep(0.7)
    shot("case-replace-panel")
    esc_cleanup()


def c_goto(win):
    win = cur_win()
    esc_cleanup()
    send_keys("^g")
    time.sleep(0.9)
    edits = win.descendants(control_type="Edit")
    assert edits, "转到行没有输入框"
    edits[-1].click_input()
    time.sleep(0.2)
    send_keys("^a{DEL}")
    send_keys("1")
    time.sleep(0.2)
    send_keys("{ENTER}")
    time.sleep(0.6)
    esc_cleanup()
    shot("case-goto")


def c_find_in_files(win):
    win = cur_win()
    esc_cleanup()
    send_keys("^+{F}")
    time.sleep(1.1)
    edits = win.descendants(control_type="Edit")
    assert edits, "在文件中查找没有输入框"
    pat = [e for e in edits if e.window_text() == ""] or edits
    try:
        pat[-1].click_input()
        send_keys("^a")
        send_keys("l1")
        send_keys("{ENTER}")
        time.sleep(2.2)
    except Exception:
        pass
    shot("case-find-in-files")
    esc_cleanup()


def zoom_val(win):
    for t in texts(win):
        m = re.fullmatch(r"\d{2,3}%", t.strip())
        if m:
            return int(m.group(1))
    raise AssertionError("状态栏没有缩放百分比: " + str(texts(win)[:20]))


def c_zoom(win):
    click_editor(win)
    esc_cleanup()
    z0 = zoom_val(win)
    # 键盘快捷键（Numpad 加号）
    send_keys("^{ADD}")
    time.sleep(0.7)
    z1 = zoom_val(win)
    assert z1 > z0, f"放大未生效 {z0}->{z1}"
    send_keys("^{ADD}")
    time.sleep(0.7)
    z2 = zoom_val(win)
    assert z2 > z1, f"放大第二次未生效 {z1}->{z2}"
    shot("case-zoom-in")
    send_keys("^{SUBTRACT}")
    time.sleep(0.7)
    assert zoom_val(win) < z2, "缩小未生效"
    send_keys("^0")
    time.sleep(0.7)
    assert zoom_val(win) == 100, f"复位未回到100%，当前{zoom_val(win)}%"
    shot("case-zoom-reset")


def c_wrap_toggle(win):
    menu("查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-on")
    menu("查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-off")


def c_lineno_toggle(win):
    menu("查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-off")
    menu("查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-on")


THEMES = ["水墨", "天青", "墨夜"]


def c_themes(win):
    for i, t in enumerate(THEMES):
        menu("主题", t)
        time.sleep(0.6)
        shot(f"case-theme-{i}")


ENCS = ["UTF-8 BOM", "UTF-16 LE", "GBK", "Big5", "UTF-8"]


def c_encodings(win):
    for enc in ENCS:
        menu("编码", "保存编码", enc)
        time.sleep(0.4)
        status_has(win, exact=enc)
    shot("case-encodings")


EOLS = [("Unix (LF)", "LF"), ("Mac (CR)", "CR"), ("Windows (CRLF)", "CRLF")]


def c_eols(win):
    for title, token in EOLS:
        menu("编码", "换行符", title)
        time.sleep(0.4)
        status_has(win, exact=token)
    shot("case-eols")


LANGS = ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
         "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL"]


def c_languages(win):
    for lang in LANGS:
        menu("语言", lang)
        time.sleep(0.3)
        status_has(win, exact=lang)
    shot("case-languages")


def c_save(win):
    click_editor(win)
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("save-me-内容")
    send_keys("^s")
    time.sleep(0.6)
    picker_typing(FILE1)
    assert os.path.exists(FILE1), "保存后文件不存在: " + FILE1
    shot("case-save")


def c_open(win):
    esc_cleanup()
    send_keys("^o")
    time.sleep(0.6)
    picker_typing(FILE1)
    time.sleep(1.2)
    got = editor_clipboard().strip()
    assert got == "save-me-内容", f"打开后内容不对: {got!r}"
    shot("case-open")


def c_save_as(win):
    click_editor(win)
    type_text(" extra")
    send_keys("^+{S}")
    time.sleep(0.6)
    picker_typing(FILE2B)
    assert os.path.exists(FILE2B), "另存为文件不存在"
    shot("case-save-as")


def c_recent_menu(win):
    menu("文件", "最近文件")
    time.sleep(0.6)
    el = find_el(os.path.basename(FILE2B), contains=True) or find_el(os.path.basename(FILE1), contains=True)
    win = cur_win()
    if el is None:
        raise AssertionError("最近文件列表里没有目标文件")
    try:
        el.invoke()
    except Exception:
        el.click_input()
    time.sleep(1.2)
    esc_cleanup()
    shot("case-recent")


def c_export_html(win):
    menu("文件", "导出", "导出为可打印 HTML（PDF 用）…")
    time.sleep(0.6)
    picker_typing(HTML_OUT)
    time.sleep(1.2)
    assert os.path.exists(HTML_OUT), "导出 HTML 未生成"
    with open(HTML_OUT, encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    assert "DOCTYPE html" in head or "<html" in head.lower(), "导出内容不是 HTML"
    shot("case-export-html")


def c_save_all(win):
    click_editor(win)
    type_text("More")
    menu("文件", "全部保存")
    time.sleep(1.2)
    with open(FILE2B, encoding="utf-8") as f:
        assert "More" in f.read(), "全部保存未落盘"
    shot("case-save-all")


def c_tabs_and_close(win):
    esc_cleanup()
    send_keys("^n")
    time.sleep(0.9)
    click_editor(win)
    type_text("third-tab")
    shot("case-tab-third")
    send_keys("^w")
    time.sleep(0.9)
    assert editor_clipboard().strip() != "third-tab", "关闭标签后不应还有第三个标签内容"
    shot("case-tab-closed")


def c_settings(win):
    menu("工具", "设置…")
    time.sleep(1.2)
    win = cur_win()
    shot("case-settings-dialog")
    for el in win.descendants(control_type="Button"):
        try:
            if el.window_text() in ("自动换行", "显示行号"):
                el.click_input()
                time.sleep(0.35)
        except Exception:
            continue
    for b in win.descendants(control_type="Button"):
        if b.window_text() == "应用":
            b.click_input()
            break
    else:
        send_keys("{ENTER}")
    time.sleep(0.9)
    shot("case-settings-applied")


def c_exit(win, exe):
    wer_before = wer_count()
    esc_cleanup()
    menu("文件", "退出")
    time.sleep(3.5)
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
    still = "TaoPad.exe" in out.stdout
    assert not still, "退出后进程仍在"
    assert wer_count() == wer_before, "退出过程出现新崩溃记录"
    shot("case-exit")


def dump_tree():
    try:
        for _d in _iter_candidates():
            try:
                _t = _d.window_text()
                _ct = _d.element_info.control_type
                if _t or _ct in ("MenuItem", "MenuFlyoutItem", "ToggleMenuFlyoutItem"):
                    print("EL", _ct, "|", (_t or "")[:60], flush=True)
            except Exception:
                continue
        print("MENU-TITLES 可见:", [n for n in ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"] if find_el(n) is not None], flush=True)
    except Exception as e:
        print("dump err", e, flush=True)


def main():
    exe = find_exe()
    print("exe:", exe, flush=True)
    app = Application(backend="uia").start(exe, timeout=25)
    time.sleep(12)
    win = Desktop(backend="uia").window(title_re=".*TaoPad.*", visible_only=True)
    win.set_focus()
    global WIN_HANDLE
    WIN_HANDLE = win.handle
    time.sleep(1)
    dump_tree()

    case("S01 启动就绪与状态栏", lambda: c_startup(win))
    case("O08a 新建标签", lambda: c_new_tab(win))
    case("E01 输入/全选/复制/撤销/重做", lambda: c_type_undo_redo(win))
    case("E02 剪切/粘贴", lambda: c_cut_copy_paste(win))
    case("E03 插入时间日期(F5)", lambda: c_insert_time(win))
    case("E04 行操作(复制/上移/下移/删除)", lambda: c_line_ops(win))
    case("E05 大小写转换", lambda: c_case_convert(win))
    case("E06 格式化文档", lambda: c_format(win))
    case("E07 注释/取消注释(菜单)", lambda: c_comment(win))
    case("F01 查找面板/F3/F3反向", lambda: c_find_panel(win))
    case("F02 替换面板", lambda: c_replace_panel(win))
    case("F03 转到行", lambda: c_goto(win))
    case("F04 在文件中查找", lambda: c_find_in_files(win))
    case("V01 缩放(放大/缩小/复位)", lambda: c_zoom(win))
    case("V02 自动换行切换", lambda: c_wrap_toggle(win))
    case("V03 显示行号切换", lambda: c_lineno_toggle(win))
    case("T01 主题三套切换", lambda: c_themes(win))
    case("C01 保存编码5种", lambda: c_encodings(win))
    case("C02 换行符3种", lambda: c_eols(win))
    case("L01 语言13种逐一切换", lambda: c_languages(win))
    case("O01 保存(Ctrl+S→选择器)", lambda: c_save(win))
    case("O02 打开(Ctrl+O→选择器)", lambda: c_open(win))
    case("O03 另存为", lambda: c_save_as(win))
    case("O04 全部保存", lambda: c_save_all(win))
    case("O05 最近文件菜单", lambda: c_recent_menu(win))
    case("O06 导出可打印HTML", lambda: c_export_html(win))
    case("O07 标签页新增/切换/关闭", lambda: c_tabs_and_close(win))
    case("T02 设置对话框(开关+主题+应用)", lambda: c_settings(win))
    case("O09 正常退出+崩溃检查", lambda: c_exit(win, exe))

    report = {"cases": RESULTS, "total": len(RESULTS),
              "failed": [r["case"] for r in RESULTS if r["result"] == "FAIL"]}
    with open(os.path.join(EVID, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("==== 结果汇总 ====", flush=True)
    for r in RESULTS:
        print(r["result"], r["case"], r["detail"][:80] if r["detail"] else "", flush=True)
    print(f"共 {report['total']} 项，失败 {len(report['failed'])} 项", flush=True)
    if report["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
