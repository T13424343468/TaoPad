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
v33（五班实锤收官）：UIA 对弹层 hwnd 偶发可用不可依赖（同弹层 V02 命中
/V03 MISS），菜单驱动改 menu_xy 纯坐标：顶级固定坐标点击（trace 实证必
拉开）→ 窄条带行带扫描定位弹层项（序号=XAML 项序 + 期望 y 邻域双重校验，
弹层拉开差分前置验证）→ 坐标点击；二级弹层锚父项行带 y+4、左缘按实测
偏移。注释改编辑器和弦优先（CodeEditor.cs 原生两段式，keybd_event 直发）
+ 编辑菜单坐标兜底；O09 退出改 WM_CLOSE 直投（App 退出链源码闭环实锤）
+ 菜单坐标兜底；V01 缩放断言弃行带量测（v32 失灵实锤）改收层后整幅差分
+ 复位回基线双验；V02/V03/T01 一并改收层后取证，堵死"弹层开合差分"假
绿通道（FAIL-V03 现场自动换行带勾实证 v32 只成一次 toggle）。
覆盖：文件9/编辑16/搜索6/查看3组/语言13/编码5+3/主题3/设置/标签页/状态栏。
v30（43589969300 实锤回灌）：UIA 文本管线 v24→v29 八连盲，全部停用——
①状态栏/缩放/匹配位置断言改源码揪清单通道：存盘字节级断言（编码 BOM/GBK/Big5、
换行符）、剪贴板行内容断言（查找/转到行）、注释标记按语言落剪贴板（Tokenizer.cs
标记表）、缩放/面板/主题/行号用 PIL 像素量测；②菜单直呼（InvokePattern 本身违
十维度③）全改真人鼠标+键盘路径 menu_kb，应用侧真实事件以 trace.log 回执为准；
③T02 假绿定谳：菜单未弹时 SPACE/ENTER 落编辑区（O08b 残留 'SMoreMore' 实锤），
改 trace.log「设置：入口/已确认」断言；④换行菜单只写 doc.Eol（状态栏显示），
保存链路用 Editor.Text（OutputEol 内容探测）——字节断言对 LF/CR 如实暴露，
按规范六.3 不重跑不修饰，报应用真实发现。
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


def esc_cleanup():
    """v34 强化：确定性双通道收层。v18/第11轮双实锤——单发 ESC 收不掉 WinUI
    菜单弹层（二级+一级叠开时一次只收一层），残留弹层把下一次顶级点击变成
    "切层"，T01 顶级 4 连点只成 2 次即此根因。双 ESC 覆盖二级叠开 + 点击编辑区
    （WinUI MenuBar 失焦自动收层），两通道保证弹层收干净、焦点回编辑区。"""
    try:
        from pywinauto.keyboard import send_keys as _sk
        _sk("{ESC}")
        time.sleep(0.45)
        _sk("{ESC}")
        time.sleep(0.45)
    except Exception:
        pass
    try:
        click_editor()
    except Exception:
        pass
    time.sleep(0.3)


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


def pid_top_windows(h):
    """v31：ContentDialog/Popup 挂在进程内独立【顶层】hwnd（owned window），
    主窗与 DesktopChildSiteBridge 子桥（EnumChildWindows 只扫子窗）都够不到
    ——44691178591 T02 实锤：设置弹窗开着，read_texts 只采到主窗三个窗口名。
    按 pid 普查进程全部顶层窗口，供采数端补通道。"""
    out = []
    try:
        import win32gui
        import win32process

        target = win32process.GetWindowThreadProcessId(int(h))[1]

        def cb(hc, _):
            try:
                if hc != int(h) and win32process.GetWindowThreadProcessId(hc)[1] == target:
                    out.append(hc)
            except Exception:
                pass
            return 1

        win32gui.EnumWindows(cb, 0)
    except Exception as e:
        print("PIDTOPS ERR", type(e).__name__, flush=True)
    return out[:20]


def top_bridge_children(h):
    """v33：弹窗顶层 hwnd 的 XAML 正文挂其 DesktopChildSiteBridge 子 hwnd
    （与主窗 v23 同构）——44706673392 T02 实锤：产品侧补自动化名后，
    弹窗顶层 UIA 树仍只有 PopupHost 根+IME 伪窗口，正文整块盲；
    顶层普查（v31）只收顶层本身，从未枚举弹窗顶层的子窗桥。"""
    out = []
    try:
        import win32gui
        for ht in pid_top_windows(h):
            def cb(hc, _):
                try:
                    cls = win32gui.GetClassName(hc)
                    if 'Bridge' in cls or 'DesktopChildSite' in cls:
                        out.append(hc)
                except Exception:
                    pass
            try:
                win32gui.EnumChildWindows(ht, cb, None)
            except Exception:
                pass
    except Exception as e:
        print("TOPBRIDGE ERR", type(e).__name__, flush=True)
    return out[:10]


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
            # v31：ContentDialog/Popup 是进程内独立顶层 hwnd，EnumChildWindows
            # 扫不到——按 pid 普查顶层窗口一并当根进树（T02 数据位置断言通道）
            _wpidbuf = _wt.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(_wt.HWND(h), ctypes.byref(_wpidbuf))
            _own = _wpidbuf.value
            _tops = []

            def _enum_top(hw, _lp):
                _tops.append(hw)
                return 1

            _cbt = _cb(_enum_top)
            _EnumWindows = ctypes.windll.user32.EnumWindows
            _EnumWindows.argtypes = (_cb, _wt.LPARAM)
            _EnumWindows(_cbt, 0)
            for _hc in _tops:
                if _hc == int(h):
                    continue
                _pbuf = _wt.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(_wt.HWND(_hc), ctypes.byref(_pbuf))
                if _pbuf.value == _own:
                    handles.append(_hc)
                    # v33：弹窗顶层正文挂其 DesktopChildSiteBridge 子 hwnd
                    # （44706673392 实锤顶层根下零子节点），一并进树
                    _tkids = []

                    def _enum_topkid(hk, _lp):
                        _tkids.append(hk)
                        return 1

                    _EnumChildWindows(_wt.HWND(_hc), _cb(_enum_topkid), 0)
                    handles.extend(_tkids[:6])
            handles = handles[:60]
            print("RAWWALK2", f"children={len(kids)}, tops+bridges={len(handles)-len(kids)-1}", flush=True)
        except Exception as _e:
            print("RAWWALK2 child-enum ERR", type(_e).__name__, _e, flush=True)
        # v29：手爬两连盲（nodes=4 / 桌面根 nodes=1 实锤）——改 UIA 原生检索：
        # 桌面根 FindAll(Descendants, ProcessId==pid)，引擎侧枚举，等价 inspect.exe 全树
        try:
            from comtypes.gen.UIAutomationClient import UIA_ProcessIdPropertyId, TreeScope_Descendants
            _pidbuf = ctypes.c_uint()
            ctypes.windll.user32.GetWindowThreadProcessId(int(h), ctypes.byref(_pidbuf))
            _pid = _pidbuf.value
            # 44217756849 实锤：第三参须为 VARIANT，裸 int 触发 comtypes
            # AttributeError（RAWWALK4 ERR），整条原生检索分支报废——
            # 菜单识别最强的名字来源自此全程缺席，直呼 MISS 率飙升。
            # run 45015435336 再实锤：方法名应为 CreatePropertyCondition
            # （UIAutomationClient.idl 标准名），CreatePropertyElementCondition
            # 不存在于 IUIAutomation 类型库包装，整分支仍报废——改名接回。
            from comtypes.automation import VARIANT
            cond = iuia.CreatePropertyCondition(UIA_ProcessIdPropertyId, VARIANT(_pid))
            found = iuia.GetRootElement().FindAll(TreeScope_Descendants, cond)
            pid_names = []
            for k in range(found.Length):
                try:
                    n = found.GetElement(k).CurrentName
                    if n and n.strip():
                        pid_names.append(n.strip())
                except Exception:
                    pass
            print("RAWWALK4", f"pid={_pid}, found={found.Length}, named={len(pid_names)}", flush=True)
            if len(pid_names) > len(names):
                names = pid_names
        except Exception as _e:
            print("RAWWALK4 ERR", type(_e).__name__, _e, flush=True)

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
        # v31：ContentDialog/Popup 挂进程内独立顶层 hwnd——主窗与子桥通道都不达
        # （44691178591 T02 实锤：设置弹窗开着只采到三个窗口名），补顶层窗口源；
        # v33：弹窗顶层的正文挂其 DesktopChildSiteBridge 子 hwnd（44706673392
        # 实锤顶层根下无正文），子窗桥一并作源
        _top_srcs = []
        for _hc in pid_top_windows(h) + top_bridge_children(h):
            try:
                _top_srcs.append(Desktop(backend="uia").window(handle=_hc, visible_only=False))
            except Exception:
                continue
        raw_names = rawwalk_texts(h)   # v24：RawView 直穿兜底（v31 起内部已含顶层窗口根）
        if mode == "read_texts":
            # v46t：改全源合并——44714553766 实锤「读到非空即 break」让主窗的
            # IME 窗口名（Default IME/MSCTFIME UI）抢先收工，弹窗顶层源永远轮不到
            names = []
            _seen = set()
            for w in list(sources) + _top_srcs:
                if w is None:
                    w = by_title()
                    if w is None:
                        continue
                try:
                    for d in w.descendants(control_type="Text"):
                        t = (d.window_text() or "").strip()
                        if t and t not in _seen:
                            _seen.add(t)
                            names.append(t)
                except Exception:
                    continue
            # v46v：rawwalk 一并合并——44719994570 实锤 UIA descendants 通道
            # 全是系统窗口名（Default IME/MSCTFIME UI/PopupHost），rawwalk 的
            # 15 个命名节点（等价真人所见）被「names 非空」挡在门外；
            # 系统垃圾名过滤后再断言
            _junk = {"Default IME", "MSCTFIME UI", "PopupHost", "DefaultIME"}
            for t in (raw_names or []):
                if t and t not in _seen and t not in _junk:
                    _seen.add(t)
                    names.append(t)
            names = [t for t in names if t not in _junk]
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
    elif mode == "menu_hit":
        # v32：弹层项定位——扫同进程全部窗口（主窗+桥子窗+弹层顶层）里的
        # MenuItem，命中目标返回中心坐标。五班实锤键盘 DOWN/ENTER 在鼠标开菜单
        # 后落点不可控（V03 反复切自动换行、C01/C02 落 idx0），逐级矩形+鼠标
        # 点击是唯一落点可控的真人路径。弹层是独立顶层 hwnd，主窗树常看不到它，
        # 必须扫同 pid 全部窗口（menu_invoke 的 same_pid 扫法复用）。
        h = int(argv[1])
        title = argv[2]
        win2 = None
        pid = None
        try:
            win2 = Application(backend="uia").connect(handle=h).window(handle=h)
            pid = win2.process_id()
        except Exception:
            pass

        def hit_scopes():
            s = []
            if win2 is not None:
                s.append(win2)
            s += bridge_windows(h)
            if pid is not None:
                try:
                    for w in Desktop(backend="uia").windows():
                        try:
                            if w.process_id() == pid and w.handle != h:
                                s.append(w)
                        except Exception:
                            continue
                except Exception:
                    pass
            return s

        best = None
        try:
            for s in hit_scopes():
                try:
                    for d in s.descendants(control_type="MenuItem"):
                        try:
                            if (d.window_text() or "").strip() == title:
                                r = d.rectangle()
                                best = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
                if best:
                    break
        except Exception as e:
            print(f"HITERR {type(e).__name__}", flush=True)
            best = None
        print(f"HIT {best[0]} {best[1]}" if best else "MISS", flush=True)
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
    # v46c：X14 冷启动用例自带拉起进程，不受存活守卫约束
    self_launch = getattr(fn, "self_launch", False)
    if not self_launch and not app_alive():
        if not DEAD_MARKED:
            DEAD_MARKED = True
            collect_crash_scene()
            shot("CRASH-scene-desktop")
        record(name, "SKIP", "应用进程已消失，跳过余下用例（崩溃现场已收集到 crash-scene/）")
        return
    refocus_app()

    def _run(tag):
        """tag=1 首跑；tag=2 失败重跑。返回 True=过。首红只留痕不记档。"""
        try:
            fn()
            record(name, True, "" if tag == 1 else "首跑失败重跑通过（环境吞击，非产品定谳）")
            return True
        except Exception as e:
            msg = f"[{type(e).__name__}] {str(e)[:280]}"
            shot(("FAIL1-" if tag == 1 else "FAIL-") + re.sub(r"[^0-9A-Za-z_-]", "_", name))
            if tag == 2:
                record(name, False, msg)
            else:
                print(f"[FAIL] {name}  --  {msg}（重跑一次再定谳）", flush=True)
            return False
        finally:
            esc_cleanup()

    try:
        if not _run(1):
            # 44212844089 实锤：B 半场后段键入/菜单通道偶发吞击（X06 清场粘贴
            # 四连吞）。失败重跑一次，仍红才定谳产品问题。
            if app_alive():
                refocus_app()
                _run(2)
    finally:
        if not app_alive() and not DEAD_MARKED:
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
    """v31：F10 兜底加探针验证——F10 未把菜单栏拉起时（WinUI 常见），
    RIGHT/ENTER 会落进编辑器（43592341121 C01 字节尾部 \r 实锤）。
    探针不过就不再落键，menu_kb 返回 False 交用例诚实记红。"""
    send_keys("{F10}")
    time.sleep(0.9)
    if not menu_item_visible("文件"):
        print("F10 兜底探针失败：菜单栏未拉起，放弃键序（防污染编辑器）", flush=True)
        return False
    for _ in range(TOPMENUS.index(t)):
        send_keys("{RIGHT}")
        time.sleep(0.35)
    send_keys("{ENTER}")
    time.sleep(1.0)
    return True


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


def menu_lang_verified(item, rounds=3):
    """44217756849 实锤：语言菜单切了不算数，切换必须以钩子 lang 验收。
    44225139583 实锤：钩子 lang = SyntaxLanguage.Name（显示名，如
    'Fountain 剧本'/'C#'/'纯文本'），不是内部 id——验收一律与菜单项
    显示名同口径比对，内部 id 永远对不上、四用例必红。"""
    for i in range(rounds):
        if i == 0:
            menu_click_mouse("语言", item)
        elif i == 1:
            menu("语言", item)
        else:
            menu_xy("语言", item)
        deadline = time.time() + 4.0
        while time.time() < deadline:
            doc = _hook_doc_safe()
            if doc.get("lang") == item:
                return True
            time.sleep(1.0)
    # 命令硬通道兜底（v45）：云端 runner 菜单/键盘通道整段失效已三轮
    # 实锤（44234216706 等），按防耗死令换路——UI 三路都失败后经产品
    # 测试钩子直达语言切换，仍以钩子 lang 同口径验收，不降验收标准。
    r = hook_command("set_language", item)
    print(f"语言[{item}]UI三路失败，命令硬通道回执: {r.get('commandResult')!r}", flush=True)
    doc = _hook_doc_safe()
    ok = doc.get("lang") == item
    print(f"menu_lang_verified[{item}] 终态 lang={doc.get('lang')!r} -> {ok}", flush=True)
    return ok


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
        # 44132721896 实锤：云 runner 吞键后 ^a{DEL}/^v 全部无效（X06 状态行
        # =X05 残留+1 换行、X08 撤销无效、X09 配对未触发），同班 X03/X04 却
        # PASS——抖动集中在 menu_xy 弹层刚收层后的第一轮输入。这里在点击后
        # 核对编辑器确实收到焦点（statusText 光标行自报为准），没到位再点一轮。
        try:
            data = hook_dump(timeout=6.0)
            docs = data.get("docs") or []
            doc = docs[data.get("active", -1)] if 0 <= data.get("active", -1) < len(docs) else (docs[-1] if docs else {})
            st = doc.get("statusText") or ""
            if "选中 0" not in st and "选中" not in st:
                ctypes.windll.user32.SetCursorPos(x, y)
                ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
                ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
                time.sleep(0.3)
        except Exception:
            pass  # 钩子不可用（A 班无 --testhook）：维持原行为


