# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化（v7，面板闭环+鼠标路径版）
每次界面元素枚举/点击都在独立 Python 子进程里完成——
WinUI 菜单浮层曾把主进程的 COM/UIA 状态拖瘫（v1-v4 的根因），
子进程天生免疫。键盘/剪贴板/截图仍在主进程。
v7：查找/替换等面板用例结束后强制关闭并轮询验证；
菜单打开优先鼠标路径（UIA 矩形→真实坐标点击），键盘 F10 兜底；
状态栏断言改轮询重试；退出前先全部保存、进程退出轮询 10 秒。
覆盖：文件9/编辑16/搜索6/查看3组/语言13/编码5+3/主题3/设置/标签页/状态栏。
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
from pywinauto.keyboard import send_keys
import pyperclip

DOCS = os.path.join(os.environ.get("USERPROFILE", r"C:\Users\runneradmin"), "Documents")
os.makedirs(DOCS, exist_ok=True)
FILE1 = os.path.join(DOCS, "taopad-it1.txt")
FILE2B = os.path.join(DOCS, "taopad-it3.txt")
HTML_OUT = os.path.join(DOCS, "taopad-export.html")

RESULTS = []
WIN_HANDLE = None

# ---------------- 子进程工作器 ----------------

def worker_run(argv):
    """独立进程做 UIA 操作，返回 stdout 字符串"""
    exe = sys.executable
    out = subprocess.run([exe, os.path.abspath(__file__), "__worker"] + argv,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=90)
    return out.stdout + out.stderr


def worker_texts():
    out = worker_run(["read_texts", str(WIN_HANDLE)])
    m = re.search(r"TEXTS (.*)", out)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return []
    print("worker read_texts 失败:", out[:200], flush=True)
    return []


def worker_find_click(title, retry=1):
    for attempt in range(retry + 1):
        out = worker_run(["find_click", title])
        if "OK" in out:
            return True
        if attempt < retry:
            send_keys("{ESC}")
            time.sleep(0.5)
            # 关掉残留浮层后重开由调用方负责
    print(f"worker find_click 未找到[{title}]:", out[:200], flush=True)
    return False


def worker_has_edit():
    out = worker_run(["has_edit", str(WIN_HANDLE)])
    m = re.search(r"EDIT (\d+)", out)
    return int(m.group(1)) if m else -1


def worker_click_last_edit():
    return "OK" in worker_run(["click_last_edit", str(WIN_HANDLE)])


def worker_click_button(name):
    return "OK" in worker_run(["click_button", name])


def worker_edits_on_win():
    out = worker_run(["count_edits", str(WIN_HANDLE)])
    m = re.search(r"EDITC (\d+)", out)
    return int(m.group(1)) if m else -1


def worker_click_menu(title):
    """鼠标路径：UIA 取菜单栏项矩形 → 真实坐标点击（与键盘路径互为对照）"""
    for _ in range(2):
        out = worker_run(["mouse_menu", str(WIN_HANDLE), title])
        if "OK" in out:
            return True
        send_keys("{ESC}")
        time.sleep(0.5)
    return False


def close_panel(verify=True, timeout=8.0):
    """点编辑器 + ESC 关闭查找/替换等面板，并轮询验证面板确已关闭（编辑框数量回落）"""
    click_editor()
    esc_cleanup()
    if not verify:
        return True
    t0 = time.time()
    while time.time() - t0 < timeout:
        if worker_edits_on_win() <= 1:
            return True
        send_keys("{ESC}")
        time.sleep(0.8)
    return worker_edits_on_win() <= 1


def worker_dump():
    out = worker_run(["dump", str(WIN_HANDLE)])
    for line in out.splitlines():
        if line.startswith(("EL", "MENU", "DUMPERR")):
            print(line, flush=True)


# ---------------- 子进程入口 ----------------

