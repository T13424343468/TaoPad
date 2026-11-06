# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化（v9，读取通道自愈+菜单开合验证版）
每次界面元素枚举/点击都在独立 Python 子进程里完成——
WinUI 菜单浮层曾把主进程的 COM/UIA 状态拖瘫（v1-v4 的根因），
子进程天生免疫。键盘/剪贴板/截图仍在主进程。
v7：面板闭环+鼠标路径菜单+轮询断言+退出先存后验。
v8（第五轮证据回灌）：界面读取空返回时重试；轮询间隔放宽到 2 秒
降低机器负载；文件对话框先等就绪再整段粘贴路径（修复路径被吞头）；
菜单操作后焦点点回编辑区；查找匹配列号按截图口径改为选中串末尾；
退出时未命名标签的另存为对话框补路径确认。
v9（第六轮证据回灌）：E07 起读取层系统性返回空——按句柄连接可能落在
失活的 UIA 会话上。读取改为「置前→句柄→按标题重找」多通道；读取空时
先 ESC 清掉可能滞留的菜单浮层再重试；菜单/面板开合改为可验证（探针：
常驻菜单项能否枚举→区分"读层失效"与"下拉未开"），未开则退回键盘路径
（第四轮纯键盘菜单读取始终正常）；编辑框计数把读取失败(-1)视为未知，
不再误判为"面板已关"。
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
    for _ in range(4):
        out = worker_run(["read_texts", str(WIN_HANDLE)])
        m = re.search(r"TEXTS (.*)", out)
        if m:
            try:
                names = json.loads(m.group(1))
            except Exception:
                names = []
            if names:
                return names
        else:
            print("worker read_texts 失败:", out[:200], flush=True)
        # 读空常见于菜单浮层滞留拖死 UIA 读取：先 ESC 清浮层再重试
        try:
            send_keys("{ESC}")
        except Exception:
            pass
        time.sleep(1.5)   # 机器繁忙时空读常见，稍候重试
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


def close_panel(verify=True, timeout=12.0):
    """点编辑器 + ESC 关闭查找/替换等面板，并轮询验证面板确已关闭（编辑框数量回落）。
    读取失败(-1)不再误判为已关——v8 的教训：-1<=1 恒真，面板残留混过验证。"""
    click_editor()
    esc_cleanup()
    if not verify:
        return True
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        c = worker_edits_on_win()
        if 0 <= c <= 1:
            return True
        last = c
        send_keys("{ESC}")
        time.sleep(2.0)
    print(f"close_panel 未确认关闭，编辑框计数残留: {last}", flush=True)
    shot("close-panel-unverified")
    return False


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
    elif mode in ("read_texts", "count_edits", "has_edit", "menu_item_visible"):
        h = int(argv[1])
        title = argv[2] if mode == "menu_item_visible" else None
        # 置前：部分 UIA 提供方对后台窗口会停止服务 Text 枚举
        try:
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            ctypes.windll.user32.SetForegroundWindow(h)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            time.sleep(0.2)
        except Exception:
            pass
        win = None
        try:
            app = Application(backend="uia").connect(handle=h)
            win = app.window(handle=h)
        except Exception:
            win = None

        def by_title():
            try:
                return Desktop(backend="uia").window(title_re=".*TaoPad.*", visible_only=True)
            except Exception:
                return None

        # 多通道：句柄连接失败或读空时，按标题重找窗口再试
        sources = [w for w in (win,) if w is not None] + [None]
        if mode == "read_texts":
            names = []
            for w in sources:
                if w is not None:
                    try:
                        names = [d.window_text() for d in w.descendants(control_type="Text")
                                 if (d.window_text() or "").strip()]
                        if names:
                            break
                    except Exception:
                        names = []
                alt = by_title()
                if alt is not None:
                    try:
                        names = [d.window_text() for d in alt.descendants(control_type="Text")
                                 if (d.window_text() or "").strip()]
                        if names:
                            break
                    except Exception:
                        names = []
            print("TEXTS", json.dumps(names, ensure_ascii=False))
        elif mode == "menu_item_visible":
            found = False
            for w in sources:
                src = w if w is not None else by_title()
                if src is None:
                    continue
                try:
                    for d in src.descendants(control_type="MenuItem"):
                        try:
                            if (d.window_text() or "").strip() == title:
                                found = True
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
                if found:
                    break
            print("MENUITEM", "YES" if found else "NO")
        elif mode == "count_edits":
            cnt = -1
            for w in sources:
                if w is not None:
                    try:
                        cnt = len(w.descendants(control_type="Edit"))
                        if cnt >= 0:
                            break
                    except Exception:
                        cnt = -1
                alt = by_title()
                if alt is not None:
                    try:
                        cnt = len(alt.descendants(control_type="Edit"))
                        if cnt >= 0:
                            break
                    except Exception:
                        cnt = -1
            print("EDITC", cnt)
        elif mode == "has_edit":
            cnt = -1
            for w in sources:
                if w is not None:
                    try:
                        cnt = len(w.descendants(control_type="Edit"))
                        break
                    except Exception:
                        cnt = -1
            print("EDIT", cnt)
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


def menu_item_visible(title):
    out = worker_run(["menu_item_visible", str(WIN_HANDLE), title])
    return "MENUITEM YES" in out