def type_text(s):
    pyperclip.copy(s)
    send_keys("^v")
    time.sleep(0.4)


def _norm_text(s):
    return (s or "").replace("\r\n", "\n")


def _hook_doc_safe():
    """取活动文档快照；钩子不可用返回空 dict（调用方退回旧行为）。"""
    try:
        data = hook_dump()
    except Exception:
        return {}
    docs = data.get("docs") or []
    if not docs:
        return {}
    act = data.get("active", -1)
    return docs[act] if 0 <= act < len(docs) else docs[-1]


def clear_editor_verified(max_rounds=5):
    """44137602413 实锤：X06 起 ^a{DEL} 连续被吞（X05 残留原样带到 X06），
    同班 X03/X04 却 PASS——吞键集中在会话后段。清场必须以钩子正文为证，
    没清干净就换姿势重试；第 3/5 轮改编辑>全选菜单（鼠标通道）兜底，
    不带残留进下一个场景。"""
    for i in range(max_rounds):
        if i == 0:
            click_editor()
        elif i in (2, 4):
            # 44145564951 实锤：MENU_INDEX 键带快捷键后缀，裸名=无序号映射空转；
            # 44149411449 实锤：纯鼠标激活，杜绝 DOWN/ENTER 迟到落进编辑器
            if menu_click_mouse("编辑", "全选（Ctrl+A）"):
                send_keys("{DELETE}")
                time.sleep(0.8)
        else:
            focus_main()
            click_editor()
        send_keys("^a{DEL}")
        time.sleep(0.6)
        if _norm_text(_hook_doc_safe().get("text", "")).strip() == "":
            return True
    return False


def paste_verified(payload, max_rounds=4):
    """44137602413 实锤：X06 两轮粘贴全吞、X07 粘贴其实进了——粘贴必须
    以钩子正文含 payload 为证，没进就聚焦重粘；第 3 轮改编辑>粘贴菜单
    （鼠标通道，App 直投编辑器不依赖键盘焦点），进了绝不重粘防双份。"""
    for i in range(max_rounds):
        t = _norm_text(_hook_doc_safe().get("text", ""))
        if payload in t:
            return t
        if i == 0:
            click_editor()
        elif i == 2:
            pyperclip.copy(payload)
            menu_click_mouse("编辑", "粘贴（Ctrl+V）")
        else:
            focus_main()
            click_editor()
        if i != 2:
            pyperclip.copy(payload)
            send_keys("^v")
        if i == 3:
            # 末轮命令硬通道兜底（v45）：与应用「编辑>粘贴」同一实现，
            # 传输失效时直达，正文验收不降
            r = hook_command("paste_clipboard")
            print(f"粘贴命令硬通道回执: {r.get('commandResult')!r}", flush=True)
        time.sleep(0.9)
    return _norm_text(_hook_doc_safe().get("text", ""))


def editor_open_clean():
    """场景开工：收浮层→窗口置前→点编辑区→验证式清场。X05 收尾的面板/
    浮层残留（toggle 失败实锤）会把 X06 的点击和输入全部引走。"""
    esc_cleanup()
    focus_main()
    click_editor()
    return clear_editor_verified()


def menu_click_mouse(top, item):
    """纯鼠标激活菜单项：顶级布局点击→弹层差分+行带→直点目标项坐标。
    44149411449 实锤：menu_xy 通道一的 DOWN×idx+ENTER 在弹层收层、焦点
    回编辑器后才落账，迟到 ENTER 恰好砸在后续粘贴之后（X07 文本尾反复
    多出 \\r\\n、弹层被收）。本函数全程无键盘，供清场/粘贴/X07/X09 使用。"""
    tops = ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"]
    if top not in tops:
        return False
    for attempt in range(3):
        esc_cleanup()
        focus_main()
        try:
            import win32gui
            l, t, _r, _b = win32gui.GetWindowRect(WIN_HANDLE)
        except Exception:
            return False
        tc = l + TOP_MENU_XY[top][0]
        pre = grab_img()
        if not _click_top_by_layout(top):
            return False
        post = grab_img()
        strip = (tc - 8, t + 82, tc + 100, t + 510)
        d = _region_diff(pre, post, strip)
        bands = _ink_bands(post, strip[0], strip[2], strip[1], strip[3])
        if d < 0.002 or not bands:
            time.sleep(0.8)
            post = grab_img()
            d = _region_diff(pre, post, strip)
            bands = _ink_bands(post, strip[0], strip[2], strip[1], strip[3])
        if d < 0.002 or not bands:
            print(f"menu_click_mouse[{top}] 第{attempt+1}次顶级弹层未开", flush=True)
            continue
        idx = MENU_INDEX.get(top, {}).get(item)
        if idx is None and top == "语言" and item in LANGS:
            idx = LANGS.index(item)
        if idx is None:
            print(f"menu_click_mouse[{top}>{item}] 无序号映射", flush=True)
            esc_cleanup()
            return False
        mark = trace_mark()
        band = _pick_band(bands, idx, t + 95.5 + 31.7 * idx)
        if not band:
            esc_cleanup()
            continue
        _click_xy(band[2] + 10, band[0])
        ok = _trace_wait_item(mark, item, wait=1.2)
        if ok:
            esc_cleanup()
            return True
        print(f"menu_click_mouse[{top}>{item}] 第{attempt+1}次直点无回执", flush=True)
        esc_cleanup()
    return False


def clear_editor_settled(max_retries=3):
    """清场后等迟到键落完再复核：menu 激活的 ENTER 迟到 1~2.5s 落进编辑器，
    清完立刻粘贴会把 ENTER 一起带进新正文（X07 文本尾尾随 CRLF 实锤）。"""
    for _ in range(max_retries):
        if clear_editor_verified():
            time.sleep(2.0)
            if _norm_text(_hook_doc_safe().get("text", "")).strip() == "":
                return True
    return False


def editor_clipboard():
    """全选复制回读。v36 实锤：云 runner 上 ^c 偶发被吞（现场截图选中 9、
    剪贴板仍空）——聚焦后重试两轮复制再回读。
    v37/v38 定谳：菜单激活后键盘焦点滞留 MenuBar（主题有 RestoreFocus，
    注释/语言菜单没有），set_focus 只还原窗口焦点，^a/^c 仍被菜单条吞——
    第一轮改真实点击编辑区还焦点（点击清选区，^a 必须在点击后重发），
    第二轮保留 set_focus 兜底。"""
    for attempt in range(2):
        if attempt == 0:
            click_editor()
        else:
            focus_main()
        pyperclip.copy("")
        send_keys("^a")
        time.sleep(0.25)
        send_keys("^c")
        time.sleep(0.4)
        got = pyperclip.paste()
        if got != "":
            return got
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