def worker_main(argv):
    from pywinauto import Application, Desktop
    mode = argv[0]
    if mode == "find_click":
        title = argv[1]
        for w in Desktop(backend="uia").windows():
            try:
                for d in w.descendants():
                    try:
                        if (d.window_text() or "").strip() == title:
                            try:
                                d.invoke()
                            except Exception:
                                d.click_input()
                            print("OK")
                            return
                    except Exception:
                        continue
            except Exception:
                continue
        print("NOTFOUND")
    elif mode == "read_texts":
        h = int(argv[1])
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        names = [d.window_text() for d in win.descendants(control_type="Text") if (d.window_text() or "").strip()]
        print("TEXTS", json.dumps(names, ensure_ascii=False))
    elif mode == "has_edit":
        h = int(argv[1])
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        print("EDIT", len(win.descendants(control_type="Edit")))
    elif mode == "count_edits":
        h = int(argv[1])
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        print("EDITC", len(win.descendants(control_type="Edit")))
    elif mode == "mouse_menu":
        h = int(argv[1])
        title = argv[2]
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        for d in win.descendants(control_type="MenuItem"):
            try:
                if (d.window_text() or "").strip() == title:
                    rect = d.rectangle()
                    x = (rect.left + rect.right) // 2
                    y = (rect.top + rect.bottom) // 2
                    ctypes.windll.user32.SetCursorPos(x, y)
                    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                    print("OK")
                    return
            except Exception:
                continue
        print("NOTFOUND")
    elif mode == "click_last_edit":
        h = int(argv[1])
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        edits = win.descendants(control_type="Edit")
        if not edits:
            print("NONE")
            return
        edits[-1].click_input()
        print("OK")
    elif mode == "click_button":
        name = argv[1]
        for w in Desktop(backend="uia").windows():
            try:
                for d in w.descendants(control_type="Button"):
                    try:
                        if (d.window_text() or "").strip() == name:
                            d.click_input()
                            print("OK")
                            return
                    except Exception:
                        continue
            except Exception:
                continue
        print("NOTFOUND")
    elif mode == "dump":
        h = int(argv[1])
        app = Application(backend="uia").connect(handle=h)
        win = app.window(handle=h)
        n = 0
        for d in win.descendants():
            try:
                t = (d.window_text() or "").strip()
                ct = d.element_info.control_type
                if t or ct in ("MenuItem", "MenuFlyoutItem", "ToggleMenuFlyoutItem"):
                    print("EL", ct, "|", t[:60])
            except Exception:
                continue
        menu_titles = ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"]
        found = []
        for t in menu_titles:
            hit = False
            for d in win.descendants(control_type="MenuItem"):
                try:
                    if (d.window_text() or "").strip() == t:
                        hit = True
                        break
                except Exception:
                    continue
            if hit:
                found.append(t)
        print("MENU-TITLES 可见:", found)


# ---------------- 主进程工具 ----------------

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


def esc_cleanup():
    try:
        send_keys("{ESC}")
        time.sleep(0.25)
        send_keys("{ESC}")
        time.sleep(0.4)
    except Exception:
        pass


TOPMENUS = ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"]
MENUS = {
    "文件": ["新建", "打开…", "最近文件", "保存", "另存为…", "全部保存", "导出", "关闭标签", "退出"],
    "编辑": ["撤销", "重做", "剪切", "复制", "粘贴", "全选", "插入时间日期", "行操作", "大小写转换", "格式化", "注释选区", "取消注释选区"],
    "搜索": ["查找", "替换", "在文件中查找…", "查找下一个", "查找上一个", "转到行…"],
    "查看": ["自动换行", "显示行号", "缩放"],
    "语言": ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
             "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL"],
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


