#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.
#SingleInstance, force
#Persistent
SetBatchLines, -1

supported_resolutions:="
(
1280 x 720
1440 x 900
1600 x 900
1920 x 1080
1920 x 1200
2560 x 1080
2560 x 1440
2560 x 1600
3440 x 1440
3840 x 2160
)"

update_log:="
(

> 新增2560x1600分辨率支持
> Added 2560x1600 resolution support

)"

version:="0.2.10"

isCNServer:=0
; 出现了一个国际服玩家UI位置与国服不一致的情况。尚不能确定是服务器间差异或是其他的客户端差异所造成。暂时先令所有的图标搜索范围均扩大。
isWorking:=False

;@Ahk2Exe-IgnoreBegin
if A_Args.Length() > 0
{
	for n, param in A_Args
	{
		RegExMatch(param, "--out=(\w+)", outName)
		if(outName1=="version") {
			f := FileOpen("version.txt","w")
			f.Write(version)
			f.Close()
			ExitApp
		}
	}
}
;@Ahk2Exe-IgnoreEnd

;@Ahk2Exe-SetCompanyName HelloWorks
;@Ahk2Exe-SetName Genshin Fishing Automata
;@Ahk2Exe-SetDescription Genshin Fishing Automata
;@Ahk2Exe-SetVersion %version%
;@Ahk2Exe-SetMainIcon icon.ico
;@Ahk2Exe-ExeName GenshinFishing

for objItem in ComObjGet("winmgmts:").ExecQuery("SELECT * FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled = True")
{
	mac_addr:=objItem.MACAddress
	Break
}
#Include regist.ahk
; fork: always skip the upstream "free version" wait screen
g_regist := true


#Include menu.ahk

UAC()
#include notice.ahk

IniRead, logLevel, setting.ini, update, log, 0
IniRead, lastUpdate, setting.ini, update, last, 0
IniRead, autoUpdate, setting.ini, update, autoupdate, 1
IniRead, updateMirror, setting.ini, update, mirror, 1
IniWrite, % updateMirror, setting.ini, update, mirror
IniRead, debugmode, setting.ini, update, debug, 0
IniRead, autoBaitEnabled, setting.ini, bait, enabled, 1
IniRead, targetFish, setting.ini, bait, target, medaka
IniRead, baitButtonX, setting.ini, bait, button_x, 1736
IniRead, baitButtonY, setting.ini, bait, button_y, 926
IniRead, baitConfirmX, setting.ini, bait, confirm_x, 0
IniRead, baitConfirmY, setting.ini, bait, confirm_y, 0
IniRead, baitCancelX, setting.ini, bait, cancel_x, 0
IniRead, baitCancelY, setting.ini, bait, cancel_y, 0
IniRead, baitMenuOpenDelay, setting.ini, bait, menu_open_delay_ms, 500
IniRead, baitClickDelay, setting.ini, bait, click_delay_ms, 150
IniRead, baitDetectVariation, setting.ini, bait, detect_variation, 48
IniRead, baitRetryDelay, setting.ini, bait, retry_ms, 8000
IniRead, autocastEnabled, setting.ini, autocast, enabled, 0
IniRead, aimOriginX, setting.ini, autocast, aim_origin_x, 960
IniRead, aimOriginY, setting.ini, autocast, aim_origin_y, 620
IniRead, aimGainX, setting.ini, autocast, aim_gain_x, 1.0
IniRead, aimGainY, setting.ini, autocast, aim_gain_y, 1.0
IniRead, aimFishOffset, setting.ini, autocast, fish_offset, 110
IniRead, aimMaxMove, setting.ini, autocast, max_move, 500
IniRead, aimSettleDelay, setting.ini, autocast, settle_ms, 700
IniRead, autocastCooldown, setting.ini, autocast, cooldown_ms, 6000

bait_alias_map:=Object("fruitpaste","fruitpaste"
,"fruitpastebait","fruitpaste"
,"fruitpastebaitblue","fruitpaste"
,"redrot","redrot"
,"redrotbait","redrot"
,"falseworm","falseworm"
,"falsewormbait","falseworm"
,"fakefly","fakefly"
,"fakeflybait","fakefly"
,"sugardew","sugardew"
,"sugardewbait","sugardew"
,"sourbait","sourbait"
,"sour","sourbait"
,"emberglow","emberglowbait"
,"emberglowbait","emberglowbait"
,"spinelgrain","spinelgrainbait"
,"spinelgrainbait","spinelgrainbait"
,"berry","berrybait"
,"berrybait","berrybait"
,"refreshinglakka","refreshinglakkabait"
,"refreshinglakkabait","refreshinglakkabait"
,"flashingmaintenancemekbait","flashingmaintenancemekbait")