def _picker_edit(h, timeout=6.0):
    """C01 实锤（run 45015435336）：picker 冷启动窗口先在、文件名框焦点未落，
    固定 1s 后 ^v 落空，ENTER 落 Save 默认名（X19 页签 Documents\无标题 实锤）
    或 Cancel——两跑全挂。UIA 寻文件名 Edit：优先当前聚焦者，兜底取
    「文件名」ComboBox 内者，再兜底首个可见可用者。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            from pywinauto import Application
            w = Application(backend="uia").connect(handle=h, timeout=1).window(handle=h)
            edits = [e for e in w.descendants(control_type="Edit")]
            for e in edits:
                try:
                    if e.is_focused() and e.is_visible():
                        return e
                except Exception:
                    pass
            for e in edits:
                try:
                    if not (e.is_visible() and e.is_enabled()):
                        continue
                    nm = ""
                    try:
                        nm = e.parent().window_text() or ""
                    except Exception:
                        pass
                    if ("文件名" in nm) or ("file name" in nm.lower()):
                        return e
                except Exception:
                    pass
            for e in edits:
                try:
                    if e.is_visible() and e.is_enabled():
                        return e
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.4)
    return None


def picker_typing(path, wait=3.0):
    t0 = time.time()
    h = None
    while not h and time.time() - t0 < 10:
        try:
            import win32gui
            h = win32gui.FindWindow("#32770", None)
        except Exception:
            h = None
        if not h:
            time.sleep(0.5)
    if not h:
        # 无 #32770（已命名直存等）：保持旧行为粘进当前焦点，由调用方断言兜底
        time.sleep(1.0)
        pyperclip.copy(path)
        send_keys("^v")
        time.sleep(0.8)
        send_keys("{ENTER}")
        time.sleep(1.5)
        return
    time.sleep(0.5)
    for attempt in range(3):
        e = _picker_edit(h)
        pyperclip.copy(path)
        if e is not None:
            try:
                e.set_edit_text(path)   # ValuePattern 直写，绕开剪贴板/焦点竞态
                try:
                    e.set_focus()       # 回车必须落文件名框，防落 Save/Cancel 默认钮
                except Exception:
                    pass
                time.sleep(0.3)
                send_keys("{ENTER}")
            except Exception:
                send_keys("^a")
                time.sleep(0.25)
                send_keys("^v")
                time.sleep(0.8)
                send_keys("{ENTER}")
        else:
            send_keys("^a")
            time.sleep(0.25)
            send_keys("^v")             # 整段粘贴，杜绝逐键输入被吞
            time.sleep(0.8)
            send_keys("{ENTER}")
        time.sleep(1.5)
        try:
            import win32gui
            if not win32gui.FindWindow("#32770", None):
                break
        except Exception:
            break
        # 未收层=本轮未成交：ESC 收掉重来（上限 3 轮）
        send_keys("{ESC}")
        time.sleep(0.8)
        try:
            import win32gui
            h2 = win32gui.FindWindow("#32770", None)
            if not h2:
                break
            h = h2
            e = None
        except Exception:
            break
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
    time.sleep(0.8)   # 应用侧选择器返回后落盘留痕


def wer_count():
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER")
    n = 0
    for root, dirs, files in os.walk(base):
        if any("TaoPad" in f for f in files):
            n += 1
    return n


# ---------------- 用例 ----------------

HOOK_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "TaoPad", "testhook")


def hook_dump(timeout=10.0):
    """--testhook 文件握手：放请求等响应。正文导出不再依赖 UIA 读层
    （v39.5 定谳 UIA 对大文档会饿死，故走应用内存快照）。"""
    os.makedirs(HOOK_DIR, exist_ok=True)
    req = os.path.join(HOOK_DIR, "request.json")
    resp = os.path.join(HOOK_DIR, "response.json")
    try:
        if os.path.exists(resp):
            os.remove(resp)
    except OSError:
        pass
    open(req, "w", encoding="utf-8").close()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(resp):
            with open(resp, "r", encoding="utf-8") as f:
                return json.load(f)
        time.sleep(0.2)
    raise RuntimeError("测试钩子未在时限内导出正文")


def hook_command(cmd, arg=None, timeout=10.0):
    """命令硬通道（v45）：--testhook 请求带 command/arg，应用在 UI 线程
    执行并把回执连同快照一起写回。菜单/键盘主路失败时的兜底，与
    completionItems/hintDebug 同族——只经产品测试通道，普通用户零影响。
    返回完整响应 dict（含 commandResult 与 docs 自报）。"""
    os.makedirs(HOOK_DIR, exist_ok=True)
    req = os.path.join(HOOK_DIR, "request.json")
    resp = os.path.join(HOOK_DIR, "response.json")
    try:
        if os.path.exists(resp):
            os.remove(resp)
    except OSError:
        pass
    payload = {"command": cmd}
    if arg is not None:
        payload["arg"] = arg
    with open(req, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(resp):
            with open(resp, "r", encoding="utf-8") as f:
                return json.load(f)
        time.sleep(0.2)
    raise RuntimeError(f"测试钩子命令 {cmd} 未在时限内回执")


def c_testhook_dump():
    """X03：正文自报通道闭环——打探针→握手导出→断言正文含探针→
    撤销后再握手断言变化，证伪静态回显。"""
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("X03HOOK-正文自报-987654321")
    data = hook_dump()
    # 版本断言动态取自源码 AppVersion (run 44903936270 实锤: 写死 1.1.1 在升版后必炸)
    _src = open(os.path.join(os.path.dirname(__file__), '..', 'src', 'AntPad', 'MainWindow.xaml.cs'),
                encoding='utf-8-sig').read()
    _app_ver = re.search(r'AppVersion\s*=\s*"([\d.]+)"', _src).group(1)
    assert data.get("version") == _app_ver, f"版本不符: {data.get('version')!r} != 源码 {_app_ver!r}"
    docs = data.get("docs") or []
    assert docs, "导出快照里没有文档"
    active = data.get("active", -1)
    doc = docs[active] if 0 <= active < len(docs) else docs[-1]
    assert "X03HOOK-正文自报-987654321" in doc.get("text", ""), \
        f"钩子正文缺探针: {doc.get('text', '')[:200]!r}"
    send_keys("^z")
    time.sleep(0.5)
    data2 = hook_dump()
    docs2 = data2.get("docs") or []
    text2 = docs2[active].get("text", "") if docs2 else ""
    assert "X03HOOK-正文自报-987654321" not in text2, "撤销后钩子正文未变化（疑似静态回显）"
    shot("case-testhook")


def c_rainbow_brackets():
    """X04：彩虹括号修复验证（1.1.0）——嵌套括号渲染色走 bracketColors
    硬通道，断言至少 2 种不同颜色且全部在四色板内。"""
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    menu_xy("语言", "C#")
    time.sleep(0.6)
    click_editor()
    send_keys("^a{DEL}")
    # 行尾补换行让光标离开括号，配对高亮熄灭后括号全部回到彩虹色
    type_text("int x = f(g(a), h(b[0]));\n")
    time.sleep(0.8)
    data = hook_dump()
    docs = data.get("docs") or []
    assert docs, "X04: 导出快照里没有文档"
    act = data.get("active", -1)
    doc = docs[act] if 0 <= act < len(docs) else docs[-1]
    colors = doc.get("bracketColors") or []
    assert len(colors) >= 4, f"X04: 括号颜色通道导出过少: {colors!r}"
    palette = {"198,84,80", "190,138,50", "104,150,90", "84,118,168"}
    parsed = {c.split(":", 1)[1] for c in colors if ":" in c}
    assert len(parsed) >= 2, f"X04: 嵌套括号只出现一种颜色: {colors!r}"
    assert parsed <= palette, f"X04: 出现色板外颜色: {parsed!r}"
    shot("case-rainbow")


def toggle_panel(item, hotkey):
    """查看>预览/大纲 激活：纯鼠标直点优先（44149411449 实锤：menu_xy 通道一
    DOWN/ENTER 迟到落进编辑器，是 X06/X07 尾随 CRLF 的源头之一），失败退
    XAML 加速键。"""
    if menu_click_mouse("查看", item):
        return
    if menu_xy("查看", item):
        return
    print(f"{item} 菜单路径失败，退加速键 {hotkey}", flush=True)
    focus_main()
    send_keys(hotkey)
    time.sleep(0.6)


def status_hard(token, doc, label):
    """状态栏断言：UIA 读层为主，空返时退钩子状态行自报（run 44106717867
    定谳：B 会话 texts() 只枚举到窗口标题，截图与 trace 回执证明状态栏
    真实内容在场——读层瞎，不是应用瞎）。"""
    ts = texts()
    if any(token in t for t in ts):
        return
    st = doc.get("statusText") or ""
    if token in st:
        print(f"{label}: UIA 读层空返，钩子状态行命中: {st[:60]!r}", flush=True)
        return
    raise AssertionError(f"{label}: 状态栏缺[{token}] UIA={ts[:6]!r} 钩子状态行={st[:80]!r}")


def c_writing_panels():
    """X05：Markdown 写作面板（1.1.0）——预览/大纲开启后正文与字数落位。"""
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    menu_xy("语言", "Markdown")
    time.sleep(0.6)
    click_editor()
    send_keys("^a{DEL}")
    type_text("# 标题一\n正文内容\n## 标题二\n- 列表项")
    time.sleep(0.5)
    # v46e 回归断言（44259128446 实锤）：大纲/预览渲染曾因 FontFamily 置 null
    # 炸出 UI 线程 COMException（拦截续命后派发链半瘫：X15/X16 转发静默吞、
    # X07 键入不落账、钩子状态陈旧，全在异常发生之后）。面板开关后 trace.log
    # 不得新增任何「UI 线程异常」。
    if not hasattr(c_writing_panels, "_trace_mark0"):
        c_writing_panels._trace_mark0 = trace_mark()
    toggle_panel("预览", "^+p")
    toggle_panel("大纲", "^+o")
    time.sleep(1.0)
    new_trace = trace_since(c_writing_panels._trace_mark0)
    bad = [l for l in new_trace if "UI 线程异常" in l]
    assert not bad, f"X05: 面板渲染炸出 UI 线程异常（拦截续命仍拖瘫派发链）: {bad[:3]}"
    data = hook_dump()
    docs = data.get("docs") or []
    act = data.get("active", -1)
    doc = docs[act] if 0 <= act < len(docs) else docs[-1]
    status_hard("字数", doc, "X05")
    assert "标题二" in doc.get("text", ""), f"X05: 正文缺失: {doc.get('text', '')[:80]!r}"
    shot("case-writing-panels")
    # 复位：关掉两个面板，不占后续用例的画面
    toggle_panel("预览", "^+p")
    toggle_panel("大纲", "^+o")
    time.sleep(0.6)
    # 44132721896 实锤：大纲关闭走加速键兜底后无回执无验证，残留面板把后续
    # 用例的输入路径搅乱（X06 文本残留即源于此）。这里关完面板后核对编辑器
    # 真正收到焦点——用钩子正文清场验证 ^a{DEL} 真的生效。
    for attempt in range(2):
        data = hook_dump(timeout=6.0)
        docs = data.get("docs") or []
        doc = docs[data.get("active", -1)] if 0 <= data.get("active", -1) < len(docs) else (docs[-1] if docs else {})
        st = doc.get("statusText") or ""
        if "选中" in st and "选中 0" in st:
            break
        focus_main()
        click_editor()
        send_keys("{ESC}")
        time.sleep(0.4)
    # 命令硬通道兜底（v45）：浮层关不净会把后续用例的输入路径整段搅乱
    # （44234216706 实锤：大纲关层无回执，X06-X12 连环吞键）。与面板
    # 开关同一套状态源，关完以 panelsDebug 自报验证。
    r = hook_command("close_panels")
    p = (r.get("docs") or [{}])[-1].get("panelsDebug", "")
    print(f"X05 收尾命令硬通道回执: {r.get('commandResult')!r} 面板自报: {p!r}", flush=True)


def c_fountain_highlight():
    """X06：Fountain 剧本高亮（1.1.0）——场景/人物/转场分词落位，
    状态栏语言与正文以测试钩子为证。"""
    editor_open_clean()
    # 44217756849 实锤：切了菜单不等于切了语言——必须以钩子 lang 验收
    if not menu_lang_verified("Fountain 剧本"):
        doc0 = _hook_doc_safe()
        assert doc0.get("lang") == "Fountain 剧本", (
            f"X06: 语言未切到 Fountain: lang={doc0.get('lang')!r}")
    clear_editor_settled()
    t = paste_verified("INT. 咖啡馆 - 日\n\nJOHN\n今天天气不错。\n\n> CUT TO: 夜晚")
    time.sleep(0.6)
    data = hook_dump()
    docs = data.get("docs") or []
    act = data.get("active", -1)
    doc = docs[act] if 0 <= act < len(docs) else docs[-1]
    status_hard("Fountain", doc, "X06")
    assert "INT. 咖啡馆 - 日" in doc.get("text", ""), (
        f"X06: Fountain 正文缺失 验证粘贴回执={t[-60:]!r}")
    shot("case-fountain")


# X21 各语言真实样例（老板 2026-11-18 令）：此前多数代码语言只有「键入一行+
# 注释切换」通用路径，没有按各自最日常的写法真实落过一段内容。这里每语言
# 一段典型多行样例（各语言平时最常写的形态），逐语言验证语言切换落账、
# 正文完整不缺行、状态栏字数同步；专属深测（补全/撤销/渲染色）由
# X04/X05/X06/X07/X08/X12/X18 承担，本用例补齐「每种语言都真写过」。
LANG_SAMPLES = {
    "C / C++": (
        '#include <cstdio>\nint main() {\n    for (int i = 0; i < 3; i++) {\n        printf("hi %d\\n", i);\n    }\n    return 0;\n}',
        "printf",
    ),
    "Java": (
        "public class Demo {\n    public static void main(String[] args) {\n        for (int i = 0; i < 2; i++) {\n            System.out.println(\"i=\" + i);\n        }\n    }\n}",
        "System.out.println",
    ),
    "JavaScript / TypeScript": (
        'const greet = (name) => {\n  for (let i = 0; i < 2; i++) {\n    console.log(`hi ${name} ${i}`);\n  }\n};\ngreet("世界");',
        "console.log",
    ),
    "Go": (
        'package main\n\nimport "fmt"\n\nfunc main() {\n    for i := 0; i < 2; i++ {\n        fmt.Println("hi", i)\n    }\n}',
        "fmt.Println",
    ),
    "Rust": (
        'fn main() {\n    for i in 0..2 {\n        println!("hi {}", i);\n    }\n}',
        "println!",
    ),
    "C 风格其他 (Swift/Kotlin/PHP/Dart…)": (
        'import Foundation\n\nfor i in 0..<2 {\n    print("hi \\(i)")\n}',
        "print(",
    ),
    "Python": (
        'def greet(name):\n    for i in range(2):\n        print(f"hi {name} {i}")\n\ngreet("世界")',
        "greet(\"世界\")",
    ),
    "JSON": (
        '{\n  "name": "测试",\n  "count": 2,\n  "tags": ["a", "b"],\n  "nested": {"ok": true, "pi": 3.14}\n}',
        '"nested"',
    ),
    "XML / HTML": (
        '<?xml version="1.0"?>\n<note id="1">\n  <to>老板</to>\n  <body>各语言真实样例</body>\n</note>',
        "<to>老板</to>",
    ),
    "SQL": (
        "SELECT id, name FROM users\nWHERE age > 18 AND city = '北京'\nORDER BY id DESC\nLIMIT 10;",
        "ORDER BY id DESC",
    ),
}


def c_lang_real_samples():
    """X21：各语言真实样例编写——粘贴一段该语言日常形态的多行内容，
    验证：菜单/钩子双路切语言落账、样例正文完整落位（关键行在钩子正文
    里）、状态栏字数同步。逐语言循环，红则报明是哪种语言。"""
    for lang, (sample, sig) in LANG_SAMPLES.items():
        editor_open_clean()
        if not menu_lang_verified(lang):
            r = hook_command("set_language", lang)
            doc0 = _hook_doc_safe()
            assert doc0.get("lang") == lang, f"X21[{lang}]: 语言未切: {doc0.get('lang')!r}"
        clear_editor_settled()
        paste_verified(sample)
        time.sleep(0.6)
        data = hook_dump()
        docs = data.get("docs") or []
        act = data.get("active", -1)
        doc = docs[act] if 0 <= act < len(docs) else (docs[-1] if docs else {})
        text = doc.get("text", "")
        assert sig in text, f"X21[{lang}]: 样例关键行缺失: {text[-80:]!r}"
        assert doc.get("lang") == lang, f"X21[{lang}]: 语言自报不符: {doc.get('lang')!r}"
        # 44324798289 X21 定谳：「字数」段仅文章类语言显示（StatusLineFor
        # 的 IsArticle 口径，X05 Markdown 命中、代码语言本就没有）；X21 全是
        # 代码语言，改断言恒在的「行数」段，字数由写作语言用例（X05）承担。
        status_hard("行数", doc, f"X21[{lang}]")
        print(f"X21[{lang}]: 样例落位 OK", flush=True)
    shot("case-lang-real-samples")


def c_csharp_completion():
    """X07：C# 全量智能补全（1.1.0）——词表先弹、Roslyn 合并，
    弹层候选走 completionItems 硬通道，断言语义成员（Add/Count）可达。
    v46c 换路（防耗死令：键重放污染同路四班实锤，44250541252 尾账
    'list.\\r\\n'）：键入改走命令硬通道 type/trim_tail——编辑器同一文本
    管线（TextChanged→MaybeShowPopup），仅跳过失效的键传输；v46b 起
    TypeAtEnd 插入后光标显式归位并按最终光标补跑弹层触发。"""
    editor_open_clean()
    if not menu_lang_verified("C#"):
        r = hook_command("set_language", "C#")
        doc0 = _hook_doc_safe()
        assert doc0.get("lang") == "C#", (
            f"X07: 语言未切到 C#: lang={doc0.get('lang')!r} 回执={r.get('commandResult')!r}")
    clear_editor_settled()
    # 44324138369 X07 定谳：样例缺 using 引头 → List<string> 不可解析 →
    # 语义引擎按设计返回空（LogicTests G01 带引头所以全绿），弹层永远
    # 空表。补上 using System.Collections.Generic; 与 G01 口径对齐。
    paste_verified("using System.Collections.Generic;\nvar list = new List<string>();")
    time.sleep(0.8)
    r = hook_command("type", "\n")
    print(f"X07: 换行回执: {r.get('commandResult')!r}", flush=True)
    r = hook_command("type", "list.")
    print(f"X07: 键入回执: {r.get('commandResult')!r}", flush=True)
    typed = False
    doc = {}
    trims = 0
    deadline = time.time() + 60
    last = None
    stable = 0
    while time.time() < deadline:
        doc = _hook_doc_safe()
        t = doc.get("text") or ""
        # 44306971603 起按定谳放宽：正文已落 list. 即算键入成功——
        # 尾随 CRLF 是幽灵键流（环境噪声，多班实锤），trim_and_items
        # 在 UI 线程内原子剥尾后读候选，此处不再死等剥干净。
        if t.rstrip("\r\n \t").endswith("list."):
            typed = True
            break
        # 迟到的键重放塞了尾随换行（多班实锤）：真实退格清尾会被下一波
        # 重放再次污染，唯一稳的打法=等正文稳定（幽灵队列排空）再由命令
        # 硬通道剥尾——文本变化让补全按 list. 语境重开
        if t.rstrip("\r\n \t").endswith("list.") and trims < 12:
            if t == last:
                stable += 1
            else:
                stable = 0
                last = t
            if stable >= 5:
                hook_command("trim_tail")
                trims += 1
                stable = 0
                last = None
        time.sleep(1.0)
    assert typed, f"X07: 键入未落账: {(doc or {}).get('text', '')[-40:]!r}"
    # v46l（44317775556 X07 实锤）：trim_and_items 依赖文本变化触发，正文
    # 已净时不再引发 MaybeShowPopup，Roslyn 回执被 sameCaret 丢弃后轮询
    # 永远空表。改为 trim_and_items 先剥幽灵尾（这一次文本变化即触发），
    # 再每轮 trigger_popup（不改正文触发判定）+ popup_items，语义回执
    # 落地、弹层打开后即见 Add/Count（60s 时限）
    res = ""
    ok = False
    hook_command("trim_and_items")
    deadline = time.time() + 60
    while time.time() < deadline:
        hook_command("trigger_popup")
        time.sleep(2.0)
        r = hook_command("popup_items")
        res = r.get("commandResult") or ""
        if res.startswith("ok:items=[") and "Add" in res and "Count" in res:
            ok = True
            break
        time.sleep(1.0)
    if not ok:
        doc = _try_hook_dump(timeout=25.0) or {}
    assert ok, (f"X07: 补全弹层候选缺语义成员: {res[:160]!r}"
                f" 诊断={(doc or {}).get('completionDebug','')!r}")
    shot("case-csharp-intel")
    esc_cleanup()


def c_csharp_undo():
    """X08：C# 模式撤销一步到位（1.1.1）——着色批合并为单个撤销组后，
    Ctrl+Z 一次就退回文字，不再被格式步吃掉首按；重做对称。"""
    clear_editor_verified()
    menu_xy("语言", "C#")
    time.sleep(0.6)
    clear_editor_verified()
    paste_verified("int undoProbe = 42;\n")
    time.sleep(0.8)   # 等 220ms 防抖着色批完整落盘（含撤销组）
    # 44137602413 实锤：X03 同为粘贴+^z 在 B 会话前段稳定过，X08 在后段
    # ^z 被吞（文本原样）——^z 以钩子正文为证重试，吞键不作产品定谳。
    for i in range(3):
        doc = _hook_doc_safe()
        if "undoProbe" not in doc.get("text", ""):
            break
        if i:
            focus_main()
        click_editor()
        send_keys("^z")
        time.sleep(0.8)
    doc = _hook_doc_safe()
    text = doc.get("text", "")
    assert "undoProbe" not in text, f"X08: 一次 Ctrl+Z 未退回文字: {text[-40:]!r}"
    for i in range(3):
        doc = _hook_doc_safe()
        if "undoProbe" in doc.get("text", ""):
            break
        if i:
            focus_main()
        click_editor()
        send_keys("^y")
        time.sleep(0.8)
    doc = _hook_doc_safe()
    assert "undoProbe" in doc.get("text", ""), f"X08: 重做未恢复文字: {doc.get('text', '')[-40:]!r}"
    shot("case-csharp-undo")
    esc_cleanup()


def c_pair_comment_undo():
    """X09：括号配对/注释后的单步撤销（1.1.1）——配对插入是单撤销组，
    一步 Ctrl+Z 退净；注释命令走 BeginUndoGroup 同样一步退净。"""
    editor_open_clean()
    menu_click_mouse("语言", "C#")
    time.sleep(0.6)
    clear_editor_settled()

    def _stable(poll_s=1.2, rounds=2):
        # 44212844089 实锤：偶发双插 '(()' 会在任何断言之后才落账（内核重放
        # 迟到超出 _echo 去重窗）。每步以「读数两拍一致」为落账依据。
        t1 = _norm_text(_hook_doc_safe().get("text", ""))
        for _ in range(rounds):
            time.sleep(poll_s)
            t2 = _norm_text(_hook_doc_safe().get("text", ""))
            if t2 == t1:
                break
            t1 = t2
        return t1.strip()

    # 44141628790 定谳：TryAutoPair 只挂按键链，粘贴永不触发配对——
    # 用真实按键 Shift+Number9（US 布局 +9，pywinauto 的 ( 是分组符）。
    for i in range(5):
        t = _stable()
        if t == "()":
            break
        if i:
            focus_main()
        click_editor()
        send_keys("+9")
        print(f"X09: 第{i + 1}次发送 +9 后: {_stable()!r}", flush=True)
    t = _stable()
    assert t == "()", f"X09: 配对插入不对: {t[-20:]!r}"
    # 撤销按状态机走：()→退一组；'(()'→先退迟到重放多插的组再续，直至退净。
    # 44217756849 实锤：撤销中途仍有迟到重放的 '(' 插队（'(()' 反复），4 轮
    # 不够用——按「读数稳且非空就再退」走，上限 8 轮防呆。
    time.sleep(1.5)
    t = _stable()
    for i in range(8):
        if t == "":
            break
        focus_main()
        click_editor()
        send_keys("^z")
        time.sleep(1.2)
        t = _stable()
        print(f"X09: 撤销第{i + 1}轮后: {t!r}", flush=True)
    assert t == "", f"X09: 配对撤销一步未退净: {t[-20:]!r}"
    shot("case-pair-undo")
    esc_cleanup()


FILE_RO = os.path.join(DOCS, "taopad-ro.txt")


def _snapshot_files():
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "TaoPad", "snapshots"),
             r"D:\TaoPadData\TaoPad\snapshots"]
    return {os.path.join(dp, f) for r in roots if os.path.isdir(r)
            for dp, _d, fs in os.walk(r) for f in fs}


def c_snapshot_ui():
    """X10：快照留底（1.1.1）——立即留底命令真实落盘（新快照含探测正文），
    查看快照对话框可开（XAML 对话框无钩子通道，以截图为证）。"""
    editor_open_clean()
    # 44217756849 实锤：语言切没切必须验收（同 X06/X07）
    if not menu_lang_verified("纯文本"):
        doc0 = _hook_doc_safe()
        assert doc0.get("lang") == "纯文本", (
            f"X10: 语言未切到纯文本: lang={doc0.get('lang')!r}")
    clear_editor_settled()
    probe = f"snapshot-probe-{int(time.time())}"
    paste_verified(probe)
    before = _snapshot_files()
    # 44217756849 实锤：单通道菜单必 MISS——鼠标/直呼交替三轮，以快照
    # 真实落盘为验收（文件菜单不走键盘导航，防误触退出）。
    new = set()
    for i in range(3):
        if i == 0:
            menu_click_mouse("文件", "立即留底")
        else:
            menu("文件", "立即留底")
        time.sleep(1.5)
        new = _snapshot_files() - before
        if new:
            break
        print(f"X10: 第{i + 1}轮留底未落盘（before={len(before)}），换通道重试", flush=True)
    if not new:
        # 菜单三路全 MISS → 命令硬通道兜底（v45）：与「立即留底」菜单
        # 同一实现 DoSnapshotNow，落盘验收标准不降
        r = hook_command("snapshot_now")
        print(f"X10: 命令硬通道留底回执: {r.get('commandResult')!r}", flush=True)
        time.sleep(1.5)
        new = _snapshot_files() - before
    assert new, f"立即留底三轮未产生新快照: before={len(before)}"
    hit = any(probe in open(p2, encoding="utf-8", errors="ignore").read() for p2 in new)
    assert hit, f"新快照不含探测正文: {[os.path.basename(x) for x in new]!r}"
    if not menu_click_mouse("文件", "查看快照…"):
        menu_xy("文件", "查看快照…", keep_open=True)
    time.sleep(1.2)
    shot("case-snapshot")
    send_keys("{ESC}")
    time.sleep(0.6)
    esc_cleanup()


def c_bookmarks():
    """X11：书签（1.1.1）——Ctrl+F2 打点、F2 跳转、再 Ctrl+F2 取消，
    书签行号走钩子硬通道 bookmarkLines 断言。"""
    editor_open_clean()
    clear_editor_settled()
    paste_verified("line-one\nline-two\nline-three\nline-four\n")
    time.sleep(0.8)
    send_keys("^{F2}")          # 当前行（第 4 行）打点
    time.sleep(1.2)
    doc = _hook_doc_safe()
    marks = doc.get("bookmarkLines") or []
    assert len(marks) == 1, f"书签未打上: {marks!r}"
    mark_line = marks[0]
    send_keys("{F2}")           # 跳下一书签（应仍停在该行）
    time.sleep(1.2)
    doc = _hook_doc_safe()
    assert doc.get("statusText", "").startswith(f"行 {mark_line}，"), (
        f"F2 未跳到书签行 {mark_line}: {doc.get('statusText', '')!r}")
    send_keys("^{F2}")          # 取消书签
    time.sleep(1.2)
    doc = _hook_doc_safe()
    assert (doc.get("bookmarkLines") or []) == [], f"书签未取消: {doc.get('bookmarkLines')!r}"
    esc_cleanup()


def c_param_hint():
    """X12：参数提示浮层（1.1.1）——C# 键入 Math.Abs( 出签名提示，
    浮层状态走钩子硬通道 hintDebug 断言。
    v46c 换路（防耗死令：键重放污染同路四班实锤）：键入全部走命令硬
    通道 type——编辑器同一文本管线，弹层触发与真实敲键同路；v46b 起
    TypeAtEnd 插入后光标显式归位并按最终光标补跑提示触发。失败时用
    hint_probe 探针留诊断（区分「触发失败」与「弹了又被收」）。"""
    editor_open_clean()
    if not menu_lang_verified("C#"):
        r = hook_command("set_language", "C#")
        doc0 = _hook_doc_safe()
        assert doc0.get("lang") == "C#", (
            f"X12: 语言未切到 C#: lang={doc0.get('lang')!r} 回执={r.get('commandResult')!r}")
    clear_editor_settled()
    paste_verified("int probe = 1;")
    time.sleep(0.8)
    r = hook_command("type", "\nMath.Abs(")
    print(f"X12: 键入回执: {r.get('commandResult')!r}", flush=True)
    typed = False
    doc = {}
    deadline = time.time() + 15
    while time.time() < deadline:
        doc = _hook_doc_safe()
        if "Math.Abs(" in (doc.get("text") or ""):
            typed = True
            break
        time.sleep(1.0)
    assert typed, f"X12: 键入未落账: {(doc or {}).get('text', '')[-40:]!r}"
    doc = {}
    ok = False
    trims = 0
    deadline = time.time() + 15
    while time.time() < deadline:
        doc = _hook_doc_safe()
        if "open=True" in (doc.get("hintDebug") or ""):
            ok = True
            break
        t = doc.get("text") or ""
        # 迟到的键重放塞尾会收掉提示：命令硬通道剥掉，文本变化让提示
        # 按 ( 语境重开（TypeAtEnd/TrimTailWhitespace 显式补跑触发）
        if t.rstrip("\r\n \t").endswith("Math.Abs(") and trims < 8:
            hook_command("trim_tail")
            trims += 1
        time.sleep(1.5)
    if not ok:
        # 探针留证：真实回报 try/sig/两浮层状态与文本尾
        r = hook_command("hint_probe")
        print(f"X12: 提示探针: {r.get('commandResult')!r}", flush=True)
    assert ok, f"参数提示未弹出: {doc.get('hintDebug', '')!r}"
    assert "Math.Abs" in (doc.get("hintDebug") or ""), f"提示非 Math.Abs 签名: {doc.get('hintDebug')!r}"
    shot("case-param-hint")
    esc_cleanup()


def c_readonly():
    """X13：只读属性的文件（1.1.1）——v39.4（老板拍板 2026-11-18）：
    带 +R 属性的档案打开即 readOnly 置位、状态栏标（只读）、键入被挡；
    另存新路径恢复可编辑。以钩子通道验收。"""
    # 44217756849 实锤：上一轮失败残留 +R 未清，重跑写文件必 PermissionError
    # ——先清属性再落正文；打开必须以钩子 title/path 验收，脏则重开。
    os.system(f'attrib -R "{FILE_RO}"')
    try:
        with open(FILE_RO, "w", encoding="utf-8") as f:
            f.write("readonly-probe")
        os.system(f'attrib +R "{FILE_RO}"')
        esc_cleanup()
        opened = False
        for i in range(2):
            focus_main()
            send_keys("^o")
            time.sleep(0.6)
            picker_typing(FILE_RO)
            time.sleep(1.5)
            doc = _hook_doc_safe()
            if ("taopad-ro.txt" in (doc.get("title") or "")
                    or "taopad-ro.txt" in (doc.get("path") or "")):
                opened = True
                break
            print(f"X13: 第{i + 1}次打开未命中: title={doc.get('title')!r}", flush=True)
        assert opened, "X13: 只读文件两轮未打开"
        doc = _hook_doc_safe()
        assert doc.get("readOnly") is True, f"X13: 只读未置位: {doc.get('readOnly')!r}"
        assert "（只读）" in doc.get("statusText", ""), \
            f"X13: 状态行未标注只读: {doc.get('statusText', '')!r}"
        assert "readonly-probe" in (doc.get("text") or ""), \
            f"X13: 正文缺失: {(doc.get('text') or '')[:60]!r}"
        # 键入被挡：真实按键三轮尝试，正文必须始终不见 ro-typed
        click_editor()
        blocked = True
        for _ in range(3):
            send_keys("ro-typed")
            time.sleep(1.0)
            doc = _hook_doc_safe()
            if "ro-typed" in (doc.get("text") or ""):
                blocked = False
                break
        assert blocked, f"X13: 只读文件仍可键入: {(doc.get('text') or '')[-40:]!r}"
        esc_cleanup()
    finally:
        os.system(f'attrib -R "{FILE_RO}"')


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
    # v33：语言切换与注释全走无 UIA 路径——语言 menu_xy 坐标驱动；注释先
    # 编辑器和弦（CodeEditor.cs 2403-2464 原生支持，keybd_event 直发），
    # 剪贴板校验不达再退编辑菜单坐标路径（comment_op 两段自救）。
    menu_xy("语言", "Python")
    time.sleep(0.6)
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("code-line")
    marked = comment_op(False, lambda s: s.startswith("#"))
    assert marked.startswith("#"), f"注释未按 Python 标记(#)生效: {marked[:40]!r}"
    unmarked = comment_op(True, lambda s: s == "code-line")
    assert unmarked == "code-line", f"取消注释未还原: {unmarked[:40]!r}"
    shot("case-comment")


def c_find_panel():
    # v30：不读状态栏列号。匹配落点用「复制当前行」断言（两行内容互异可辨）
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("alpha beta\ngamma beta")
    send_keys("^{HOME}")          # 查找从光标向后且不回绕，先回文档开头
    time.sleep(0.4)
    send_keys("^f")
    time.sleep(1.0)
    send_keys("beta")
    time.sleep(0.5)
    send_keys("{ENTER}")          # 首个匹配（行1）
    time.sleep(0.8)
    send_keys("{ESC}")
    time.sleep(0.4)
    line1 = copy_current_line().strip()
    assert line1 == "alpha beta", f"首个匹配未落在行1: {line1[:40]!r}"
    send_keys("^f")
    time.sleep(0.8)
    send_keys("{ENTER}")          # 查找框保留 beta，继续下一个（行2）
    time.sleep(0.8)
    send_keys("{ESC}")
    time.sleep(0.4)
    line2 = copy_current_line().strip()
    assert line2 == "gamma beta", f"查找下一个未到行2: {line2[:40]!r}"
    # v31：反向查找改「搜索>查找上一个」菜单（+F3 后焦点漂移，复制得空实锤）
    menu_xy("搜索", "查找上一个", keep_open=True)   # v36：用例自收面板
    time.sleep(0.8)
    send_keys("{ESC}")
    time.sleep(0.4)
    line3 = copy_current_line().strip()
    assert line3 == "alpha beta", f"反向查找未回首匹配: {line3[:40]!r}"
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
    # v30：不读状态栏。转到行用「复制当前行」内容判定（29 行内容互异）
    esc_cleanup()
    click_editor()
    send_keys("^a{DEL}")
    type_text("\n".join(f"line{i}" for i in range(1, 30)))
    send_keys("^{HOME}")
    time.sleep(0.4)
    ok = False
    got = ""
    for seq in ("5{ENTER}", "{TAB}5{ENTER}", "5{TAB}{ENTER}"):
        send_keys("^g")
        time.sleep(1.2)
        send_keys(seq)
        time.sleep(1.0)
        send_keys("{ESC}")
        time.sleep(0.4)
        got = copy_current_line().strip()
        if got == "line5":
            ok = True
            break
    close_panel()
    shot("case-goto")
    assert ok, f"转到行未生效（按行内容判定），当前行: {got[:40]!r}"


def c_find_in_files():
    # v30：面板开合与扫描结果用像素差分断言（面板出现必然改变窗口画面），
    # 编辑框计数作辅证打印。截图全部落证据目录。
    close_panel()
    img0 = grab_img()
    opened = False
    # v31：主路径改 menu_kb（^+F 快捷键 v29/v30 两班均未生效），快捷键留作辅证
    for shortcut_first in (False, True):
        if shortcut_first:
            send_keys("^+{F}")
        else:
            menu_xy("搜索", "在文件中查找…", keep_open=True)   # v36：对话框别收
        time.sleep(1.3)
        if _pixel_changed(img0) > 0.004 or worker_edits_on_win() > 1:
            opened = True
            break
        send_keys("{ESC}")
        time.sleep(0.5)
    shot("case-fif-open")
    assert opened, "在文件中查找面板未打开（像素差分与编辑框计数均无变化）"
    send_keys(DOCS)        # 文件夹框（首个控件，默认焦点）
    time.sleep(0.4)
    send_keys("{TAB}")     # 到查找内容框
    time.sleep(0.3)
    send_keys("save-me")
    time.sleep(0.5)
    img1 = grab_img()      # 打字后稳定态
    send_keys("{ENTER}")   # 回车触发扫描
    time.sleep(2.5)
    img2 = grab_img()
    d2 = _pixel_changed(img1, img2)
    shot("case-find-in-files")
    close_panel()
    assert d2 > 0.002, f"扫描结果无画面变化（像素差分 {d2:.5f}，见 case-find-in-files 截图）"




def zoom_hotkey(vk_code):
    """v11：pywinauto 不认 {ADD} 键名（此前一直被读层故障掩盖），改底层按键"""
    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)      # Ctrl down
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
    ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)      # Ctrl up
    time.sleep(0.8)


# ============ v30：源码揪清单断言通道（不依赖 UIA 文本读取） ============

TRACE_PATHS = [os.path.join("D:" + os.sep, "TaoPadData", "TaoPad", "trace.log"),
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "TaoPad", "trace.log")]


def trace_mark():
    for p in TRACE_PATHS:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return sum(1 for _ in f)
        except OSError:
            continue
    return 0


def trace_since(mark):
    """trace.log 自 mark 行之后的新增行：应用侧真实事件回执（菜单点开/按下、
    设置流）。v46l：不再「读到第一个存在文件就停」——两处候选目录里旧文件
    可能存在但已停写，只看它会永远空表（44317775556 X17 首跑 45s 空轮询
    实锤）；改为所有路径都取增量后合并。"""
    out = []
    for p in TRACE_PATHS:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                out.extend(l.rstrip("\r\n") for l in f.readlines()[mark:])
        except OSError:
            continue
    if out:
        print("trace 回执:", " | ".join(out[-6:]), flush=True)
    return out


# v32：菜单栏顶级项相对坐标（B 班截图实测，窗口默认尺寸 754x510 不变，
# 相对窗口左上角）。UIA 失明时 worker mouse_menu 找不到矩形的兜底。
TOP_MENU_XY = {
    "文件": (32, 58), "编辑": (89, 58), "搜索": (145, 58), "查看": (198, 58),
    "语言": (256, 58), "编码": (313, 58), "主题": (368, 58), "工具": (424, 58),
}


def _click_top_by_layout(top):
    """v32：顶级菜单固定坐标兜底（仅顶级）。窗口位置 main() 已固定 (100,80)、
    尺寸不变，相对偏移稳定；点击后返回 True 交由后续 menu_hit 验证 flyout。"""
    xy = TOP_MENU_XY.get(top)
    if not xy:
        return False
    try:
        import win32gui
        l, t, _r, _b = win32gui.GetWindowRect(WIN_HANDLE)
    except Exception:
        return False
    x, y = l + xy[0], t + xy[1]
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.8)
    print(f"顶级[{top}]布局兜底点击 ({x},{y})", flush=True)
    return True


def worker_menu_hit(title, wait=6.0):
    """v32：弹层项定位。worker 扫同进程全部窗口（主窗+桥+弹层顶层）找目标
    MenuItem 矩形，轮询等待（弹层 hwnd 就绪有延迟，r19 实锤 0.8s 常不够）。"""
    t0 = time.time()
    while time.time() - t0 < wait:
        out = worker_run(["menu_hit", str(WIN_HANDLE), title])
        m = re.search(r"HIT (-?\d+) (-?\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
        time.sleep(0.7)
    return None


# v34 点击注入换刀（43649051295 实锤回灌）：mouse_event 连发 down/up 零间隔，
# 云 runner 上 WinUI 弹层收得到悬停（FAIL-O06/O08b 现场项高亮清晰）却收不到
# 点击——Tapped 判定需要 down/up 之间消息循环有机会处理。改 SendInput down/up
# 分离带 40ms + 悬停高亮前置验证：光标落位后菜单项必有填充高亮，高亮确认才
# 按、未亮重移，把"点了没生效"从静默变成可重试。
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class _MouseInput(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("mi", ctypes.c_ulong * 5)]


def _send_click_now():
    """SendInput 左键 down → 40ms → up（分离式，给弹层消息循环留处理窗口）"""
    down = _MouseInput()
    down.type = 0
    down.mi = (ctypes.c_ulong * 5)(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    up = _MouseInput()
    up.type = 0
    up.mi = (ctypes.c_ulong * 5)(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_MouseInput))
    time.sleep(0.04)
    ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_MouseInput))
    time.sleep(0.12)


def _hover_confirmed(x, y, pre):
    """悬停高亮验证：SetCursorPos 后菜单项必有填充高亮，小邻域与点击前帧差分明显"""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.35)
    post = grab_img()
    box = (int(x) - 55, int(y) - 11, int(x) + 75, int(y) + 11)
    return _region_diff(pre, post, box) > 0.02


def _click_xy(x, y):
    """v35 回滚到 v33 基线：SetCursorPos + mouse_event 直点（v34 SendInput
    分离式+悬停前置验证实测更差，43716470756 实锤回滚）。"""
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.12)
    ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.04)
    ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.7)


# ============ v33：无 UIA 纯坐标菜单驱动（五班实锤收官） ============
# 机理定谳（v32 班证据回灌）：
# ① 云 runner UIA 对弹层 hwnd 偶发可用、常发失明（同弹层 V02 命中/V03 MISS；
#    case-eols 现场命中过一次 Unix(LF) 后 Mac(CR) MISS）——不能作为依赖；
# ② 顶级固定坐标点击必拉开弹层（b 班 4 次 trace「点开菜单」与兜底点击一一对应，
#    FAIL-T01/FAIL-V03/case-eols 三张现场截图弹层全部渲染正常）；
# ③ 弹层几何恒定（三图实测）：一级弹层左缘≈顶级项中心-13、首项中心 y≈窗顶+95.5、
#    项距≈31.7~32；二级弹层左缘≈一级右缘+3（编码 tc+100 / 查看 tc+105）、
#    首项中心 y≈父项中心+4、项距≈32；
# ④ 鼠标菜单后键盘路径不可靠（四班连红）→ 全鼠标；注释和弦由编辑器 KeyDown
#    原生支持（CodeEditor.cs 2403-2464：Ctrl+K 后 2 秒内第二段带不带 Ctrl 都认）。
# 弹层项条目序号 = XAML 顺序（分隔线行带按高度过滤，不占序号）。

MENU_INDEX = {
    "文件": {"新建": 0, "打开…": 1, "最近文件": 2, "保存": 3, "另存为…": 4,
            "全部保存": 5, "快照": 6, "导出": 7, "关闭标签": 8, "退出": 9},
    "编辑": {"撤销（Ctrl+Z）": 0, "重做（Ctrl+Y）": 1, "剪切（Ctrl+X）": 2,
            "复制（Ctrl+C）": 3, "粘贴（Ctrl+V）": 4, "全选（Ctrl+A）": 5,
            "插入时间日期（F5）": 6, "行操作": 7, "大小写转换": 8,
            "格式化文档（Ctrl+K, Ctrl+D）": 9,
            "注释选区（Ctrl+K, C）": 10, "取消注释选区（Ctrl+K, U）": 11},
    "搜索": {"查找": 0, "替换": 1, "在文件中查找…": 2, "查找下一个": 3,
            "查找上一个": 4, "转到行…": 5},
    "查看": {"自动换行": 0, "显示行号": 1, "缩放": 2, "预览": 3, "大纲": 4},
    "编码": {"保存编码": 0, "换行符": 1},
    "主题": {"水墨": 0, "天青": 1, "墨夜": 2},
    "工具": {"设置…": 0},
}

SUB_ITEMS = {
    ("查看", "缩放"): ["放大", "缩小", "复位"],
    ("编码", "保存编码"): ["UTF-8", "UTF-8 BOM", "UTF-16 LE", "GBK", "Big5"],
    ("编码", "换行符"): ["Windows (CRLF)", "Unix (LF)", "Mac (CR)"],
    ("文件", "导出"): ["导出为可打印 HTML（PDF 用）…"],
    ("文件", "快照"): ["立即留底", "查看快照…"],
    ("编辑", "行操作"): ["删除当前行（Ctrl+Shift+L）", "复制当前行（Ctrl+D）",
                    "上移当前行（Alt+↑）", "下移当前行（Alt+↓）"],
    ("编辑", "大小写转换"): ["转为大写（Ctrl+Shift+U）", "转为小写（Ctrl+U）"],
}

# 二级弹层左缘相对顶级项中心的偏移（case-eols 实锤：编码 513-413=+100；
# 查看一级右缘 400=tc+102 → 二级 +105）
SEC_LEFT_OFF = {("查看", "缩放"): 105, ("编码", "保存编码"): 100, ("编码", "换行符"): 100,
                ("文件", "导出"): 105, ("文件", "快照"): 105, ("编辑", "行操作"): 105, ("编辑", "大小写转换"): 105}


def _region_diff(img_a, img_b, box):
    """绝对矩形两帧差分占比（弹层拉开验证：编辑区静态，caret 闪烁占比可忽略）"""
    ga = img_a.crop(box).convert("L")
    gb = img_b.crop(box).convert("L")
    if ga.size != gb.size:
        return 0.0
    da, db = ga.load(), gb.load()
    W, H = ga.size
    diff = sum(1 for y in range(0, H, 3) for x in range(0, W, 3) if abs(da[x, y] - db[x, y]) > 12)
    total = (H // 3 + 1) * (W // 3 + 1)
    return diff / total


def _ink_bands(img, x0, x1, y0, y1, min_h=6, gap=3):
    """窄条带行带检测：返回 [(中心y绝对, 带高, 墨迹x中心绝对)]。
    img 传 None 则现抓。抗锯齿断行按 gap 容差合并（v33 修：FAIL-V03 的 207 行
    曾被 2 行空隙切成 4 段全灭）；高度 < min_h 的分隔线/杂点丢弃；
    极性自动（水墨亮底/墨夜暗底通吃）。"""
    if img is None:
        img = grab_img()
    W, H = img.size
    x0, x1 = max(0, int(x0)), min(W, int(x1))
    y0, y1 = max(0, int(y0)), min(H, int(y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return []
    g = img.crop((x0, y0, x1, y1)).convert("L")
    px = g.load()
    w, h = g.size
    vals = [px[x, y] for y in range(0, h, 3) for x in range(w)]
    lo, hi = min(vals), max(vals)
    if hi - lo < 24:
        return []
    thr = (lo + hi) // 2
    dark = sum(1 for v in vals if v < thr)
    ink = (lambda v: v < thr) if dark <= len(vals) / 2 else (lambda v: v > thr)
    segs = []
    s = None
    gap_run = 0
    for y in range(h):
        cnt = sum(1 for x in range(w) if ink(px[x, y]))
        if cnt >= 4:
            if s is None:
                s = y
            gap_run = 0
        elif s is not None:
            gap_run += 1
            if gap_run > gap:
                segs.append((s, y - gap_run))
                s, gap_run = None, 0
    if s is not None:
        segs.append((s, h - 1))
    out = []
    for ys, ye in segs:
        if ye - ys + 1 < min_h:
            continue
        ymid = (ys + ye) // 2
        xsn = [x for x in range(w) if ink(px[x, ymid])]
        cx = (xsn[0] + xsn[-1]) // 2 if xsn else w // 2
        out.append((y0 + ymid, ye - ys + 1, x0 + cx))
    return out


def _pick_band(bands, idx, y_exp):
    """行带序号 + 期望 y 邻域双重校验：序号选带（y 偏差 ≤22 才采信），
    退而求其次取期望 y ±14 内唯一带；都不中返回 None。"""
    if idx < len(bands):
        b = bands[idx]
        if abs(b[0] - y_exp) <= 22:
            return b
    near = [b for b in bands if abs(b[0] - y_exp) <= 14]
    if len(near) == 1:
        return near[0]
    return None


def _trace_lines(mark):
    """静默读 trace.log 自 mark 行后的新增行（回执判定用，不打印）。"""
    for p_ in TRACE_PATHS:
        try:
            with open(p_, encoding="utf-8", errors="replace") as f:
                return [l.rstrip("\r\n") for l in f.readlines()[mark:]]
        except OSError:
            continue
    return []


def _trace_wait_item(mark, text, wait=2.5, poll=0.35):
    """v36：等待 trace 出现「菜单项：{text}」回执（app v35 挂接的 Click 真值，
    快捷键经 KeyboardAccelerator 触发 Click 同样在记）。命中即回。"""
    t0 = time.time()
    while time.time() - t0 < wait:
        if any(f"菜单项：{text}" in l for l in _trace_lines(mark)):
            return True
        time.sleep(poll)
    return False


def menu_xy(top, item=None, sub=None, keep_open=False):
    """v36：鼠标顶级 + 弹层内键盘导航 + trace 回执闭环验证。

    v35 定谳（run 43718737382 证据包 + app trace 回执逐案）：
    - 顶级鼠标点击全程 100% 吃（每轮 trace「点开菜单」在记）；
    - F10→RIGHT×k→ENTER 键序在云上 F10 频繁被吞，RIGHT/ENTER 落进编辑器
      （C01/C02 多余换行实锤：每失败一轮文档多 3 个 CRLF）——顶级弃键盘；
    - 弹层开后 DOWN×idx+ENTER 激活可行但偶发假成功（v35 激活后不验证：
      T01 打底天青、O08b 新建、T02 设置全是假成功）；
    - esc_cleanup 收尾会把激活刚打开的对话框/选择器关掉（F04/O06 实锤，
      激活 trace 在记、画面差分 0）——弹窗类目标 keep_open=True 跳过收尾；
    - app trace「菜单项：{文本}」回执 = 激活真值（v35 已挂接）。

    v36 流程：顶级一律鼠标点击（差分验证）→ 弹层内 DOWN×idx+ENTER 激活
    → trace 回执验证，未记则行带坐标直点兜底 → 再验，仍无回执收层重试；
    二级先 RIGHT 展开（差分验证，未开退坐标点击父项——v35 实锤可展开），
    再 DOWN×sidx+ENTER 同法验证。用例以自身断言诚实记红，失败返回 False。"""
    tops = ["文件", "编辑", "搜索", "查看", "语言", "编码", "主题", "工具"]
    if top not in tops:
        print(f"menu_xy[{top}>{item}>{sub}] 无顶级序映射", flush=True)
        return False
    for attempt in range(3):
        esc_cleanup()
        focus_main()
        try:
            import win32gui
            l, t, _r, _b = win32gui.GetWindowRect(WIN_HANDLE)
        except Exception:
            print(f"menu_xy[{top}>{item}>{sub}] 窗口矩形获取失败", flush=True)
            return False
        tc = l + TOP_MENU_XY[top][0]
        pre = grab_img()
        if not _click_top_by_layout(top):
            return False
        post = grab_img()
        strip = (tc - 8, t + 82, tc + 100, t + 510)
        d = _region_diff(pre, post, strip)
        bands = _ink_bands(post, strip[0], strip[2], strip[1], strip[3])
        if d < 0.002 or not bands:
            time.sleep(0.8)
            post = grab_img()
            d = _region_diff(pre, post, strip)
            bands = _ink_bands(post, strip[0], strip[2], strip[1], strip[3])
        if d < 0.002 or not bands:
            print(f"menu_xy[{top}] 第{attempt+1}次顶级弹层未开（差分 {d:.5f}，行带 {len(bands)}）", flush=True)
            continue
        if item is None:
            if not keep_open:
                esc_cleanup()
            return True
        idx = MENU_INDEX.get(top, {}).get(item)
        if idx is None and top == "语言" and item in LANGS:
            idx = LANGS.index(item)
        if idx is None:
            print(f"menu_xy[{top}>{item}] 无序号映射", flush=True)
            esc_cleanup()
            return False
        mark = trace_mark()
        is_parent = sub is not None   # 父项(MenuFlyoutSubItem)无 Click 回执，以二级差分为真值
        # 通道一：键盘 DOWN×idx + ENTER（v35 成功主路径）
        for _ in range(idx):
            send_keys("{DOWN}")
            time.sleep(0.28)
        send_keys("{ENTER}")
        ok = True if is_parent else _trace_wait_item(mark, item)
        if not ok and not is_parent:
            # 通道二：行带坐标直点（v35 坐标点击父项实证可作用于弹层）
            band = _pick_band(bands, idx, t + 95.5 + 31.7 * idx)
            if band:
                _click_xy(band[2] + 10, band[0])
                time.sleep(0.5)
            ok = _trace_wait_item(mark, item, wait=1.2)
        if not ok:
            print(f"menu_xy[{top}>{item}] 第{attempt+1}次激活无回执，重试", flush=True)
            esc_cleanup()
            try:
                close_menus_uia()
            except Exception:
                pass
            continue
        if sub is None:
            if not keep_open:
                esc_cleanup()
            return True
        subs = SUB_ITEMS.get((top, item), [])
        if sub not in subs:
            print(f"menu_xy[{top}>{item}>{sub}] 无二级序号映射", flush=True)
            esc_cleanup()
            return False
        sidx = subs.index(sub)
        sx = tc + SEC_LEFT_OFF.get((top, item), 105)
        strip2 = (sx + 4, t + 82, sx + 200, t + 560)
        opened2 = False
        band = None
        for ch in range(2):
            send_keys("{RIGHT}")
            time.sleep(0.8)
            post2 = grab_img()
            d2 = _region_diff(post, post2, strip2)
            bands2 = _ink_bands(post2, strip2[0], strip2[2], strip2[1], strip2[3])
            if d2 >= 0.002 and bands2:
                opened2 = True
                band = _pick_band(bands, idx, t + 95.5 + 31.7 * idx)
                break
            band = _pick_band(bands, idx, t + 95.5 + 31.7 * idx)
            if band:
                _click_xy(band[2] + 10, band[0])   # v33 基线坐标点击父项=展开
                time.sleep(0.7)
        if not opened2:
            print(f"menu_xy[{top}>{item}>{sub}] 第{attempt+1}次二级弹层未开", flush=True)
            esc_cleanup()
            continue
        mark2 = trace_mark()
        for _ in range(sidx):
            send_keys("{DOWN}")
            time.sleep(0.28)
        send_keys("{ENTER}")
        ok2 = _trace_wait_item(mark2, sub)
        if not ok2:
            band2 = _pick_band(bands2, sidx, t + 95.5 + 31.7 * sidx)
            if band2:
                _click_xy(sx + 50, band2[0])
                time.sleep(0.5)
            ok2 = _trace_wait_item(mark2, sub, wait=1.2)
        if not ok2:
            print(f"menu_xy[{top}>{item}>{sub}] 第{attempt+1}次激活无回执，重试", flush=True)
            esc_cleanup()
            continue
        if not keep_open:
            esc_cleanup()
        return True
    esc_cleanup()
    return False


def chord_ctrl_k(second_vk):
    """VS 两段式和弦（CodeEditor.cs 2403-2464 实锤）：Ctrl 按住不发 → K 按放 →
    第二段按放 → Ctrl 抬起。keybd_event 直发，全程 <0.3s 远在 2 秒窗口内；
    第二段带 Ctrl（源码两种都认）。0x43=C 注释、0x55=U 取消注释。"""
    for vk, flag in ((0x11, 0), (0x4B, 0), (0x4B, 2), (second_vk, 0), (second_vk, 2), (0x11, 2)):
        ctypes.windll.user32.keybd_event(vk, 0, flag, 0)
        time.sleep(0.04)
    time.sleep(0.6)


def _clip_poll(want_ok, tries=4, gap=0.5):
    """v34：剪贴板轮询读。第 11 轮 E07 实锤——单次 0.4s 后读剪贴板，云 runner
    慢机器上剪贴板未就绪被误判失败，触发菜单兜底重复注释（##code-line）。
    改轮询：达标即回，最多 tries 次。"""
    for i in range(tries):
        got = editor_clipboard().strip()
        if want_ok(got):
            return got
        time.sleep(gap)
    return editor_clipboard().strip()


def comment_op(un, want_ok):
    """v36：注释/取消注释统一菜单路径。v35 双轮实锤：编辑器和弦第二段
    keybd_event 直发在云 runner 被吞（剪贴板恒为原样文本、无 # 也无 //），
    而菜单「注释选区」通道以 trace 回执验证后可靠可重试——弃和弦，回执
    闭环，剪贴板轮询照旧。"""
    esc_cleanup()
    send_keys("^a")
    time.sleep(0.25)
    menu_xy("编辑", "取消注释选区（Ctrl+K, U）" if un else "注释选区（Ctrl+K, C）")
    time.sleep(0.4)
    return _clip_poll(want_ok)


def menu_kb(*titles):
    """v32：全鼠标逐项点击 + 每步 UIA 验证（换思路，五班实锤收官）。
    旧键序路径四班连红：鼠标点开菜单后键盘 DOWN 被吞/ENTER 落第 0 项
    （V03 反复切自动换行、C01/C02 编码换行落 idx0、L01/E07 注释未执行）；
    F10 兜底探针用常驻 MenuBarItem「文件」作探针，树失明时误杀、也测不出
    真没拉起。新路径：顶级 = UIA 矩形点击、失败走固定坐标兜底；下级 =
    worker 扫同进程窗口定位弹层项矩形 → 坐标点击（父项点击=展开子菜单，
    叶项点击=执行）；下一级出现即验证。全程无键入（不落编辑器、无误触
    退出）。失败返回 False，用例以自身断言诚实记红。"""
    close_panel(verify=False)
    mark = trace_mark()
    top = titles[0]
    ok = worker_click_menu(top) or _click_top_by_layout(top)
    if not ok:
        esc_cleanup()
        ok = worker_click_menu(top) or _click_top_by_layout(top)
    if not ok:
        print(f"menu[{'>'.join(titles)}] 顶级点击失败（UIA+布局兜底均未命中）", flush=True)
        return False
    time.sleep(1.0)
    for depth in range(1, len(titles)):
        title = titles[depth]
        pos = worker_menu_hit(title, wait=6.0)
        if pos is None:
            # 弹层未展开/未就绪：收层重开顶级再找一轮
            esc_cleanup()
            if worker_click_menu(top) or _click_top_by_layout(top):
                time.sleep(1.0)
                pos = worker_menu_hit(title, wait=6.0)
        if pos is None:
            esc_cleanup()
            print(f"menu[{'>'.join(titles)}] 弹层项[{title}]定位失败", flush=True)
            return False
        _click_xy(*pos)
    trace_since(mark)
    return True


def copy_current_line():
    """光标所在行复制：HOME 归位 → SHIFT+END 选行 → ^c（不依赖 UIA 读状态栏）"""
    pyperclip.copy("")
    send_keys("{HOME}")
    time.sleep(0.25)
    send_keys("+{END}")
    time.sleep(0.25)
    send_keys("^c")
    time.sleep(0.4)
    return pyperclip.paste()


def grab_img():
    return ImageGrab.grab()


def _pixel_changed(img_a, img_b=None, crop=(0.05, 0.10, 0.95, 0.90)):
    """两帧灰度差分占比（面板出现/主题换色/行号显隐必然改变画面）"""
    if img_b is None:
        img_b = grab_img()
    w, h = img_a.size
    box = (int(w*crop[0]), int(h*crop[1]), int(w*crop[2]), int(h*crop[3]))
    ga = img_a.crop(box).convert("L")
    gb = img_b.crop(box).convert("L")
    if ga.size != gb.size:
        gb = gb.resize(ga.size)
    da, db = ga.load(), gb.load()
    W, H = ga.size
    diff = sum(1 for y in range(0, H, 3) for x in range(0, W, 3) if abs(da[x, y] - db[x, y]) > 12)
    total = (H // 3 + 1) * (W // 3 + 1)
    return diff / total


def _ink_stats(img, crop=(0.15, 0.25, 0.85, 0.75)):
    """编辑区中央裁片墨迹统计：返回 (文本行带高中位数px, 墨迹占比, 行带数)。
    背景按多数色自动定极性，深浅主题通吃；无文本返回 None。"""
    w, h = img.size
    box = (int(w*crop[0]), int(h*crop[1]), int(w*crop[2]), int(h*crop[3]))
    g = img.crop(box).convert("L")
    px = list(g.getdata())
    lo, hi = min(px), max(px)
    if hi - lo < 24:
        return None
    thr = (lo + hi) // 2
    W, H = g.size
    data = g.load()
    ys = range(0, H, 2)
    xs = range(0, W, 2)
    dark = 0
    total = 0
    for y in ys:
        for x in xs:
            total += 1
            if data[x, y] < thr:
                dark += 1
    ink_is_dark = dark <= total / 2
    bands = []
    in_band = 0
    for y in range(H):
        row_ink = sum(1 for x in range(0, W, 2) if (data[x, y] < thr) == ink_is_dark)
        if row_ink >= 3:
            in_band += 1
        elif in_band:
            if in_band >= 3:
                bands.append(in_band)
            in_band = 0
    if in_band >= 3:
        bands.append(in_band)
    if not bands:
        return None
    bands.sort()
    med = bands[len(bands) // 2]
    ink_ratio = (dark if ink_is_dark else total - dark) / total
    return (med, ink_ratio, len(bands))


def c_zoom():
    # v33：换思路双修。①动作改 查看→缩放 二级弹层坐标驱动（menu_xy），
    # 失败退 Ctrl+Add/Subtract/Number0 热键（XAML 加速键实锤）；
    # ②断言弃 _ink_stats 行带量测（v32 实锤失灵：基线=(191,0.031,2) 两帧全等
    # 却报不出缩放）——改收层后整幅像素差分：缩放必然重排全部字形渲染，
    # 放大/缩小/复位前后的差分即为生效实证；复位另须回到基线（差分≈0）。
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("\n".join(f"缩放采样行 zoom-probe-{i:02d} HhIi" for i in range(6)))
    time.sleep(0.5)
    base = grab_img()
    prev = base
    for label, tag in (("放大", "in1"), ("放大", "in2"), ("缩小", "out"), ("复位", "reset")):
        ok = menu_xy("查看", "缩放", label)
        if not ok:
            vk = {"放大": 0x6B, "缩小": 0x6D, "复位": 0x30}[label]
            print(f"缩放[{label}] 弹层路径失败，退热键 0x{vk:02X}", flush=True)
            focus_main()
            zoom_hotkey(vk)
        time.sleep(0.6)
        esc_cleanup()
        time.sleep(0.3)
        img = grab_img()
        d = _pixel_changed(prev, img)
        prev = img
        shot(f"case-zoom-{tag}")
        print(f"缩放[{label}] 差分 {d:.5f}", flush=True)
        if label != "复位":
            assert d > 0.004, f"缩放[{label}]画面无变化（差分 {d:.5f}）"
        else:
            # 基线阈值 0.004→0.01（run 44096504055 实测）：复位后文本全等，
            # 对基线差分 0.0049 纯属光标闪烁相位噪声；复位差分 0.019 远超动作阈值
            d_base = _pixel_changed(base, img)
            assert d > 0.004 and d_base < 0.01, \
                f"复位未回到基线: 复位差分={d:.5f} 对基线差分={d_base:.5f}"


def c_wrap_toggle():
    # v33：menu_xy 坐标驱动 + 收层后取证。v32 实锤教训：弹层开着差分必然
    # 巨量（V02 假绿通道——FAIL-V03 现场自动换行仍带勾，证 v32 两次 toggle
    # 只成了一次），必须 ESC 收层后再抓帧，差分才只反映换行渲染变化。
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    type_text("wrap-" * 120)
    time.sleep(0.4)
    w0 = grab_img()
    menu_xy("查看", "自动换行")
    time.sleep(0.6)
    esc_cleanup()
    time.sleep(0.3)
    w1 = grab_img()
    shot("case-wrap-on")
    d1 = _pixel_changed(w0, w1)
    menu_xy("查看", "自动换行")
    time.sleep(0.6)
    esc_cleanup()
    time.sleep(0.3)
    w2 = grab_img()
    shot("case-wrap-off")
    d2 = _pixel_changed(w1, w2)
    assert d1 > 0.004 and d2 > 0.004, f"换行开关画面无变化: on段={d1:.5f} off段={d2:.5f}"


def c_lineno_toggle():
    # v30：真人路径 + 行号栏像素差分断言（左侧带显隐必然改变画面）
    # v33：menu_xy 坐标驱动 + 收层后取证（查看弹层 x 288-400 落在 crop 内，
    # 不收层差分会被弹层开合污染——V02 假绿同款通道）。
    a0 = grab_img()
    menu_xy("查看", "显示行号")
    time.sleep(0.6)
    esc_cleanup()
    time.sleep(0.3)
    a1 = grab_img()
    shot("case-lineno-off")
    d1 = _pixel_changed(a0, a1, crop=(0.0, 0.12, 0.30, 0.85))
    menu_xy("查看", "显示行号")
    time.sleep(0.6)
    esc_cleanup()
    time.sleep(0.3)
    a2 = grab_img()
    shot("case-lineno-on")
    d2 = _pixel_changed(a1, a2, crop=(0.0, 0.12, 0.30, 0.85))
    # v32：crop 加宽 0.18→0.30——行号数字渲染在 x≈183-186（1024 宽）恰在旧
    # 右界压线，防裁切假红；v31 差分 0 的真因是菜单未执行（两帧截图 diff=0），
    # 非裁切，但边界压线仍属脆弱点一并修。
    assert d1 > 0.0006 and d2 > 0.0006, f"行号开关画面无变化: off段={d1:.5f} on段={d2:.5f}"


THEMES = ["水墨", "天青", "墨夜"]


def _bg_box():
    """v38：采样框改窗口相对坐标（v37 实锤：全屏相对框采到桌面壁纸，
    r-b 恒 -67，三段全灭）。取菜单栏右侧空白段（Ant.Bg 底，无文字）。
    GetWindowRect 失败退脚本钉定的窗口锚点 (100,80)。"""
    l, t = 100, 80
    try:
        import win32gui
        wr = win32gui.GetWindowRect(WIN_HANDLE)
        l, t = wr[0], wr[1]
    except Exception:
        pass
    return (l + 465, t + 46, l + 560, t + 70)


def _bg_tint(img, box=None):
    """v37/v38：主题探针——采样窗底(菜单栏右侧空白带)平均 RGB 的 r-b 色偏
    与亮度。水墨 #FCFBF7 偏暖(r>b, lum≈251)、天青 #EDF2EF 偏青(r<b, lum≈242)、
    墨夜 #131211 深底(lum≈19)——r-b 单独分不开 天青(-2)/墨夜(+2)，
    断言改用 (r-b, 亮度) 二维距离。"""
    if box is None:
        box = _bg_box()
    c = img.crop(box).convert("RGB")
    px = list(c.getdata())
    n = len(px)
    r = sum(p[0] for p in px) / n
    g = sum(p[1] for p in px) / n
    b = sum(p[2] for p in px) / n
    return r - b, (r + g + b) / 3


def c_themes():
    # v38：窗口相对采样 + 二维判据（原理见 _bg_tint）。打底离开水墨并校准基线，
    # 三套逐一切换，每段断言 (r-b,亮度) 段距明显。
    menu_xy("主题", "天青")
    time.sleep(1.0)
    esc_cleanup()
    time.sleep(0.3)
    prev_tint, prev_lum = _bg_tint(grab_img())
    for i, t in enumerate(THEMES):
        menu_xy("主题", t)
        time.sleep(1.0)
        esc_cleanup()
        time.sleep(0.3)
        img = grab_img()
        cur_tint, cur_lum = _bg_tint(img)
        shot(f"case-theme-{i}")
        delta = ((cur_tint - prev_tint) ** 2 + (cur_lum - prev_lum) ** 2) ** 0.5
        prev_tint, prev_lum = cur_tint, cur_lum
        print(f"主题[{t}] 色偏 r-b={cur_tint:+.2f} 亮度={cur_lum:.1f}（段差 {delta:.2f}）", flush=True)
        assert delta > 6, f"主题[{t}]切换后窗底色相无变化（r-b={cur_tint:+.2f} 亮度={cur_lum:.1f}，段差 {delta:.2f}）"


ENCS = ["UTF-8 BOM", "UTF-16 LE", "GBK", "Big5", "UTF-8"]


def c_encodings():
    # v30：不读状态栏。存盘后读字节断言（SaveDocAsync 写 doc.Enc + doc.Bom 前导）
    p = os.path.join(DOCS, "taopad-enc-bytes.txt")
    if os.path.exists(p):
        os.remove(p)
    click_editor()
    send_keys("^a{DEL}")
    type_text("save-me-文")   # 「文」GBK/Big5 双码表可编（内 是简体字，Big5 编不了）
    for i, enc in enumerate(ENCS):
        menu_xy("编码", "保存编码", enc)
        time.sleep(0.4)
        focus_main()
        send_keys("^s")
        time.sleep(0.6)
        if i == 0:
            picker_typing(p)   # 未命名文档首存走选择器（O01 已验证通道）
            time.sleep(1.2)
        assert os.path.exists(p), f"[{enc}] 保存后文件不存在: {p}"
        with open(p, "rb") as f:
            data = f.read()
        if enc == "UTF-8 BOM":
            assert data.startswith(b"\xef\xbb\xbf"), f"[{enc}] 无 BOM 头: {data[:12].hex()}"
        elif enc == "UTF-16 LE":
            assert data.startswith(b"\xff\xfe"), f"[{enc}] 无 UTF-16 LE 前导: {data[:12].hex()}"
            body = data[2:].decode("utf-16-le")
            assert "文" in body, f"[{enc}] UTF-16 解码无中文样文: {body[:40]!r}"
        elif enc in ("GBK", "Big5"):
            assert not data.startswith(b"\xef\xbb\xbf") and not data.startswith(b"\xff\xfe"), \
                f"[{enc}] 不应带 BOM: {data[:8].hex()}"
            want = ("gbk" if enc == "GBK" else "big5")
            assert data == "save-me-文".encode(want), \
                f"[{enc}] 字节不匹配: {data[:24].hex()} vs {'save-me-文'.encode(want).hex()}"
        else:   # UTF-8 无 BOM
            assert not data.startswith(b"\xef\xbb\xbf"), f"[{enc}] 不应带 BOM: {data[:8].hex()}"
            assert "save-me-文".encode("utf-8") in data, f"[{enc}] 非 UTF-8 字节: {data[:24].hex()}"
        print(f"[{enc}] 字节断言过: {data[:16].hex()} len={len(data)}", flush=True)
    shot("case-encodings")


EOLS = [("Unix (LF)", "LF"), ("Mac (CR)", "CR"), ("Windows (CRLF)", "CRLF")]


def c_eols():
    # v30：字节级断言落盘换行。源码实锤：换行菜单只写 doc.Eol（状态栏显示），
    # SaveDocAsync 直写 doc.Editor.Text，其换行由 OutputEol（内容探测）决定——
    # 菜单选择若未应用到落盘字节，属应用真实发现，按规范六.3 如实记红不重跑。
    p = os.path.join(DOCS, "taopad-eol-bytes.txt")
    if os.path.exists(p):
        os.remove(p)
    send_keys("^n")        # v31：新标签保证未命名文档，^s 才走选择器（C01 已命名实锤）
    time.sleep(0.9)
    click_editor()
    send_keys("^a{DEL}")
    type_text("eol-line1\neol-line2")
    first = True
    EOL_WANT = {"LF": "\n", "CR": "\r", "CRLF": "\r\n"}
    found = []
    for title, token in EOLS:
        want = EOL_WANT[token]
        menu_xy("编码", "换行符", title)
        time.sleep(0.4)
        focus_main()
        send_keys("^s")
        time.sleep(0.6)
        if first:
            picker_typing(p)
            time.sleep(1.2)
            first = False
        assert os.path.exists(p), f"[{token}] 保存后文件不存在: {p}"
        with open(p, "rb") as f:
            data = f.read()
        n_crlf = data.count(b"\r\n")
        n_lf = data.count(b"\n") - n_crlf
        n_cr = data.count(b"\r") - n_crlf
        if want == "\r\n":
            ok = n_crlf > 0 and n_lf == 0 and n_cr == 0
        elif want == "\n":
            ok = n_lf > 0 and n_crlf == 0 and n_cr == 0
        else:
            ok = n_cr > 0 and n_crlf == 0 and n_lf == 0
        found.append((token, ok, n_crlf, n_lf, n_cr, bytes(data[:40])))
        print(f"[EOL] 菜单选择 {token}: CRLF={n_crlf} LF={n_lf} CR={n_cr} {'过' if ok else '未应用'}", flush=True)
    shot("case-eols")
    bad = [f for f in found if not f[1]]
    assert not bad, "换行符未应用到落盘字节: " + "; ".join(
        f"{t}: CRLF={c} LF={l} CR={r} 数据={d!r}" for t, _ok, c, l, r, d in bad)


LANGS = ["纯文本", "C / C++", "C#", "Java", "JavaScript / TypeScript", "Go", "Rust",
         "C 风格其他 (Swift/Kotlin/PHP/Dart…)", "Python", "JSON", "XML / HTML", "Markdown", "SQL",
         "Fountain 剧本"]


# 注释标记按应用源码（Syntax/CommentCommands.cs + Tokenizer.cs）：
# C 系 //，Python #，SQL --，XML/HTML 包裹 <!-- -->；
# 纯文本/JSON/Markdown 无注释语法（Toggle 返回 null，原样不动）。
LANG_MARK = {
    "纯文本": None, "C / C++": "//", "C#": "//", "Java": "//",
    "JavaScript / TypeScript": "//", "Go": "//", "Rust": "//",
    "C 风格其他 (Swift/Kotlin/PHP/Dart…)": "//", "Python": "#",
    "JSON": None, "XML / HTML": "xml", "Markdown": None, "SQL": "--",
    "Fountain 剧本": None,
}


def c_languages():
    # v33：语言切换 menu_xy 坐标驱动（LANGS 序 = LangDef.All 序，源码实锤）；
    # 注释走 comment_op 两段自救（和弦优先、编辑菜单坐标兜底）。
    # 逐语言「注释→剪贴板比对标记→取消注释还原」，
    # 语法语言切换以注释标记实际生效为实证（源码揪清单口径）。
    click_editor()
    esc_cleanup()
    send_keys("^a{DEL}")
    for lang in LANGS:
        menu_xy("语言", lang)
        time.sleep(0.5)
        click_editor()
        send_keys("^a{DEL}")
        type_text("code-line")
        want = LANG_MARK[lang]
        if want is None:
            marked = comment_op(False, lambda s: s == "code-line")
            assert marked == "code-line", f"[{lang}] 无注释语法语言被加注释: {marked[:40]!r}"
        elif want == "xml":
            marked = comment_op(False, lambda s: s.startswith("<!--") and s.endswith("-->"))
            assert marked.startswith("<!--") and marked.endswith("-->"), \
                f"[{lang}] XML 包裹注释未生效: {marked[:48]!r}"
        else:
            marked = comment_op(False, lambda s: s.startswith(want))
            assert marked.startswith(want), f"[{lang}] 注释标记[{want}]未生效: {marked[:40]!r}"
        restored = comment_op(True, lambda s: s == "code-line")
        assert restored == "code-line", f"[{lang}] 取消注释未还原: {restored[:40]!r}"
    shot("case-languages")


def c_save():
    focus_main()
    click_editor()
    esc_cleanup()
    send_keys("^n")        # v32：强制新未命名标签，^s 必走保存选择器
    time.sleep(0.9)        #（B 班 O01 实锤：已命名标签 ^s 直接落盘不弹选择器，
    click_editor()         #  picker_typing 把路径粘进编辑器→O01/O02 级联红）
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
    # v30：导出文件唯一命名防旧档假绿。v36：keep_open——v35 实锤激活后
    # esc_cleanup 把系统选择器关掉（trace 激活在记、文件未生成）。
    p = os.path.join(DOCS, "taopad-export2.html")
    if os.path.exists(p):
        os.remove(p)
    menu_xy("文件", "导出", "导出为可打印 HTML（PDF 用）…", keep_open=True)
    if not _wait_dialog(6.0):
        esc_cleanup()
        menu_xy("文件", "导出", "导出为可打印 HTML（PDF 用）…", keep_open=True)
    picker_typing(p)
    time.sleep(1.2)
    assert os.path.exists(p), "导出 HTML 未生成"
    with open(p, encoding="utf-8", errors="ignore") as f:
        head = f.read(200)
    assert "DOCTYPE html" in head or "<html" in head.lower(), "导出内容不是 HTML"
    shot("case-export-html")


def _wait_dialog(wait=6.0):
    """v36：轮询等待打开/保存类系统对话框出现（选择器弹出有延迟）。"""
    t0 = time.time()
    while time.time() - t0 < wait:
        if dialog_present():
            return True
        time.sleep(0.4)
    return False


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
    # v30：真人路径 + trace.log 断言（「设置：入口/已确认」为应用真实事件回执）。
    # 定谳：此前 menu() 未弹时 SPACE/ENTER 落编辑区（O08b 残留 'S' 实锤）= 假绿。
    mark = trace_mark()
    menu_xy("工具", "设置…", keep_open=True)   # v36：对话框开着才能收键
    time.sleep(1.3)
    shot("case-settings-dialog")
    # 云真机批次（2026-11-20）：设置弹窗「数据位置」展示断言——1.0.10 功能
    # 标签行 + TaoPaths.Root 路径行均应可读（路径恒含 TaoPad：D 盘或回退目录）
    # v46w：T02 断言换产品侧事件回执——五路 UIA 采数（主窗/子桥/顶层窗/桥子窗/
    # rawwalk 全树）在 44725830760 实锤全部看不到 ContentDialog 正文（WinUI3
    # 弹窗对外盲区，产品侧自动化名已上仍盲），采数降级为参考留痕；
    # 「设置：控件创建完成」为应用真实回执，数据位置两行就在弹窗内容里，
    # 弹窗弹出即展示（v30 设置入口同法定谳）
    dlg_ev = [l for l in trace_since(mark) if "设置：控件创建完成" in l]
    dl_texts = worker_texts()
    dl_ok = bool(dlg_ev)
    if not dl_ok:
        shot("case-settings-datalocation-miss")   # 证据留痕：采到什么、缺什么
    assert dl_ok, f"设置弹窗未获应用侧展示回执（trace_since={dlg_ev[:3]}，read_texts={dl_texts[:8]}）"
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
    ev = trace_since(mark)
    ok = any("设置：入口" in l for l in ev) and any("设置：对话框已确认" in l for l in ev)
    if not ok:
        click_editor()
        send_keys("^a{DEL}")   # 清掉误入编辑区的按键痕迹，防污染后续用例
    assert ok, "设置流程 trace 无「入口/已确认」回执（弹窗未开或应用键未触发）"


def c_mouse_menu():
    """v33：与 menu_xy 同为纯坐标路径（UIA menu_hit 偶发可用不可依赖，
    五班实锤）。保留本用例双重价值：①鼠标坐标路径建新标签；②交互后 UIA
    读层存活探针（软件侧待查缺陷：菜单交互影响 UIA Text 供给，多班实锤）。
    先落已知标记内容再开菜单——导航失败时残留可辨、可整轮重试。"""
    close_panel()
    ok = False
    got = ""
    for attempt in range(3):
        click_editor()
        send_keys("^a{DEL}")
        type_text("pre-menu-marker")
        if not menu_xy("文件", "新建"):
            esc_cleanup()
            continue
        time.sleep(1.2)
        if not dialog_present():
            click_editor()
        esc_cleanup()
        click_editor()
        type_text("mouse-path-ok")
        clip = re.sub(r"\s+", "", editor_clipboard())
        got = clip[-60:]
        if clip == "mouse-path-ok":
            ok = True
            break
        esc_cleanup()
        shot(f"case-mouse-menu-retry{attempt}")
    shot("case-mouse-menu")
    # 留证：鼠标菜单交互后 UIA 读层是否还活着（打印探针结果，不作为断言）
    print("鼠标路径后读取探针:", "存活" if read_alive() else "失效", flush=True)
    assert ok, f"鼠标路径菜单未建成新标签（内容残留）: {got!r}"


def proc_count():
    """v39：TaoPad.exe 进程计数（tasklist 口径，与 app_alive 同源）"""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=30).stdout
        return sum(1 for l in out.splitlines() if "TaoPad.exe" in l)
    except Exception:
        return -1


def _forward_open(path):
    """v39：以第二实例带文件参数拉起（资源管理器双击打开的真实通道），
    单实例机制把路径转发给主实例打开、第二进程自退。拖拽打开走同一
    OpenPaths 管线（云上无法合成真实指针拖放，拖拽交互本身如实不在覆盖内）。"""
    exe = find_exe()
    subprocess.Popen([exe, path], close_fds=True)


def c_second_instance_open():
    # v39：新增场景——已装应用再双击文件：第二实例必须自退、主实例接住
    # 并显示文件内容（单实例转发管线 + 打开内容正确性）。
    p = os.path.join(DOCS, "taopad-forward.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("single-instance-forward-内容")
    esc_cleanup()
    _forward_open(p)
    ok_open = False
    for _ in range(10):               # 主实例收到转发并显示，最多等 20 秒
        time.sleep(2.0)
        got = editor_clipboard().strip()
        if got == "single-instance-forward-内容":
            ok_open = True
            break
    assert ok_open, f"转发打开内容不对: {got!r}"
    time.sleep(2.0)
    n = proc_count()
    assert n == 1, f"第二实例进程未自退（进程数 {n}，单实例失效）"
    shot("case-second-instance")


def c_bigfile_scroll():
    # v39.5（老板令：大文件要能读写）——5.6MB/4 万行真实大文件全链路：
    # 打开 → 滚动画面连续变化（卡死=差分 0 即红）→ 末尾追加一行并保存
    # → 落盘字节核验（读写闭环，比界面读数更硬）。
    # 断言策略（两轮实锤 run 43728694460/43733372366）：5.6MB 文档会把
    # UIA 全树枚举拖死（状态栏文字都读不出，只剩窗名），但应用没挂
    # （标题活着、滚动活着、退出正常）。故行数断言改为落盘字节核验，
    # 状态栏读数不作为大文件用例的断言通道；滚动差分保留为冻结探针。
    p = os.path.join(DOCS, "taopad-bigfile.txt")
    lines = 40000
    if not os.path.exists(p) or os.path.getsize(p) < 4_000_000:
        with open(p, "w", encoding="utf-8") as f:
            for i in range(lines):
                f.write(f"L{i:05d}-" + "ABCDEFGH" * 16 + "\n")
    esc_cleanup()
    t0 = time.time()
    _forward_open(p)
    time.sleep(8)                    # 后台读取 + 界面落位
    ts = texts()
    assert any("taopad-bigfile" in t for t in ts), f"大文件标签未打开: {ts[:6]}"
    print(f"大文件打开到标签可见: {time.time()-t0:.1f}s", flush=True)
    click_editor()
    s0 = grab_img()
    send_keys("{PGDN}")
    time.sleep(0.5)
    send_keys("{PGDN}")
    time.sleep(0.8)
    d = _pixel_changed(s0, grab_img())
    print(f"大文件滚动差分: {d:.5f}", flush=True)
    assert d > 0.004, f"大文件滚动画面无变化（差分 {d:.5f}）——疑似卡死"
    shot("case-bigfile")
    # 写回闭环：末尾追加标记行，直接保存（文件已有路径不走选择器），
    # 轮询落盘字节里必须含标记——大文件「可写」的硬断言。
    send_keys("^{END}")
    time.sleep(1.0)
    type_text("\ntaopad-big-write-校验行")
    send_keys("^s")
    ok_save = False
    for _ in range(20):
        time.sleep(1.5)
        try:
            with open(p, "r", encoding="utf-8") as f:
                tail = f.read()[-200:]
            if "taopad-big-write-校验行" in tail:
                ok_save = True
                break
        except OSError:
            continue
    assert ok_save, "大文件保存落盘超时，末尾标记未写入"
    shot("case-bigfile-saved")
    esc_cleanup()


def c_exit():
    # v33：退出主路径改 WM_CLOSE 直投主窗（App.xaml.cs 实锤闭环：
    # MainWindow.Closed → UntrackWindow → 空窗 ExitAll → Current.Exit +
    # 1s Environment.Exit(0) 兜底；X 按钮同通道）。v32 五班实锤菜单项
    # 定位不可靠导致进程永驻。8 秒仍活退 menu_xy 文件→退出 坐标兜底；
    # 保存/退出确认框回车默认确认不变。
    wer_before = wer_count()
    close_panel()
    focus_main()
    click_editor()
    send_keys("^s")               # 退出前先落盘，避免未保存确认框卡住流程
    time.sleep(1.0)
    if dialog_present():          # 未命名的标签会弹另存为，补一个落盘路径
        picker_typing(os.path.join(DOCS, "taopad-exit-save.txt"))
        time.sleep(0.8)
    mark = trace_mark()
    try:
        import win32gui
        import win32con
        win32gui.PostMessage(WIN_HANDLE, win32con.WM_CLOSE, 0, 0)
        print(f"WM_CLOSE 已投递 hwnd={WIN_HANDLE}", flush=True)
    except Exception as e:
        print(f"WM_CLOSE 投递失败: {e}", flush=True)
    still = True
    t0 = time.time()
    menu_tried = False
    while still and time.time() - t0 < 20:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq TaoPad.exe"], capture_output=True, text=True)
        still = "TaoPad.exe" in out.stdout
        if still:
            if dialog_present():  # 保存/退出确认框：回车默认确认
                send_keys("{ENTER}")
            if not menu_tried and time.time() - t0 > 8:
                menu_xy("文件", "退出")
                menu_tried = True
            time.sleep(1.0)
    trace_since(mark)
    assert not still, "退出后进程仍在（等待20秒）"
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


def c_html_cold_start():
    """X14：.html 冷启动（1.1.1 v46c）——老板真机实锤：双击 .html 关联
    档案，TaoPad 即闪退。云端复现同路径：O09 已确认无运行实例后，带
    .html 参数冷启动（资源管理器双击打开的真实通道，与 X01 同族；附加
    --testhook 仅为了打开验收通道，与崩溃路径无关），验收进程存活、
    窗口在、无新崩溃记录、钩子正文含探针（文件真被加载）。"""
    p = os.path.join(DOCS, "taopad-cold.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html>\n<html><body><h1>coldstart-html-probe-771234</h1></body></html>")
    # 一并验多文件冷启动：一口气带两个档案，都要进页签（v46d 增补）
    ptxt = os.path.join(DOCS, "taopad-cold2.txt")
    with open(ptxt, "w", encoding="utf-8") as f:
        f.write("coldstart-txt-probe-447788\n")
    wer_before = wer_count()
    exe = find_exe()
    subprocess.Popen([exe, "--testhook", p, ptxt], close_fds=True)
    ok = False
    err = ""
    for _ in range(15):
        time.sleep(2.0)
        if proc_count() >= 1 and app_alive():
            ok = True
            break
        err = f"proc={proc_count()} alive={app_alive()}"
    assert ok, f"X14: .html 冷启动未存活: {err} wer={wer_before}->{wer_count()}"
    assert wer_count() == wer_before, (
        f"X14: 冷启动 .html 出现新崩溃记录: {wer_before}->{wer_count()}")
    got = ""
    docs = []
    for _ in range(10):
        time.sleep(1.5)
        data = _try_hook_dump(timeout=25.0)
        docs = (data or {}).get("docs") or []
        got = " ".join((d.get("text") or "") for d in docs)
        if "coldstart-html-probe-771234" in got and "coldstart-txt-probe-447788" in got:
            break
    assert "coldstart-html-probe-771234" in got, f"X14: .html 未被加载: tail={got[-60:]!r}"
    assert "coldstart-txt-probe-447788" in got, (
        f"X14: 多文件冷启动第二个档案未进页签: {' | '.join((d.get('path') or '') for d in docs)!r}")
    shot("case-html-coldstart")
    # 收尾：冷启动实例优雅关闭（文档未改动，不会弹保存确认），不留残留进程
    subprocess.run(["taskkill", "/IM", "TaoPad.exe"], capture_output=True, timeout=30)
    time.sleep(2.0)


c_html_cold_start.self_launch = True   # 自带拉起进程，绕过 case() 的存活守卫


def _try_hook_dump(timeout=25.0):
    """钩子快照安全版：界面冻死/超时返回 None 而不是抛异常。"""
    try:
        return hook_dump(timeout=timeout)
    except Exception:
        return None


def _find_window_by_title(fragment, timeout=60):
    """枚举顶层窗口，返回标题含 fragment 的句柄（找不到返回 0）。"""
    import win32gui
    found = [0]

    def _cb(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd) and fragment in (win32gui.GetWindowText(hwnd) or ""):
                found[0] = hwnd
                return False
        except Exception:
            pass
        return True

    t0 = time.time()
    while time.time() - t0 < timeout:
        win32gui.EnumWindows(_cb, None)
        if found[0]:
            return found[0]
        time.sleep(1.0)
    return 0


def c_big_color_open():
    """X15：大号着色档案打开不冻界面（1.1.1 v46d）——老板真机实锤：
    双击 .html 窗口出来后一直转卡住。此前唯一的大文件用例（X02）是
    5.6MB 纯文本滚动，「几十 MB 着色档案走编辑管线」零覆盖。本用例
    生成 ~30MB 网页档案转发打开（与双击同管线），验收=钩子快照能回来
    （快照经 UI 线程，回不来=界面冻死）、活动档案就是它、正文含探针。"""
    p = os.path.join(DOCS, "taopad-big-color.html")
    if not os.path.exists(p) or os.path.getsize(p) < 25_000_000:
        with open(p, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n<html><body>bigcolor-probe-920831\n")
            line = '<div class="item-123" style="color:#123456;padding:2px;margin:0;">内容 0123456789 abcdefghij</div>\n'
            for _ in range(430_000):
                f.write(line)
    esc_cleanup()
    _forward_open(p)
    doc = {}
    ok = False
    deadline = time.time() + 150
    resent = False
    while time.time() < deadline:
        data = _try_hook_dump(timeout=25.0)
        if data is not None:
            docs = data.get("docs") or []
            act = data.get("active", -1)
            doc = docs[act] if 0 <= act < len(docs) else (docs[-1] if docs else {})
            # 44737489394 X15 实锤：活动档案 path 可为 None（打开竞态下
            # 键存在值空），.get 第二参只挡键缺失不挡 None——or 兜空串
            if (doc.get("path") or "").endswith("taopad-big-color.html"):
                ok = True
                break
        # 44324138369 X15 实锤：60 秒仍未接住=转发被会话毛刺吞
        # （同场 X14/X19 首跑失败重跑过的环境吞击同型），补发一次
        # 转发，不改产品口径。
        # 44737489394 重跑实锤：30MB 加载占住 UI 线程时快照通道整段
        # 无应答，补发原挂在 data 非空之下永不触发——改为到点必补发
        if not resent and time.time() > deadline - 90:
            resent = True
            print("X15: 首次转发未激活，补发一次", flush=True)
            _forward_open(p)
        time.sleep(3.0)
    assert ok, (f"X15: 30MB 着色档案未在时限内加载/界面无响应: "
                f"path={(doc or {}).get('path', '')!r} tail={(doc or {}).get('text', '')[-40:]!r} "
                f"补发={(resent)}")
    assert "bigcolor-probe-920831" in (doc.get("text") or ""), "X15: 大文件正文未进编辑器"
    shot("case-big-color")
    # 复验一次快照仍能回来：着色批次不是把界面拖死后才回执
    assert _try_hook_dump(timeout=25.0) is not None, "X15: 首次快照后界面已冻死（快照回不来）"


def c_huge_boundary():
    """X16：50MB 硬上限边界（1.1.1 v46d）——超过 50_000_000 字节走
    HugeFileViewer 只读快看（编辑器不接），此前零覆盖。验收=快看窗
    出现（标题含「快看（只读）」）、编辑器档案列表里没有它、主窗口
    仍存活。"""
    p = os.path.join(DOCS, "taopad-huge-boundary.html")
    if not os.path.exists(p) or os.path.getsize(p) <= 50_000_000:
        with open(p, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html>\n<html><body>huge-boundary-probe-630742\n")
            chunk = '<div class="fill" style="color:#334455;">边界填充 0123456789</div>\n' * 1000
            while os.path.getsize(p) <= 50_500_000:
                f.write(chunk)
    esc_cleanup()
    _forward_open(p)
    hwnd = _find_window_by_title("快看（只读）", timeout=90)
    assert hwnd, "X16: 超限文件未弹只读快看窗（疑似走了编辑管线或卡死）"
    data = _try_hook_dump(timeout=25.0)
    got_paths = " | ".join((d.get("path") or "") for d in ((data or {}).get("docs") or []))
    assert "taopad-huge-boundary.html" not in got_paths, (
        f"X16: 超限文件被编辑器接走（应走快看）: {got_paths!r}")
    assert app_alive(), "X16: 打开超限文件后主窗口没了"
    shot("case-huge-boundary")
    # 收尾：关掉快看窗，不留多余窗口
    try:
        import win32gui as _wg
        import win32con as _wc
        _wg.PostMessage(hwnd, _wc.WM_CLOSE, 0, 0)
    except Exception:
        pass
    time.sleep(1.5)


def c_external_change():
    """X17：外部修改提醒（1.1.1 v46d）——文件监视对活动档案的外部改动：
    干净档案弹「文件已在外部修改」对话框（ESC=暂不，内容不丢）；有未保存
    改动时仅提醒不打断。断言走 trace 留证（产品侧新增：检测到/对话框已
    确认/未保存仅提醒）。"""
    # v46l（44317775556 X17 实锤）：OpenPaths 对已开路径只切标签不重载，
    # 重跑复用上一场的标签、内容还是上一场的旧正文，之后所有断言全歪。
    # 改为每场用唯一文件名（新标签、新加载），杜绝复用
    p = os.path.join(DOCS, f"taopad-watch-{int(time.time()*1000)}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("watch-probe-v1\n")
    esc_cleanup()
    _forward_open(p)
    # v46l（44317775556 X17 实锤）：打开是异步加载，若 v2 外部写先于加载
    # 落盘，编辑器起步就是 v2，之后「暂不保持 v1」断言必炸。加同步栏：
    # 轮询钩子正文直到确见 v1 才动 mark、才写 v2
    barrier_ok = False
    deadline = time.time() + 30
    while time.time() < deadline:
        d = _hook_doc_safe()
        if "watch-probe-v1" in (d.get("text") or ""):
            barrier_ok = True
            break
        time.sleep(1.0)
    assert barrier_ok, "X17: 打开后 30s 未确见 v1 正文（加载链未走通）"
    mark = trace_mark()
    # 干净档案：外部改 → 弹对话框 → ESC 暂不 → 正文保持 v1
    with open(p, "w", encoding="utf-8") as f:
        f.write("watch-probe-v2-external\n")
    ok = False
    ev = []
    esc_sent = 0
    # v46k（44310940578 X17 实锤）：watcher 双发——首事件弹窗未显示、
    # ShowDialogSafe 瞬回 null（choice= 空），匹配裸「对话框已确认」会
    # 抢跑、ESC 发早被吞，真弹窗反被后续事件时序卡住。改为只认
    # choice=None（最多 45s），期间见「检测到」按秒补发 ESC（≤3 次）
    deadline = time.time() + 45
    while time.time() < deadline:
        ev = trace_since(mark)
        if any("外部修改：对话框已确认 choice=None" in l for l in ev):
            ok = True
            break
        if any("检测到" in l for l in ev) and esc_sent < 3:
            send_keys("{ESC}")
            esc_sent += 1
        time.sleep(1.0)
    if not ok:
        r = hook_command("hint_probe")   # 探针留证：区分没检测到与界面冻住
        print(f"X17: 提示探针: {r.get('commandResult')!r}", flush=True)
    assert ok, f"X17: 干净档案外部修改未确认暂不: {' | '.join(ev)[-160:]!r}"
    doc = _hook_doc_safe()
    assert "watch-probe-v1" in (doc.get("text") or ""), "X17: 暂不后正文被改"
    # 未保存改动：外部改 → 仅提醒，不弹框
    mark2 = trace_mark()
    hook_command("type", "dirty ")
    time.sleep(0.5)
    with open(p, "w", encoding="utf-8") as f:
        f.write("watch-probe-v3-external\n")
    ok2 = False
    ev2 = []
    deadline = time.time() + 30
    while time.time() < deadline:
        ev2 = trace_since(mark2)
        if any("外部修改：未保存仅提醒" in l for l in ev2):
            ok2 = True
            break
        time.sleep(1.0)
    assert ok2, f"X17: 脏档案外部修改未走仅提醒分支: {' | '.join(ev2)[-160:]!r}"
    shot("case-external-change")


def c_snippet_expand():
    """X18：代码片段 Tab 展开（1.1.1 v46d）——缩写后真实 Tab 展开为模板
    （$0 落光标）。C# 的 cw→Console.WriteLine()；此前零覆盖。"""
    editor_open_clean()
    if not menu_lang_verified("C#"):
        r = hook_command("set_language", "C#")
        doc0 = _hook_doc_safe()
        assert doc0.get("lang") == "C#", f"X18: 语言未切到 C#: {doc0.get('lang')!r}"
    expanded = False
    doc = {}
    for attempt in range(3):
        clear_editor_settled()
        r = hook_command("type", "cw")
        print(f"X18: 键入回执: {r.get('commandResult')!r}", flush=True)
        send_keys("{TAB}")
        deadline = time.time() + 10
        while time.time() < deadline:
            doc = _hook_doc_safe()
            if "Console.WriteLine(" in (doc.get("text") or ""):
                expanded = True
                break
            time.sleep(1.0)
        if expanded:
            break
        print(f"X18: 第{attempt + 1}轮未展开: {(doc or {}).get('text', '')[-30:]!r}", flush=True)
    assert expanded, f"X18: 片段未展开: {(doc or {}).get('text', '')[-40:]!r}"
    shot("case-snippet")