def menu(*titles):
    """打开菜单：优先鼠标路径（UIA 取菜单项矩形→真实坐标点击），
    鼠标未命中退回键盘 F10 导航；下拉内仍走键盘。
    先关残留面板，防止面板劫持菜单焦点。"""
    close_panel()
    opened = worker_click_menu(titles[0])
    if not opened:
        send_keys("{F10}")
        time.sleep(0.9)
        topi = TOPMENUS.index(titles[0])
        for _ in range(topi):
            send_keys("{RIGHT}")
            time.sleep(0.35)
        send_keys("{ENTER}")
    time.sleep(1.0)
    if len(titles) > 1:
        lst = MENUS[titles[0]]
        for _ in range(lst.index(titles[1])):
            send_keys("{DOWN}")
            time.sleep(0.35)
        if len(titles) > 2:
            send_keys("{RIGHT}")
            time.sleep(1.0)
            sub = SUBMENUS[titles[1]]
            for _ in range(sub.index(titles[2])):
                send_keys("{DOWN}")
                time.sleep(0.35)
        send_keys("{ENTER}")
        time.sleep(1.1)


def texts():
    return worker_texts()


def status_has(exact=None, contains=None, timeout=8.0):
    """轮询重试，等界面/菜单操作落盘后再断言"""
    t0 = time.time()
    ts = []
    while True:
        ts = texts()
        if exact is not None and any(t.strip() == exact for t in ts):
            return
        if contains is not None and any(contains in t for t in ts):
            return
        if exact is None and contains is None:
            return
        if time.time() - t0 > timeout:
            if exact is not None:
                raise AssertionError(f"状态栏没有精确项[{exact}]，当前: {ts[:20]}")
            raise AssertionError(f"状态栏没有包含[{contains}]，当前: {ts[:20]}")
        time.sleep(1.0)


def click_editor():
    h = WIN_HANDLE
    try:
        import win32gui  # noqa
        rect = win32gui.GetWindowRect(h)
    except Exception:
        rect = None
    if rect:
        x = int((rect[0] + rect[2]) / 2)
        y = int(rect[1] + (rect[3] - rect[1]) * 0.62)
        ctypes.windll.user32.SetCursorPos(x, y)
        ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
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
    time.sleep(wait)
    send_keys(path, with_spaces=True)
    time.sleep(0.5)
    send_keys("{ENTER}")
    time.sleep(1.5)
    # 已存在替换确认框：键入回车默认=是
    for _ in range(2):
        try:
            import win32gui, win32con
            h = win32gui.FindWindow(None, "Confirm Save As") or win32gui.FindWindow(None, "确认另存为")
            if h:
                win32gui.SetForegroundWindow(h)
                time.sleep(0.3)
                send_keys("{ENTER}")
                time.sleep(1.2)
                continue
        except Exception:
            pass
        break


def wer_count():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER")
    n = 0
    for root, dirs, files in os.walk(base):
        if any("TaoPad" in f for f in files):
            n += 1
    return n


# ---------------- 用例 ----------------

def c_startup():
    status_has(contains="行 1，列 1")
    shot("case-startup")


def c_new_tab():
    send_keys("^n")
    time.sleep(0.9)
    click_editor()
    type_text("tab2")
    shot("case-new-tab")


def c_type_undo_redo():
    click_editor()
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


def c_cut_copy_paste():
    click_editor()
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


def c_insert_time():
    click_editor()
    send_keys("^a{DEL}")
    type_text("t:")
    before = len(editor_clipboard())
    send_keys("{F5}")
    time.sleep(0.6)
    after = len(editor_clipboard())
    assert after > before, f"插入时间未生效，前{before}后{after}"
    shot("case-insert-time")


def c_line_ops():
    click_editor()
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


def c_case_convert():
    click_editor()
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


def c_format():
    click_editor()
    esc_cleanup()
    type_text("\ndef f(x):\n    return x\n")
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^k^d")
    time.sleep(0.7)
    shot("case-format")


