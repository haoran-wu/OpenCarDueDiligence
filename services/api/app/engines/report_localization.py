"""Deterministic localization for report-owned prose.

Evidence excerpts, provider names, DTC descriptions supplied by a source, and
user-entered inspection text are never machine-translated here.  Chinese
reports label those values as source-language text instead of pretending that
the whole evidence record has been translated.
"""

from __future__ import annotations

import re

from ..models import RiskFinding


_UNKNOWN_EXACT = {
    "VIN/basic identity is entered but not corroborated by both listing and physical scan evidence": "已录入 VIN/基本车辆身份，但尚未由车源快照和实车扫描两类证据共同印证。",
    "VIN and basic vehicle identity have not all been verified": "VIN 和基本车辆身份尚未全部核实。",
    "Exact generation/platform/engine/transmission/drivetrain/production date is not fully resolved": "具体代际、平台、发动机、变速箱、驱动形式和生产日期尚未全部确认。",
    "No evidence-backed target listing snapshot is saved": "尚未保存有证据支持的目标车源快照。",
    "No extracted, evidence-backed vehicle history report facts are recorded": "尚未记录从车辆历史报告中提取并可追溯的事实。",
    "Original title, owner identity, VIN, and lien status are not verified": "原始 title、车主身份、VIN 和 lien 状态尚未核实。",
    "No substantive generic powertrain scan with explicit module coverage is recorded": "尚未记录包含明确模块覆盖范围的有效通用动力系统扫描。",
    "Emissions readiness is incomplete or could not be decoded": "排放 readiness 尚未完成或无法解码。",
    "No OBD scan is recorded": "尚未记录 OBD 扫描。",
    "ABS/SRS/body module status is unknown": "ABS、SRS 和车身模块状态未知。",
    "Recent maintenance/repair receipts have no extracted, verifiable content": "近期保养或维修票据尚无已提取且可核实的内容。",
}

_ACTION_EXACT = {
    "Stop the transaction until every blocking finding is independently resolved": "在所有阻断性发现得到独立核实并解决前，停止交易。",
    "Arrange an independent pre-purchase inspection and keep the engine cold for arrival": "安排独立购前检查（PPI），并要求到场时保持冷车。",
    "Resolve high-severity PPI/diagnostic findings and obtain written repair quotes before negotiating": "谈价前解决高严重度的 PPI/诊断发现，并取得书面维修报价。",
    "Convert confirmed PPI findings into written repair quotes before making a conditional offer": "提出有条件报价前，把已确认的 PPI 发现转化为书面维修报价。",
    "Verify title/identity/lien and complete the state transaction plan before payment": "付款前核实 title、身份和 lien，并完成所在州的交易计划。",
}

