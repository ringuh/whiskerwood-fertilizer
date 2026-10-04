"""Generates the Blueprint paste text (T3D) for the Fertilizer mod into tools/out/.
Usage: python tools/fertilizer_build.py   (needs the modkit's jmap, see t3d.py)

Assets (/Game/Mods/Fertilizer/):
  BP_Startup       Actor. Registers the mod option Fertilizer_Range.
  WBP_FieldHelper  Widget BP, parent UI_FarmFieldDetails. Hidden copy of the crop field window used to read
                   (ComputeState) and set (SetFertilizerActive) any field; both are private to that class.
  WBP_FertButton   Widget BP, designer only: Button "Btn" -> TextBlock "Label" (both Is Variable).
  WBP_ClickWaiter  Widget BP, empty. Waits ~0.1 s after a click (UI ticks while paused) and calls
                   BP_MapLoad.OnClickCheck. NOTE: its "On Click Check" call node pastes with a broken
                   Target type; delete it and re-create it by dragging from the Owner variable.
  BP_MapLoad       Actor. Puts the button into every crop field window and does the fertilizing.
Log lines need Saved\\mods\\Fertilizer\\debug.txt (any text).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from t3d import *

OUT = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT, exist_ok=True)
MOD = 'Fertilizer'
M = '/Game/Mods/%s/' % MOD
STARTUP, MAPLOAD, HELPER = M + 'BP_Startup', M + 'BP_MapLoad', M + 'WBP_FieldHelper'
KSL = '/Script/Engine.KismetSystemLibrary'
KML = '/Script/Engine.KismetMathLibrary'
KSTR = '/Script/Engine.KismetStringLibrary'
API = '/Script/SystemCore.ModAPI'
PA = '/Script/ProjectArco.'
GA, FIELDV, AWB = PA + 'GridActor', PA + 'UI_FarmFieldDetails', PA + 'ArcoWidgetBase'
UW = '/Script/UMG.UserWidget'
STATE_S = PA + 'FarmFieldUIState'
OPT_ID = 'Fertilizer_Range'
VALUES = ['5', '10', '15', '20', '30', '40', '50', '75', '100']
DEFAULT = '30'

ACTOR = OBJ('/Script/Engine.Actor')
UWT = OBJ(UW)
HELPER_CLS = "/Script/UMG.WidgetBlueprintGeneratedClass'%s.%s_C'" % (HELPER, HELPER.split('/')[-1])
HELPER_T = T('object', obj=HELPER_CLS)

# ---- PinSubCategoryMemberReference support (delegate pins)
_orig_fmt = Pin.fmt
def _fmt(self):
    s = _orig_fmt(self)
    mr = getattr(self, 'memref', None)
    if mr: s = s.replace('PinType.PinSubCategoryMemberReference=()', 'PinType.PinSubCategoryMemberReference=(%s)' % mr, 1)
    return s
Pin.fmt = _fmt


def modapi(g, x, y, name='Api'):
    return g.call(API + ':GetModAPI', name, x, y)


def api_call(g, fn, x, y, name=None, **kw):
    a = modapi(g, x - 250, y + 150, name=(name or fn) + 'Api')
    n = g.call(API + ':' + fn, name or fn, x, y, **kw)
    link(a['ReturnValue'], n['self'])
    return n


class _Gate(Node):
    def __init__(self, entry, exit_):
        self._e, self._x = entry, exit_; self.name = entry.node.name
    def __getitem__(self, k):
        return {'execute': self._e, 'then': self._x}[k]


def log(g, x, y, msg_pin=None, msg=None, name='Log'):
    """Debug-only log line (Debug = debug.txt present), joined back by a reroute knot."""
    dg = g.get('Debug', BOOL, x - 200, y + 120, name=name + 'DebugGet')
    br = g.branch(x - 150, y, name + 'IfDebug'); link(dg['Debug'], br['Condition'])
    n = api_call(g, 'LogMessage', x, y, name=name, doPrependDate='true')
    if msg_pin: link(msg_pin, n['Msg'])
    elif msg: n.set('Msg', msg)
    ex(br, n)
    k = g.add(BG + 'K2Node_Knot', name + 'Join', [], x + 250, y - 40)
    k.pin('InputPin', EXEC); k.pin('OutputPin', EXEC, out=True)
    link(n['then'], k['InputPin']); link(br['else'], k['InputPin'])
    return _Gate(br['execute'], k['OutputPin'])


def concat(g, x, y, *parts):
    cur = None
    for i, p in enumerate(parts):
        if cur is None:
            if isinstance(p, str):
                c = g.call(KSTR + ':Concat_StrStr', 'Cat', x, y); c.set('A', p); cur = c['ReturnValue']; continue
            cur = p; continue
        c = g.call(KSTR + ':Concat_StrStr', 'Cat', x + 40 * i, y + 30 * i)
        link(cur, c['A'])
        if isinstance(p, str): c.set('B', p)
        else: link(p, c['B'])
        cur = c['ReturnValue']
    return cur


def is_valid(g, pin, x, y, name='Valid'):
    n = g.call(KSL + ':IsValid', name, x, y); link(pin, n['Object']); return n['ReturnValue']


def tostr(g, fn, pin, x, y, name):
    n = g.call(KSTR + ':' + fn, name, x, y)
    inp = [p for p in n.pins if not p.out and p.name != 'self'][0]
    link(pin, inp); return n['ReturnValue']


def struct_node(g, kind, spath, show, x, y, name):
    props = J()[spath]['properties']
    n = g.add(BG + 'K2Node_%sStruct' % kind, name,
              ['StructType="/Script/CoreUObject.ScriptStruct\'%s\'"' % spath, 'bMadeAfterOverridePinRemoval=True'], x, y)
    for i, p in enumerate(props):
        n.header.append('ShowPinForProperties(%d)=(PropertyName="%s",bShowPin=%s,bCanToggleVisibility=True)' % (i, p['name'], p['name'] in show))
    sname = spath.split('.')[-1]
    if kind == 'Break':
        n.pin(sname, STRUCT(spath))
    for p in props:
        if p['name'] in show:
            n.pin(p['name'], prop_type(p), out=(kind == 'Break'))
    if kind == 'Make':
        n.pin(sname, STRUCT(spath), out=True)
    return n


def class_cast(g, x, y, name):
    n = g.add(BG + 'K2Node_ClassDynamicCast', name, ['TargetType="%s"' % cls_ref('/Script/Engine.Actor')], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True); n.pin('CastFailed', EXEC, out=True)
    n.pin('Class', CLS('/Script/CoreUObject.Object'))
    n.pin('AsActor', CLS('/Script/Engine.Actor'), out=True)
    n.pin('bSuccess', BOOL, out=True, hidden=True)
    return n


def bind(g, asset, target_pin, owner, delegate, sig_pkg, sig, event_node, x, y, name):
    n = g.add(BG + 'K2Node_AddDelegate', name,
              ['DelegateReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), delegate)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', OBJ(owner), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    d = n.pin('Delegate', T('delegate'))
    d.memref = 'MemberParent="/Script/CoreUObject.Package\'%s\'",MemberName="%s"' % (sig_pkg, sig)
    link(target_pin, n['self'])
    ev = event_node['OutputDelegate']
    ev.memref = 'MemberParent="/Script/Engine.BlueprintGeneratedClass\'%s.%s_C\'",MemberName="%s"' % (asset, asset.split('/')[-1], event_node.name)
    link(ev, d)
    return n


def self_node(g, x, y, name):
    n = g.add(BG + 'K2Node_Self', name, [], x, y)
    n.pin('self', T('object', sub='self'), out=True)
    return n


def call_self_event(g, fn, x, y, name=None):
    n = g.add(BG + 'K2Node_CallFunction', name or ('Call' + fn),
              ['FunctionReference=(MemberName="%s",bSelfContext=True)' % fn], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', T('object', sub='self'), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    return n


def input_key(g, key, x, y, name):
    n = g.add(BG + 'K2Node_InputKey', name, ['InputKey=%s' % key, 'bConsumeInput=False'], x, y)
    n.pin('Pressed', EXEC, out=True); n.pin('Released', EXEC, out=True)
    n.pin('Key', STRUCT('/Script/InputCore.Key'), out=True)
    return n


def helper_get(g, var, t, helper_pin, x, y, name):
    n = g.add(BG + 'K2Node_VariableGet', name,
              ['VariableReference=(MemberParent="%s",MemberName="%s")' % (HELPER_CLS, var)], x, y)
    n.pin(var, t, out=True)
    n.pin('self', HELPER_T, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    link(helper_pin, n['self'])
    return n


def write(name, g):
    open(os.path.join(OUT, name + '.txt'), 'w', encoding='utf-8').write(g.text())


# =========================================================================== BP_Startup (Actor)
g = Graph(STARTUP)
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, 0)
vals = g.add(BG + 'K2Node_MakeArray', 'Vals', ['NumInputs=%d' % len(VALUES)], 300, 250)
vals.pin('Array', ARR(STR), out=True)
for i, v in enumerate(VALUES):
    vals.pin('[%d]' % i, STR, default=v)
reg = api_call(g, 'RegisterModOptions', 600, 0, name='Reg',
               optionId=OPT_ID,
               optionDisplayName='Fertilizer - range (tiles)',
               DefaultValue=DEFAULT,
               optionDescription='The crop field button turns Fertilizer on for every field with the same crop '
                                 'within this many tiles of the selected field. Fields that already have it on are left alone.')
link(vals['Array'], reg['Values'])
ex(bp, reg)
write('BP_Startup', g)

# =========================================================================== WBP_FieldHelper (Widget BP, parent UI_FarmFieldDetails)
# Variables: State (FarmFieldUIState structure)
g = Graph(HELPER)
evR = g.custom_event('ReadState', [], 0, 0)
cs = g.call(FIELDV + ':ComputeState', 'Compute', 250, 200)
# Target left empty = self (a Self node pastes as a plain 'Self' type and fails to connect)
ss = g.setv('State', STRUCT(STATE_S), 500, 0, name='SetState'); link(cs['ReturnValue'], ss['State']); ex(evR, ss)
evA = g.custom_event('ApplyFertilizer', [], 0, 500)
sf = g.call(FIELDV + ':SetFertilizerActive', 'FertilizerOn', 300, 500, bNewActive='true')
ex(evA, sf)
write('WBP_FieldHelper', g)

# =========================================================================== BP_MapLoad (Actor)
# How it works (no tick, no polling):
#  - A world left click (InputKey LeftMouseButton, released, not consumed, also while paused) or a click on any
#    button inside the open crop field window shows WBP_ClickWaiter, which ~0.1 s later calls OnClickCheck.
#  - OnClickCheck finds the visible crop field window (UI_FarmFieldDetails, not our hidden helper). The game makes
#    a new window for every field opened; for a new one it finds the VerticalBox under "contents"
#    (NaviUi.FindDecendentsOfClasses) and AddChild(WBP_FertButton), centres it, and binds the window's own
#    buttons (seed choices etc.). Then (new or same window) the label is set from the field's crop.
#  - Button click: Sel = window.Context (the FarmPlot_C tile), helper reads its crop (None / fallow = nothing to do),
#    then every FarmPlot_C within Range tiles (rootPosition X/Y distance, checked first) with the same crop and
#    fertilizer off gets SetFertilizerActive(true) via the hidden helper (one change per field: its other tiles
#    then read on).
# Variables: Debug (Boolean), Helper (WBP_FieldHelper ref), FertButton (WBP_FertButton ref),
#            Waiter (WBP_ClickWaiter ref), Win (User Widget ref), Injected (User Widget ref), Target (Panel Widget ref),
#            Sel (Actor ref), SelRoot (Vector), SelSeeds (Name), Range (Integer), Changed (Integer)
BTN = M + 'WBP_FertButton'
BTN_CLS = "/Script/UMG.WidgetBlueprintGeneratedClass'%s.%s_C'" % (BTN, BTN.split('/')[-1])
BTN_T = T('object', obj=BTN_CLS)
WIDGET_T = OBJ('/Script/UMG.Widget')
WAITER = M + 'WBP_ClickWaiter'
WAITER_CLS = "/Script/UMG.WidgetBlueprintGeneratedClass'%s.%s_C'" % (WAITER, WAITER.split('/')[-1])
WAITER_T = T('object', obj=WAITER_CLS)
MAPLOAD_CLS = "/Script/Engine.BlueprintGeneratedClass'%s.%s_C'" % (MAPLOAD, MAPLOAD.split('/')[-1])
MAPLOAD_T = T('object', obj=MAPLOAD_CLS)
PANEL = '/Script/UMG.PanelWidget'
VEC = STRUCT('/Script/CoreUObject.Vector')
g = Graph(MAPLOAD)
STATE_T = STRUCT(STATE_S)


def bp_get(g, cls, var, t, target_pin, x, y, name):
    n = g.add(BG + 'K2Node_VariableGet', name, ['VariableReference=(MemberParent="%s",MemberName="%s")' % (cls, var)], x, y)
    n.pin(var, t, out=True)
    n.pin('self', T('object', obj=cls), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    link(target_pin, n['self'])
    return n


def bp_call(g, cls, fn, target_pin, x, y, name):
    n = g.add(BG + 'K2Node_CallFunction', name, ['FunctionReference=(MemberParent="%s",MemberName="%s")' % (cls, fn)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', T('object', obj=cls), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    link(target_pin, n['self'])
    return n


def nm(g, pin, x, y, name):
    n = g.call(KSL + ':GetDisplayName', name, x, y); link(pin, n['Object']); return n['ReturnValue']


def clsname(g, pin, x, y, name):
    c = g.call('/Script/Engine.GameplayStatics:GetObjectClass', name + 'Cls', x, y); link(pin, c['Object'])
    n = g.call(KSL + ':GetClassDisplayName', name, x + 200, y); link(c['ReturnValue'], n['Class'])
    return n['ReturnValue']



# ---- button label helpers
TXT = OBJ('/Script/UMG.TextBlock')
def crop_word(g, crop_pin, x, y, tag):
    """crop Name (berries, wood, mushroom, ...) -> display word from the game's loc table (resource.<crop>, wood -> trees)"""
    cs = g.call(KSTR + ':Conv_NameToString', 'CropStr' + tag, x, y); link(crop_pin, cs['InName'])
    isW = g.call(KSTR + ':EqualEqual_StrStr', 'IsWood' + tag, x + 200, y + 100, B='wood'); link(cs['ReturnValue'], isW['A'])
    k0 = g.call(KML + ':SelectString', 'LocCrop' + tag, x + 400, y, A='trees'); link(cs['ReturnValue'], k0['B']); link(isW['ReturnValue'], k0['bPickA'])
    key = concat(g, x + 600, y, 'resource.', k0['ReturnValue'])
    kn = g.call(KSTR + ':Conv_StringToName', 'LocKey' + tag, x + 800, y); link(key, kn['InString'])
    w = g.call('/Script/SystemCore.LocManager:GetWordFromKey', 'LocWord' + tag, x + 1000, y); link(kn['ReturnValue'], w['Key'])
    em = g.call(KSTR + ':IsEmpty', 'NoWord' + tag, x + 1200, y + 100); link(w['ReturnValue'], em['InString'])
    d = g.call(KML + ':SelectString', 'CropWord' + tag, x + 1400, y); link(cs['ReturnValue'], d['A']); link(w['ReturnValue'], d['B']); link(em['ReturnValue'], d['bPickA'])
    return d['ReturnValue']