def c_comment():
    # 纯文本没有行注释配置，先经「语言」菜单切到 Python（顺带验证语言菜单导航）
    menu("语言", "Python")
    status_has(exact="Python")
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("code-line")
    n0 = len(editor_clipboard())
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^k")
    time.sleep(0.3)
    send_keys("c")
    time.sleep(0.7)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"注释未生效 {n0}->{n1}"
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^k")
    time.sleep(0.3)
    send_keys("u")
    time.sleep(0.7)
    n2 = len(editor_clipboard())
    assert n2 < n1, f"取消注释未生效 {n1}->{n2}"
    shot("case-comment")
    menu("语言", "纯文本")
    time.sleep(0.4)


def c_find_panel():
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("xx apple yy apple")
    send_keys("^{HOME}")          # 查找从光标向后且不回绕，先回文档开头
    time.sleep(0.4)
    send_keys("^f")
    time.sleep(1.0)
    send_keys("apple")
    time.sleep(0.4)
    send_keys("{ENTER}")
    time.sleep(0.7)
    status_has(contains="列 4")   # 第一个 apple 在第 4 列
    send_keys("{F3}")
    time.sleep(0.7)
    status_has(contains="列 13")  # 第二个 apple 在第 13 列
    send_keys("+{F3}")            # 查找上一个
    time.sleep(0.6)
    shot("case-find-panel")
    close_panel()
    click_editor()


def c_replace_panel():
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("cat cat cat")
    send_keys("^h")
    time.sleep(1.0)
    send_keys("cat")
    time.sleep(0.3)
    send_keys("{TAB}")
    time.sleep(0.3)
    send_keys("dog")
    time.sleep(0.3)
    send_keys("{ENTER}")
    time.sleep(0.7)
    shot("case-replace-panel")
    close_panel()


def c_goto():
    esc_cleanup()
    click_editor()
    send_keys("^a{DEL}")
    type_text("\n".join(f"line{i}" for i in range(1, 30)))
    send_keys("^g")
    time.sleep(1.2)
    ok = False
    for seq in ("5{ENTER}", "{TAB}5{ENTER}", "5{TAB}{ENTER}"):
        send_keys(seq)
        time.sleep(1.0)
        if any("行 5，列" in t for t in texts()):
            ok = True
            break
        send_keys("^g")
        time.sleep(1.0)
    close_panel()
    shot("case-goto")
    assert ok, "转到行未生效，状态栏未见 行 5"


def c_find_in_files():
    close_panel()
    opened = False
    for _ in range(3):
        send_keys("^+{F}")
        time.sleep(1.3)
        if worker_edits_on_win() > 1:   # 面板带输入框，编辑框数量增加即视为已开
            opened = True
            break
        send_keys("{ESC}")
        time.sleep(0.5)
    assert opened, "在文件中查找面板未打开"
    send_keys(DOCS)        # 文件夹框（首个控件，默认焦点）
    time.sleep(0.4)
    send_keys("{TAB}")     # 到查找内容框
    time.sleep(0.3)
    send_keys("save-me")
    time.sleep(0.3)
    send_keys("{ENTER}")   # 回车触发扫描
    time.sleep(2.5)
    shot("case-find-in-files")
    close_panel()


def zoom_val():
    t0 = time.time()
    while time.time() - t0 < 8.0:
        for t in texts():
            m = re.fullmatch(r"(\d{2,3})%", t.strip())
            if m:
                return int(m.group(1))
        time.sleep(1.0)
    raise AssertionError("状态栏没有缩放百分比: " + str(texts()[:20]))


def c_zoom():
    click_editor()
    esc_cleanup()
    z0 = zoom_val()
    send_keys("^{ADD}")
    time.sleep(0.8)
    z1 = zoom_val()
    assert z1 > z0, f"放大未生效 {z0}->{z1}"
    send_keys("^{ADD}")
    time.sleep(0.8)
    z2 = zoom_val()
    assert z2 > z1, f"放大第二次未生效 {z1}->{z2}"
    shot("case-zoom-in")
    send_keys("^{SUBTRACT}")
    time.sleep(0.8)
    assert zoom_val() < z2, "缩小未生效"
    send_keys("^0")
    time.sleep(0.8)
    assert zoom_val() == 100, f"复位未回到100%，当前{zoom_val()}%"
    shot("case-zoom-reset")


