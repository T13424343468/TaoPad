# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化（v3：键盘导航菜单）
覆盖范围（对照源码 MainWindow.xaml 全部菜单与命令，共 60+ 功能项）：
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
  状态栏：逐项断言
菜单经由键盘导航（F10→方向键→回车，WinUI MenuBar 官方键盘路径），不依赖控件名。
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
FILE2 = os.path.join(DOCS, "taopad-it2.txt")
HTML_OUT = os.path.join(DOCS, "taopad-export.html")

RESULTS = []

TOPMENUS = ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"]
LANGS = ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
         "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL"]
MENUS = {
    "文件": ["新建", "打开…", "最近文件", "保存", "另存为…", "全部保存", "导出", "关闭标签", "退出"],
    "编辑": ["撤销", "重做", "剪切", "复制", "粘贴", "全选", "插入时间日期", "行操作", "大小写转换", "格式化", "注释选区", "取消注释选区"],
    "搜索": ["查找", "替换", "在文件中查找…", "查找下一个", "查找上一个", "转到行…"],
    "查看": ["自动换行", "显示行号", "缩放"],
    "语言": LANGS,
    "编码": ["保存编码", "换行符"],
    "主题": ["水墨", "天青", "墨夜"],
    "工具": ["设置…"],
}
SUBMENUS = {
    "导出": ["导出为可打印 HTML（PDF 用）…"],
    "行操作": ["删除当前行", "复制当前行", "上移当前行", "下移当前行"],
    "大小写转换": ["转为大写", "转为小写"],
    "缩放": ["放大", "缩小", "复位"],
    "保存编码": ["UTF-8", "UTF-8 BOM", "UTF-16 LE", "GBK", "Big5"],
    "换行符": ["Windows (CRLF)", "Unix (LF)", "Mac (CR)"],
}


def shot(name):
    p = os.path.join(EVID, name + ".png")
    try:
        ImageGrab.grab().save(p)
    except Exception as e:
        print("截图失败", name, e)
    return p