def set_label(g, prev, prev_pin, text_pin, x, y, tag):
    fb = g.get('FertButton', BTN_T, x, y + 200, name='BtnGetL' + tag)
    lb = bp_get(g, BTN_CLS, 'Label', TXT, fb['FertButton'], x + 150, y + 200, 'LabelGet' + tag)
    tt = g.call('/Script/Engine.KismetTextLibrary:Conv_StringToText', 'LabelText' + tag, x + 150, y + 350); link(text_pin, tt['InString'])
    st = g.call('/Script/UMG.TextBlock:SetText', 'SetLabel' + tag, x + 350, y); link(lb['Label'], st['self']); link(tt['ReturnValue'], st['InText'])
    ex(prev, st, prev_pin)
    return st

def set_enabled(g, prev, prev_pin, on, x, y, tag):
    fb = g.get('FertButton', BTN_T, x, y + 200, name='BtnGetE' + tag)
    se = g.call('/Script/UMG.Widget:SetIsEnabled', 'Enable' + tag, x + 200, y, bInIsEnabled='true' if on else 'false')
    link(fb['FertButton'], se['self']); ex(prev, se, prev_pin)
    return se

# ---- BeginPlay
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, -2000)
api = modapi(g, 200, -1850, name='BindApi')
evL = g.custom_event('OnLoaded', [], 0, -1600)
b1 = bind(g, MAPLOAD, api['ReturnValue'], API, 'onLoadingFinished', '/Script/SystemCore', 'ModAPI_OnEvent__DelegateSignature', evL, 400, -2000, 'BindLoaded'); ex(bp, b1)