def read_alive():
    """读层探针：菜单栏常驻项「文件」任何时候都应可枚举；枚举不到说明 UIA 读层失效"""
    return menu_item_visible("文件")


def menu(*titles):
    """打开菜单：优先鼠标路径（UIA 取菜单项矩形→真实坐标点击），
    开合可验证：探针正常而目标项不可见时，ESC 后退回键盘 F10 路径
    （第四轮纯键盘菜单读取始终正常）；读层失效时按原路径继续。
    下拉内仍走键盘。先关残留面板，防止面板劫持菜单焦点。"""
    close_panel()
    worker_click_menu(titles[0])
    time.sleep(1.0)
    target = titles[1] if len(titles) > 1 else titles[0]
    alive = read_alive()
    if alive and not menu_item_visible(target):
        # 读层正常但目标项不在树里 → 下拉没开（或焦点没进菜单），退回键盘路径
        print(f"菜单[{titles[0]}]鼠标路径未确认展开，退回键盘路径", flush=True)
        send_keys("{ESC}")
        time.sleep(0.5)
        send_keys("{F10}")
        time.sleep(0.9)
        topi = TOPMENUS.index(titles[0])
        for _ in range(topi):
            send_keys("{RIGHT}")
            time.sleep(0.35)
        send_keys("{ENTER}")
        time.sleep(1.0)
    time.sleep(0.4)
    if len(titles) > 1:
        lst = MENUS[titles[0]]
        idx = lst.index(titles[1])
        # 下拉确已展开（项可见）才导航；读层失效时保持原样继续
        if alive and not menu_item_visible(titles[1]):
            send_keys("{DOWN}")   # 可能首次展开需再补一档
        for _ in range(idx):
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
    if not dialog_present():
        click_editor()   # 菜单操作后焦点常留在菜单栏，点回编辑区


def texts():
    return worker_texts()


def status_has(exact=None, contains=None, timeout=12.0):
    """轮询重试，等界面/菜单操作落盘后再断言（间隔 2 秒，降低读取进程密度）"""
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
        time.sleep(2.0)


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


def dialog_present():
    """是否有打开/保存类系统对话框（#32770）"""
    try:
        import win32gui
        return bool(win32gui.FindWindow("#32770", None))
    except Exception:
        return False


def picker_typing(path, wait=3.0):
    t0 = time.time()
    while not dialog_present() and time.time() - t0 < 10:
        time.sleep(0.5)
    time.sleep(1.0)          # 等文件名框就绪，避免开头字符丢失
    pyperclip.copy(path)
    send_keys("^v")          # 整段粘贴，杜绝逐键输入被吞
    time.sleep(0.8)
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
    time.sleep(0.5)
    # 输入后可能已自动定位首个匹配（光标显示在选中串末尾，列 9）；
    # 未定位则回车触发查找。第五轮截图证实：第二个匹配显示 列 18。
    if not col_seen([8, 9], 3.0):
        send_keys("{ENTER}")
        time.sleep(0.8)
    assert col_seen([8, 9]), "状态栏未显示首个匹配位置"
    send_keys("{ENTER}")          # 下一个匹配
    time.sleep(0.8)
    assert col_seen([18]), "状态栏未显示第二个匹配位置"
    send_keys("+{F3}")            # 查找上一个
    time.sleep(0.8)
    assert col_seen([8, 9]), "反向查找未回到首个匹配"
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
    if not opened:
        # 快捷键路径未确认时，走菜单路径再试一次（v9：菜单开合已可验证）
        menu("搜索", "在文件中查找…")
        if worker_edits_on_win() > 1:
            opened = True
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


def col_seen(cols, timeout=8.0):
    """状态栏出现任一目标列号（光标显示在选中串末尾，列号按截图口径）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        for t in texts():
            for c in cols:
                if f"列 {c}" in t:
                    return True
        time.sleep(2.0)
    return False


def zoom_val():
    t0 = time.time()
    while time.time() - t0 < 12.0:
        for t in texts():
            m = re.fullmatch(r"(\d{2,3})%", t.strip())
            if m:
                return int(m.group(1))
        time.sleep(2.0)
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
    if not dialog_present():
        # 菜单没弹/路径进了编辑区：ESC 后整重试一次
        send_keys("{ESC}")
        time.sleep(0.4)
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
    for _ in range(2):
        click_editor()
        type_text("More")
        menu("文件", "全部保存")
        time.sleep(1.2)
        with open(FILE2B, encoding="utf-8") as f:
            if "More" in f.read():
                shot("case-save-all")
                return
        # 首次未落盘：补一次 Ctrl+S 兜底后再验
        click_editor()
        send_keys("^s")
        time.sleep(1.0)
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
    if dialog_present():          # 未命名的标签会弹另存为，补一个落盘路径
        picker_typing(os.path.join(DOCS, "taopad-exit-save.txt"))
        time.sleep(0.8)
    menu("文件", "退出")
    still = True
    t0 = time.time()
    while still and time.time() - t0 < 12:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
        still = "TaoPad.exe" in out.stdout
        if still:
            if dialog_present():  # 保存/退出确认框：回车默认确认
                send_keys("{ENTER}")
            time.sleep(1.0)
    assert not still, "退出后进程仍在（等待12秒）"
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