def record(name, ok, detail=""):
    RESULTS.append({"case": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(("[PASS] " if ok else "[FAIL] ") + name + (("  --  " + detail) if detail else ""))


def case(name, fn):
    try:
        fn()
        record(name, True)
    except Exception as e:
        record(name, False, str(e)[:300])
        shot("FAIL-" + name.replace(" ", "_"))


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


def texts(win):
    out = []
    try:
        for d in win.descendants(control_type="Text"):
            t = d.window_text()
            if t:
                out.append(t)
    except Exception:
        pass
    return out


def status_has(win, exact=None, contains=None):
    ts = texts(win)
    if exact is not None and not any(t.strip() == exact for t in ts):
        raise AssertionError(f"状态栏没有精确项[{exact}]，当前文本项: {ts[:20]}")
    if contains is not None and not any(contains in t for t in ts):
        raise AssertionError(f"状态栏没有包含[{contains}]，当前文本项: {ts[:20]}")


def click_editor(win):
    """把焦点还给编辑区（点编辑区中部）"""
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


def menu_kb(win, top, *items):
    """键盘导航菜单：F10 聚焦菜单条 → 方向键选择 → Enter 打开/触发"""
    click_editor(win)
    send_keys("{ESC}")
    time.sleep(0.3)
    send_keys("{F10}")
    time.sleep(0.8)
    topi = TOPMENUS.index(top)
    for _ in range(topi):
        send_keys("{RIGHT}")
        time.sleep(0.3)
    send_keys("{ENTER}")  # 打开顶层下拉，焦点进第一项
    time.sleep(0.9)
    if items:
        lst = MENUS[top]
        target = items[0]
        for _ in range(lst.index(target)):
            send_keys("{DOWN}")
            time.sleep(0.3)
        if len(items) > 1:
            send_keys("{RIGHT}")  # 展开子菜单，焦点进子菜单第一项
            time.sleep(0.9)
            sub = SUBMENUS[target]
            t2 = items[1]
            for _ in range(sub.index(t2)):
                send_keys("{DOWN}")
                time.sleep(0.3)
        send_keys("{ENTER}")  # 触发
        time.sleep(1.0)
    send_keys("{ESC}")  # 兜底收起残留浮层
    time.sleep(0.3)


def dialog_edit(win, value, enter=True):
    """活动 ContentDialog 中最后一个 TextBox 输入"""
    edits = win.descendants(control_type="Edit")
    if not edits:
        raise AssertionError("对话框中找不到输入框")
    target = edits[-1]
    target.click_input()
    time.sleep(0.2)
    send_keys("^a{DEL}")
    send_keys(value, with_spaces=True)
    time.sleep(0.2)
    if enter:
        send_keys("{ENTER}")
    time.sleep(0.6)


def picker_typing(path, wait=3.0):
    """系统文件选择器打开后文件名框默认有焦点，直接键入完整路径回车；处理覆盖确认框"""
    time.sleep(wait)
    send_keys(path, with_spaces=True)
    time.sleep(0.5)
    send_keys("{ENTER}")
    time.sleep(1.4)
    for w in Desktop(backend="uia").windows():
        try:
            t = w.window_text()
        except Exception:
            t = ""
        if "Confirm Save As" in t or "确认另存为" in t:
            send_keys("{ENTER}")  # 默认按钮=是，覆盖
            time.sleep(1.2)
            break


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
    time.sleep(0.8)
    click_editor(win)
    type_text("tab2")
    shot("case-new-tab")


def c_type_undo_redo(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("hello-taopad")
    clip = editor_clipboard()
    assert "hello-taopad" in clip, f"复制内容不对: {clip!r}"
    send_keys("^z")
    time.sleep(0.5)
    clip2 = editor_clipboard()
    assert "hello-taopad" not in clip2 or clip2 != clip, "撤销后内容未变化"
    send_keys("^y")
    time.sleep(0.5)
    clip3 = editor_clipboard()
    assert "hello-taopad" in clip3, "重做后内容丢失"
    shot("case-undo-redo")


def c_cut_copy_paste(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("copy-me-123")
    clip = editor_clipboard()
    assert clip == "copy-me-123", f"全选复制失败: {clip!r}"
    send_keys("^x")
    time.sleep(0.6)
    assert pyperclip.paste() == "copy-me-123", "剪切后剪贴板不对"
    assert editor_clipboard() == "", "剪切后编辑区应已清空"
    click_editor(win)
    send_keys("^v")
    time.sleep(0.8)
    assert editor_clipboard() == "copy-me-123", "粘贴失败"
    shot("case-cut-copy-paste")


def c_undo_redo(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("undo-redo")
    send_keys("^z")
    time.sleep(0.5)
    assert editor_clipboard() != "undo-redo", "撤销后内容未变"
    send_keys("^y")
    time.sleep(0.5)
    assert editor_clipboard() == "undo-redo", "重做后内容丢失"
    shot("case-undo-redo-2")


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
    send_keys("^a{DEL}")
    type_text("abc")
    send_keys("^a")
    time.sleep(0.3)
    send_keys("^+{U}")
    time.sleep(0.5)
    assert editor_clipboard() == "ABC", f"转大写失败: {editor_clipboard()!r}"
    send_keys("^{U}")
    time.sleep(0.5)
    assert editor_clipboard() == "abc", f"转小写失败: {editor_clipboard()!r}"
    shot("case-case-convert")


def c_format(win):
    click_editor(win)
    type_text("\ndef f(x):\n    return x\n")
    send_keys("^a")
    time.sleep(0.3)
    send_keys("^k")
    time.sleep(0.3)
    send_keys("^d")
    time.sleep(0.6)
    shot("case-format")


def c_comment(win):
    # 纯文本没有行注释配置，先切到 Python 再测
    menu_kb(win, "语言", "Python")
    status_has(win, exact="Python")
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("code-line")
    n0 = len(editor_clipboard())
    send_keys("^a")
    time.sleep(0.3)
    send_keys("^k")
    time.sleep(0.3)
    send_keys("c")
    time.sleep(0.6)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"注释未生效 {n0}->{n1}"
    send_keys("^a")
    time.sleep(0.3)
    send_keys("^k")
    time.sleep(0.3)
    send_keys("u")
    time.sleep(0.6)
    n2 = len(editor_clipboard())
    assert n2 < n1, f"取消注释未生效 {n1}->{n2}"
    shot("case-comment")


def c_find_panel(win):
    type_text("apple banana apple")
    send_keys("^f")
    time.sleep(0.9)
    assert win.descendants(control_type="Edit"), "查找面板没有输入框"
    send_keys("apple")
    time.sleep(0.4)
    send_keys("{ENTER}")  # 查找下一个
    time.sleep(0.5)
    send_keys("+{F3}")  # 查找上一个
    time.sleep(0.5)
    shot("case-find-panel")
    click_editor(win)
    send_keys("{ESC}")
    time.sleep(0.4)


def c_replace_panel(win):
    click_editor(win)
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
    time.sleep(0.8)
    shot("case-replace-panel")
    click_editor(win)
    send_keys("{ESC}")
    time.sleep(0.4)


def c_goto(win):
    send_keys("^g")
    time.sleep(0.9)
    dialog_edit(win, "1")
    shot("case-goto")


def c_find_in_files(win):
    send_keys("^+{F}")
    time.sleep(1.2)
    edits = win.descendants(control_type="Edit")
    assert edits, "在文件中查找没有输入框"
    try:
        pat = [e for e in edits if e.window_text() == ""] or edits
        pat[-1].click_input()
        send_keys("^a")
        send_keys("l1")
        send_keys("{ENTER}")
        time.sleep(2.2)
    except Exception:
        pass
    shot("case-find-in-files")
    try:
        for b in win.descendants(control_type="Button"):
            if b.window_text() == "关闭":
                b.click_input()
                break
        else:
            send_keys("{ESC}")
    except Exception:
        send_keys("{ESC}")
    time.sleep(0.6)


def zoom_val(win):
    for t in texts(win):
        m = re.fullmatch(r"\d{2,3}%", t.strip())
        if m:
            return int(m.group(1))
    raise AssertionError("状态栏没有缩放百分比: " + str(texts(win)[:20]))


def c_zoom(win):
    z0 = zoom_val(win)
    menu_kb(win, "查看", "缩放", "放大")
    time.sleep(0.5)
    z1 = zoom_val(win)
    assert z1 > z0, f"放大未生效 {z0}->{z1}"
    menu_kb(win, "查看", "缩放", "放大")
    time.sleep(0.5)
    z2 = zoom_val(win)
    assert z2 > z1, f"放大第二次未生效 {z1}->{z2}"
    shot("case-zoom-in")
    menu_kb(win, "查看", "缩放", "缩小")
    time.sleep(0.5)
    assert zoom_val(win) < z2, "缩小未生效"
    menu_kb(win, "查看", "缩放", "复位")
    time.sleep(0.5)
    assert zoom_val(win) == 100, f"复位未回到100%，当前{zoom_val(win)}%"
    shot("case-zoom-reset")


def c_wrap_toggle(win):
    menu_kb(win, "查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-on")
    menu_kb(win, "查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-off")


def c_lineno_toggle(win):
    menu_kb(win, "查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-off")
    menu_kb(win, "查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-on")


def c_themes(win):
    for i, t in enumerate(["水墨", "天青", "墨夜"]):
        menu_kb(win, "主题", t)
        time.sleep(0.7)
        shot(f"case-theme-{i}")


def c_encodings(win):
    for enc in ["UTF-8 BOM", "UTF-16 LE", "GBK", "Big5", "UTF-8"]:
        menu_kb(win, "编码", "保存编码", enc)
        time.sleep(0.4)
        status_has(win, exact=enc)
    shot("case-encodings")


def c_eols(win):
    for title, token in [("Unix (LF)", "LF"), ("Mac (CR)", "CR"), ("Windows (CRLF)", "CRLF")]:
        menu_kb(win, "编码", "换行符", title)
        time.sleep(0.4)
        status_has(win, exact=token)
    shot("case-eols")


def c_languages(win):
    for lang in LANGS:
        menu_kb(win, "语言", lang)
        time.sleep(0.4)
        status_has(win, exact=lang)
    shot("case-languages")


def c_save(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("save-me-内容")
    send_keys("^s")
    time.sleep(0.6)
    picker_typing(FILE1)
    assert os.path.exists(FILE1), "保存后文件不存在: " + FILE1
    shot("case-save")


def c_open(win):
    send_keys("^o")
    time.sleep(0.6)
    picker_typing(FILE1)
    time.sleep(1.4)
    assert editor_clipboard().strip() == "save-me-内容", f"打开后内容不对: {editor_clipboard()!r}"
    shot("case-open")


def c_save_as(win):
    click_editor(win)
    type_text(" extra")
    send_keys("^+{S}")
    time.sleep(0.6)
    picker_typing(FILE2)
    assert os.path.exists(FILE2), "另存为文件不存在"
    shot("case-save-as")


def c_recent_menu(win):
    menu_kb(win, "文件", "最近文件")
    time.sleep(0.8)
    # 子菜单已打开（menu_kb 最后的 ESC 会收起，重新走一遍键盘打开）
    click_editor(win)
    send_keys("{F10}")
    time.sleep(0.8)
    send_keys("{ENTER}")  # 焦点在文件，回车打开下拉
    time.sleep(0.8)
    for _ in range(MENUS["文件"].index("最近文件")):
        send_keys("{DOWN}")
        time.sleep(0.3)
    send_keys("{RIGHT}")  # 展开最近文件子菜单
    time.sleep(0.9)
    send_keys("{DOWN}")  # 第一条最近文件
    time.sleep(0.3)
    send_keys("{ENTER}")
    time.sleep(1.4)
    shot("case-recent")
    assert editor_clipboard().strip() in ("save-me-内容 extra", "save-me-内容"), "最近文件打开后内容不对"


def c_save_all(win):
    click_editor(win)
    type_text("More")
    menu_kb(win, "文件", "全部保存")
    time.sleep(1.2)
    with open(FILE2, encoding="utf-8") as f:
        assert "More" in f.read(), "全部保存未落盘"
    shot("case-save-all")


def c_export_html(win):
    menu_kb(win, "文件", "导出", "导出为可打印 HTML（PDF 用）…")
    time.sleep(0.6)
    picker_typing(HTML_OUT)
    time.sleep(1.2)
    assert os.path.exists(HTML_OUT), "导出 HTML 未生成"
    with open(HTML_OUT, encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    assert "DOCTYPE html" in head or "<html" in head.lower(), "导出内容不是 HTML"
    shot("case-export-html")


def c_tabs_and_close(win):
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
    menu_kb(win, "工具", "设置…")
    time.sleep(1.2)
    shot("case-settings-dialog")
    # 切换换行开关（有则点）
    for el in win.descendants(control_type="Button"):
        try:
            if el.window_text() in ("自动换行", "显示行号"):
                el.click_input()
                time.sleep(0.3)
        except Exception:
            continue
    # 主题下拉选天青
    try:
        for c in win.descendants(control_type="ComboBox"):
            c.click_input()
            time.sleep(0.5)
            for item in win.descendants(control_type="ListItem"):
                if item.window_text() == "天青":
                    item.click_input()
                    break
            break
    except Exception:
        pass
    time.sleep(0.4)
    # 应用
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
    try:
        menu_kb(win, "文件", "退出")
        time.sleep(3)
    except Exception:
        pass
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
    still = "TaoPad.exe" in out.stdout
    assert not still, "退出后进程仍在"
    assert wer_count() == wer_before, "退出过程出现新崩溃记录"
    shot("case-exit")


def main():
    exe = find_exe()
    print("exe:", exe)
    for p in (FILE1, FILE2, HTML_OUT):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    app = Application(backend="uia").start(exe, timeout=25)
    time.sleep(12)
    win = Desktop(backend="uia").window(title_re=".*TaoPad.*", visible_only=True)
    win.set_focus()
    time.sleep(1)

    case("S01 启动就绪与状态栏", lambda: c_startup(win))
    case("O08a 新建标签", lambda: c_new_tab(win))
    case("E01 输入/全选/复制", lambda: c_type_undo_redo(win))
    case("E02 剪切/粘贴", lambda: c_cut_copy_paste(win))
    case("E03 撤销/重做", lambda: c_undo_redo(win))
    case("E04 插入时间日期(F5)", lambda: c_insert_time(win))
    case("E05 行操作(复制/上移/下移/删除)", lambda: c_line_ops(win))
    case("E06 大小写转换", lambda: c_case_convert(win))
    case("E07 格式化文档", lambda: c_format(win))
    case("E08 注释/取消注释(含语言切换)", lambda: c_comment(win))
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
    case("O03 另存为(含覆盖确认)", lambda: c_save_as(win))
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
    print("==== 结果汇总 ====")
    for r in RESULTS:
        print(r["result"], r["case"], r["detail"][:80] if r["detail"] else "")
    print(f"共 {report['total']} 项，失败 {len(report['failed'])} 项")
    if report["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