def c_wrap_toggle():
    menu("查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-on")
    menu("查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-off")


def c_lineno_toggle():
    menu("查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-off")
    menu("查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-on")


THEMES = ["水墨", "天青", "墨夜"]


def c_themes():
    for i, t in enumerate(THEMES):
        menu("主题", t)
        time.sleep(0.6)
        shot(f"case-theme-{i}")


ENCS = ["UTF-8 BOM", "UTF-16 LE", "GBK", "Big5", "UTF-8"]


def c_encodings():
    for enc in ENCS:
        menu("编码", "保存编码", enc)
        time.sleep(0.4)
        status_has(exact=enc)
    shot("case-encodings")


EOLS = [("Unix (LF)", "LF"), ("Mac (CR)", "CR"), ("Windows (CRLF)", "CRLF")]


def c_eols():
    for title, token in EOLS:
        menu("编码", "换行符", title)
        time.sleep(0.4)
        status_has(exact=token)
    shot("case-eols")


LANGS = ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
         "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL"]


def c_languages():
    for lang in LANGS:
        menu("语言", lang)
        time.sleep(0.3)
        status_has(exact=lang)
    shot("case-languages")


def c_save():
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("save-me-内容")
    send_keys("^s")
    time.sleep(0.6)
    picker_typing(FILE1)
    assert os.path.exists(FILE1), "保存后文件不存在: " + FILE1
    shot("case-save")


def c_open():
    esc_cleanup()
    send_keys("^o")
    time.sleep(0.6)
    picker_typing(FILE1)
    time.sleep(1.2)
    got = editor_clipboard().strip()
    assert got == "save-me-内容", f"打开后内容不对: {got!r}"
    shot("case-open")


def c_save_as():
    click_editor()
    type_text(" extra")
    send_keys("^+{S}")
    time.sleep(0.6)
    picker_typing(FILE2B)
    assert os.path.exists(FILE2B), "另存为文件不存在"
    shot("case-save-as")


def c_recent_menu():
    close_panel()
    if not worker_click_menu("文件"):
        # 键盘兜底：F10 聚焦菜单条（焦点在第一项「文件」），回车打开下拉
        send_keys("{F10}")
        time.sleep(0.9)
        send_keys("{ENTER}")
    time.sleep(1.0)
    for _ in range(MENUS["文件"].index("最近文件")):
        send_keys("{DOWN}")
        time.sleep(0.3)
    send_keys("{RIGHT}")          # 展开最近文件子菜单
    time.sleep(1.0)
    send_keys("{DOWN}")           # 第一条最近文件
    time.sleep(0.3)
    send_keys("{ENTER}")
    time.sleep(1.5)
    esc_cleanup()
    shot("case-recent")
    got = editor_clipboard().strip()
    known = ("save-me-内容 extra", "save-me-内容 extraMore", " extra", " extraMore", "save-me-内容")
    assert got in known, f"最近文件打开后内容不对: {got!r}"