fish_bait_defaults:=Object("medaka","fruitpaste"
,"aizenmedaka","fruitpaste"
,"dawncatcher","fruitpaste"
,"crystalfish","fruitpaste"
,"glazemedaka","fruitpaste"
,"sweetflowermedaka","fruitpaste"
,"stickleback","redrot"
,"akaimaou","redrot"
,"betta","redrot"
,"venomspinefish","redrot"
,"snowstrider","redrot"
,"lungedstickleback","redrot"
,"koi","fakefly"
,"rustykoi","fakefly"
,"goldenkoi","fakefly"
,"pufferfish","fakefly"
,"bitterpufferfish","fakefly"
,"formaloray","fakefly"
,"tea-coloredshirakodai","falseworm"
,"teacoloredshirakodai","falseworm"
,"brownshirakodai","falseworm"
,"purpleshirakodai","falseworm"
,"abidingangelfish","falseworm"
,"raimeiangelfish","falseworm"
,"divdaray","falseworm"
,"halcyonjadeaxemarlin","sugardew"
,"lazuriteaxemarlin","sugardew"
,"peachofthedeepwaves","sugardew"
,"sandstormangler","sugardew"
,"sunsetcloudangler","sugardew"
,"truefruitangler","sugardew"
,"blazingheartfeatherbass","sugardew"
,"ripplingheartfeatherbass","sugardew"
,"streamingaxemarlin","sugardew"
,"jadeheartfeatherbass","sourbait"
,"maintenancemekgoldleader","flashingmaintenancemekbait"
,"maintenancemekinitialconfiguration","flashingmaintenancemekbait"
,"maintenancemekplatinumcollection","flashingmaintenancemekbait"
,"maintenancemeksituationcontroller","flashingmaintenancemekbait"
,"maintenancemekwaterbodycleaner","flashingmaintenancemekbait"
,"magmarapidfightingfish","emberglowbait"
,"phonyphlogistonunihornfish","emberglowbait"
,"secretsourcescoutsweeper","emberglowbait"
,"divingrapidfightingfish","spinelgrainbait"
,"floralrapidfightingfish","spinelgrainbait"
,"greenwavesunfish","spinelgrainbait"
,"dusksunfish","spinelgrainbait"
,"pseudosharkunihornfish","spinelgrainbait"
,"blazingaxeheadfish","berrybait"
,"commonaxeheadfish","berrybait"
,"frostedaxeheadfish","berrybait"
,"azuregazecrystaleye","refreshinglakkabait"
,"nightgazecrystaleye","refreshinglakkabait"
,"veggiemaulershark","refreshinglakkabait"
,"neonmaulershark","refreshinglakkabait"
,"ray","sourbait")
fish_bait_map:=Object()
for fishName, defaultBait in fish_bait_defaults
{
	IniRead, configuredBait, setting.ini, bait_target, % fishName, % defaultBait
	configuredBait := normalizeBaitName(configuredBait)
	normalizedFish := normalizeFishName(fishName)
	fish_bait_map[normalizedFish] := configuredBait
}
selectedBait:=""
lastBaitActionTick:=0
lastBaitUnsupportedNotified:=0
lastScanTick:=0
lastAutoCastTick:=0
lastBaitLogMsg:=""
Gosub, log_init
log("Start at " A_YYYY "-" A_MM "-" A_DD)
IfExist, updater.exe
{
	FileDelete, updater.exe
}
#include update.ahk

TrayTip, % "Genshin Fishing Automata", % "Genshin Fishing Automata Start`nv" version "`n原神钓鱼人偶启动"

img_list:=Object("bar",Object("filename","bar.png")
,"casting",Object("filename","casting.png")
,"cur",Object("filename","cur.png")
,"left",Object("filename","left.png")
,"ready",Object("filename","ready.png")
,"reel",Object("filename","reel.png")
,"right",Object("filename","right.png"))
; for k, v in img_list
; {
; 	pBitmap := Gdip_CreateBitmapFromFile( v.path )
; 	v.w:= Gdip_GetImageWidth( pBitmap )
; 	v.h:= Gdip_GetImageHeight( pBitmap )
; 	Gdip_DisposeImage( pBitmap )
; 	msgbox, % k "`n" v.path "`nw[" v.w "]`nh[" v.h "]"
; }

; #Include, Gdip_ImageSearch.ahk
; #Include, Gdip.ahk
; pToken := Gdip_Startup()

#include *i fileinstalls.ahk
ensureAssetsAvailable()


DllCall("QueryPerformanceFrequency", "Int64P", freq)
freq/=1000
CoordMode, Pixel, Client
CoordMode, Mouse, Client
state:="unknown"
statePredict:="unknown"
stateUnknownStart:=0
isResolutionValid:=0
OnExit, exit
SetTimer, main, -100
Return

log_init:
pLogfile:=FileOpen("genshinfishing.log", "a")
lastLogWrite:=A_TickCount
Return