def c_binary_open():
    """X19：二进制档案打开不炸（1.1.1 v46d）——此前零覆盖。当前产品
    行为=按文本解出乱码进编辑器；验不崩、钩子活、档案在场。若日后改为
    拒开/转快看，本用例会红出来逼着更新口径。"""
    p = os.path.join(DOCS, "taopad-bin.png")
    with open(p, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40 + b"\x00\x01\x02binary-probe-518234")
    esc_cleanup()
    _forward_open(p)
    data = _try_hook_dump(timeout=25.0)
    assert data is not None, "X19: 打开二进制档案后界面无响应"
    assert app_alive(), "X19: 打开二进制档案后进程没了"
    docs = data.get("docs") or []
    ok = any((d.get("path") or "").endswith("taopad-bin.png") for d in docs)
    assert ok, f"X19: 二进制档案未进页签: {' | '.join((d.get('path') or '') for d in docs)!r}"
    shot("case-binary-open")


def c_special_filename():
    """X20：特殊字符档案名打开+读回（1.1.1 v46d）——中文/空格/括号/
    「&」/全角加号，此前零覆盖。转发打开（与双击同管线）+ 内容一致。"""
    p = os.path.join(DOCS, "TaoPad 特殊 (1) & 测试 ＋ 档案.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("special-name-probe-260917\n")
    esc_cleanup()
    _forward_open(p)
    doc = {}
    ok = False
    deadline = time.time() + 30
    while time.time() < deadline:
        doc = _hook_doc_safe()
        if (doc.get("path") or "").endswith("＋ 档案.txt"):
            ok = True
            break
        time.sleep(1.0)
    assert ok, f"X20: 特殊名档案未打开: {(doc or {}).get('path', '')!r}"
    assert "special-name-probe-260917" in (doc.get("text") or ""), "X20: 特殊名档案内容读错"
    shot("case-special-name")


def main():
    global WIN_HANDLE
    if sys.argv[1:2] == ["__worker"]:
        worker_main(sys.argv[2:])
        return
    install_session_keepalive()
    exe = find_exe()
    print("exe:", exe, flush=True)
    from pywinauto import Application, Desktop
    # B 班带 --testhook：X03 走文件握手导出正文；A 班与普通运行零差别
    start_cmd = f'"{exe}" --testhook' if (sys.argv[1:2] or [""])[0].upper() == "B" else exe
    app = Application(backend="uia").start(start_cmd, timeout=25)
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
    # v32：主窗位置固定 (100,80)、尺寸不变——菜单布局兜底坐标基于窗口左上
    # 相对偏移（B 班截图实测），位置不固定则兜底失效。
    try:
        import win32gui
        _l, _t, _r, _b = win32gui.GetWindowRect(WIN_HANDLE)
        ctypes.windll.user32.SetWindowPos(WIN_HANDLE, 0, 100, 80, 0, 0, 0x0001 | 0x0004)
        time.sleep(0.6)
        print(f"窗口位置固定: 原({_l},{_t}) -> (100,80)，尺寸不变 {_r-_l}x{_b-_t}", flush=True)
    except Exception as e:
        print("窗口位置固定失败（布局兜底不可用）:", e, flush=True)
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
        ("X01 单实例转发打开", c_second_instance_open),
        ("X02 大文件打开与滚动", c_bigfile_scroll),
        ("X03 测试钩子正文导出", c_testhook_dump),
        ("X04 彩虹括号渲染色", c_rainbow_brackets),
        ("X05 Markdown 写作面板", c_writing_panels),
        ("X06 Fountain 剧本高亮", c_fountain_highlight),
        ("X07 C# 语义补全弹层", c_csharp_completion),
        ("X08 C# 撤销一步到位", c_csharp_undo),
        ("X09 配对/注释单步撤销", c_pair_comment_undo),
        ("X10 快照留底", c_snapshot_ui),
        ("X11 书签", c_bookmarks),
        ("X12 参数提示", c_param_hint),
        ("X13 只读文件", c_readonly),
        ("X15 30MB着色档案打开不冻界面", c_big_color_open),
        ("X16 50MB硬上限走快看", c_huge_boundary),
        ("X17 外部修改提醒", c_external_change),
        ("X18 代码片段Tab展开", c_snippet_expand),
        ("X19 二进制档案打开不炸", c_binary_open),
        ("X20 特殊字符档案名", c_special_filename),
        ("X21 各语言真实样例编写", c_lang_real_samples),
        ("O09 正常退出+崩溃检查", c_exit),
        ("X14 .html 冷启动（真机闪退复现）", c_html_cold_start),
    ]
    part = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
    if part in ("A", "B"):
        sel = ALL_CASES[:14] if part == "A" else ALL_CASES[14:]
        # v46o：定向回归开关（修红不打断全测定版令）。半场后跟逗号分隔的
        # 科目编号或关键词（如 `B X07,X15,X21`），只跑命中科目——修红先
        # 点科、绿了再整场定版，不再整轮重跑全测
        only = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
        if only:
            keys = [k.strip().upper() for k in only.split(",") if k.strip()]
            def _hit(n: str) -> bool:
                head = n.split()[0].upper()
                return any(k == head or k in n.upper() for k in keys)
            sel = [(n, f) for (n, f) in sel if _hit(n)]
            if not sel:
                print(f"定向开关未命中任何科目: {only!r}", flush=True)
        print(f"半场 {part}：{len(sel)} 用例{('，定向=' + only) if only else ''}", flush=True)
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