def c_export_html():
    menu("文件", "导出", "导出为可打印 HTML（PDF 用）…")
    time.sleep(0.6)
    picker_typing(HTML_OUT)
    time.sleep(1.2)
    assert os.path.exists(HTML_OUT), "导出 HTML 未生成"
    with open(HTML_OUT, encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    assert "DOCTYPE html" in head or "<html" in head.lower(), "导出内容不是 HTML"
    shot("case-export-html")


def c_save_all():
    click_editor()
    type_text("More")
    menu("文件", "全部保存")
    time.sleep(1.2)
    with open(FILE2B, encoding="utf-8") as f:
        assert "More" in f.read(), "全部保存未落盘"
    shot("case-save-all")


def c_tabs_and_close():
    esc_cleanup()
    send_keys("^n")
    time.sleep(0.9)
    click_editor()
    type_text("third-tab")
    shot("case-tab-third")
    send_keys("^w")
    time.sleep(0.9)
    assert editor_clipboard().strip() != "third-tab", "关闭标签后不应还有第三个标签内容"
    shot("case-tab-closed")


def c_settings():
    menu("工具", "设置…")
    time.sleep(1.3)
    shot("case-settings-dialog")
    send_keys("{SPACE}")     # 焦点默认落在第一个开关（自动换行），空格切换
    time.sleep(0.4)
    send_keys("{TAB}")
    time.sleep(0.3)
    send_keys("{SPACE}")     # 第二个开关（显示行号）
    time.sleep(0.4)
    shot("case-settings-toggled")
    send_keys("{ENTER}")     # 默认按钮=应用
    time.sleep(1.2)
    shot("case-settings-applied")


def c_exit():
    wer_before = wer_count()
    close_panel()
    menu("文件", "全部保存")      # 退出前先落盘，避免未保存确认框卡住流程
    time.sleep(1.0)
    menu("文件", "退出")
    still = True
    t0 = time.time()
    while still and time.time() - t0 < 10:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
        still = "TaoPad.exe" in out.stdout
        if still:
            time.sleep(1.0)
    assert not still, "退出后进程仍在（等待10秒）"
    assert wer_count() == wer_before, "退出过程出现新崩溃记录"
    shot("case-exit")


def main():
    global WIN_HANDLE
    if sys.argv[1:2] == ["__worker"]:
        worker_main(sys.argv[2:])
        return
    exe = find_exe()
    print("exe:", exe, flush=True)
    from pywinauto import Application, Desktop
    app = Application(backend="uia").start(exe, timeout=25)
    time.sleep(12)
    win = Desktop(backend="uia").window(title_re=".*TaoPad.*", visible_only=True)
    win.set_focus()
    WIN_HANDLE = win.handle
    time.sleep(1)
    worker_dump()

    case("S01 启动就绪与状态栏", c_startup)
    case("O08a 新建标签", c_new_tab)
    case("E01 输入/全选/复制/撤销/重做", c_type_undo_redo)
    case("E02 剪切/粘贴", c_cut_copy_paste)
    case("E03 插入时间日期(F5)", c_insert_time)
    case("E04 行操作(复制/上移/下移/删除)", c_line_ops)
    case("E05 大小写转换", c_case_convert)
    case("E06 格式化文档", c_format)
    case("E07 注释/取消注释(菜单)", c_comment)
    case("F01 查找面板/F3/F3反向", c_find_panel)
    case("F02 替换面板", c_replace_panel)
    case("F03 转到行", c_goto)
    case("F04 在文件中查找", c_find_in_files)
    case("V01 缩放(放大/缩小/复位)", c_zoom)
    case("V02 自动换行切换", c_wrap_toggle)
    case("V03 显示行号切换", c_lineno_toggle)
    case("T01 主题三套切换", c_themes)
    case("C01 保存编码5种", c_encodings)
    case("C02 换行符3种", c_eols)
    case("L01 语言13种逐一切换", c_languages)
    case("O01 保存(Ctrl+S→选择器)", c_save)
    case("O02 打开(Ctrl+O→选择器)", c_open)
    case("O03 另存为", c_save_as)
    case("O04 全部保存", c_save_all)
    case("O05 最近文件菜单", c_recent_menu)
    case("O06 导出可打印HTML", c_export_html)
    case("O07 标签页新增/切换/关闭", c_tabs_and_close)
    case("T02 设置对话框(开关+主题+应用)", c_settings)
    case("O09 正常退出+崩溃检查", c_exit)

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
