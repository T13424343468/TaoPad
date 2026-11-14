# -*- coding: utf-8 -*-
"""
TaoPad 云端真机全功能界面自动化（v14，直呼回传修复版）
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
v10（第七轮证据回灌）：v9 多通道读取+ESC 清浮层仍救不回——E07 起读取
依旧全空，而键盘路径菜单四轮里读取始终正常。结论：鼠标点菜单栏这一
交互本身会拖瘫应用的 UIA Text 供给（软件侧待查缺陷）。v10 改为键盘菜单
为主路径，鼠标点菜单单独设专项对照用例放在收尾（功能验证走内容比对，
不依赖 UIA 读层），并在读取失效时自动 dump 留证。
v11（第八轮证据回灌）：第八轮读层全程存活（键盘菜单生效，坐实鼠标点
菜单栏拖瘫读层的结论），但键盘菜单自身大面积失灵：状态栏停在原语言、
编辑区多出换行——症状指向子进程读取里的 ALT 置前小技巧：按下并释放
ALT 会把菜单栏置为"菜单模式"，随后的 F10 被当成关闭菜单，方向键和回车
漏进编辑区。v11 去掉 ALT 置前，只保留句柄+按标题双通道读取；菜单打开
后加一次可见性验证、未开重试一次；缩放改用底层按键（pywinauto 不认
{ADD} 键名，此前一直被读层故障掩盖）。
覆盖：文件9/编辑16/搜索6/查看3组/语言13/编码5+3/主题3/设置/标签页/状态栏。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
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
APP_WINDOW = None


def esc_clear():
    """模块级：ESC 清浮层。原嵌套在 menu_invoke 的 try 内，connect 失败即未绑定，
    失败收尾路径必然 UnboundLocalError 把 worker 整个带崩（43532793701 A 场实锤）。"""
    try:
        from pywinauto.keyboard import send_keys as _sk
        _sk("{ESC}")
        time.sleep(0.6)
    except Exception:
        pass


def close_menus_uia():
    """v19：UIA 确定性收层（父进程侧入口，worker_run 转发到 worker 内执行）。
    v18 班实锤（run 43554708080 失败截图：E07 现场语言下拉悬空未关）：WinUI MenuBar
    弹出层打开期间主窗 UIA 读层整树返空（状态栏断言得 []、菜单枚举 MISS），且 ESC
    收不掉弹出层时连锁拖垮后续所有用例。本函数返回 worker 的收层输出或 ERR 标记。"""
    return worker_run(["close_menus", str(WIN_HANDLE)])

# ---------------- 子进程工作器 ----------------

def child_bridges(h):
    """WinUI3 正文挂在 DesktopChildSiteBridge 子 hwnd 上（43580989437 实锤：
    顶层窗口 UIA 树只有标题栏按钮+菜单浮层，标签页/编辑器/状态栏整块对
    ControlView 盲——两轮产品侧补挂无效后的采数端换刀）。"""
    out = []
    try:
        import win32gui
        def cb(hc, _):
            try:
                cls = win32gui.GetClassName(hc)
                if 'Bridge' in cls or 'DesktopChildSite' in cls:
                    out.append(hc)
            except Exception:
                pass
        win32gui.EnumChildWindows(h, cb, None)
    except Exception:
        pass
    return out


def bridge_windows(h):
    ws = []
    for hc in child_bridges(h):
        try:
            ws.append(Desktop(backend="uia").window(handle=hc, visible_only=False))
        except Exception:
            continue
    return ws


def rawwalk_texts(h):
    """v24：RawView 直穿——ControlView 下 WinUI3 主窗正文对 pywinauto 全盲
    （43580989437/43582362285 两班实锤：子窗桥通道菜单可达、正文文本仍空）。
    用 UIA RawViewWalker 从目标句柄根节点全树 DFS，收所有非空 Name。
    这就是 inspect.exe 看到的树，等价于真人所见。"""
    names = []
    try:
        import comtypes
        import pywinauto.uia_defines  # noqa: F401  确保 UIAutomationClient 类型库就绪
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        comtypes.CoInitializeEx()
        iuia = comtypes.client.CreateObject(CUIAutomation(), interface=IUIAutomation)
        walker = iuia.RawViewWalker
        # v25：UIA 树不跨 hwnd——主窗根下正文全盲（RAWWALK nodes=1 实锤），
        # 必须把 DesktopChildSiteBridge 等子 hwnd 也当根逐个进树
        handles = [int(h)]
        try:
            from ctypes import wintypes as _wt
            _cb = ctypes.WINFUNCTYPE(_wt.LPARAM, _wt.HWND, _wt.LPARAM)
            kids = []
            def _enum(hc, _lp):
                kids.append(hc)
                return 1
            cb_inst = _cb(_enum)
            _EnumChildWindows = ctypes.windll.user32.EnumChildWindows
            _EnumChildWindows.argtypes = (_wt.HWND, _cb, _wt.LPARAM)
            _EnumChildWindows(_wt.HWND(h), cb_inst, 0)
            handles.extend(kids[:20])
            print("RAWWALK2", f"children={len(kids)}", flush=True)
        except Exception as _e:
            print("RAWWALK2 child-enum ERR", type(_e).__name__, _e, flush=True)
        # v27：子窗桥直连仍摸不到正文（RAWWALK nodes=4 实锤）——改从桌面根全树 DFS，
        # 按 ProcessId 过滤出本进程的全部元素（inspect.exe 等价视角，不依赖 hwnd 归属）
        try:
            _pidbuf = ctypes.c_uint()
            ctypes.windll.user32.GetWindowThreadProcessId(int(h), ctypes.byref(_pidbuf))
            _pid = _pidbuf.value  # v28：第二参才是 PID 出参，返回值是线程号（v27 班实锤全树零命中）
            stack_pid = [iuia.GetRootElement()]
            seen_pid = 0
            pid_names = []
            while stack_pid and seen_pid < 30000:
                cur = stack_pid.pop()
                seen_pid += 1
                try:
                    if cur.CurrentProcessId == _pid:
                        try:
                            n = cur.CurrentName
                            if n and n.strip():
                                pid_names.append(n.strip())
                        except Exception:
                            pass
                except Exception:
                    continue
                try:
                    child = walker.GetFirstChildElement(cur)
                    sibs = []
                    while child is not None and len(sibs) < 400:
                        sibs.append(child)
                        child = walker.GetNextSiblingElement(child)
                    stack_pid.extend(reversed(sibs))
                except Exception:
                    continue
            print("RAWWALK3", f"pid={_pid}, nodes={seen_pid}, named={len(pid_names)}", flush=True)
            if len(pid_names) > len(names):
                names = pid_names
        except Exception as _e:
            print("RAWWALK3 ERR", type(_e).__name__, _e, flush=True)

        stack = []
        seen = 0
        for hcur in handles:
            try:
                stack.append(iuia.ElementFromHandle(hcur))
            except Exception:
                continue
        while stack and seen < 6000:
            cur = stack.pop()
            seen += 1
            try:
                n = cur.CurrentName
                if n and n.strip():
                    names.append(n.strip())
            except Exception:
                pass
            try:
                child = walker.GetFirstChildElement(cur)
                sibs = []
                while child is not None and len(sibs) < 200:
                    sibs.append(child)
                    child = walker.GetNextSiblingElement(child)
                stack.extend(reversed(sibs))
            except Exception:
                pass
        print("RAWWALK", f"nodes={seen}, named={len(names)}", flush=True)
    except Exception as e:
        print("RAWWALK ERR", type(e).__name__, flush=True)
        return []
    return names


def worker_run(argv):
    """独立进程做 UIA 操作，返回 stdout 字符串。v14：兜底超时与异常，
    任何失败都回传明确标记，不让传话通道静默变空。"""
    exe = sys.executable
    try:
        out = subprocess.run([exe, os.path.abspath(__file__), "__worker"] + argv,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=90)
        return out.stdout + out.stderr
    except subprocess.TimeoutExpired as e:
        partial = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else str(e.stdout or "")
        return f"WORKER_TIMEOUT {partial}"
    except Exception as e:
        return f"WORKER_ERR {type(e).__name__}"


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
    print(f"WORKER-ALIVE {mode}", flush=True)   # v15：子进程一进就回执，丢在哪环立刻可见
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
    elif mode == "close_menus":
        # v19：UIA 确定性收层。对每个 MenuBarItem 依次尝试 collapse / expand（切换收起）/
        # click_input（再点一次即收起）三链，任一成功即算收层；全部失败回 ESC 兜底。
        h = int(argv[1])
        closed = 0
        try:
            app = Application(backend="uia").connect(handle=h)
            win = app.window(handle=h)
            for d in win.descendants(control_type="MenuItem"):
                done = False
                for act in ("collapse", "expand", "click_input"):
                    try:
                        getattr(d, act)()
                        done = True
                        break
                    except Exception:
                        continue
                if done:
                    closed += 1
        except Exception as e:
            print(f"CLOSEMENUS ERR:{type(e).__name__}", flush=True)
        print(f"CLOSEMENUS closed={closed}", flush=True)
        if closed == 0:
            try:
                from pywinauto.keyboard import send_keys as _sk
                _sk("{ESC}")
            except Exception:
                pass
    elif mode in ("read_texts", "count_edits", "has_edit", "menu_item_visible", "menu_invoke"):   # v16：白名单漏了 menu_invoke，内层分支从未可达（第十二轮空回音、第十三轮只有进门回执的根因）
        h = int(argv[1])
        title = argv[2] if mode == "menu_item_visible" else None
        # v11：去掉 ALT 置前——按下并释放 ALT 会把应用切进菜单模式，
        # 让随后的 F10 变成"关闭菜单"、方向键漏进编辑区（第八轮实锤）
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

        # 多通道：句柄连接失败或读空时，按标题重找窗口再试；
        # v23：补 DesktopChildSiteBridge 子窗通道（正文 UIA 挂在桥上，43580989437 实锤）
        sources = [w for w in (win,) if w is not None] + bridge_windows(h) + [None]
        raw_names = rawwalk_texts(h)   # v24：RawView 直穿兜底
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
            if not names and raw_names:
                names = raw_names
            if not names:
                # v20 空读诊断：顶层窗口普查 + 主窗原始后代计数——定位死树范围
                try:
                    _census = []
                    for _w in Desktop(backend="uia").windows():
                        try:
                            _census.append(f"h={_w.handle},pid={_w.process_id()},t={(_w.window_text() or '')[:24]!r}")
                        except Exception:
                            _census.append("<enum-err>")
                    print("CENSUS", " | ".join(_census) if _census else "<desktop-empty>", flush=True)
                    try:
                        _raw = len(win.descendants()) if win is not None else -1
                    except Exception as _e:
                        _raw = f"ERR:{type(_e).__name__}"
                    print(f"RAWDESC {_raw}", flush=True)
                except Exception as _e:
                    print(f"CENSUS-ERR {type(_e).__name__}", flush=True)
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
        elif mode == "menu_invoke":
            # v13：UIA 直呼菜单——无鼠标无键盘、不经焦点，直接触发菜单项 Click。
            # 第十轮查明键盘路径从未真正点中下拉项（查看/主题用例仅截图无断言，
            # 语言/编码状态栏从未变过），故改走 UIA。titles 以 | 连接传入。
            titles = (argv[2] if len(argv) > 2 else "").split("|")
            h = int(argv[1])   # v14：本分支此前漏定义 h，连接必抛 NameError
            print("MENUINVOKE start", flush=True)   # v14：实时回传，防崩溃丢缓冲
            found = "ERR:none"
            try:
                win2 = Application(backend="uia").connect(handle=h).window(handle=h)
                pid = win2.process_id()

                def same_pid():
                    res = []
                    try:
                        for w in Desktop(backend="uia").windows():
                            try:
                                if w.process_id() == pid:
                                    res.append(w)
                            except Exception:
                                continue
                    except Exception:
                        pass
                    return res

                for idx, tname in enumerate(titles):
                    target = None
                    for attempt in range(3):   # v17：枚举不到先清浮层再重试
                        scopes = [win2] + bridge_windows(h) + (same_pid() if idx == 0 else [])   # v19：顶级项也扫同进程窗口（父浮层未收起时菜单栏可能挂在弹层）；v23 补桥通道
                        for scope in scopes:
                            try:
                                for d in scope.descendants(control_type="MenuItem"):
                                    try:
                                        if (d.window_text() or "").strip() == tname:
                                            target = d
                                            break
                                    except Exception:
                                        continue
                            except Exception:
                                pass
                            if target is not None:
                                break
                        if target is not None or attempt == 2:
                            break
                        print("MENUINVOKE", f"retry{attempt+1}:{tname}", flush=True)
                        esc_clear()
                    if target is None:
                        found = f"MISS:{tname}"
                        break
                    if idx == len(titles) - 1:
                        ok = False
                        for action in ("invoke", "select", "expand", "toggle", "click", "click_input"):
                            # v18：尝试链补 toggle/click——ToggleMenuFlyoutItem 的
                            # SelectionItem/Invoke 均缺，Toggle/Click 是它真有的 pattern
                            try:
                                getattr(target, action)()
                                ok = True
                                break
                            except Exception:
                                continue
                        if not ok:
                            # v19（43554708080 实锤 NOINVOKE:Python）：UIA 动作链全失败时
                            # 用元素真实矩形做鼠标点击兜底（无键盘、无误触退出风险）
                            try:
                                r = target.rectangle()
                                x = (r.left + r.right) // 2
                                y = (r.top + r.bottom) // 2
                                ctypes.windll.user32.SetCursorPos(x, y)
                                ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                                ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                                ok = True
                            except Exception:
                                ok = False
                        found = "OK" if ok else f"NOINVOKE:{tname}"
                    else:
                        ok2 = False
                        try:
                            target.invoke()
                            ok2 = True
                        except Exception:
                            pass
                        if not ok2:
                            try:
                                target.select()
                                ok2 = True
                            except Exception:
                                pass
                        if not ok2:
                            found = f"NOEXPAND:{tname}"
                            break
                        # v19：弹出层 hwnd 就绪有延迟（r19 实锤 0.8s 常常不够，导致下一级
                        # 枚举 MISS）。改为轮询等待下一级菜单项出现，最多 4 秒。
                        _next_t = titles[idx + 1]
                        _deadline = time.time() + 4.0
                        while time.time() < _deadline:
                            _hit = False
                            try:
                                for w2 in ([win2] + bridge_windows(h) + same_pid()):
                                    try:
                                        for d2 in w2.descendants(control_type="MenuItem"):
                                            try:
                                                if (d2.window_text() or "").strip() == _next_t:
                                                    _hit = True
                                                    break
                                            except Exception:
                                                continue
                                    except Exception:
                                        pass
                                    if _hit:
                                        break
                            except Exception:
                                pass
                            if _hit:
                                break
                            time.sleep(0.5)
            except Exception as e:
                found = f"ERR:{type(e).__name__}"
            if not found.startswith(("OK", "ERR:none")):
                # v19：失败收尾改 UIA 确定性收层——ESC 收不住 MenuBar 弹出层是
                # r19 实锤根因（run 43554708080 失败截图：语言下拉悬空未关）。
                # 对每个 MenuItem 依次 collapse/expand/click_input 收层，
                # 全部失败再兜一轮 ESC。防悬层拖垮下一条用例。
                _closed = 0
                try:
                    for _d in win2.descendants(control_type="MenuItem"):
                        for _act in ("collapse", "expand", "click_input"):
                            try:
                                getattr(_d, _act)()
                                _closed += 1
                                break
                            except Exception:
                                continue
                except Exception:
                    pass
                if _closed > 0:
                    time.sleep(0.4)
                else:
                    esc_clear()   # v17：UIA 收层全败时再清一次浮层
                    try:
                        from pywinauto.keyboard import send_keys as _sk2
                        _sk2("{ESC}")
                        time.sleep(0.4)
                    except Exception:
                        pass
            print("MENUINVOKE", found)
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

def mem_probe(tag):
    """逐用例内存探针：记录 python 与 TaoPad 进程工作集到 ui-evidence/memlog.csv。
    目的：第四轮 ui-automation 于 ~57 分钟同象失联（runner lost communication），
    下一轮以内存曲线定谳泄漏归属（应用泄漏 / 测试器泄漏 / 其他资源）。"""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=60).stdout
        rows = [l.strip() for l in out.splitlines() if ("TaoPad" in l or "python" in l)]
        with open(os.path.join(EVID, "memlog.csv"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S") + "," + tag.replace(",", ";") + ",rows=" + str(len(rows)) + "\n")
            for l in rows:
                f.write(l + "\n")
    except Exception as e:
        print("mem_probe失败", tag, e, flush=True)

def shot(name):
    p = os.path.join(EVID, name + ".png")
    try:
        ImageGrab.grab().save(p)
    except Exception as e:
        print("截图失败", name, e)
    return p


def flush_report():
    try:
        report = {"cases": RESULTS, "total": len(RESULTS),
                  "failed": [r["case"] for r in RESULTS if r["result"] == "FAIL"]}
        with open(os.path.join(EVID, "report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("flush_report失败", e, flush=True)

def record(name, ok, detail=""):
    if ok in ("PASS", "FAIL", "SKIP"):
        result = ok
    else:
        result = "PASS" if ok else "FAIL"
    RESULTS.append({"case": name, "result": result, "detail": detail})
    print(f"[{result}] " + name + (("  --  " + detail) if detail else ""), flush=True)
    flush_report()


def refocus_app():
    r"""hosted agent 控制台会间歇抢走前台，导致 send_keys 误入控制台；
    证据：失败截图里前台是 C:\ProgramData\GitHub\Host 终端，TaoPad 被压在后面。
    每个用例执行前把应用窗口拉回前台。"""
    try:
        if APP_WINDOW is not None:
            APP_WINDOW.set_focus()
    except Exception:
        pass

def app_alive():
    """应用进程存活探针：TaoPad.exe 不在进程表 = 本班已崩，余下用例不空跑。"""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=60).stdout
        return any("TaoPad.exe" in l for l in out.splitlines())
    except Exception:
        return True   # 探针失败不误判崩


def collect_crash_scene():
    """崩溃现场取证：crash/trace 日志、LocalDumps 转储、WER 报告、应用事件日志
    全部落 ui-evidence/crash-scene/，随证据包上传。五班 E07 恒崩却零现场，
    根因无法定位的缺口就是这一步。"""
    try:
        dest = os.path.join(EVID, "crash-scene")
        os.makedirs(dest, exist_ok=True)
        local = os.environ.get("LOCALAPPDATA", "")
        roots = [os.path.join(local, "TaoPad"),
                 r"D:\TaoPadData\TaoPad",
                 os.path.join(local, r"Microsoft\Windows\WER"),
                 os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\WER")]
        for root in roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root):
                if not ("TaoPad" in dirpath or any("TaoPad" in f for f in files)):
                    continue
                rel = re.sub(r"[^0-9A-Za-z_.-]", "_", os.path.relpath(dirpath, root))
                tgt = os.path.join(dest, rel)
                os.makedirs(tgt, exist_ok=True)
                for f in files:
                    try:
                        shutil.copy2(os.path.join(dirpath, f), os.path.join(tgt, f))
                    except Exception:
                        pass
        # 应用事件日志近 2 小时 TaoPad 相关条目（.NET Runtime/Windows Error Reporting 崩溃都在这里）
        try:
            ps = ("Get-WinEvent -FilterHashtable @{LogName='Application';StartTime=(Get-Date).AddHours(-2)} "
                  "-ErrorAction SilentlyContinue | "
                  "Where-Object { $_.Message -match 'TaoPad' -or $_.ProviderName -match 'TaoPad' } | "
                  "Format-List TimeCreated,ProviderName,Id,LevelDisplayName,Message | Out-String -Width 400")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=120)
            with open(os.path.join(dest, "application-events.txt"), "w", encoding="utf-8") as f:
                f.write(out.stdout or out.stderr or "")
        except Exception as e:
            print("事件日志收集失败", e, flush=True)
        print("崩溃现场已收集到", dest, flush=True)
    except Exception as e:
        print("崩溃现场收集失败", e, flush=True)


DEAD_MARKED = False

def case(name, fn):
    global DEAD_MARKED
    mem_probe(name)
    if not app_alive():
        if not DEAD_MARKED:
            DEAD_MARKED = True
            collect_crash_scene()
            shot("CRASH-scene-desktop")
        record(name, "SKIP", "应用进程已消失，跳过余下用例（崩溃现场已收集到 crash-scene/）")
        return
    refocus_app()
    try:
        fn()
        record(name, True)
    except Exception as e:
        record(name, False, f"[{type(e).__name__}] {str(e)[:280]}")
        shot("FAIL-" + re.sub(r"[^0-9A-Za-z_-]", "_", name))
        if not app_alive():   # 用例失败后进程也没了：立即抓崩溃现场
            DEAD_MARKED = True
            collect_crash_scene()
            shot("CRASH-scene-desktop")


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


def _open_top_keyboard(t):
    send_keys("{F10}")
    time.sleep(0.9)
    for _ in range(TOPMENUS.index(t)):
        send_keys("{RIGHT}")
        time.sleep(0.35)
    send_keys("{ENTER}")
    time.sleep(1.0)


def menu(*titles):
    """v18：主路径 UIA 直呼；直呼失败**禁用键盘回退**——定谳班 43552147010
    调用栈实锤：五班 E07 进程"安静消失"= 键盘回退乱序键入误触「文件→退出」
    （F10/RIGHT/ENTER/DOWN 落点不可控，ENTER 点中退出项 → OnExit → ExitAll
    → Environment.Exit(0)，无崩溃痕迹）。v18 直呼失败改为 ESC 清浮层后再试
    一轮直呼（worker 自带 3 次枚举重试），仍失败就让用例断言失败——
    宁可 FAIL 本用例，不可误触退出拖死整班。"""
    close_panel()
    out = worker_run(["menu_invoke", str(WIN_HANDLE), "|".join(titles)])
    ok = "MENUINVOKE OK" in out
    print(f"菜单[{'>'.join(titles)}]UIA直呼: {out!r}", flush=True)   # v15：repr 原样回显，空与不可见字符可辨
    try:   # v15：回执落盘，随证据文件上传，绕开任何管道疑虑
        with open(os.path.join(EVID, "menu_invoke_trace.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} menu({'|'.join(titles)}) -> {out!r}\n")
    except Exception:
        pass
    if not ok:
        # v18：ESC 清浮层后再试一轮直呼；键盘回退已废弃（误触退出实锤）
        try:
            from pywinauto.keyboard import send_keys as _sk
            _sk("{ESC}")
            time.sleep(0.6)
        except Exception:
            pass
        out = worker_run(["menu_invoke", str(WIN_HANDLE), "|".join(titles)])
        ok = "MENUINVOKE OK" in out
        print(f"菜单[{'>'.join(titles)}]UIA直呼重试: {out!r}", flush=True)
        try:
            with open(os.path.join(EVID, "menu_invoke_trace.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} menu-retry({'|'.join(titles)}) -> {out!r}\n")
        except Exception:
            pass
    # v19：无论成败，确定性收净 MenuBar 弹出层——r19 实锤悬空下拉导致主窗
    # UIA 读层整树返空、后续用例连锁全挂。收层后再读状态栏与下一个用例才可靠。
    try:
        _cm = close_menus_uia()
        print(f"菜单收层回执: {_cm!r}", flush=True)   # v20：回执显式可见，收层成效可判
    except Exception as _e:
        print(f"菜单收层异常: {type(_e).__name__}", flush=True)
    if ok:
        print(f"读层存活: {read_alive()}", flush=True)
        if dialog_present():
            click_editor()   # 下拉未自动收起时点编辑区收尾
        return
    # v18：两轮直呼都失败，放弃本菜单操作（用例稍后以状态栏断言 FAIL 收场）。
    # 不再 send_keys 键盘回退——那会误触「文件→退出」终结整个班次。
    print(f"菜单[{'>'.join(titles)}]两轮直呼失败，放弃键盘回退（v18 防误触退出）", flush=True)


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
            worker_dump()   # 读取失效现场留证：看 UIA 树里还剩什么
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


def focus_main():
    """v12：把主窗口拉回前台再发键。v10 的 ALT 置前曾靠每个读取进程反复
    SetForegroundWindow 顺手锚定焦点，v11 撤掉后保存/打开链路失焦红掉
    （O01-O04 连锁）。改用 pywinauto set_focus（AttachThreadInput 实现，
    不像 ALT 按放会把应用切进菜单模式）。"""
    try:
        from pywinauto import Application
        Application(backend="uia").connect(handle=WIN_HANDLE).window(handle=WIN_HANDLE).set_focus()
        time.sleep(0.3)
    except Exception:
        pass


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
    # 审查专项修复：注释和弦必须同一事件串连发（^kc / ^ku）。
    # 原 "^k" 与 "c" 分两段发送，第二段被当普通字符插入、命令未触发，
    # 还会把 "c"/"u" 写进正文（E07 四班恒崩实锤）。
    send_keys("^kc")
    time.sleep(0.7)
    n1 = len(editor_clipboard())
    assert n1 > n0, f"注释未生效 {n0}->{n1}"
    send_keys("^a")
    time.sleep(0.25)
    send_keys("^ku")
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


def zoom_hotkey(vk_code):
    """v11：pywinauto 不认 {ADD} 键名（此前一直被读层故障掩盖），改底层按键"""
    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)      # Ctrl down
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
    ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)      # Ctrl up
    time.sleep(0.8)


def c_zoom():
    click_editor()
    esc_cleanup()
    z0 = zoom_val()
    zoom_hotkey(0x6B)          # Ctrl+小键盘加号 = 放大
    z1 = zoom_val()
    assert z1 > z0, f"放大未生效 {z0}->{z1}"
    zoom_hotkey(0x6B)
    z2 = zoom_val()
    assert z2 > z1, f"放大第二次未生效 {z1}->{z2}"
    shot("case-zoom-in")
    zoom_hotkey(0x6D)          # Ctrl+小键盘减号 = 缩小
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
    focus_main()
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("save-me-内容")
    focus_main()
    send_keys("^s")
    time.sleep(0.6)
    picker_typing(FILE1)
    assert os.path.exists(FILE1), "保存后文件不存在: " + FILE1
    shot("case-save")


def c_open():
    esc_cleanup()
    focus_main()
    send_keys("^o")
    time.sleep(0.6)
    picker_typing(FILE1)
    time.sleep(1.2)
    got = editor_clipboard().strip()
    assert got == "save-me-内容", f"打开后内容不对: {got!r}"
    shot("case-open")


def c_save_as():
    focus_main()
    click_editor()
    type_text(" extra")
    focus_main()
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
    # 剪贴板回读带 \r\n、历史键入偶发漂移，按去空白口径核对是否打开了正确文件
    got_nospace = re.sub(r"\s+", "", got)
    assert got_nospace.startswith("save-me-内容"), f"最近文件打开后内容不对: {got!r}"


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
        focus_main()
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


def c_mouse_menu():
    """鼠标路径专项对照：真实坐标点击菜单栏「文件」→键盘导航到「新建」。
    功能验证走内容比对（新建后应是空编辑区），不依赖 UIA 读层——
    鼠标点菜单栏疑似会拖瘫应用 UIA Text 供给，此用例用于复现与留证。"""
    close_panel()
    ok = worker_click_menu("文件")
    time.sleep(1.0)
    for _ in range(MENUS["文件"].index("新建")):
        send_keys("{DOWN}")
        time.sleep(0.3)
    send_keys("{ENTER}")
    time.sleep(1.2)
    if not dialog_present():
        click_editor()
    esc_cleanup()
    click_editor()
    type_text("mouse-path-ok")
    clip = re.sub(r"\s+", "", editor_clipboard())
    assert clip == "mouse-path-ok", (
        f"鼠标路径菜单未建成新标签（内容残留）: {clip[-60:]!r}")
    shot("case-mouse-menu")
    # 留证：鼠标菜单交互后 UIA 读层是否还活着（打印探针结果，不作为断言）
    print("鼠标路径后读取探针:", "存活" if read_alive() else "失效", flush=True)


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


def install_session_keepalive():
    """对症自救：GitHub hosted Windows runner 的交互会话约 60 分钟被断开，
    五轮 ui-automation 恒定 ~57 分钟 runner lost communication 与该坑吻合。
    手段：1) 关屏保与电源空闲超时；2) 后台线程每 20s 微动鼠标保持会话活跃。"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, "ScreenSaveActive", 0, winreg.REG_SZ, "0")
        winreg.CloseKey(k)
    except Exception as e:
        print("屏保设置失败", e, flush=True)
    for cmd in (["powercfg", "/change", "standby-timeout-ac", "0"],
                ["powercfg", "/change", "monitor-timeout-ac", "0"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:
            pass
    try:
        import ctypes.wintypes
        def _kick():
            pt = ctypes.wintypes.POINT()
            while True:
                try:
                    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                        ctypes.windll.user32.SetCursorPos(pt.x + 1, pt.y)
                        ctypes.windll.user32.SetCursorPos(pt.x, pt.y)
                except Exception:
                    pass
                time.sleep(20)
        th = threading.Thread(target=_kick, daemon=True)
        th.start()
        print("session keepalive installed", flush=True)
    except Exception as e:
        print("keepalive 启动失败", e, flush=True)

def main():
    global WIN_HANDLE
    if sys.argv[1:2] == ["__worker"]:
        worker_main(sys.argv[2:])
        return
    install_session_keepalive()
    exe = find_exe()
    print("exe:", exe, flush=True)
    from pywinauto import Application, Desktop
    app = Application(backend="uia").start(exe, timeout=25)
    time.sleep(12)
    # 把宿主机 agent/PowerShell 控制台窗口全部最小化，防抢前台（证据：FAIL 截图前台为其终端）
    try:
        for w in Desktop(backend="uia").windows(visible_only=True):
            t = (w.window_text() or "")
            if t.startswith("C:\\") or ("GitHub" in t and "Host" in t):
                try:
                    w.minimize()
                    print("已最小化控制台窗口:", t[:60], flush=True)
                except Exception:
                    pass
    except Exception as e:
        print("控制台最小化失败", e, flush=True)
    win = Desktop(backend="uia").window(title_re=".*TaoPad.*", visible_only=True)
    win.set_focus()
    WIN_HANDLE = win.handle
    global APP_WINDOW
    APP_WINDOW = win
    time.sleep(1)
    worker_dump()

    ALL_CASES = [
        ("S01 启动就绪与状态栏", c_startup),
        ("O08a 新建标签", c_new_tab),
        ("E01 输入/全选/复制/撤销/重做", c_type_undo_redo),
        ("E02 剪切/粘贴", c_cut_copy_paste),
        ("E03 插入时间日期(F5)", c_insert_time),
        ("E04 行操作(复制/上移/下移/删除)", c_line_ops),
        ("E05 大小写转换", c_case_convert),
        ("E06 格式化文档", c_format),
        ("E07 注释/取消注释(菜单)", c_comment),
        ("F01 查找面板/F3/F3反向", c_find_panel),
        ("F02 替换面板", c_replace_panel),
        ("F03 转到行", c_goto),
        ("F04 在文件中查找", c_find_in_files),
        ("V01 缩放(放大/缩小/复位)", c_zoom),
        ("V02 自动换行切换", c_wrap_toggle),
        ("V03 显示行号切换", c_lineno_toggle),
        ("T01 主题三套切换", c_themes),
        ("C01 保存编码5种", c_encodings),
        ("C02 换行符3种", c_eols),
        ("L01 语言13种逐一切换", c_languages),
        ("O01 保存(Ctrl+S→选择器)", c_save),
        ("O02 打开(Ctrl+O→选择器)", c_open),
        ("O03 另存为", c_save_as),
        ("O04 全部保存", c_save_all),
        ("O05 最近文件菜单", c_recent_menu),
        ("O06 导出可打印HTML", c_export_html),
        ("O07 标签页新增/切换/关闭", c_tabs_and_close),
        ("T02 设置对话框(开关+主题+应用)", c_settings),
        ("O08b 鼠标路径菜单对照", c_mouse_menu),
        ("O09 正常退出+崩溃检查", c_exit),
    ]
    part = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
    if part in ("A", "B"):
        sel = ALL_CASES[:14] if part == "A" else ALL_CASES[14:]
        print(f"半场 {part}：{len(sel)} 用例", flush=True)
    else:
        sel = ALL_CASES
    try:
        for name, fn in sel:
            case(name, fn)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        try:
            with open(os.path.join(EVID, "crash.txt"), "w", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
        sys.exit(2)

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