# ---- OnLoaded: Debug, input, helper, button
rdf = api_call(g, 'ReadModTextFile', 300, -1600, name='ReadDebugFile', modName=MOD, Filename='debug.txt'); ex(evL, rdf)
dfe = g.call(KSTR + ':IsEmpty', 'DebugFileEmpty', 550, -1450); link(rdf['ReturnValue'], dfe['InString'])
dfn = g.call(KML + ':Not_PreBool', 'DebugFileThere', 750, -1450); link(dfe['ReturnValue'], dfn['A'])
sdb = g.setv('Debug', BOOL, 650, -1600, name='SetDebug'); link(dfn['ReturnValue'], sdb['Debug']); ex(rdf, sdb)
l0 = log(g, 1100, -1600, msg='Fertilizer ready', name='LogReady'); ex(sdb, l0)
pc = g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC', 1350, -1400)
ei = g.call('/Script/Engine.Actor:EnableInput', 'EnableClicks', 1500, -1600)
link(self_node(g, 1350, -1500, 'MeInput')['self'], ei['self']); link(pc['ReturnValue'], ei['PlayerController']); ex(l0, ei)
cw = g.create_widget(HELPER, 1800, -1600, name='CreateHelper'); cw['ReturnValue'].t = HELPER_T
link(pc['ReturnValue'], cw['OwningPlayer']); ex(ei, cw)
sh = g.setv('Helper', HELPER_T, 2100, -1600, name='SetHelper'); link(cw['ReturnValue'], sh['Helper']); ex(cw, sh)
cb = g.create_widget(BTN, 2350, -1600, name='CreateButton'); cb['ReturnValue'].t = BTN_T
link(pc['ReturnValue'], cb['OwningPlayer']); ex(sh, cb)
sb = g.setv('FertButton', BTN_T, 2650, -1600, name='SetButton'); link(cb['ReturnValue'], sb['FertButton']); ex(cb, sb)
btn = bp_get(g, BTN_CLS, 'Btn', OBJ('/Script/UMG.Button'), cb['ReturnValue'], 2650, -1400, 'BtnGet')
evK = g.custom_event('OnFertClick', [], 0, 1000)
bc = bind(g, MAPLOAD, btn['Btn'], '/Script/UMG.Button', 'OnClicked', '/Script/UMG', 'OnButtonClickedEvent__DelegateSignature', evK, 2900, -1600, 'BindClick')
ex(sb, bc)