_CHECK_EXACT = {
    "Inspect the original title and obtain a current NMVTIS/DMV title record": "检查原始 title，并取得当前的 NMVTIS/DMV title 记录。",
    "Require an independent body/structure inspection and repair documentation": "要求独立车身/结构检查及维修文件。",
    "Request both inspection receipts, scan all emissions DTC states, and verify readiness after a normal drive cycle": "索要两次验车凭据，扫描所有排放 DTC 状态，并在正常驾驶循环后核实 readiness。",
    "Obtain the failed inspection sheet, repair invoice, and current PPI confirmation": "取得验车失败单、维修发票及当前 PPI 确认。",
    "Request maintenance receipts covering the gap and verify fluid/service condition during PPI": "索要覆盖记录空档期的保养凭据，并在 PPI 中核实油液和保养状态。",
    "Compare the original title, report page, physical VIN, and seller's written explanation": "对照原始 title、报告页面、实车 VIN 和卖家的书面说明。",
    "Compare dashboard, door-jamb, title, and report VINs character by character": "逐字符核对仪表台、门框、title 和报告中的 VIN。",
    "Complete the manufacturer drive cycle without clearing codes, then rescan": "不要清码，完成厂家规定的驾驶循环后重新扫描。",
    "Obtain original inspection/title records and compare the dashboard odometer": "取得原始验车/title 记录，并与仪表里程核对。",
    "Resolve or price this item using the written PPI finding": "依据书面 PPI 发现解决该项目，或将其计入价格。",
    "Verify this concern during an independent PPI and obtain a written diagnosis before negotiating": "在独立 PPI 中核实该问题，并在谈价前取得书面诊断。",
    "Obtain the full VIN and compare it character by character with the listing, history records, and physical vehicle before traveling or paying": "出发或付款前取得完整 VIN，并与车源、历史记录及实车逐字符核对。",
    "Request a redacted original title photo showing the VIN, issuing state, title status, assignment, and lien area; inspect the original before payment": "索要打码后的原始 title 照片，保留 VIN、签发州、title 状态、转让栏和 lien 栏；付款前检查原件。",
    "Confirm the seller will show photo ID and match the name to the current original title in person; resolve any lien or authority mismatch before payment": "确认卖家会现场出示带照片证件，并将姓名与当前原始 title 核对；付款前解决任何 lien 或处分权不一致。",
    "Match the dashboard, door-label, original-title, history-report, and diagnostic-scan VINs character by character before proceeding": "继续交易前，逐字符核对仪表台、车门标签、原始 title、历史报告和诊断扫描中的 VIN。",
    "Obtain explicit permission for an independent PPI and road test before traveling or making an offer": "出发或报价前，取得独立 PPI 和道路试驾的明确许可。",
    "Review freeze-frame and misfire counters after a true cold start": "真正冷启动后检查 freeze-frame 和失火计数。",
    "Swap-test ignition components only if appropriate, then retest": "仅在适用时互换点火部件进行测试，然后复测。",
    "Perform compression/leak-down and injector tests if the misfire remains": "若失火仍存在，进行缸压/泄漏和喷油器测试。",
    "Check for exhaust leaks and other engine codes before catalyst testing": "测试催化器前先检查排气泄漏和其他发动机报码。",
    "Graph upstream/downstream oxygen-sensor behavior at operating temperature": "在工作温度下绘制上游/下游氧传感器曲线。",
    "Verify fuel trims and catalyst efficiency with a qualified technician": "由合格技师核实燃油修正和催化效率。",
    "Scan the transmission control module with a manufacturer-capable tool": "使用支持厂家模块的设备扫描变速箱控制模块。",
    "Check fluid condition/leaks and road-test shift quality": "检查油液状态和泄漏，并通过试驾评估换挡质量。",
    "Do not price a transmission replacement until the underlying TCM code is known": "在取得底层 TCM 报码前，不要按更换变速箱估价。",
    "Smoke/pressure-test the charge-air system": "对增压空气系统做烟雾/压力测试。",
    "Command and inspect wastegate/boost control operation": "执行并检查 wastegate/增压控制动作。",
    "Inspect turbo oil supply and shaft condition before quoting a turbo": "在报价更换涡轮前，检查涡轮供油和轴状态。",
    "Read the manufacturer service information for this exact powertrain": "查阅该具体动力总成的厂家维修资料。",
    "Review freeze-frame/live data and reproduce the symptom": "检查 freeze-frame/实时数据并复现症状。",
    "Obtain a written diagnosis before assigning a replacement part": "指定更换部件前先取得书面诊断。",
    "Obtain a written itemized repair quote": "取得逐项列明的书面维修报价。",
}

_SCENARIO_EXACT = {
    "Ignition/connection diagnosis and minor repair": "点火/连接诊断及小修",
    "Fuel, air, or valve-control repair": "燃油、进气或气门控制维修",
    "Internal engine repair after failed compression/leak-down test": "缸压/泄漏测试失败后的发动机内部维修",
    "Leak/sensor diagnosis": "泄漏/传感器诊断",
    "Confirmed emissions repair": "经确认的排放系统维修",
    "OEM catalyst plus contributing repair": "原厂催化器及相关原因维修",
    "Module scan and minor electrical/fluid repair": "模块扫描及小型电气/油液维修",
    "Valve body, solenoid, or control repair": "阀体、电磁阀或控制系统维修",
    "Confirmed internal transmission repair": "经确认的变速箱内部维修",
    "Hose/leak/control repair": "软管、泄漏或控制系统维修",
    "Wastegate or boost-control repair": "Wastegate 或增压控制维修",
    "Confirmed turbocharger replacement": "经确认的涡轮增压器更换",
    "Diagnostic/minor repair": "诊断/小修",
    "System-specific repair": "对应系统维修",
    "Worst reasonable system repair": "合理最坏情形的系统维修",
}

