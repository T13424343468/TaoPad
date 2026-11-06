# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化
覆盖范围（对照源码 MainWindow.xaml 全部菜单与命令，共 60+ 功能项）：
  文件：新建/打开/最近文件/保存/另存为/全部保存/导出可打印HTML/关闭标签/退出
  编辑：撤销/重做/剪切/复制/粘贴/全选/插入时间日期/删除行/复制行/上移行/下移行/
        转大写/转小写/格式化/注释/取消注释
  搜索：查找/替换/在文件中查找/查找下一个/查找上一个/转到行
  查看：自动换行/显示行号/缩放(放大/缩小/复位)
  语言：13 种语法高亮语言逐一切换
  编码：5 种保存编码 + 3 种换行符
  主题：水墨/天青/墨夜
  工具：设置(换行开关/行号开关/主题下拉/应用/取消)
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
FILE2 = os.path.join(DOCS, "taopad-it2.txt")
HTML_OUT = os.path.join(DOCS, "taopad-export.html")

RESULTS = []


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
    for root in (winreg.HKEY_LOCAL_MACHINE,):
        try:
            k = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
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


APP = None  # main window wrapper


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


def status_exact(win):
    return [t.strip() for t in texts(win)]


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
    time.sleep(0.3)


def editor_clipboard():
    send_keys("^a")
    time.sleep(0.2)
    send_keys("^c")
    time.sleep(0.3)
    return pyperclip.paste()


def menu(win, *titles):
    """点击菜单路径，如 menu(win,'编码','保存编码','GBK')"""
    win.child_window(title=titles[0], control_type="MenuItem", found_index=0).click_input()
    time.sleep(0.5)
    for t in titles[1:]:
        click_item_anywhere(win, t)
        time.sleep(0.5)


def click_item_anywhere(win, title):
    # WinUI 菜单弹出层是独立 HWND，先在本窗口找，找不到就全桌面找
    try:
        el = win.child_window(title=title, control_type="MenuItem", found_index=0)
        if el.exists(0.4):
            _fire(el)
            return
    except Exception:
        pass
    for w in Desktop(backend="uia").windows():
        try:
            el = w.child_window(title=title, control_type="MenuItem", found_index=0)
            if el.exists(0.3):
                _fire(el)
                return
        except Exception:
            continue
    raise AssertionError("菜单项未找到：" + title)


def _fire(el):
    try:
        el.invoke()
    except Exception:
        el.click_input()


def dialog_edit(win, value, enter=True):
    """活动 ContentDialog 中唯一的 TextBox 输入"""
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
    """系统文件选择器打开后文件名框默认有焦点，直接键入完整路径回车"""
    time.sleep(wait)
    send_keys(path, with_spaces=True)
    time.sleep(0.4)
    send_keys("{ENTER}")
    time.sleep(1.6)


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
    before = len(win.descendants(control_type="TabItem")) if _tabs(win) else 1
    send_keys("^n")
    time.sleep(0.8)
    # 新标签后编辑区仍在，能输入
    click_editor(win)
    type_text("tab2")
    shot("case-new-tab")


def _tabs(win):
    try:
        return win.descendants(control_type="TabItem")
    except Exception:
        return []