# ---- world left click (InputKey, works while paused) -> show the invisible WBP_ClickWaiter; its Tick
#      (UI ticks even when the game is paused) calls OnClickCheck once after ~0.1 s and removes itself.
kL = g.add(BG + 'K2Node_InputKey', 'KeyClick', ['InputKey=LeftMouseButton', 'bConsumeInput=False', 'bExecuteWhenPaused=True'], 0, -1000)
kL.pin('Pressed', EXEC, out=True); kL.pin('Released', EXEC, out=True); kL.pin('Key', STRUCT('/Script/InputCore.Key'), out=True)
wtg = g.get('Waiter', WAITER_T, 100, -800, name='WaiterGetK')
inv = g.call('/Script/UMG.Widget:IsInViewport', 'WaiterShown', 300, -800); link(wtg['Waiter'], inv['self'])
bk = g.branch(300, -1000, 'BrWaiterIdle'); link(inv['ReturnValue'], bk['Condition']); ex(kL, bk, 'Released')
atv = g.call('/Script/UMG.UserWidget:AddToViewport', 'ShowWaiter', 550, -1000); link(wtg['Waiter'], atv['self']); ex(bk, atv, 'else')
# a button inside the crop field window was clicked (seed choice, toggles): refresh the label shortly after
evWB = g.custom_event('OnWindowButton', [], 0, -800)
wtg2 = g.get('Waiter', WAITER_T, 100, -650, name='WaiterGetB')
inv2 = g.call('/Script/UMG.Widget:IsInViewport', 'WaiterShownB', 300, -650); link(wtg2['Waiter'], inv2['self'])
bk2 = g.branch(300, -800, 'BrWaiterIdleB'); link(inv2['ReturnValue'], bk2['Condition']); ex(evWB, bk2)
atv2 = g.call('/Script/UMG.UserWidget:AddToViewport', 'ShowWaiterB', 550, -800); link(wtg2['Waiter'], atv2['self']); ex(bk2, atv2, 'else')

# create the waiter in OnLoaded (after BindClick) and give it a reference back to this actor
cwt = g.create_widget(WAITER, 3200, -1600, name='CreateWaiter'); cwt['ReturnValue'].t = WAITER_T
link(pc['ReturnValue'], cwt['OwningPlayer']); ex(bc, cwt)
swt = g.setv('Waiter', WAITER_T, 3500, -1600, name='SetWaiter'); link(cwt['ReturnValue'], swt['Waiter']); ex(cwt, swt)
# Owner set by name: a typed "Set Owner" node / Self node into a BP_MapLoad-typed pin doesn't paste cleanly
sow = g.call(KSL + ':SetObjectPropertyByName', 'WaiterOwner', 3800, -1600, PropertyName='Owner')
link(cwt['ReturnValue'], sow['Object']); link(self_node(g, 3650, -1400, 'MeOwner')['self'], sow['Value']); ex(swt, sow)

# ---- OnClickCheck: find the visible crop field window
evC = g.custom_event('OnClickCheck', [], 0, -400)
sw0 = g.setv('Win', UWT, 250, -400, name='ClearWin'); ex(evC, sw0)
gw = g.call('/Script/UMG.WidgetBlueprintLibrary:GetAllWidgetsOfClass', 'AllFieldWindows', 500, -400, WidgetClass=FIELDV, TopLevelOnly='false')
gw['FoundWidgets'].t = ARR(UWT)
link(self_node(g, 350, -200, 'MeWC')['self'], gw['WorldContextObject']); ex(sw0, gw)
lpW = g.macro('ForEachLoop', UWT, 800, -400, name='WindowLoop'); link(gw['FoundWidgets'], lpW['Array']); ex(gw, lpW, 'then', 'Exec')
W = lpW['Array Element']
hg = g.get('Helper', HELPER_T, 900, -150, name='HelperGetW')
notH = g.call(KML + ':NotEqual_ObjectObject', 'NotHelper', 1100, -200); link(W, notH['A']); link(hg['Helper'], notH['B'])
vis = g.call('/Script/UMG.Widget:IsVisible', 'WinVisible', 1100, -50); link(W, vis['self'])
okW = g.call(KML + ':BooleanAND', 'VisibleWindow', 1300, -150); link(notH['ReturnValue'], okW['A']); link(vis['ReturnValue'], okW['B'])
bW = g.branch(1150, -400, 'BrIsWindow'); link(okW['ReturnValue'], bW['Condition']); ex(lpW, bW, 'LoopBody')
swW = g.setv('Win', UWT, 1400, -400, name='SetWin'); link(W, swW['Win']); ex(bW, swW)