log(txt,level=0)
{
	global logLevel, pLogfile
	if(logLevel >= level) {
		pLogfile.WriteLine(A_Hour ":" A_Min ":" A_Sec "." A_MSec "[" level "]:" txt)
		if(A_TickCount - lastLogWrite > 10000) {
			pLogfile.Close()
			Gosub, log_init
		}
	}
}

genshin_window_exist()
{
	; global isCNServer
	genshinHwnd := WinExist("ahk_exe GenshinImpact.exe")
	; isCNServer := 0
	if not genshinHwnd
	{
		genshinHwnd := WinExist("ahk_exe YuanShen.exe")
		; isCNServer := 1
	}
	return genshinHwnd
}

ttm(txt, delay=1500)
{
	ToolTip, % txt
	SetTimer, kttm, % -delay
	Return
	kttm:
	ToolTip,
	Return
}

tt(txt, delay=2000)
{
	ToolTip, % txt, 1, 1
	SetTimer, ktt, % -delay
	Return
	ktt:
	ToolTip,
	Return
}
; 图标位置
; 右下角 w 82.5% h 87.5%
; Bar
; w 25%~75%
; h 0%~30%
; 浮漂
; w 25%~75%
; h 由 bar 参数 barY-10 ~ barY+30

genshin_hwnd := genshin_window_exist()
if(genshin_hwnd)
{
	; pBitmap:=Gdip_BitmapFromHWND(genshin_hwnd)
	; Gdip_SaveBitmapToFile(pBitmap, "output.jpg")
	; MsgBox, DONE

	; hdc := GetDC(genshin_hwnd)
	; CreateCompatibleDC(hdc)
	; Gdip_GraphicsFromHDC
	; Gdip_CreateBitmapFromHBITMAP
	; Gdip_SetBitmapToClipboard
}

getClientSize(hWnd, ByRef w := "", ByRef h := "")
{
	VarSetCapacity(rect, 16, 0)
	DllCall("GetClientRect", "ptr", hWnd, "ptr", &rect)
	w := NumGet(rect, 8, "int")
	h := NumGet(rect, 12, "int")
}

dLinePt(p)
{
	global dLine
	return Ceil(p*dLine)
}

ensureAssetsAvailable()
{
	targetRoot := A_Temp "/genshinfishing"
	if(!InStr(FileExist(targetRoot), "D")) {
		FileCreateDir, % targetRoot
	}
	Loop, Files, % A_ScriptDir "\assets\*", D
	{
		dirName := A_LoopFileName
		dstDir := targetRoot "/" dirName
		if(!InStr(FileExist(dstDir), "D")) {
			FileCreateDir, % dstDir
		}
		; always overwrite so updated templates replace stale temp copies
		Loop, Files, % A_LoopFileLongPath "\*.*", F
		{
			FileCopy, % A_LoopFileLongPath, % dstDir "/" A_LoopFileName, 1
		}
	}
}

normalizeFishName(v)
{
	v := Trim(v)
	StringLower, v, v
	v := RegExReplace(v, "[\s\-_'\.\(\)]", "")
	return v
}

normalizeBaitName(v)
{
	global bait_alias_map
	v := normalizeFishName(v)
	if(bait_alias_map.HasKey(v)) {
		return bait_alias_map[v]
	}
	return v
}

baitTemplatePath(name)
{
	global winW, winH
	return A_Temp "/genshinfishing/" winW winH "/" name ".png"
}

; The "Select Bait" dialog shows a horizontally centered grid of ~123px cards
; (only baits usable in the current water body), with Cancel/Confirm below.
; Bait templates are 84x84 (click center +42). Several scale variants exist
; because the exact in-game icon scale is fractional.
findBaitInMenu(targetBait, ByRef clickX, ByRef clickY, ByRef alreadySelected)
{
	global baitDetectVariation
	alreadySelected := 0
	for _, suffix in ["", "_b", "_c"]
	{
		templatePath := baitTemplatePath("bait_" targetBait suffix)
		if(!FileExist(templatePath)) {
			continue
		}
		ImageSearch, foundX, foundY, 460, 300, 1460, 720, % "*" baitDetectVariation " *TransFuchsia " templatePath
		if(!ErrorLevel) {
			clickX := foundX + 42
			clickY := foundY + 42
			return 1
		}
	}
	; the selected card is rendered zoomed, so it needs its own template
	templatePath := baitTemplatePath("bait_" targetBait "_sel")
	if(FileExist(templatePath)) {
		ImageSearch, foundX, foundY, 460, 300, 1460, 720, % "*" baitDetectVariation " *TransFuchsia " templatePath
		if(!ErrorLevel) {
			clickX := foundX + 42
			clickY := foundY + 42
			alreadySelected := 1
			return 1
		}
	}
	return 0
}