_FINDING_FIXED = {
    "HISTORY_TITLE_BRAND": (
        "历史证据显示 branded title",
        "已提取到明确的 salvage/rebuilt/junk/lemon title 表述。继续前应核实原始 title 和签发州 DMV 记录。",
    ),
    "HISTORY_STRUCTURAL_DAMAGE": (
        "历史记录报告结构损伤",
        "报告包含明确的损伤表述。CARFAX/历史数据本身不能证明维修质量或当前结构安全性。",
    ),
    "HISTORY_FLOOD_DAMAGE": (
        "历史记录报告泡水或进水损伤",
        "报告包含明确的损伤表述。CARFAX/历史数据本身不能证明维修质量或当前结构安全性。",
    ),
    "HISTORY_ACCIDENT_DAMAGE": (
        "历史记录报告事故或损伤",
        "报告包含明确的损伤表述。CARFAX/历史数据本身不能证明维修质量或当前结构安全性。",
    ),
    "HISTORY_REPEATED_EMISSIONS_FAILURES": (
        "历史记录中出现多次排放验车失败",
        "多次失败可能由不同原因造成，包括 readiness 未完成。应取得实际验车结果，不能仅凭历史记录推断某个部件损坏。",
    ),
    "HISTORY_SAFETY_FAILURE": (
        "历史记录中出现安全验车失败",
        "历史记录未说明失败项目是轻微问题还是安全关键问题。应核实失败单和已完成的维修。",
    ),
    "HISTORY_SERVICE_RECORD_GAP": (
        "所提供报告存在较长的保养记录空档",
        "这是已报告记录的空档，不代表车辆一定缺乏保养。应索要凭据，并通过 PPI 判断当前状况。",
    ),
    "VIN_MISMATCH": (
        "不同证据中的 VIN 不一致",
        "案件、车源或扫描中的 VIN 不一致。在实车 VIN、title 和记录完全一致前应停止交易。",
    ),
}


def _source_text(kind: str, value: str) -> str:
    return f"原文（{kind}，可能为英文）/ Source text: {value}"


def localize_unknown_zh(text: str) -> str:
    if text in _UNKNOWN_EXACT:
        return _UNKNOWN_EXACT[text]
    module_match = re.fullmatch(
        r"(ABS|SRS|BODY) module was not verified by the available scanner", text
    )
    if module_match:
        return f"现有扫描器尚未核实 {module_match.group(1)} 模块。"
    self_match = re.fullmatch(
        r"Five-stage buyer inspection critical checks are only (\d+)% complete",
        text,
    )
    if self_match:
        return f"五阶段买家检查的关键项目仅完成 {self_match.group(1)}%。"
    ppi_match = re.fullmatch(
        r"Independent PPI requires an identified inspector and all applicable critical checks; current completion is (\d+)%",
        text,
    )
    if ppi_match:
        return (
            "独立 PPI 必须记录可识别的检查方并完成所有适用的关键项目；"
            f"当前完成度为 {ppi_match.group(1)}%。"
        )
    return _source_text("未本地化的系统状态", text)


def localize_action_zh(text: str) -> str:
    return _ACTION_EXACT.get(text, _source_text("未本地化的下一步", text))


def _localize_check(text: str) -> str:
    return _CHECK_EXACT.get(text, _source_text("检查说明", text))


def _localize_scenario_label(text: str, *, system_owned: bool) -> str:
    if text in _SCENARIO_EXACT:
        return _SCENARIO_EXACT[text]
    return _source_text("维修情形", text) if not system_owned else text