# after the loop: log, then a visible window we haven't injected into yet?
wg = g.get('Win', UWT, 900, 100, name='WinGetC')
ig = g.get('Injected', UWT, 900, 200, name='InjectedGetC')
newW = g.call(KML + ':NotEqual_ObjectObject', 'NewWindow', 1100, 150); link(wg['Win'], newW['A']); link(ig['Injected'], newW['B'])
inj = g.call(KML + ':BooleanAND', 'NeedInject', 1300, 100); link(is_valid(g, wg['Win'], 1100, 50, 'WinValid'), inj['A']); link(newW['ReturnValue'], inj['B'])
bI = g.branch(1300, 250, 'BrInject'); link(inj['ReturnValue'], bI['Condition']); ex(lpW, bI, 'Completed')
bSame = g.branch(1300, 700, 'BrSameWindow'); link(is_valid(g, wg['Win'], 1150, 850, 'WinValidS'), bSame['Condition']); ex(bI, bSame, 'else')
lW = log(g, 1500, 250, msg_pin=concat(g, 1450, 450, 'Fertilizer: new crop field window ', nm(g, wg['Win'], 1300, 500, 'WinName'),
                                        ' [', clsname(g, wg['Win'], 1300, 600, 'WinClassName'), ']'), name='LogNewWin')
ex(bI, lW)

# panels inside the window (NaviUi.FindDecendentsOfClasses; GetAllWidgetsOfClass misses nested widgets)
st0 = g.setv('Target', OBJ(PANEL), 1800, 250, name='ClearTarget'); ex(lW, st0)
fd = g.call('/Script/SystemCore.NaviUi:FindDecendentsOfClasses', 'WindowPanels', 2100, 250, ignoreHidden='false')
link(wg['Win'], fd['searchRoot'])
ex(st0, fd)
elemC = dict(fd['candidateClasses'].t); elemC['cont'] = 'None'; elemC['ref'] = False; elemC['const'] = False
mk = g.add(BG + 'K2Node_MakeArray', 'PanelClasses', ['NumInputs=1'], 1900, 450)
mk.pin('Array', ARR(elemC), out=True)
mk.pin('[0]', elemC, defobj='/Script/UMG.VerticalBox')
link(mk['Array'], fd['candidateClasses'])
fd['ReturnValue'].t = ARR(WIDGET_T)
lpP = g.macro('ForEachLoop', WIDGET_T, 2400, 250, name='PanelLoop'); link(fd['ReturnValue'], lpP['Array']); ex(fd, lpP, 'then', 'Exec')
PW = lpP['Array Element']
pp = g.call('/Script/UMG.Widget:GetParent', 'BoxParent', 2600, 500); link(PW, pp['self'])
ppn = nm(g, pp['ReturnValue'], 2800, 500, 'BoxParentName')
isC = g.call(KSTR + ':EqualEqual_StrStr', 'UnderContents', 3000, 500, B='contents'); link(ppn, isC['A'])
tg = g.get('Target', OBJ(PANEL), 2800, 650, name='TargetGetP')
noT = g.call(KML + ':Not_PreBool', 'NoTargetYet', 3000, 650); link(is_valid(g, tg['Target'], 2850, 750, 'TargetValidP'), noT['A'])
take = g.call(KML + ':BooleanOR', 'TakeBox', 3200, 550); link(isC['ReturnValue'], take['A']); link(noT['ReturnValue'], take['B'])
bT = g.branch(2700, 250, 'BrTakeBox'); link(take['ReturnValue'], bT['Condition']); ex(lpP, bT, 'LoopBody')
cpw = g.cast(PANEL, False, 2950, 250, name='BoxAsPanel'); link(PW, cpw['Object']); ex(bT, cpw)
stT = g.setv('Target', OBJ(PANEL), 3200, 250, name='SetTarget'); link(cpw['AsPanel Widget'], stT['Target']); ex(cpw, stT)

# put the button into the first VerticalBox found
tg2 = g.get('Target', OBJ(PANEL), 2500, 1100, name='TargetGetA')
bHT = g.branch(2700, 1000, 'BrHaveTarget'); link(is_valid(g, tg2['Target'], 2500, 1200, 'TargetValidA'), bHT['Condition']); ex(lpP, bHT, 'Completed')
lNT = log(g, 3000, 1300, msg='Fertilizer: no VerticalBox in the window, cannot add the button', name='LogNoTarget'); ex(bHT, lNT, 'else')
fbg = g.get('FertButton', BTN_T, 2800, 1200, name='ButtonGetA')
ac = g.call(PANEL + ':AddChild', 'AddButton', 3000, 1000); link(tg2['Target'], ac['self']); link(fbg['FertButton'], ac['Content']); ex(bHT, ac)
si = g.setv('Injected', UWT, 3300, 1000, name='MarkInjected'); link(g.get('Win', UWT, 3200, 1200, name='WinGetI')['Win'], si['Injected']); ex(ac, si)
lA = log(g, 3600, 1000, msg_pin=concat(g, 3550, 1200, 'Fertilizer: button added to ', nm(g, tg2['Target'], 3400, 1300, 'TargetName'),
                                         ' slot ', clsname(g, ac['ReturnValue'], 3400, 1400, 'SlotClass')), name='LogAdded')
ex(si, lA)