; Locate the Confirm/Cancel button by template; fall back to configured
; coordinates. Finding neither means the dialog is not open.
findMenuButton(which, ByRef clickX, ByRef clickY)
{
	global baitDetectVariation
	global baitConfirmX, baitConfirmY, baitCancelX, baitCancelY
	templatePath := baitTemplatePath("menu_" which)
	if(FileExist(templatePath)) {
		ImageSearch, foundX, foundY, 460, 700, 1460, 830, % "*" baitDetectVariation " " templatePath
		if(!ErrorLevel) {
			clickX := foundX + (which = "confirm" ? 80 : 75)
			clickY := foundY + 18
			return 1
		}
	}
	if(which = "confirm" && baitConfirmX > 0 && baitConfirmY > 0) {
		clickX := baitConfirmX
		clickY := baitConfirmY
		return 1
	}
	if(which = "cancel" && baitCancelX > 0 && baitCancelY > 0) {
		clickX := baitCancelX
		clickY := baitCancelY
		return 1
	}
	return 0
}

resolveTargetBait()
{
	global targetFish, fish_bait_map
	normalizedTarget := normalizeFishName(targetFish)
	if(normalizedTarget = "") {
		return ""
	}
	if(fish_bait_map.HasKey(normalizedTarget)) {
		return fish_bait_map[normalizedTarget]
	}
	; allow setting target directly to a bait name
	return normalizeBaitName(normalizedTarget)
}

logOnce(msg, level=1)
{
	global lastBaitLogMsg
	if(lastBaitLogMsg != msg) {
		log(msg, level)
		lastBaitLogMsg := msg
	}
}

; Fishing mode shows the rod (cast/LMB) and bait (menu/RMB) buttons at the
; bottom right. Both are white glyphs on a semi-transparent circle, so each
; template alone could false-positive on other white UI; requiring the pair
; at their fixed relative offset (bait sits 95px right of rod) makes it safe.
findFishingModeButtons(ByRef baitBtnX, ByRef baitBtnY)
{
	global baitDetectVariation, baitButtonX, baitButtonY
	rodPath := baitTemplatePath("btn_rod")
	baitPath := baitTemplatePath("btn_bait")
	if(FileExist(rodPath) && FileExist(baitPath)) {
		ImageSearch, rodX, rodY, 1500, 930, 1919, 1079, % "*" baitDetectVariation " *TransFuchsia " rodPath
		if(ErrorLevel) {
			return 0
		}
		ImageSearch, foundX, foundY, 1500, 930, 1919, 1079, % "*" baitDetectVariation " *TransFuchsia " baitPath
		if(ErrorLevel) {
			return 0
		}
		if(Abs((foundX - rodX) - 95) > 8 || Abs(foundY - rodY) > 8) {
			return 0
		}
		baitBtnX := foundX + 30
		baitBtnY := foundY + 30
		return 1
	}
	; templates missing: fall back to the configured position, unverified
	baitBtnX := baitButtonX
	baitBtnY := baitButtonY
	return 1
}

scanResultPath()
{
	return A_Temp "\genshinfishing\scan_result.ini"
}