def localize_finding_zh(finding: RiskFinding) -> RiskFinding:
    """Translate fixed engine prose and explicitly label source-owned text."""

    title = finding.title
    detail = finding.detail
    system_owned = True

    if finding.code in _FINDING_FIXED:
        title, detail = _FINDING_FIXED[finding.code]
    elif finding.code == "LISTING_HISTORY_CONFLICT":
        title = "车源描述与所提供历史证据冲突"
        conflicts = []
        if "clean title" in finding.detail:
            conflicts.append("车源声称 clean title，但历史证据报告了 title brand")
        if "denies accident" in finding.detail:
            conflicts.append("车源否认事故/损伤，但历史证据明确报告了事故或损伤")
        detail = "；".join(conflicts or ["车源描述与历史证据存在文件层面的冲突"]) + "。依赖车源描述前必须解决该冲突。"
    elif finding.code.startswith("READINESS_NOT_READY_"):
        title = "Readiness monitors 尚未完成"
        detail = "监测项未完成可能来自电瓶亏电/断开、近期清码或正常维修；这不能证明卖家清过报码。"
    elif finding.code == "ODOMETER_SEQUENCE_CONFLICT":
        title = "历史时间线中的里程出现下降"
        numbers = re.search(r"Mileage falls from ([\d,]+) to ([\d,]+)", finding.detail)
        detail = (
            f"里程从 {numbers.group(1)} 降至 {numbers.group(2)}；应核实来源记录和 title 里程披露。"
            if numbers
            else "历史记录中的里程顺序存在冲突；应核实来源记录和 title 里程披露。"
        )
    elif finding.code.startswith("DTC_P030"):
        dtc = finding.code.split("_")[1]
        title = f"{dtc} 失火诊断分支"
        detail = "ECU 检测到失火，但不能据此确定某个点火线圈或单一部件损坏；点火、供油、漏气、气门控制和缸压都仍是可能原因。"
    elif finding.code.startswith("DTC_P0420_"):
        title = "P0420 催化效率诊断分支"
        detail = "P0420 表示催化系统效率低于阈值，本身不能证明必须更换催化器；排气泄漏、传感器、供油问题或既往失火都可能相关。"
    elif finding.code.startswith("DTC_P0700_"):
        title = "变速箱控制模块请求点亮警告灯"
        detail = "P0700 是变速箱控制模块发出的请求，不是对具体部件的诊断。"
    elif finding.code.startswith("DTC_P0299_"):
        title = "P0299 增压不足诊断分支"
        detail = "增压不足可能来自泄漏、控制部件、传感器或涡轮磨损；单凭报码不能决定维修方案。"
    elif finding.code.startswith("DTC_"):
        parts = finding.code.split("_")
        dtc = parts[1] if len(parts) > 1 else finding.code
        title = f"{dtc} 需要进一步诊断"
        default_detail = "A diagnostic code is evidence of a monitored condition, not proof of a failed part."
        detail = (
            "诊断报码表明监测到某种状态，但不能证明某个部件已经损坏。"
            if finding.detail == default_detail
            else _source_text("DTC 描述", finding.detail)
        )
    elif finding.code.startswith("INSPECTION_"):
        system_owned = False
        title = _source_text("检查项目", finding.title)
        result_match = re.fullmatch(r"Inspection result: ([A-Z_]+)", finding.detail)
        detail = (
            f"检查结果：{result_match.group(1)}。"
            if result_match
            else _source_text("检查备注", finding.detail)
        )
    else:
        system_owned = False
        title = _source_text("发现标题", finding.title)
        detail = _source_text("发现说明", finding.detail)

    scenarios = [
        scenario.model_copy(
            update={
                "label": _localize_scenario_label(
                    scenario.label, system_owned=system_owned
                ),
                "confirmation_tests": [
                    _localize_check(item) for item in scenario.confirmation_tests
                ],
            }
        )
        for scenario in finding.repair_scenarios
    ]
    return finding.model_copy(
        update={
            "title": title,
            "detail": detail,
            "next_checks": [_localize_check(item) for item in finding.next_checks],
            "repair_scenarios": scenarios,
        }
    )