# style the slot (centred, a little space above) and set the label for this field's crop
csl = g.cast('/Script/UMG.VerticalBoxSlot', False, 3900, 1000, name='AsVBoxSlot'); link(ac['ReturnValue'], csl['Object']); ex(lA, csl)
csl['AsVertical Box Slot'].name = 'AsVerticalBoxSlot'
sha = g.call('/Script/UMG.VerticalBoxSlot:SetHorizontalAlignment', 'CentreButton', 4150, 1000, InHorizontalAlignment='HAlign_Center')
link(csl['AsVerticalBoxSlot'], sha['self']); ex(csl, sha)
spd = g.call('/Script/UMG.VerticalBoxSlot:SetPadding', 'PadButton', 4400, 1000, InPadding='(Left=0.000000,Top=12.000000,Right=0.000000,Bottom=4.000000)')
link(csl['AsVerticalBoxSlot'], spd['self']); ex(sha, spd)
fdB = g.call('/Script/SystemCore.NaviUi:FindDecendentsOfClasses', 'WindowButtons', 4400, 700, ignoreHidden='false')
link(g.get('Win', UWT, 4250, 850, name='WinGetB')['Win'], fdB['searchRoot']); ex(spd, fdB)
mkB = g.add(BG + 'K2Node_MakeArray', 'ButtonClasses', ['NumInputs=1'], 4250, 950)
mkB.pin('Array', ARR(elemC), out=True); mkB.pin('[0]', elemC, defobj='/Script/UMG.Button')
link(mkB['Array'], fdB['candidateClasses'])
fdB['ReturnValue'].t = ARR(WIDGET_T)
lpB = g.macro('ForEachLoop', WIDGET_T, 4650, 700, name='ButtonLoop'); link(fdB['ReturnValue'], lpB['Array']); ex(fdB, lpB, 'then', 'Exec')
cbtn = g.cast('/Script/UMG.Button', False, 4900, 700, name='AsGameButton'); link(lpB['Array Element'], cbtn['Object']); ex(lpB, cbtn, 'LoopBody')
ourBtn = bp_get(g, BTN_CLS, 'Btn', OBJ('/Script/UMG.Button'), g.get('FertButton', BTN_T, 4900, 950, name='BtnGetOurs')['FertButton'], 5050, 950, 'OurBtnGet')
notOurs = g.call(KML + ':NotEqual_ObjectObject', 'NotOurButton', 5250, 900); link(cbtn['AsButton'], notOurs['A']); link(ourBtn['Btn'], notOurs['B'])
bNO = g.branch(5150, 700, 'BrNotOurs'); link(notOurs['ReturnValue'], bNO['Condition']); ex(cbtn, bNO)
bWB = bind(g, MAPLOAD, cbtn['AsButton'], '/Script/UMG.Button', 'OnClicked', '/Script/UMG', 'OnButtonClickedEvent__DelegateSignature', evWB, 5400, 700, 'BindWindowButton')
ex(bNO, bWB)
wgL = g.get('Win', UWT, 4600, 1250, name='WinGetL')
caL = g.cast(AWB, False, 4650, 1000, name='WinAsArcoL'); link(wgL['Win'], caL['Object']); ex(csl, caL, 'CastFailed'); ex(bSame, caL); ex(lpB, caL, 'Completed')
ctxL = g.get('Context', ACTOR, 4850, 1250, owner=AWB, name='WinContextL'); link(caL['AsArco Widget Base'], ctxL['self'])
hgL = g.get('Helper', HELPER_T, 4850, 1400, name='HelperGetL')
scL = g.call(KSL + ':SetObjectPropertyByName', 'HelperToWin', 4900, 1000, PropertyName='Context')
link(hgL['Helper'], scL['Object']); link(ctxL['Context'], scL['Value']); ex(caL, scL)
rsL = g.bpcall(HELPER, 'ReadState', [], name='ReadWinField', x=5200, y=1000); link(hgL['Helper'], rsL['self']); ex(scL, rsL)
stL = helper_get(g, 'State', STATE_T, hgL['Helper'], 5200, 1200, 'WinState')
bkL = struct_node(g, 'Break', STATE_S, ['activeSeeds'], 5450, 1200, 'BreakWin'); link(stL['State'], bkL['FarmFieldUIState'])
optL = api_call(g, 'ReadModOptionValue', 5500, 1000, name='ReadRangeL', optionId=OPT_ID, fallbackValue=DEFAULT); ex(rsL, optL)
hasL0 = g.call(KML + ':NotEqual_NameName', 'NotNoneL', 5700, 1300, B='None'); link(bkL['activeSeeds'], hasL0['A'])
hasL1 = g.call(KML + ':NotEqual_NameName', 'NotFallowL', 5700, 1450, B='fallow'); link(bkL['activeSeeds'], hasL1['A'])
hasL = g.call(KML + ':BooleanAND', 'HasCropL', 5900, 1350); link(hasL0['ReturnValue'], hasL['A']); link(hasL1['ReturnValue'], hasL['B'])
bL = g.branch(5800, 1000, 'BrCropL'); link(hasL['ReturnValue'], bL['Condition']); ex(optL, bL)
txtL = concat(g, 6000, 1300, 'Fertilize all ', crop_word(g, bkL['activeSeeds'], 5600, 1500, 'L'), ' within ', optL['ReturnValue'], ' tiles')
sl1 = set_label(g, bL, 'then', txtL, 6000, 1000, 'Ready')
en1 = set_enabled(g, sl1, 'then', True, 6400, 1000, 'On')
nc = g.call(KSTR + ':Concat_StrStr', 'NoCropText', 6000, 1700, A='No crop chosen', B='')
sl2 = set_label(g, bL, 'else', nc['ReturnValue'], 6000, 1600, 'NoCrop')
en2 = set_enabled(g, sl2, 'then', False, 6400, 1600, 'Off')