; Run the python pond scanner (source checkout only). It writes ranked bait
; suggestions and fish screen positions for the current water body.
runFishScan()
{
	global lastScanTick
	scriptPath := A_ScriptDir "\tools\fish_scan.py"
	if(!FileExist(scriptPath)) {
		logOnce("fish scan tool not found; use a concrete [bait] target instead of auto", 1)
		return 0
	}
	outPath := scanResultPath()
	FileDelete, % outPath
	RunWait, % A_ComSpec " /c python """ scriptPath """ --out """ outPath """", % A_ScriptDir, Hide
	if(!FileExist(outPath)) {
		logOnce("fish scan produced no result (python/opencv installed?)", 1)
		return 0
	}
	lastScanTick := A_TickCount
	return 1
}

; Candidate baits to try, in order. target=auto asks the pond scanner;
; otherwise the configured fish/bait target is the only candidate.
buildBaitCandidates()
{
	global targetFish, selectedBait
	global lastScanTick
	candidates := []
	if(normalizeFishName(targetFish) = "auto") {
		; reuse a recent scan; autoCast() refreshes positions more often
		if(A_TickCount - lastScanTick > 30000 || !FileExist(scanResultPath())) {
			if(!runFishScan()) {
				return candidates
			}
		}
		Loop, 3
		{
			IniRead, candidateBait, % scanResultPath(), scan, % "bait" A_Index, NONE
			if(candidateBait != "NONE" && candidateBait != "") {
				candidates.Push(candidateBait)
			}
		}
		if(candidates.Length() = 0) {
			logOnce("fish scan found no recognizable fish", 1)
		}
	} else {
		targetBait := resolveTargetBait()
		if(targetBait != "") {
			candidates.Push(targetBait)
		}
	}
	return candidates
}

ensureBaitForTarget()
{
	global autoBaitEnabled, baitMenuOpenDelay, baitClickDelay, baitRetryDelay
	global selectedBait, lastBaitActionTick, lastBaitUnsupportedNotified, winW, winH

	if(!autoBaitEnabled) {
		return 1
	}

	if(winW != 1920 || winH != 1080) {
		if(!lastBaitUnsupportedNotified) {
			log("auto bait selection currently supports only 1920x1080", 1)
			lastBaitUnsupportedNotified := 1
		}
		return 0
	}
	lastBaitUnsupportedNotified := 0

	if(A_TickCount - lastBaitActionTick < baitRetryDelay && lastBaitActionTick > 0 && selectedBait = "") {
		return 0
	}

	candidates := buildBaitCandidates()
	if(candidates.Length() = 0) {
		return 0
	}
	for _, candidateBait in candidates
	{
		if(selectedBait = candidateBait) {
			return 1
		}
	}
	if(A_TickCount - lastBaitActionTick < baitRetryDelay && lastBaitActionTick > 0) {
		return 0
	}
	lastBaitActionTick := A_TickCount

	; only act when the fishing mode buttons are visible
	if(!findFishingModeButtons(baitBtnX, baitBtnY)) {
		logOnce("fishing mode buttons not visible; skip bait selection", 2)
		return 0
	}

	; the bait menu opens with a right click while in fishing mode
	Click, %baitBtnX%, %baitBtnY%, Right
	Sleep, % baitMenuOpenDelay

	; require the dialog to actually be open before clicking anything else
	if(!findMenuButton("confirm", confirmX, confirmY)) {
		log("bait menu did not open after right click", 1)
		return 0
	}

	pickedBait := ""
	for _, candidateBait in candidates
	{
		if(!FileExist(baitTemplatePath("bait_" candidateBait))) {
			logOnce("no template for bait: " candidateBait, 1)
			continue
		}
		if(findBaitInMenu(candidateBait, baitX, baitY, alreadySelected)) {
			pickedBait := candidateBait
			break
		}
	}

	if(pickedBait = "") {
		log("no candidate bait found in menu (water body mismatch?)", 1)
		if(findMenuButton("cancel", cancelX, cancelY)) {
			Click, %cancelX%, %cancelY%
			Sleep, % baitClickDelay
		}
		return 0
	}

	if(alreadySelected) {
		if(findMenuButton("cancel", cancelX, cancelY)) {
			Click, %cancelX%, %cancelY%
			Sleep, % baitClickDelay
		}
		selectedBait := pickedBait
		log("auto bait already selected: " pickedBait, 1)
		return 1
	}

	Click, %baitX%, %baitY%
	Sleep, % baitClickDelay
	Click, %confirmX%, %confirmY%
	Sleep, % baitClickDelay

	selectedBait := pickedBait
	log("auto bait selected " pickedBait " at " baitX "," baitY, 1)
	return 1
}

; Experimental: aim the cast at a scanned fish position and cast. Aiming is
; open loop: hold LMB, the landing reticle appears at roughly aim_origin,
; steer it with relative mouse movement scaled by aim_gain, then release.
; The bobber is aimed fish_offset px short of the fish so it is not scared.
autoCast()
{
	global autocastEnabled, autocastCooldown, lastAutoCastTick, lastScanTick
	global aimOriginX, aimOriginY, aimGainX, aimGainY, aimFishOffset, aimMaxMove, aimSettleDelay
	global selectedBait

	if(!autocastEnabled) {
		return
	}
	if(A_TickCount - lastAutoCastTick < autocastCooldown) {
		return
	}
	; fish move; require a recent scan for aiming
	if(A_TickCount - lastScanTick > 4000) {
		if(!runFishScan()) {
			return
		}
	}
	IniRead, fishCount, % scanResultPath(), scan, count, 0
	if(fishCount < 1) {
		return
	}
	; prefer a fish that matches the selected bait
	fishX := 0
	fishY := 0
	Loop, % fishCount
	{
		IniRead, fx, % scanResultPath(), scan, % "fish" A_Index "_x", 0
		IniRead, fy, % scanResultPath(), scan, % "fish" A_Index "_y", 0
		IniRead, fb, % scanResultPath(), scan, % "fish" A_Index "_bait", NONE
		if(fx > 0 && fishX = 0) {
			fishX := fx
			fishY := fy
		}
		if(fx > 0 && fb = selectedBait) {
			fishX := fx
			fishY := fy
			break
		}
	}
	if(fishX = 0) {
		return
	}
	lastAutoCastTick := A_TickCount

	aimTool := A_ScriptDir "\tools\aim_cast.py"
	Click, Down
	Sleep, % aimSettleDelay

	if(FileExist(aimTool)) {
		; closed loop: python watches the landing reticle and steers it onto
		; the fish (stopping fish_offset px short) while we hold the button
		log("autocast closed-loop aim at fish=" fishX "," fishY, 1)
		RunWait, % A_ComSpec " /c python """ aimTool """ --fish-x " fishX " --fish-y " fishY " --offset " aimFishOffset, % A_ScriptDir, Hide UseErrorLevel
		log("autocast aim result=" ErrorLevel " (0=aligned 2=no reticle 3=timeout)", 1)
	} else {
		; open loop fallback: needs aim_origin/aim_gain calibration
		dx := fishX - aimOriginX
		dy := fishY - aimOriginY
		len := Sqrt(dx*dx + dy*dy)
		if(len > aimFishOffset) {
			dx := dx * (len - aimFishOffset) / len
			dy := dy * (len - aimFishOffset) / len
		} else {
			dx := 0
			dy := 0
		}
		mx := Round(dx * aimGainX)
		my := Round(dy * aimGainY)
		if(mx > aimMaxMove) {
			mx := aimMaxMove
		}
		if(mx < -aimMaxMove) {
			mx := -aimMaxMove
		}
		if(my > aimMaxMove) {
			my := aimMaxMove
		}
		if(my < -aimMaxMove) {
			my := -aimMaxMove
		}
		log("autocast open-loop aim fish=" fishX "," fishY " move=" mx "," my, 1)
		steps := 12
		movedX := 0
		movedY := 0
		Loop, %steps%
		{
			stepX := Round(mx * A_Index / steps) - movedX
			stepY := Round(my * A_Index / steps) - movedY
			movedX += stepX
			movedY += stepY
			DllCall("mouse_event", "UInt", 0x0001, "Int", stepX, "Int", stepY, "UInt", 0, "UPtr", 0)
			Sleep, 15
		}
	}
	Sleep, 300
	Click, Up
}

isGenshinActive()
{
	genshin_hwnd := genshin_window_exist()
	if(!genshin_hwnd) {
		return 0
	}
	if(WinExist("A") != genshin_hwnd) {
		return 0
	}
	return 1
}

calibrateBaitButton()
{
	global baitButtonX, baitButtonY
	if(!isGenshinActive()) {
		ttm("Activate Genshin window first`n请先激活原神窗口", 1800)
		return
	}
	MouseGetPos, baitButtonX, baitButtonY
	IniWrite, % baitButtonX, setting.ini, bait, button_x
	IniWrite, % baitButtonY, setting.ini, bait, button_y
	log("bait calibration: button=" baitButtonX "," baitButtonY, 1)
	ttm("Bait button saved: " baitButtonX "," baitButtonY, 1800)
}

calibrateBaitConfirm()
{
	global baitConfirmX, baitConfirmY
	if(!isGenshinActive()) {
		ttm("Activate Genshin window first`n请先激活原神窗口", 1800)
		return
	}
	MouseGetPos, baitConfirmX, baitConfirmY
	IniWrite, % baitConfirmX, setting.ini, bait, confirm_x
	IniWrite, % baitConfirmY, setting.ini, bait, confirm_y
	log("bait calibration: confirm=" baitConfirmX "," baitConfirmY, 1)
	ttm("Confirm button saved: " baitConfirmX "," baitConfirmY, 1800)
}

calibrateBaitCancel()
{
	global baitCancelX, baitCancelY
	if(!isGenshinActive()) {
		ttm("Activate Genshin window first`n请先激活原神窗口", 1800)
		return
	}
	MouseGetPos, baitCancelX, baitCancelY
	IniWrite, % baitCancelX, setting.ini, bait, cancel_x
	IniWrite, % baitCancelY, setting.ini, bait, cancel_y
	log("bait calibration: cancel=" baitCancelX "," baitCancelY, 1)
	ttm("Cancel button saved: " baitCancelX "," baitCancelY, 1800)
}

; iconSize = dLinePt(0.0353) * dLinePt(0.0442)

getState:
if(isCNServer) {
	iconLeftPt := 0.167
} else {
	iconLeftPt := 0.222
}
iconTopPt := 0.084
iconBottomPt := 0
iconRightPt := 0

if(last_iconX>0) {
	last_iconLeftPt := (winW - last_iconX)/dLine
	last_iconTopPt := (winH - last_iconY)/dLine

	iconBottomPt := (winH - last_iconY - dLinePt(0.0442*1.5))/dLine
	iconRightPt := (winW - last_iconX - dLinePt(0.0353*1.5))/dLine
	if(iconBottomPt<0){
		iconBottomPt := 0
	}
	if(iconRightPt<0){
		iconRightPt := 0
	}
	iconLeftPt := last_iconLeftPt + (0.0353*0.5)
	iconTopPt := last_iconTopPt + (0.0442*0.5)
	log("lastIcon=" last_iconX ", " last_iconY "  dLine=" dLine, 3)
}
; log("search from [" winW-dLinePt(iconLeftPt) ", " winH-dLinePt(iconTopPt) "] to [" winW-dLinePt(iconRightPt) ", " winH-dLinePt(iconBottomPt) "]", 3)
; k:=(((winW**2)+(winH**2))**0.5)/(((1920**2)+(1080**2))**0.5)
searchX0:=winW-dLinePt(iconLeftPt)
searchY0:=winH-dLinePt(iconTopPt)
searchX1:=winW-dLinePt(iconRightPt)
searchY1:=winH-dLinePt(iconBottomPt)
ImageSearch, iconX, iconY, searchX0, searchY0, searchX1, searchY1, % "*32 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.ready.filename
if(!ErrorLevel){
	last_iconX := iconX
	last_iconY := iconY
	state:="ready"
	statePredict:=state
	stateUnknownStart := 0
	log("state->" statePredict, 1)
	return
} else {
	log("[" ErrorLevel "] not in ready state [" searchX0 "," searchY0 "," searchX1 "," searchY1 "]", 3)
}
ImageSearch, iconX, iconY, searchX0, searchY0, searchX1, searchY1, % "*32 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.reel.filename
if(!ErrorLevel){
	last_iconX := iconX
	last_iconY := iconY
	state:="reel"
	statePredict:=state
	stateUnknownStart := 0
	log("state->" statePredict, 1)
	return
} else {
	log("[" ErrorLevel "] not in reel state [" searchX0 "," searchY0 "," searchX1 "," searchY1 "]", 3)
}
ImageSearch, iconX, iconY, searchX0, searchY0, searchX1, searchY1, % "*32 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.casting.filename
if(!ErrorLevel){
	last_iconX := iconX
	last_iconY := iconY
	state:="casting"
	statePredict:=state
	stateUnknownStart := 0
	log("state->" statePredict, 1)
	return
} else {
	log("[" ErrorLevel "] not in casting state [" searchX0 "," searchY0 "," searchX1 "," searchY1 "]", 3)
}
state:="unknown"
if(stateUnknownStart == 0) {
	stateUnknownStart := A_TickCount
}
if(statePredict!="unknown" && A_TickCount - stateUnknownStart>=2000){
	last_iconX := 0
	last_iconY := 0
	statePredict:="unknown"
	; Click, Up
	log("state->" statePredict, 1)
}
Return

main:
genshin_hwnd := genshin_window_exist()
if(!genshin_hwnd){
	SetTimer, main, -800
	Return
}
if(WinExist("A") != genshin_hwnd) {
	isWorking:=False
	SetTimer, main, -500
	Return
}
getClientSize(genshin_hwnd, winW, winH)
if(oldWinW!=winW || oldWinH!=winH) {
	log("Get dimension=" winW "x" winH,1)
	if(InStr(FileExist(A_Temp "/genshinfishing/" winW winH), "D")) {
		fileCount:=0
		for k, v in img_list
		{
			if(FileExist(A_Temp "/genshinfishing/" winW winH "/" v.filename)) {
				fileCount += 1
			}
		}
		if(fileCount < img_list.Count()) {
			isResolutionValid:=0
		} else {
			isResolutionValid:=1
			dline:=Ceil(((winW**2)+(winH**2))**0.5)
			barR_left:=dLinePt(0.27)
			barR_top:=dLinePt(0.03)
			barR_right:=dLinePt(0.59)
			barR_bottom:=dLinePt(0.1)

			delta_left:=dLinePt(0.025)
			delta_top:=dLinePt(0.005)
			delta_right:=dLinePt(0.035)
			delta_bottom:=dLinePt(0.014)

			barS_left:=dLinePt(0.22)
			barS_right:=dLinePt(0.64)
		}
	} else {
		isResolutionValid:=0
	}
}
oldWinW:=winW
oldWinH:=winH
if(!isResolutionValid) {
	tt("Unsupported resolution`n不支持的分辨率`n" winW "x" winH "`n`nThe supported resolutions are as follows`n支持的分辨率如下`n" supported_resolutions)
	SetTimer, main, -800
	Return
} else {
	if(isWorking==False) {
		tt("Genshin Fishing Automata is working`n自动钓鱼人偶正常工作中")
		log("Genshin Window Active",1)
	}
}
isWorking:=True

if(statePredict=="unknown" || statePredict=="ready") {
	Gosub, getState
	if(statePredict!="unknown" && debugmode){
		tt("state = " state "`nstatePredict = " statePredict "`n" winW "," winH)
	}
	if(statePredict=="ready") {
		if(ensureBaitForTarget()) {
			autoCast()
		}
	}
	if(statePredict=="reel"){
		SetTimer, main, -40
	} else {
		barY := 0
		SetTimer, main, -800
	}
	Return
} else if(statePredict=="casting") {
	Gosub, getState
	if(debugmode){
		tt("state = " statePredict)
	}
	if(statePredict=="reel") {
		Click, Down
		SetTimer, main, -40
	} else{
		SetTimer, main, -200
	}
	Return
} else if(statePredict=="reel") {
	DllCall("QueryPerformanceCounter", "Int64P",  startTime)
	if(barY<2) {
		ImageSearch, _, barY, barR_left, barR_top, barR_right, barR_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.bar.filename
		if(ErrorLevel){
			if(barY == 0) {
				barY := 1
				Click, Down
			} else if(barY == 1) {
				barY := 0
				Click, Up
			}
		} else {
			Click, Up
			avrDetectTime:=[]
			leftX:=0
			rightX:=0
			curX:=0
			log("get barY=" barY,2)
		}
		DllCall("QueryPerformanceCounter", "Int64P",  endTime)
	} else {
		if(leftX > 0) {
			ImageSearch, leftX, leftY, leftX-delta_left, barY-delta_top, leftX+delta_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.left.filename
		} else {
			ImageSearch, leftX, leftY, barS_left, barY-delta_top, barS_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.left.filename
		}
		if(ErrorLevel){
			leftX := 0
			leftY := "Null"
		} else {
			leftPredictX := 2*leftX - leftXOld
			leftXOld := leftX
		}

		if(rightX > 0) {
			ImageSearch, rightX, rightY, rightX-delta_left, barY-delta_top, rightX+delta_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.right.filename
		} else {
			ImageSearch, rightX, rightY, barS_left, barY-delta_top, barS_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.right.filename
		}
		if(ErrorLevel){
			rightX := 0
			rightY := "Null"
		} else {
			rightPredictX := 2*rightX - rightXOld
			rightXOld := rightX
		}

		if(curX > 0) {
			ImageSearch, curX, curY, curX-delta_left, barY-delta_top, curX+delta_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.cur.filename
		} else {
			ImageSearch, curX, curY, barS_left, barY-delta_top, barS_right, barY+delta_bottom, % "*80 *TransFuchsia " A_Temp "/genshinfishing/" winW winH "/" img_list.cur.filename
		}
		if(ErrorLevel){
			curX := 0
			curY := "Null"
		} else {
			curPredictX := 2*curX - curXOld
			curXOld := curX
		}
		if(leftY == "Null" && rightY == "Null" && curY == "Null") {
			Gosub, getState
			Click, Up
		} else {
			if(leftX+rightX < leftXOld+rightXOld) {
				k := 0.2
			} else if(leftX+rightX > leftXOld+rightXOld) {
				k:= 0.8
			} else {
				k = 0.4
			}
			if(curPredictX<(k*rightPredictX + (1-k)*leftPredictX)){
				Click, Down
			} else {
				Click, Up
			}
		}
		DllCall("QueryPerformanceCounter", "Int64P",  endTime)

		detectTime:=(endTime-startTime)//freq
		if(avrDetectTime.Length()<8){
			avrDetectTime.Push(detectTime)
		} else {
			avrDetectTime.Pop()
			avrDetectTime.Push(detectTime)
		}
		sum := 0
		For index, value in avrDetectTime
			sum += value

		avrDetectMs := sum//avrDetectTime.Length()

		log("dt=" detectTime "ms`tleftX="leftX "`trightX="rightX "`t" "curX="curX "`tleftXpre="leftPredictX "`trightXpre="rightPredictX "`tcurXpre="curPredictX,2)
		if(debugmode){
			tt("barY = " barY "`n" "leftX = " leftX "`n" "rightX = " rightX "`n" "curX = " curX "`n" "barMove = " (leftX+rightX)-(leftXOld+rightXOld) "`n" state "`n" avrDetectMs "ms")
		}
	}
	lastTime:=(endTime-startTime)//freq
	if(lastTime>60) {
		SetTimer, main, -10
	} else {
		SetTimer, main, % lastTime-70
	}
	Return
}

Return

regist:
Gui, notice:+OwnDialogs
InputBox, regcode_input, Regist 注册, Please input regist code:`n请输入注册码:
if !ErrorLevel
{
	if(isRegCodeValid(regcode_input)){
		IniWrite, % regcode_input, setting.ini, regist, code
		MsgBox, 0x40,, Regist success! 注册成功!
		Reload
	} else {
		MsgBox, 16,, Invalid regist code 无效的注册码
	}
}
Return

donate:
Run, https://ko-fi.com/xianii
Return
pages:
Run, https://github.com/Nigh/Genshin-fishing
Return
exit:
pLogfile.Close()
ExitApp
donothing:
Return

^!F7::
calibrateBaitButton()
Return

^!F8::
calibrateBaitConfirm()
Return

^!F9::
calibrateBaitCancel()
Return

;@Ahk2Exe-IgnoreBegin
F5::ExitApp
F6::Reload
;@Ahk2Exe-IgnoreEnd

UAC()
{
	full_command_line := DllCall("GetCommandLine", "str")
	if not (A_IsAdmin or RegExMatch(full_command_line, " /restart(?!\S)"))
	{
		try
		{
			if A_IsCompiled
				Run *RunAs "%A_ScriptFullPath%" /restart
			else
				Run *RunAs "%A_AhkPath%" /restart "%A_ScriptFullPath%"
		}
		ExitApp
	}
}