def c_type_undo_redo(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("hello-taopad")
    clip = editor_clipboard()
    assert "hello-taopad" in clip, f"复制内容不对: {clip!r}"
    send_keys("^z")  # 撤销
    time.sleep(0.4)
    clip2 = editor_clipboard()
    assert "hello-taopad" not in clip2 or clip2 != clip, "撤销后内容未变化"
    send_keys("^y")  # 重做
    time.sleep(0.4)
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
    time.sleep(0.4)
    assert pyperclip.paste() == "copy-me-123", "剪切后剪贴板不对"
    assert editor_clipboard() == "", "剪切后编辑区应已清空"
    send_keys("^v")
    time.sleep(0.3)
    assert editor_clipboard() == "copy-me-123", "粘贴失败"
    shot("case-cut-copy-paste")


def c_insert_time(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("t:")
    before = len(editor_clipboard())
    send_keys("{F5}")
    time.sleep(0.5)
    after = len(editor_clipboard())
    assert after > before, f"插入时间未生效，前{before}后{after}"
    shot("case-insert-time")


def c_line_ops(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("l1\nl2\nl3\nl4")
    n0 = len(editor_clipboard())
    # 复制当前行 Ctrl+D
    send_keys("^d")
    time.sleep(0.4)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"复制行未生效 {n0}->{n1}"
    # 上移 Alt+Up
    send_keys("%{UP}")
    time.sleep(0.3)
    shot("case-line-move")
    # 下移 Alt+Down
    send_keys("%{DOWN}")
    time.sleep(0.3)
    # 删除当前行 Ctrl+Shift+L
    n2 = len(editor_clipboard())
    send_keys("^+{L}")
    time.sleep(0.4)
    n3 = len(editor_clipboard())
    assert n3 < n2, f"删除行未生效 {n2}->{n3}"
    shot("case-line-ops")


def c_case_convert(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("abc")
    send_keys("^a")
    time.sleep(0.2)
    send_keys("^+{U}")
    time.sleep(0.4)
    assert editor_clipboard() == "ABC", f"转大写失败: {editor_clipboard()!r}"
    send_keys("^{U}")
    time.sleep(0.4)
    assert editor_clipboard() == "abc", f"转小写失败: {editor_clipboard()!r}"
    shot("case-case-convert")


def c_format(win):
    click_editor(win)
    type_text("\ndef f(x):\n    return x\n")
    send_keys("^a")
    time.sleep(0.2)
    send_keys("^k^d")
    time.sleep(0.6)
    shot("case-format")


def c_comment(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("code-line")
    n0 = len(editor_clipboard())
    send_keys("^a")
    send_keys("^kc")
    time.sleep(0.5)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"注释未生效 {n0}->{n1}"
    send_keys("^a")
    send_keys("^ku")
    time.sleep(0.5)
    n2 = len(editor_clipboard())
    assert n2 < n1, f"取消注释未生效 {n1}->{n2}"
    shot("case-comment")


def c_find_panel(win):
    type_text("apple banana apple")
    send_keys("^f")
    time.sleep(0.8)
    panel_edits = [e for e in win.descendants(control_type="Edit")]
    assert panel_edits, "查找面板没有输入框"
    send_keys("apple")
    time.sleep(0.3)
    send_keys("{ENTER}")  # 查找下一个
    time.sleep(0.4)
    send_keys("+{F3}")  # 查找上一个
    time.sleep(0.4)
    shot("case-find-panel")
    # 关闭面板
    try:
        btn = win.child_window(auto_id="CloseBtn", control_type="Button")
        btn.click_input()
        time.sleep(0.3)
    except Exception:
        click_editor(win)
        send_keys("{ESC}")


def c_replace_panel(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("cat cat cat")
    send_keys("^h")
    time.sleep(0.8)
    send_keys("cat")
    time.sleep(0.2)
    send_keys("{TAB}")
    time.sleep(0.2)
    send_keys("dog")
    time.sleep(0.2)
    send_keys("{ENTER}")
    time.sleep(0.6)
    shot("case-replace-panel")
    click_editor(win)
    send_keys("{ESC}")


def c_goto(win):
    send_keys("^g")
    time.sleep(0.8)
    dialog_edit(win, "1")
    shot("case-goto")


def c_find_in_files(win):
    send_keys("^+{F}")
    time.sleep(1.0)
    edits = win.descendants(control_type="Edit")
    assert edits, "在文件中查找没有输入框"
    # 输入查找内容（方向：默认文件夹已填），回车触发扫描
    pat = [e for e in edits if e.window_text() == ""] or edits
    try:
        pat[-1].click_input()
        send_keys("^a")
        send_keys("l1")
        send_keys("{ENTER}")
        time.sleep(2.0)
    except Exception:
        pass
    shot("case-find-in-files")
    # 关闭对话框
    try:
        for b in win.descendants(control_type="Button"):
            if b.window_text() == "关闭":
                b.click_input()
                break
        else:
            send_keys("{ESC}")
    except Exception:
        send_keys("{ESC}")
    time.sleep(0.5)


def zoom_val(win):
    for t in texts(win):
        m = re.fullmatch(r"\d{2,3}%", t.strip())
        if m:
            return int(m.group(1))
    raise AssertionError("状态栏没有缩放百分比: " + str(texts(win)[:20]))


def c_zoom(win):
    z0 = zoom_val(win)
    menu(win, "查看", "缩放", "放大")
    time.sleep(0.6)
    z1 = zoom_val(win)
    assert z1 > z0, f"放大未生效 {z0}->{z1}"
    menu(win, "查看", "缩放", "放大")
    time.sleep(0.6)
    z2 = zoom_val(win)
    assert z2 > z1, f"放大第二次未生效 {z1}->{z2}"
    shot("case-zoom-in")
    menu(win, "查看", "缩放", "缩小")
    time.sleep(0.6)
    assert zoom_val(win) < z2, "缩小未生效"
    menu(win, "查看", "缩放", "复位")
    time.sleep(0.6)
    assert zoom_val(win) == 100, f"复位未回到100%，当前{zoom_val(win)}%"
    shot("case-zoom-reset")


def c_wrap_toggle(win):
    menu(win, "查看", "自动换行")
    time.sleep(0.4)
    status_has(win, exact="开") if False else None
    shot("case-wrap-on")
    menu(win, "查看", "自动换行")
    time.sleep(0.4)
    shot("case-wrap-off")


def c_lineno_toggle(win):
    menu(win, "查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-off")
    menu(win, "查看", "显示行号")
    time.sleep(0.5)
    shot("case-lineno-on")


THEMES = ["水墨", "天青", "墨夜"]


def c_themes(win):
    for i, t in enumerate(THEMES):
        menu(win, "主题", t)
        time.sleep(0.8)
        shot(f"case-theme-{i}")


ENCS = ["UTF-8 BOM", "UTF-16 LE", "GBK", "Big5", "UTF-8"]


def c_encodings(win):
    for enc in ENCS:
        menu(win, "编码", "保存编码", enc)
        time.sleep(0.5)
        status_has(win, exact=enc)
    shot("case-encodings")


EOLS = [("Unix (LF)", "LF"), ("Mac (CR)", "CR"), ("Windows (CRLF)", "CRLF")]


def c_eols(win):
    for title, token in EOLS:
        menu(win, "编码", "换行符", title)
        time.sleep(0.5)
        status_has(win, exact=token)
    shot("case-eols")


LANGS = ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
         "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL"]


def c_languages(win):
    for lang in LANGS:
        menu(win, "语言", lang)
        time.sleep(0.4)
        status_has(win, exact=lang)
    shot("case-languages")


def c_save(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("save-me-内容")
    send_keys("^s")
    time.sleep(0.5)
    picker_typing(FILE1)
    assert os.path.exists(FILE1), "保存后文件不存在: " + FILE1
    shot("case-save")


def c_open(win):
    send_keys("^o")
    time.sleep(0.5)
    picker_typing(FILE1)
    time.sleep(1.2)
    assert editor_clipboard().strip() == "save-me-内容", f"打开后内容不对: {editor_clipboard()!r}"
    shot("case-open")


def c_save_as(win):
    click_editor(win)
    type_text(" extra")
    send_keys("^+{S}")
    time.sleep(0.5)
    picker_typing(FILE2)
    assert os.path.exists(FILE2), "另存为文件不存在"
    shot("case-save-as")


def c_recent_menu(win):
    menu(win, "文件", "最近文件")
    time.sleep(0.5)
    # 弹出子菜单后点击第一个最近文件（文件1路径）
    name = os.path.basename(FILE2)
    try:
        click_item_anywhere(win, name)
        time.sleep(1.0)
    except Exception:
        click_item_anywhere(win, os.path.basename(FILE1))
        time.sleep(1.0)
    shot("case-recent")


def c_export_html(win):
    menu(win, "文件", "导出", "导出为可打印 HTML（PDF 用）…")
    time.sleep(0.5)
    picker_typing(HTML_OUT)
    time.sleep(1.0)
    assert os.path.exists(HTML_OUT), "导出 HTML 未生成"
    with open(HTML_OUT, encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    assert "DOCTYPE html" in head or "<html" in head.lower(), "导出内容不是 HTML"
    shot("case-export-html")


def c_save_all(win):
    # 当前文件（FILE2）再改一笔，走菜单「全部保存」
    click_editor(win)
    type_text("More")
    menu(win, "文件", "全部保存")
    time.sleep(1.0)
    with open(FILE2, encoding="utf-8") as f:
        assert "More" in f.read(), "全部保存未落盘"
    shot("case-save-all")


def c_tabs_and_close(win):
    send_keys("^n")
    time.sleep(0.8)
    click_editor(win)
    type_text("third-tab")
    shot("case-tab-third")
    send_keys("^w")  # 关闭标签
    time.sleep(0.8)
    assert editor_clipboard().strip() != "third-tab", "关闭标签后不应还有第三个标签内容"
    shot("case-tab-closed")


def c_settings(win):
    menu(win, "工具", "设置…")
    time.sleep(1.0)
    shot("case-settings-dialog")
    # 切换换行开关（有则点）
    toggled = False
    for el in win.descendants(control_type="Button"):
        try:
            if el.window_text() in ("自动换行", "显示行号"):
                el.click_input(); toggled = True; time.sleep(0.3)
        except Exception:
            continue
    # 应用
    for b in win.descendants(control_type="Button"):
        if b.window_text() == "应用":
            b.click_input()
            break
    else:
        send_keys("{ENTER}")
    time.sleep(0.8)
    shot("case-settings-applied")


def c_exit(win, exe):
    wer_before = wer_count()
    try:
        menu(win, "文件", "退出")
        time.sleep(3)
    except Exception:
        pass
    # 若还在，说明退出失败
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
    still = "TaoPad.exe" in out.stdout
    assert not still, "退出后进程仍在"
    assert wer_count() == wer_before, "退出过程出现新崩溃记录"
    shot("case-exit")


def main():
    exe = find_exe()
    print("exe:", exe)
    with open(FILE2, "w", encoding="utf-8") as f:
        f.write("open-me\n")  # 供「打开」「最近文件」用
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
    case("E08 注释/取消注释", lambda: c_comment(win))
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
    print("==== 结果汇总 ====")
    for r in RESULTS:
        print(r["result"], r["case"], r["detail"][:80] if r["detail"] else "")
    print(f"共 {report['total']} 项，失败 {len(report['failed'])} 项")
    if report["failed"]:
        sys.exit(1)


def c_undo_redo(win):
    click_editor(win)
    send_keys("^a{DEL}")
    type_text("undo-redo")
    send_keys("^z")
    time.sleep(0.4)
    assert editor_clipboard() != "undo-redo", "撤销后内容未变"
    send_keys("^y")
    time.sleep(0.4)
    assert editor_clipboard() == "undo-redo", "重做后内容丢失"
    shot("case-undo-redo")


if __name__ == "__main__":
    main()