# =========================================================================== OnFertClick: fertilize nearby fields of the same crop
igk = g.get('Injected', UWT, 200, 1200, name='InjectedGetK')
caw = g.cast(AWB, False, 250, 1000, name='WinAsArco'); link(igk['Injected'], caw['Object']); ex(evK, caw)
ctx = g.get('Context', ACTOR, 450, 1200, owner=AWB, name='WinContext'); link(caw['AsArco Widget Base'], ctx['self'])
ss = g.setv('Sel', ACTOR, 550, 1000, name='SetSel'); link(ctx['Context'], ss['Sel']); ex(caw, ss)
c0 = g.setv('Changed', INT, 800, 1000, value='0', name='ClearChanged'); ex(ss, c0)
opt = api_call(g, 'ReadModOptionValue', 1050, 1000, name='ReadRange', optionId=OPT_ID, fallbackValue=DEFAULT); ex(c0, opt)
ri = g.call(KSTR + ':Conv_StringToInt', 'RangeInt', 1300, 1150); link(opt['ReturnValue'], ri['InString'])
sr = g.setv('Range', INT, 1350, 1000, name='SetRange'); link(ri['ReturnValue'], sr['Range']); ex(opt, sr)
selg = g.get('Sel', ACTOR, 1400, 1300, name='SelGet')
hg2 = g.get('Helper', HELPER_T, 1400, 1400, name='HelperGetS')
csel = g.cast(GA, False, 1600, 1000, name='SelAsGrid'); link(selg['Sel'], csel['Object']); ex(sr, csel)
csel['AsGrid Actor'].name = 'AsGridActor'
lSx = log(g, 1900, 1400, msg='Fertilizer: the window has no field tile selected', name='LogSelNotGrid'); ex(csel, lSx, 'CastFailed')
fp1 = g.get('liveFootprint', STRUCT(PA + 'GridFootprint'), 1600, 1250, owner=GA, name='SelFootprint'); link(csel['AsGridActor'], fp1['self'])
fb1 = struct_node(g, 'Break', PA + 'GridFootprint', ['rootPosition'], 1850, 1250, 'BreakSelFp'); link(fp1['liveFootprint'], fb1['GridFootprint'])
srv = g.call(KML + ':Conv_IntVectorToVector', 'SelRootToV', 2050, 1250); link(fb1['rootPosition'], srv['InIntVector'])
sroot = g.setv('SelRoot', VEC, 1900, 1000, name='SetSelRoot'); link(srv['ReturnValue'], sroot['SelRoot']); ex(csel, sroot)
sc1 = g.call(KSL + ':SetObjectPropertyByName', 'HelperToSel', 2150, 1000, PropertyName='Context')
link(hg2['Helper'], sc1['Object']); link(selg['Sel'], sc1['Value']); ex(sroot, sc1)
rs1 = g.bpcall(HELPER, 'ReadState', [], name='ReadSel', x=2450, y=1000); link(hg2['Helper'], rs1['self']); ex(sc1, rs1)
st1 = helper_get(g, 'State', STATE_T, hg2['Helper'], 2450, 1200, 'SelState')
bk1 = struct_node(g, 'Break', STATE_S, ['activeSeeds'], 2700, 1200, 'BreakSel'); link(st1['State'], bk1['FarmFieldUIState'])
sseed = g.setv('SelSeeds', NAME, 2750, 1000, name='SetSelSeeds'); link(bk1['activeSeeds'], sseed['SelSeeds']); ex(rs1, sseed)
hasC0 = g.call(KML + ':NotEqual_NameName', 'NotNone', 3000, 1200, B='None'); link(bk1['activeSeeds'], hasC0['A'])
hasC1 = g.call(KML + ':NotEqual_NameName', 'NotFallow', 3000, 1350, B='fallow'); link(bk1['activeSeeds'], hasC1['A'])
hasCrop = g.call(KML + ':BooleanAND', 'HasCrop', 3200, 1250); link(hasC0['ReturnValue'], hasCrop['A']); link(hasC1['ReturnValue'], hasCrop['B'])
bC = g.branch(3000, 1000, 'BrHasCrop'); link(hasCrop['ReturnValue'], bC['Condition']); ex(sseed, bC)
lNc = log(g, 3300, 1400, msg='Fertilizer: selected field has no crop (fallow), nothing to do', name='LogNoCrop'); ex(bC, lNc, 'else')
lS = log(g, 3300, 1000, msg_pin=concat(g, 3250, 1200, 'Fertilizer: button pressed, crop=', tostr(g, 'Conv_NameToString', bk1['activeSeeds'], 3100, 1300, 'SelSeedStr'),
                                         ' range=', tostr(g, 'Conv_IntToString', ri['ReturnValue'], 3100, 1400, 'RangeStr')), name='LogPressed')
ex(bC, lS)
scls = g.call('/Script/Engine.GameplayStatics:GetObjectClass', 'SelClass', 3500, 1250); link(selg['Sel'], scls['Object'])
cc = class_cast(g, 3600, 1000, 'SelActorClass'); link(scls['ReturnValue'], cc['Class']); ex(lS, cc)
ga2 = g.call('/Script/Engine.GameplayStatics:GetAllActorsOfClass', 'AllTiles', 3900, 1000)
ga2['OutActors'].t = ARR(ACTOR)
link(self_node(g, 3750, 1250, 'MeWC3')['self'], ga2['WorldContextObject'])
link(cc['AsActor'], ga2['ActorClass']); ex(cc, ga2)
lpF = g.macro('ForEachLoop', ACTOR, 4200, 1000, name='TileLoop'); link(ga2['OutActors'], lpF['Array']); ex(ga2, lpF, 'then', 'Exec')
P = lpF['Array Element']
# 1) cheap distance check first
cf = g.cast(GA, False, 4500, 1000, name='TileAsGrid'); link(P, cf['Object']); ex(lpF, cf, 'LoopBody')
cf['AsGrid Actor'].name = 'AsGridActor'
fp2 = g.get('liveFootprint', STRUCT(PA + 'GridFootprint'), 4500, 1250, owner=GA, name='TileFootprint'); link(cf['AsGridActor'], fp2['self'])
fb2 = struct_node(g, 'Break', PA + 'GridFootprint', ['rootPosition'], 4750, 1250, 'BreakTileFp'); link(fp2['liveFootprint'], fb2['GridFootprint'])
v1 = g.call(KML + ':Conv_IntVectorToVector', 'TileRootV', 5000, 1250); link(fb2['rootPosition'], v1['InIntVector'])
srg = g.get('SelRoot', VEC, 5000, 1400, name='SelRootGet')
dv = g.call(KML + ':Subtract_VectorVector', 'RootDelta', 5200, 1300); link(v1['ReturnValue'], dv['A']); link(srg['SelRoot'], dv['B'])
dist = g.call(KML + ':VSizeXY', 'TileDist', 5400, 1300); link(dv['ReturnValue'], dist['A'])
rg = g.get('Range', INT, 5200, 1450, name='RangeGet')
rd = g.call(KML + ':Conv_IntToDouble', 'RangeD', 5400, 1450); link(rg['Range'], rd['inInt'])
inRange = g.call(KML + ':LessEqual_DoubleDouble', 'InRange', 5600, 1350); link(dist['ReturnValue'], inRange['A']); link(rd['ReturnValue'], inRange['B'])
bR = g.branch(4800, 1000, 'BrInRange'); link(inRange['ReturnValue'], bR['Condition']); ex(cf, bR)
# 2) in range: read the tile's field through the helper
hg3 = g.get('Helper', HELPER_T, 5000, 800, name='HelperGetF')
sc2 = g.call(KSL + ':SetObjectPropertyByName', 'HelperToTile', 5100, 1000, PropertyName='Context')
link(hg3['Helper'], sc2['Object']); link(P, sc2['Value']); ex(bR, sc2)
rs2 = g.bpcall(HELPER, 'ReadState', [], name='ReadTile', x=5400, y=1000); link(hg3['Helper'], rs2['self']); ex(sc2, rs2)
st2 = helper_get(g, 'State', STATE_T, hg3['Helper'], 5700, 1150, 'TileState')
bk2 = struct_node(g, 'Break', STATE_S, ['activeSeeds', 'bFertilizerActive'], 5950, 1150, 'BreakTile'); link(st2['State'], bk2['FarmFieldUIState'])
ssg = g.get('SelSeeds', NAME, 5950, 1350, name='SelSeedsGet')
same = g.call(KML + ':EqualEqual_NameName', 'SameCrop', 6200, 1200); link(bk2['activeSeeds'], same['A']); link(ssg['SelSeeds'], same['B'])
off = g.call(KML + ':Not_PreBool', 'FertOff', 6200, 1350); link(bk2['bFertilizerActive'], off['A'])
doIt = g.call(KML + ':BooleanAND', 'Fertilize', 6400, 1250); link(same['ReturnValue'], doIt['A']); link(off['ReturnValue'], doIt['B'])
bA = g.branch(5700, 1000, 'BrFertilize'); link(doIt['ReturnValue'], bA['Condition']); ex(rs2, bA)
ap = g.bpcall(HELPER, 'ApplyFertilizer', [], name='DoFertilize', x=6000, y=1000); link(hg3['Helper'], ap['self']); ex(bA, ap)
cg2 = g.get('Changed', INT, 6200, 850, name='ChangedGet')
inc = g.call(KML + ':Add_IntInt', 'ChangedPlus1', 6400, 850, B='1'); link(cg2['Changed'], inc['A'])
sci = g.setv('Changed', INT, 6300, 1000, name='CountChange'); link(inc['ReturnValue'], sci['Changed']); ex(ap, sci)
lF = log(g, 6700, 1000, msg_pin=concat(g, 6650, 1500, 'Fertilizer:   fertilizer on: field at ', tostr(g, 'Conv_IntVectorToString', fb2['rootPosition'], 6500, 1600, 'TileRootStr'),
                                          ' distance ', tostr(g, 'Conv_DoubleToString', dist['ReturnValue'], 6500, 1700, 'DistStr')), name='LogFertilized')
ex(sci, lF)
cgd = g.get('Changed', INT, 4400, 700, name='ChangedGetDone')
lD = log(g, 4600, 600, msg_pin=concat(g, 4600, 750, 'Fertilizer: done, fields switched on: ', tostr(g, 'Conv_IntToString', cgd['Changed'], 4450, 850, 'DoneStr')), name='LogDone')
ex(lpF, lD, 'Completed')

# show the result on the button
ssgD = g.get('SelSeeds', NAME, 4900, 800, name='SelSeedsGetD')
txtD = concat(g, 5100, 800, 'Done: ', tostr(g, 'Conv_IntToString', cgd['Changed'], 4900, 950, 'DoneCount'), ' more ',
              crop_word(g, ssgD['SelSeeds'], 4900, 1100, 'D'), ' fields fertilized')
slD = set_label(g, lD, 'then', txtD, 5300, 600, 'Done')

write('BP_MapLoad', g)

# =========================================================================== WBP_ClickWaiter (Widget BP, parent UserWidget, empty designer)
# Variables: Owner (BP_MapLoad object ref), Waited (Float)
g = Graph(WAITER)
evT = g.event('/Script/UMG.UserWidget', 'Tick', [('MyGeometry', STRUCT('/Script/SlateCore.Geometry')), ('InDeltaTime', FLT)], 'Tick', 0, 0)
wg_ = g.get('Waited', DBL, 0, 250, name='WaitedGet')
add = g.call(KML + ':Add_DoubleDouble', 'AddDelta', 200, 250); link(wg_['Waited'], add['A']); link(evT['InDeltaTime'], add['B'])
sw = g.setv('Waited', DBL, 300, 0, name='SetWaited'); link(add['ReturnValue'], sw['Waited']); ex(evT, sw)
ge = g.call(KML + ':GreaterEqual_DoubleDouble', 'LongEnough', 500, 250, B='0.1'); link(sw['Output_Get'], ge['A'])
bw = g.branch(550, 0, 'BrLongEnough'); link(ge['ReturnValue'], bw['Condition']); ex(sw, bw)
s0 = g.setv('Waited', DBL, 800, 0, value='0.0', name='ResetWaited'); ex(bw, s0)
rp = g.call('/Script/UMG.Widget:RemoveFromParent', 'Hide', 1050, 0); ex(s0, rp)
og = g.get('Owner', MAPLOAD_T, 1100, 250, name='OwnerGet')
cc_ = g.add(BG + 'K2Node_CallFunction', 'RunCheck', ['FunctionReference=(MemberParent="%s",MemberName="OnClickCheck")' % MAPLOAD_CLS], 1350, 0)
cc_.pin('execute', EXEC); cc_.pin('then', EXEC, out=True)
cc_.pin('self', MAPLOAD_T, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
link(og['Owner'], cc_['self']); ex(rp, cc_)
write('WBP_ClickWaiter', g)



# =========================================================================== validation
def validate(path):
    import re as _re
    txt = open(path, encoding='utf-8').read()
    names = set(_re.findall(r'Begin Object Class=\S+ Name="([^"]+)"', txt))
    bad = []
    for m in _re.finditer(r'LinkedTo=\(([^)]*)\)', txt):
        for ref in m.group(1).split(','):
            ref = ref.strip()
            if ref and ref.split(' ')[0] not in names: bad.append(ref)
    return len(names), bad

for gname in ('BP_Startup', 'WBP_FieldHelper', 'BP_MapLoad', 'WBP_ClickWaiter'):
    n, bad = validate(os.path.join(OUT, gname + '.txt'))
    print(gname, n, 'nodes', 'BAD LINKS' if bad else 'links ok', bad[:5])
