"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ComparisonRisk, ComparisonRow } from "@ocdd/contracts";
import {
  AlertTriangle,
  CarFront,
  ClipboardCheck,
  FileDown,
  FileStack,
  Gauge,
  GitCompareArrows,
  HardDrive,
  Landmark,
  LayoutDashboard,
  LockKeyhole,
  MessageSquareText,
  MoreHorizontal,
  Plus,
  RefreshCw,
  SearchCheck,
  ShieldCheck,
  Upload,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { api, apiErrorMessage, isApiConnectionFailure, isApiError } from "@/lib/api";
import { accessTokenMap, caseAccessFor, forgetCaseAccess, knownCaseAccesses, rememberCaseAccess } from "@/lib/case-access";
import { explicitDemoCases, hasGenericPowertrainCoverage } from "@/lib/case-record";
import { comparisonRiskClass, comparisonRiskFromLevel } from "@/lib/compare";
import { demoCases } from "@/lib/demo";
import { mobileCaseLabel } from "@/lib/mobile-case-label";
import { applyDecodedVehicleToForm, isValidModernVin, normalizeVinInput, vehicleSpecForCase } from "@/lib/new-case";
import { calculateNegotiation, eligibleNegotiationAdjustments, negotiationErrorMessage, shouldShowNegotiationArithmetic } from "@/lib/negotiation";
import {
  comparableListingImportForm,
  copyResolvedTargetConfiguration,
  listingImportPayload,
  listingImportVehicle,
  targetListingImportForm,
  type ListingImportForm,
  type ListingRole,
} from "@/lib/listing-import";
import {
  blobToBase64,
  normalizeOcddPassphrase,
  ocddDownloadName,
  ocddFileError,
  ocddPassphraseError,
} from "@/lib/ocdd-file";
import { buildLocalTransactionPlan } from "@/lib/transaction";
import type {
  CaseRecord,
  CheckStatus,
  InspectionStage,
  Language,
  NegotiationRequest,
  NegotiationResponse,
  RiskLevel,
  TransactionContextInput,
  TransactionPlan,
  VehicleSpec,
} from "@/lib/types";
import { ServiceWorkerRegister } from "./ServiceWorkerRegister";

type Tab = "overview" | "evidence" | "inspection" | "negotiate" | "transaction" | "compare";
type DataMode = "api" | "demo" | "offline";
type DeploymentMode = "local" | "cloud" | "unknown";

const copy = {
  "zh-CN": {
    workspace: "购车工作台",
    watchlist: "关注清单",
    newCase: "新建案件",
    overview: "总览",
    evidence: "证据",
    inspection: "验车",
    negotiate: "谈价",
    transaction: "交易",
    compare: "比较",
    import: "导入车源",
    analyze: "更新结论",
    coverage: "证据覆盖",
    updated: "更新于",
    decision: "当前建议",
    riskAxes: "风险维度",
    findings: "关键发现",
    valuation: "估值与报价边界",
    asking: "卖家要价",
    market: "市场基准",
    target: "目标价格",
    opening: "首次报价",
    ceiling: "最高价",
    unknown: "未知",
    ready: "已准备",
    viewEvidence: "查看证据",
    obd: "OBD 覆盖快照",
    noCodeWarning: "无报码不等于机械正常。普通 OBD 无法排除渗漏、结构问题或内部磨损。",
    save: "保存本阶段",
    generate: "生成有依据的消息",
    copy: "复制消息",
    copied: "已复制",
    transactionPlan: "生成交易步骤",
    official: "官方页面",
    hardGates: "付款前硬闸门",
    tasks: "按顺序完成",
    compareTitle: "关注清单比较",
    planningExposure: "未解决维修规划暴露",
    importHint: "粘贴车源链接或手工填入。浏览器扩展也可从当前页面预览后导入。",
    localMode: "演示数据",
    apiMode: "服务已连接",
    localApiMode: "已保存在本机",
    cloudApiMode: "加密云服务已连接",
    offlineMode: "服务未连接",
    loading: "正在打开购车工作台…",
    empty: "还没有案件。新建一个案件，然后导入车源、报告或 OBD 扫描。",
    retry: "重新连接",
    refresh: "刷新",
    amountUnavailable: "证据不足，暂不输出单点价格",
  },
  en: {
    workspace: "Buyer workspace",
    watchlist: "Watchlist",
    newCase: "New case",
    overview: "Overview",
    evidence: "Evidence",
    inspection: "Inspection",
    negotiate: "Negotiate",
    transaction: "Transaction",
    compare: "Compare",
    import: "Import listing",
    analyze: "Update conclusion",
    coverage: "Evidence coverage",
    updated: "Updated",
    decision: "Current decision",
    riskAxes: "Risk axes",
    findings: "Key findings",
    valuation: "Valuation & offer boundary",
    asking: "Asking",
    market: "Market baseline",
    target: "Target",
    opening: "Opening",
    ceiling: "Ceiling",
    unknown: "Unknown",
    ready: "Ready",
    viewEvidence: "View evidence",
    obd: "OBD coverage snapshot",
    noCodeWarning: "No codes does not mean mechanically sound. Generic OBD cannot rule out leaks, structure issues, or internal wear.",
    save: "Save this stage",
    generate: "Generate evidence-based message",
    copy: "Copy message",
    copied: "Copied",
    transactionPlan: "Generate transaction plan",
    official: "Official page",
    hardGates: "Hard gates before payment",
    tasks: "Complete in order",
    compareTitle: "Watchlist comparison",
    planningExposure: "Unresolved repair planning exposure",
    importHint: "Paste a listing URL or enter details. The browser extension can also preview and confirm-import the current page.",
    localMode: "Demo data",
    apiMode: "Service connected",
    localApiMode: "Saved locally",
    cloudApiMode: "Encrypted cloud connected",
    offlineMode: "Service disconnected",
    loading: "Opening your buyer workspace…",
    empty: "No cases yet. Create one, then import a listing, report, or OBD scan.",
    retry: "Reconnect",
    refresh: "Refresh",
    amountUnavailable: "Insufficient evidence — no point estimate",
  },
} as const;

const tabs: Array<{ id: Tab; icon: LucideIcon; scope: "case" | "global" }> = [
  { id: "overview", icon: LayoutDashboard, scope: "case" },
  { id: "evidence", icon: FileStack, scope: "case" },
  { id: "inspection", icon: ClipboardCheck, scope: "case" },
  { id: "negotiate", icon: MessageSquareText, scope: "case" },
  { id: "transaction", icon: Landmark, scope: "case" },
  { id: "compare", icon: GitCompareArrows, scope: "global" },
];

const decisionCopy: Record<CaseRecord["decision"], { zh: string; en: string }> = {
  STOP: { zh: "停止交易", en: "STOP" },
  INSPECT: { zh: "继续检查", en: "INSPECT" },
  NEGOTIATE: { zh: "可以谈价", en: "NEGOTIATE" },
  BUY_CANDIDATE: { zh: "购买候选", en: "BUY CANDIDATE" },
};

const riskCopy: Record<RiskLevel, { zh: string; en: string }> = {
  unknown: { zh: "未知", en: "Unknown" },
  low: { zh: "较低", en: "Low" },
  moderate: { zh: "中等", en: "Moderate" },
  high: { zh: "较高", en: "High" },
  critical: { zh: "严重", en: "Critical" },
};

const riskAxisCopy: Record<CaseRecord["risk_axes"][number]["id"], { zh: string; en: string }> = {
  price: { zh: "价格吸引力", en: "Price attractiveness" },
  mechanical: { zh: "机械风险", en: "Mechanical risk" },
  history: { zh: "历史记录", en: "History" },
  title: { zh: "产权交易", en: "Title & transaction" },
  evidence: { zh: "证据覆盖", en: "Evidence coverage" },
};

function riskAxisNote(record: CaseRecord, axis: CaseRecord["risk_axes"][number], language: Language): string {
  if (language !== "zh-CN") return axis.note;
  const activeFindings = record.findings.filter((finding) => finding.status !== "cleared");
  switch (axis.id) {
    case "price":
      return record.valuation.market_median === undefined || record.valuation.asking_price === undefined
        ? "尚无可用的挂牌价格对比。"
        : `已将卖家要价与挂牌价格基准对比；纳入 ${record.valuation.sample_count} 条可比车源。`;
    case "mechanical":
      return activeFindings.some((finding) => ["mechanical", "inspection"].includes(finding.category))
        ? "基于当前已记录发现；未检查系统仍保持未知。"
        : "尚未解读机械检查或独立 PPI 证据。";
    case "history":
      return activeFindings.some((finding) => finding.category === "history")
        ? "基于已导入的车辆历史证据。"
        : "尚无已确认的车辆历史结论。";
    case "title":
      return activeFindings.some((finding) => ["title", "seller"].includes(finding.category))
        ? "基于当前产权与交易发现。"
        : "Title、卖家身份和 lien 状态尚未核验。";
    case "evidence":
      return `${Math.round(record.coverage_percent)}% 的确定性证据已覆盖；未知项目不会被当作通过。`;
  }
}

const decisionDescription: Record<CaseRecord["decision"], { zh: string; en: string }> = {
  STOP: {
    zh: "存在尚未解决的付款前硬闸门。现在不要付款、签署文件或把车开走。",
    en: "A pre-payment hard gate is unresolved. Do not pay, sign, or drive the vehicle away yet.",
  },
  INSPECT: {
    zh: "信息还不足以安全购买。完成下面的关键检查后再决定。",
    en: "There is not enough verified information to buy safely. Complete the key checks below first.",
  },
  NEGOTIATE: {
    zh: "可以进入有条件谈价，但最终报价仍应以材料核对和独立检查为前提。",
    en: "You can negotiate conditionally, but the final offer should still depend on document review and an independent inspection.",
  },
  BUY_CANDIDATE: {
    zh: "这辆车可作为购买候选。成交前仍须逐项完成付款、保险和过户硬闸门。",
    en: "This vehicle is a buy candidate. Complete every payment, insurance, and title-transfer gate before closing.",
  },
};

const statusIcon: Record<CaseRecord["decision"], LucideIcon> = {
  STOP: XCircle,
  INSPECT: SearchCheck,
  NEGOTIATE: MessageSquareText,
  BUY_CANDIDATE: ShieldCheck,
};

function money(value?: number) {
  return value === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function mileage(value?: number) {
  return value === undefined ? "—" : `${value.toLocaleString("en-US")} mi`;
}

function statusLabel(language: Language, status: CheckStatus) {
  const labels = {
    unknown: { "zh-CN": "未检查", en: "Unknown" },
    pass: { "zh-CN": "通过", en: "Pass" },
    warn: { "zh-CN": "复查", en: "Review" },
    fail: { "zh-CN": "失败", en: "Fail" },
  };
  return labels[status][language];
}

function localizedDualLabel(value: string, language: Language) {
  const parts = value.split(/\s+\/\s+/);
  if (parts.length < 2) return value;
  return language === "zh-CN" ? parts[0] : parts.slice(1).join(" / ");
}

function useModalEscape(onClose: () => void, disabled = false) {
  const disabledRef = useRef(disabled);
  useEffect(() => {
    disabledRef.current = disabled;
  }, [disabled]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
    document.body.style.overflow = "hidden";
    const focusableSelector = [
      "button:not([disabled])",
      "[href]",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");
    const frame = window.requestAnimationFrame(() => {
      const dialog = document.querySelector<HTMLElement>("[role='dialog'][aria-modal='true']");
      const firstControl = dialog?.querySelector<HTMLElement>("[autofocus]") || dialog?.querySelector<HTMLElement>(focusableSelector);
      firstControl?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      const dialog = document.querySelector<HTMLElement>("[role='dialog'][aria-modal='true']");
      if (event.key === "Escape" && !disabledRef.current) {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
        .filter((control) => control.getAttribute("aria-hidden") !== "true" && control.tabIndex !== -1);
      if (!controls.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [onClose]);
}

function workflowAction(record: CaseRecord, language: Language): { label: string; tab?: Tab; import?: true } {
  if (record.status === "DISCOVERED" || record.status === "NEEDS_DATA") {
    return { label: language === "zh-CN" ? "添加关键材料" : "Add key documents", import: true };
  }
  if (record.status === "REMOTE_SCREENED" || record.status === "VIEW_SCHEDULED") {
    return { label: language === "zh-CN" ? "开始现场验车" : "Start inspection", tab: "inspection" };
  }
  if (record.status === "SELF_INSPECTED" || record.status === "PPI_COMPLETE" || record.status === "NEGOTIATING") {
    return { label: language === "zh-CN" ? "准备有依据的出价" : "Prepare an evidence-based offer", tab: "negotiate" };
  }
  if (record.status === "READY_TO_BUY" || record.status === "PURCHASED" || record.status === "REGISTERED") {
    return { label: language === "zh-CN" ? "检查购买与过户" : "Review purchase steps", tab: "transaction" };
  }
  return { label: language === "zh-CN" ? "查看关键证据" : "Review key evidence", tab: "evidence" };
}

export function Dashboard() {
  const [language, setLanguage] = useState<Language>("zh-CN");
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [activeCaseId, setActiveCaseId] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [dataMode, setDataMode] = useState<DataMode>("offline");
  const [deploymentMode, setDeploymentMode] = useState<DeploymentMode>("unknown");
  const [loadError, setLoadError] = useState<string>();
  const [toast, setToast] = useState<string>();
  const toolsButtonRef = useRef<HTMLButtonElement>(null);
  const t = copy[language];
  const activeCase = cases.find((item) => item.id === activeCaseId) || cases[0];
  const nextAction = activeCase ? workflowAction(activeCase, language) : undefined;
  const demoEnabled = process.env.NEXT_PUBLIC_OCDD_ENABLE_DEMO === "true";

  useEffect(() => {
    const storedLanguage = window.localStorage.getItem("ocdd-language") as Language | null;
    if (storedLanguage === "en" || storedLanguage === "zh-CN") {
      setLanguage(storedLanguage);
      document.documentElement.lang = storedLanguage;
    }
    void loadCases();
    // This is intentionally a one-time boot connection. User-driven refreshes
    // call loadCases directly and never substitute demo data in API mode.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!toolsOpen) return;
    const closeMenu = (event: KeyboardEvent | PointerEvent) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event instanceof PointerEvent && event.target instanceof Element && event.target.closest(".action-menu-wrap")) return;
      setToolsOpen(false);
    };
    window.addEventListener("keydown", closeMenu);
    window.addEventListener("pointerdown", closeMenu);
    return () => {
      window.removeEventListener("keydown", closeMenu);
      window.removeEventListener("pointerdown", closeMenu);
    };
  }, [toolsOpen]);

  async function loadCases() {
    setLoadState("loading");
    setLoadError(undefined);
    try {
      const health = await api.health();
      setDeploymentMode(health.deploymentMode === "cloud" ? "cloud" : health.deploymentMode === "local" ? "local" : "unknown");
      const loaded = await api.listCases();
      setCases(loaded);
      setActiveCaseId((current) => loaded.some((item) => item.id === current) ? current : loaded[0]?.id || "");
      setDataMode("api");
      setLoadState("ready");
    } catch (error) {
      if (isApiError(error) && error.status === 403) {
        const known = knownCaseAccesses();
        const recovered = await Promise.all(known.map(async ({ caseId, accessToken }) => {
          try { return await api.getCase(caseId, { accessToken }); }
          catch (reason) {
            if (isApiError(reason) && reason.status === 404) forgetCaseAccess(caseId);
            return undefined;
          }
        }));
        const loaded = recovered.filter((item): item is CaseRecord => Boolean(item));
        setCases(loaded);
        setActiveCaseId((current) => loaded.some((item) => item.id === current) ? current : loaded[0]?.id || "");
        setDataMode("api");
        setLoadState("ready");
        return;
      }
      if (demoEnabled && !isApiError(error)) {
        const demos = explicitDemoCases(demoCases);
        setCases(demos);
        setActiveCaseId(demos[0]?.id || "");
        setDataMode("demo");
        setDeploymentMode("unknown");
        setLoadState("ready");
        setLoadError(undefined);
        return;
      }
      setCases([]);
      setActiveCaseId("");
      if (isApiConnectionFailure(error)) setDeploymentMode("unknown");
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      setLoadState("error");
      setLoadError(apiErrorMessage(error, language));
    }
  }

  function updateLanguage(value: Language) {
    setLanguage(value);
    document.documentElement.lang = value;
    window.localStorage.setItem("ocdd-language", value);
  }

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(undefined), 2800);
  }

  function patchActiveCase(updater: (item: CaseRecord) => CaseRecord) {
    if (!activeCase) return;
    setCases((items) => items.map((item) => (item.id === activeCase.id ? updater(item) : item)));
  }

  function replaceCase(record: CaseRecord) {
    setCases((items) => items.map((item) => item.id === record.id ? record : item));
  }

  function handleCaseDeleted(caseId: string) {
    forgetCaseAccess(caseId);
    const remaining = cases.filter((item) => item.id !== caseId);
    setCases(remaining);
    if (activeCaseId === caseId || activeCase?.id === caseId) {
      setActiveCaseId(remaining[0]?.id || "");
      setActiveTab("overview");
    }
    setArchiveOpen(false);
    notify(language === "zh-CN" ? "案件及其已存储附件已删除" : "Case and its stored artifacts deleted");
  }

  async function refreshActiveCase(silent = false) {
    if (!activeCase || dataMode === "demo") return;
    try {
      const refreshed = await api.getCase(activeCase.id, caseAccessFor(activeCase.id));
      replaceCase(refreshed);
      setDataMode("api");
      if (!silent) notify(language === "zh-CN" ? "案件已刷新" : "Case refreshed");
    } catch (error) {
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      if (!silent) notify(apiErrorMessage(error, language));
      throw error;
    }
  }

  async function selectCase(caseId: string) {
    setActiveCaseId(caseId);
    if (dataMode === "demo") return;
    setBusy(true);
    try {
      const refreshed = await api.getCase(caseId, caseAccessFor(caseId));
      replaceCase(refreshed);
      setDataMode("api");
    } catch (error) {
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      notify(apiErrorMessage(error, language));
    } finally {
      setBusy(false);
    }
  }

  async function handleAnalyze() {
    if (!activeCase) return;
    if (dataMode === "demo") {
      notify(language === "zh-CN" ? "演示模式不写入 API" : "Demo mode does not write to the API");
      return;
    }
    setBusy(true);
    try {
      await api.analyze(activeCase.id, {}, caseAccessFor(activeCase.id));
      const refreshed = await api.getCase(activeCase.id, caseAccessFor(activeCase.id));
      replaceCase(refreshed);
      setDataMode("api");
      notify(language === "zh-CN" ? "分析已更新" : "Analysis updated");
    } catch (error) {
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      notify(apiErrorMessage(error, language));
    } finally {
      setBusy(false);
    }
  }

  async function handlePdf() {
    if (!activeCase) return;
    if (dataMode === "demo") {
      window.print();
      return;
    }
    setPdfBusy(true);
    try {
      const blob = await api.reportPdf(activeCase.id, language, caseAccessFor(activeCase.id));
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${activeCase.id}-report.pdf`;
      anchor.click();
      URL.revokeObjectURL(url);
      setDataMode("api");
    } catch (error) {
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      notify(apiErrorMessage(error, language, language === "zh-CN" ? "报告生成失败" : "Report generation failed"));
    } finally {
      setPdfBusy(false);
    }
  }

  function handlePrimaryAction() {
    if (!nextAction) return;
    if (nextAction.import) setImportOpen(true);
    if (nextAction.tab) setActiveTab(nextAction.tab);
  }

  const serviceModeLabel = dataMode === "api"
    ? deploymentMode === "local" ? t.localApiMode : deploymentMode === "cloud" ? t.cloudApiMode : t.apiMode
    : dataMode === "demo" ? t.localMode : t.offlineMode;
  const privacyStatus = dataMode === "demo"
    ? { title: language === "zh-CN" ? "演示模式" : "Demo mode", detail: language === "zh-CN" ? "演示数据不会写入真实案件。" : "Demo data is never written to a real case." }
    : deploymentMode === "local"
      ? { title: language === "zh-CN" ? "本地隐私" : "Local private storage", detail: language === "zh-CN" ? "敏感原件存放在本机加密目录。" : "Sensitive originals stay in the encrypted local store." }
      : deploymentMode === "cloud"
        ? { title: language === "zh-CN" ? "云端保留策略" : "Cloud retention", detail: language === "zh-CN" ? "上传原件会在云存储中加密暂存，并按部署方配置的保留策略处理。" : "Uploaded originals are encrypted at rest in cloud storage and handled under the deployment's retention policy." }
        : { title: language === "zh-CN" ? "存储模式未确认" : "Storage mode unconfirmed", detail: language === "zh-CN" ? "连接恢复并确认部署模式前，不要导入敏感材料。" : "Do not import sensitive material until the connection and storage mode are confirmed." };

  return (
    <div className="app-shell">
      <ServiceWorkerRegister />
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><CarFront size={22} strokeWidth={1.9} /></div>
          <div><strong>OpenCar</strong><span>{language === "zh-CN" ? "二手车尽调" : "Due Diligence"}</span></div>
        </div>

        <div className="workspace-label"><span>{language === "zh-CN" ? "当前车辆" : "Current vehicle"}</span><small className={`service-state ${dataMode}`}>{serviceModeLabel}</small></div>
        <nav className="side-nav" aria-label="Primary navigation">
          {tabs.filter((item) => item.scope === "case").map((item) => {
            const Icon = item.icon;
            return (
            <button
              key={item.id}
              className={activeTab === item.id ? "active" : ""}
              aria-current={activeTab === item.id ? "page" : undefined}
              onClick={() => setActiveTab(item.id)}
            >
              <Icon aria-hidden="true" size={18} strokeWidth={1.8} />{t[item.id]}
            </button>
          );})}
          <div className="nav-divider" />
          {tabs.filter((item) => item.scope === "global").map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={activeTab === item.id ? "active" : ""} aria-current={activeTab === item.id ? "page" : undefined} onClick={() => setActiveTab(item.id)}><Icon aria-hidden="true" size={18} strokeWidth={1.8} />{t[item.id]}</button>;
          })}
        </nav>

        <div className="watchlist-heading"><span>{t.watchlist}</span><button onClick={() => setNewCaseOpen(true)} aria-label={t.newCase}><Plus size={18} /></button></div>
        <div className="case-list">
          {cases.map((item) => (
            <button key={item.id} className={item.id === activeCase?.id ? "case-row active" : "case-row"} aria-label={`${item.name.replace(/^Synthetic demo · /, "")}, ${money(item.listing.asking_price)}, ${mileage(item.listing.mileage)}`} aria-current={item.id === activeCase?.id ? "true" : undefined} onClick={() => void selectCase(item.id)}>
              <span className={`case-dot ${item.decision.toLowerCase()}`} />
              <span><strong>{item.name.replace(/^Synthetic demo · /, "")}</strong><small>{money(item.listing.asking_price)} · {mileage(item.listing.mileage)}</small></span>
            </button>
          ))}
        </div>
        <div className="privacy-note"><LockKeyhole aria-hidden="true" size={20} /><p><strong>{privacyStatus.title}</strong><br />{privacyStatus.detail}</p></div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="mobile-brand" aria-hidden="true"><CarFront size={21} strokeWidth={1.9} /></div>
          <div className="breadcrumb">{activeCase?.name.replace(/^Synthetic demo · /, "") || "OpenCarDueDiligence"}<span>/</span>{t[activeTab]}</div>
          <div className="mobile-case-controls">
            <label>
              <span className="visually-hidden">{language === "zh-CN" ? "选择候选车辆案件" : "Select vehicle case"}</span>
              <select
                aria-label={language === "zh-CN" ? "选择候选车辆案件" : "Select vehicle case"}
                value={activeCase?.id || ""}
                disabled={busy || cases.length === 0}
                onChange={(event) => void selectCase(event.target.value)}
              >
                {cases.length === 0 && <option value="">{language === "zh-CN" ? "尚无车辆" : "No vehicles yet"}</option>}
                {cases.map((item, index) => <option key={item.id} value={item.id}>{mobileCaseLabel(item.vehicle, index, language)}</option>)}
              </select>
            </label>
            <button className="mobile-new-case" type="button" onClick={() => setNewCaseOpen(true)} aria-label={t.newCase}><Plus aria-hidden="true" size={17} />{t.newCase}</button>
          </div>
          <div className="top-actions">
            <div className="language-toggle" role="group" aria-label="Language">
              <button className={language === "zh-CN" ? "active" : ""} aria-pressed={language === "zh-CN"} onClick={() => updateLanguage("zh-CN")}>中文</button>
              <button className={language === "en" ? "active" : ""} aria-pressed={language === "en"} onClick={() => updateLanguage("en")}>EN</button>
            </div>
            <div className="action-menu-wrap">
              <button ref={toolsButtonRef} className="icon-button" type="button" aria-label={language === "zh-CN" ? "更多案件操作" : "More case actions"} aria-haspopup="menu" aria-expanded={toolsOpen} onClick={() => setToolsOpen((value) => !value)}><MoreHorizontal size={20} /></button>
              {toolsOpen && <div className="action-menu" role="menu">
                <button role="menuitem" onClick={() => { toolsButtonRef.current?.focus(); setArchiveOpen(true); setToolsOpen(false); }}><HardDrive size={17} />{language === "zh-CN" ? "案件文件" : "Case file"}</button>
                {activeCase && <button role="menuitem" disabled={busy || dataMode === "demo"} onClick={() => { void refreshActiveCase(); setToolsOpen(false); }}><RefreshCw size={17} />{t.refresh}</button>}
                {activeCase && <button role="menuitem" disabled={pdfBusy} onClick={() => { void handlePdf(); setToolsOpen(false); }}><FileDown size={17} />{pdfBusy ? (language === "zh-CN" ? "正在生成…" : "Generating…") : language === "zh-CN" ? "导出 PDF 报告" : "Export PDF report"}</button>}
                {activeCase && <button role="menuitem" disabled={busy} onClick={() => { void handleAnalyze(); setToolsOpen(false); }}><RefreshCw size={17} />{busy ? (language === "zh-CN" ? "正在分析…" : "Analyzing…") : t.analyze}</button>}
              </div>}
            </div>
            {activeCase && <button className="button ghost import-button" aria-label={language === "zh-CN" ? "添加车源" : "Add listing"} onClick={() => setImportOpen(true)}><Upload aria-hidden="true" size={17} /><span className="button-label">{language === "zh-CN" ? "添加车源" : "Add listing"}</span></button>}
            {activeCase && nextAction && <button className="button primary next-action" onClick={handlePrimaryAction}><span className="button-label">{nextAction.label}</span><span className="mobile-action-label">{language === "zh-CN" ? "继续" : "Continue"}</span></button>}
          </div>
        </header>

        <div className="content">
          {loadState === "loading" && <WorkspaceState title={t.loading} loading />}
          {loadState === "error" && <WorkspaceState title={language === "zh-CN" ? "暂时无法连接服务" : "The service is temporarily unavailable"} detail={loadError || (language === "zh-CN" ? "你的案件没有丢失。请确认服务已启动后重试。" : "Your cases have not been lost. Confirm the service is running, then retry.")} action={t.retry} onAction={() => void loadCases()} />}
          {loadState === "ready" && !activeCase && <EmptyWorkspace language={language} privacyDetail={privacyStatus.detail} onNewCase={() => setNewCaseOpen(true)} onImport={() => setArchiveOpen(true)} />}
          {loadState === "ready" && activeCase && <>
            {activeTab !== "compare" && <CaseHero record={activeCase} language={language} t={t} />}
            {activeTab === "overview" && <Overview key={activeCase.id} record={activeCase} language={language} t={t} onGoEvidence={() => setActiveTab("evidence")} onGoNegotiate={() => setActiveTab("negotiate")} onRefresh={() => void refreshActiveCase(true)} isDemo={dataMode === "demo"} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} />}
            {activeTab === "evidence" && <EvidenceView key={activeCase.id} record={activeCase} language={language} t={t} onRefresh={() => void refreshActiveCase(true)} isDemo={dataMode === "demo"} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} />}
            {activeTab === "inspection" && <InspectionView key={activeCase.id} record={activeCase} language={language} t={t} patchCase={patchActiveCase} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} onRefresh={() => void refreshActiveCase(true)} />}
            {activeTab === "negotiate" && <NegotiationView key={activeCase.id} record={activeCase} language={language} t={t} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
            {activeTab === "transaction" && <TransactionView key={activeCase.id} record={activeCase} language={language} t={t} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
            {activeTab === "compare" && <CompareView cases={cases} language={language} t={t} isDemo={dataMode === "demo"} notify={notify} />}
          </>}
        </div>
      </main>

      {importOpen && activeCase && <ImportModal record={activeCase} language={language} onClose={() => setImportOpen(false)} patchCase={patchActiveCase} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} onRefresh={() => void refreshActiveCase(true)} />}
      {archiveOpen && <CaseArchiveModal activeCase={activeCase} dataMode={dataMode} deploymentMode={deploymentMode} language={language} onClose={() => setArchiveOpen(false)} onDeleted={handleCaseDeleted} onImported={(record) => { setCases((items) => [record, ...items.filter((item) => item.id !== record.id)]); setActiveCaseId(record.id); setActiveTab("overview"); setDataMode("api"); setLoadState("ready"); setArchiveOpen(false); notify(language === "zh-CN" ? "加密案件已导入" : "Encrypted case imported"); }} />}
      {newCaseOpen && <NewCaseModal language={language} onClose={() => setNewCaseOpen(false)} onCreate={(record) => { setCases((items) => [...items, record]); setActiveCaseId(record.id); setNewCaseOpen(false); setLoadState("ready"); }} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function WorkspaceState({ title, detail, action, onAction, loading = false }: { title: string; detail?: string; action?: string; onAction?: () => void; loading?: boolean }) {
  if (loading) {
    return <section className="workspace-loading" aria-busy="true" aria-live="polite"><div className="skeleton skeleton-title" /><div className="skeleton skeleton-summary" /><div className="skeleton-grid"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div><span className="visually-hidden">{title}</span></section>;
  }
  return <section className="card workspace-state"><div><CarFront aria-hidden="true" size={30} strokeWidth={1.6} /><h2>{title}</h2>{detail && <p>{detail}</p>}{action && onAction && <button className="button primary" onClick={onAction}>{action}</button>}</div></section>;
}

function EmptyWorkspace({ language, privacyDetail, onNewCase, onImport }: { language: Language; privacyDetail: string; onNewCase: () => void; onImport: () => void }) {
  const zh = language === "zh-CN";
  return <section className="empty-workspace">
    <div className="empty-workspace-intro">
      <span className="empty-workspace-icon"><CarFront aria-hidden="true" size={26} strokeWidth={1.7} /></span>
      <h1>{zh ? "从一辆候选车开始" : "Start with one candidate vehicle"}</h1>
      <p>{zh ? "建立案件后，材料、风险、验车、谈价和过户步骤都会保存在同一条可追溯记录中。" : "Keep documents, risks, inspection, negotiation, and purchase steps in one traceable record."}</p>
      <div className="empty-workspace-actions">
        <button className="button primary" onClick={onNewCase}><Plus aria-hidden="true" size={17} />{zh ? "新建车辆案件" : "Create vehicle case"}</button>
        <button className="button ghost" onClick={onImport}><HardDrive aria-hidden="true" size={17} />{zh ? "导入 .ocdd 案件" : "Import .ocdd case"}</button>
      </div>
    </div>
    <ol className="onboarding-steps">
      <li><span>1</span><div><strong>{zh ? "添加车辆" : "Add the vehicle"}</strong><p>{zh ? "先录入 VIN，或年款、品牌和车型。" : "Start with a VIN or year, make, and model."}</p></div></li>
      <li><span>2</span><div><strong>{zh ? "补充可核实材料" : "Add verifiable evidence"}</strong><p>{zh ? "导入车源、历史报告、Title、OBD 或 PPI。" : "Import the listing, history report, title, OBD, or PPI."}</p></div></li>
      <li><span>3</span><div><strong>{zh ? "获得明确下一步" : "Get the next safe step"}</strong><p>{zh ? "系统区分未知和已确认事实，再给出检查或谈价建议。" : "Unknowns stay separate from verified facts before inspection or offer guidance."}</p></div></li>
    </ol>
    <p className="empty-workspace-privacy"><LockKeyhole aria-hidden="true" size={16} />{privacyDetail} {zh ? "未检查项目始终保持未知。" : "Unchecked items always remain unknown."}</p>
  </section>;
}

function CaseHero({ record, language, t }: { record: CaseRecord; language: Language; t: typeof copy[Language] }) {
  const spec = [record.vehicle.generation, record.vehicle.engine, record.vehicle.transmission, record.vehicle.drivetrain].filter(Boolean).join(" · ");
  const updated = new Intl.DateTimeFormat(language === "zh-CN" ? "zh-CN" : "en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(record.updated_at));
  const exposure = record.unresolved_planning_exposure;
  return (
    <section className="case-hero">
      <div className="case-identity">
        <h1>{record.name.replace(/^Synthetic demo · /, "")}</h1>
        <p>{spec || (language === "zh-CN" ? "精确机械配置尚未确认" : "Exact mechanical configuration not confirmed")}</p>
        <span className="updated-at">{record.listing.location ? `${record.listing.location} · ` : ""}{t.updated} {updated}</span>
        {(record.findings.length > 0 || record.evidence.length > 0) && <span className="source-language-note">{language === "zh-CN" ? "案件结论与证据正文保留来源原文，不自动翻译；部分系统结论可能显示英文。" : "Findings and evidence remain in their source language and are not machine-translated."}</span>}
      </div>
      <div className="case-summary" aria-label={language === "zh-CN" ? "车辆摘要" : "Vehicle summary"}>
        <div><span>{t.asking}</span><strong>{money(record.listing.asking_price)}</strong></div>
        <div><span>{language === "zh-CN" ? "里程" : "Mileage"}</span><strong>{mileage(record.listing.mileage)}</strong></div>
        <div><span>{t.coverage}</span><strong>{Math.round(record.coverage_percent)}%</strong></div>
        <div><span>{language === "zh-CN" ? "未决维修暴露" : "Unresolved exposure"}</span><strong>{exposure ? `${money(exposure[0])}–${money(exposure[1])}` : "—"}</strong></div>
      </div>
    </section>
  );
}

function Overview({ record, language, t, onGoEvidence, onGoNegotiate, onRefresh, isDemo, notify, setConnected }: { record: CaseRecord; language: Language; t: typeof copy[Language]; onGoEvidence: () => void; onGoNegotiate: () => void; onRefresh: () => void; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void }) {
  const DecisionIcon = statusIcon[record.decision];
  const priorityFindings = record.findings
    .filter((finding) => finding.status !== "cleared")
    .sort((a, b) => ({ critical: 0, high: 1, moderate: 2, unknown: 3, low: 4 }[a.level] - ({ critical: 0, high: 1, moderate: 2, unknown: 3, low: 4 }[b.level])))
    .slice(0, 3);
  return (
    <div className="dashboard-grid">
      <section className={`decision-brief span-2 ${record.decision.toLowerCase()}`}>
        <div className="decision-summary">
          <span className="decision-icon"><DecisionIcon aria-hidden="true" size={24} strokeWidth={1.8} /></span>
          <div>
            <span className="section-kicker">{t.decision}</span>
            <h2>{language === "zh-CN" ? decisionCopy[record.decision].zh : decisionCopy[record.decision].en}</h2>
            <p>{language === "zh-CN" ? decisionDescription[record.decision].zh : decisionDescription[record.decision].en}</p>
          </div>
        </div>
        <div className="decision-reasons">
          <h3>{language === "zh-CN" ? "做决定前还要确认" : "What still needs to be confirmed"}</h3>
          {priorityFindings.length ? <ol>{priorityFindings.map((finding) => <li key={finding.id}><span>{finding.title}</span><small>{finding.next_check || finding.summary}</small></li>)}</ol> : <p>{language === "zh-CN" ? "尚无足够材料形成具体结论。先添加车源、title 和检查记录。" : "There is not enough evidence for specific findings yet. Add the listing, title, and inspection records."}</p>}
        </div>
        <div className="decision-actions"><button className="button primary" onClick={onGoEvidence}>{language === "zh-CN" ? "检查关键材料" : "Review key documents"}</button></div>
      </section>

      <section className="card span-2">
        <div className="card-heading"><div><h2>{t.riskAxes}</h2><p>{language === "zh-CN" ? "各维度独立判断，不合并成容易误导的总分。" : "Each dimension is assessed separately; no misleading composite score."}</p></div></div>
        <div className="risk-list">
          {record.risk_axes.map((axis) => (
            <article className={`risk-row ${axis.level}`} key={axis.id}>
              <span className="risk-indicator" aria-hidden="true" />
              <div><strong>{language === "zh-CN" ? riskAxisCopy[axis.id].zh : riskAxisCopy[axis.id].en}</strong><p>{riskAxisNote(record, axis, language)}</p></div>
              <span className={`status-badge ${axis.level}`}>{language === "zh-CN" ? riskCopy[axis.level].zh : riskCopy[axis.level].en}</span>
            </article>
          ))}
        </div>
      </section>

      <ValuationCard record={record} language={language} t={t} onGoNegotiate={onGoNegotiate} />

      <section className="card findings-card">
        <div className="card-heading"><div><h2>{t.findings}</h2></div><button className="text-button" onClick={onGoEvidence}>{t.viewEvidence} →</button></div>
        <div className="finding-list">
          {record.findings.length === 0 && <div className="empty-state">{language === "zh-CN" ? "尚无结论。先导入历史报告和检查结果。" : "No findings yet. Import history and inspection evidence first."}</div>}
          {record.findings.map((finding) => (
            <article key={finding.id}>
              <span className={`severity ${finding.status === "cleared" ? "cleared" : finding.level}`} />
              <div><div className="finding-title-row"><h3>{finding.title}</h3>{finding.status === "cleared" && <span className="status-badge low">{language === "zh-CN" ? "已排除" : "Cleared"}</span>}</div><p>{finding.summary}</p><small>{language === "zh-CN" ? "下一步" : "Next"}：{finding.next_check || "—"}</small></div>
              <div className="exposure">{finding.status !== "cleared" && finding.exposure_high ? `${money(finding.exposure_low)}–${money(finding.exposure_high)}` : "—"}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="card span-2 obd-card">
        <div className="card-heading"><div><h2>{t.obd}</h2><p>{language === "zh-CN" ? "扫描结果只代表本次已读取的模块。未扫描的模块保持未知。" : "Results apply only to modules read in this scan. Unscanned modules remain unknown."}</p></div><span className={`readiness ${record.diagnostics.readiness}`}>{record.diagnostics.readiness === "ready" ? language === "zh-CN" ? "排放监测已就绪" : "Readiness complete" : record.diagnostics.readiness === "not_ready" ? language === "zh-CN" ? "存在未就绪项" : "Not ready" : t.unknown}</span></div>
        <div className="obd-layout">
          <div><h3>{language === "zh-CN" ? "本次扫描覆盖" : "Covered by this scan"}</h3>{record.diagnostics.coverage.length ? record.diagnostics.coverage.map((item) => <span className="token pass" key={item}>✓ {item}</span>) : <span className="token unknown">— {t.unknown}</span>}<h3 className="token-heading">DTC</h3>{record.diagnostics.codes.length ? record.diagnostics.codes.map((item) => <span className="token warn" key={item}>! {item}</span>) : hasGenericPowertrainCoverage(record.diagnostics.coverage) ? <span className="token unknown">— {language === "zh-CN" ? "本次普通动力系统扫描未报告 DTC" : "No generic powertrain DTC reported in this scan"}</span> : <span className="token unknown">— {language === "zh-CN" ? "尚无普通动力系统 DTC 扫描数据" : "No generic powertrain DTC scan data"}</span>}</div>
          <div><h3>{language === "zh-CN" ? "没有覆盖" : "Not covered"}</h3>{record.diagnostics.not_covered.map((item) => <span className="token unknown" key={item}>? {item}</span>)}</div>
          <div className="obd-warning"><AlertTriangle aria-hidden="true" size={20} /><div><strong>{language === "zh-CN" ? "重要限制" : "Important limitation"}</strong><p>{t.noCodeWarning}</p></div></div>
        </div>
        <ManualObdForm record={record} language={language} isDemo={isDemo} notify={notify} setConnected={setConnected} onRefresh={onRefresh} />
      </section>
    </div>
  );
}

function ManualObdForm({ record, language, isDemo, notify, setConnected, onRefresh }: { record: CaseRecord; language: Language; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void; onRefresh: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ scanner: "manual entry", codes: "", readiness: "UNKNOWN", mil: "unknown", notes: "" });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isDemo) {
      notify(language === "zh-CN" ? "演示模式不会保存扫描" : "Demo mode does not save scans");
      return;
    }
    const codes = form.codes.split(/[\s,;]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
    const invalid = codes.find((code) => !/^[PBCU][0-9A-F]{4}$/.test(code));
    if (invalid) {
      notify(language === "zh-CN" ? `报码格式不正确：${invalid}` : `Invalid DTC format: ${invalid}`);
      return;
    }
    setBusy(true);
    try {
      await api.addObdScan(record.id, {
        scannerName: form.scanner,
        milOn: form.mil === "unknown" ? null : form.mil === "on",
        dtcs: codes.map((code) => ({ code, status: "pending" })),
        readiness: [{ name: "generic_readiness", status: form.readiness }],
        moduleCoverage: { powertrain: "SCANNED", abs: "NOT_SCANNED", srs: "NOT_SCANNED", body: "NOT_SCANNED" },
        limitations: ["Generic emissions scan only; ABS, SRS, body, and OEM modules were not scanned."],
        notes: form.notes || undefined,
        evidenceLabel: "Manual generic OBD scan",
      }, caseAccessFor(record.id));
      setConnected(true);
      onRefresh();
      setOpen(false);
      notify(language === "zh-CN" ? "OBD 扫描已保存；未覆盖模块仍为未知" : "OBD scan saved; unscanned modules remain unknown");
    } catch (error) {
      setConnected(!isApiConnectionFailure(error));
      notify(apiErrorMessage(error, language, language === "zh-CN" ? "OBD 扫描保存失败" : "OBD upload failed"));
    } finally {
      setBusy(false);
    }
  }

  return <div className="inline-tool">
    <button className="button ghost" onClick={() => setOpen((value) => !value)}><Gauge aria-hidden="true" size={17} />{language === "zh-CN" ? open ? "收起 OBD 录入" : "手工录入普通 OBD" : open ? "Close OBD entry" : "Enter generic OBD scan"}</button>
    {open && <form className="inline-form" onSubmit={submit}>
      <div className="form-pair"><label>{language === "zh-CN" ? "扫描器" : "Scanner"}<input value={form.scanner} onChange={(event) => setForm({ ...form, scanner: event.target.value })} /></label><label>{language === "zh-CN" ? "故障码（DTC）" : "Diagnostic trouble codes"}<input value={form.codes} onChange={(event) => setForm({ ...form, codes: event.target.value })} placeholder="P0301, P0420" /></label></div>
      <div className="form-pair"><label>{language === "zh-CN" ? "排放监测就绪状态" : "Emissions readiness"}<select value={form.readiness} onChange={(event) => setForm({ ...form, readiness: event.target.value })}><option value="UNKNOWN">{language === "zh-CN" ? "未知" : "Unknown"}</option><option value="READY">{language === "zh-CN" ? "已声明的监测项全部就绪" : "All declared monitors ready"}</option><option value="NOT_READY">{language === "zh-CN" ? "一个或多个项目未就绪" : "One or more not ready"}</option></select></label><label>{language === "zh-CN" ? "发动机故障灯" : "Malfunction indicator lamp"}<select value={form.mil} onChange={(event) => setForm({ ...form, mil: event.target.value })}><option value="unknown">{language === "zh-CN" ? "未知" : "Unknown"}</option><option value="off">{language === "zh-CN" ? "熄灭" : "Off"}</option><option value="on">{language === "zh-CN" ? "点亮" : "On"}</option></select></label></div>
      <label>{language === "zh-CN" ? "备注" : "Notes"}<textarea rows={2} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
      <button className="button primary" disabled={busy || isDemo}>{busy ? (language === "zh-CN" ? "正在保存…" : "Saving…") : language === "zh-CN" ? "保存只读扫描" : "Save read-only scan"}</button>
    </form>}
  </div>;
}

function ValuationCard({ record, language, t, onGoNegotiate }: { record: CaseRecord; language: Language; t: typeof copy[Language]; onGoNegotiate: () => void }) {
  const value = record.valuation;
  const hasMarket = value.market_median !== undefined;
  const hasOfferBoundary = value.opening !== undefined && value.target !== undefined && value.ceiling !== undefined;
  const confidenceLabel = {
    low: language === "zh-CN" ? "低置信度" : "Low confidence",
    medium: language === "zh-CN" ? "中等置信度" : "Medium confidence",
    high: language === "zh-CN" ? "高置信度" : "High confidence",
  }[value.confidence];
  const marketLabel = value.market_label === "sold-price range"
    ? language === "zh-CN" ? "成交价参考区间" : "Sold-price reference range"
    : value.market_label === "reference-value range"
      ? language === "zh-CN" ? "外部估值参考区间" : "External reference-value range"
      : language === "zh-CN" ? "挂牌价参考区间" : "Asking-price reference range";
  return (
    <section className="card valuation-card">
      <div className="card-heading"><div><h2>{t.valuation}</h2><p>{language === "zh-CN" ? "挂牌数据与实际成交价分开呈现。" : "Asking-price data is kept separate from completed sales."}</p></div><span className={`confidence ${value.confidence}`}>{confidenceLabel}</span></div>
      <div className="valuation-main"><span>{t.asking}</span><strong>{money(value.asking_price)}</strong></div>
      {hasMarket ? (
        <>
          <div className="market-summary"><div><span>{marketLabel}</span><strong>{money(value.q1)}–{money(value.q3)}</strong></div><div><span>{language === "zh-CN" ? "加权中位数" : "Weighted median"}</span><strong>{money(value.market_median)}</strong></div><div><span>{language === "zh-CN" ? "可比样本" : "Comparable sample"}</span><strong>{value.sample_count} {language === "zh-CN" ? "辆" : "vehicles"}</strong></div></div>
          {hasOfferBoundary
            ? <div className="offer-grid"><div><span>{t.opening}</span><strong>{money(value.opening)}</strong></div><div><span>{t.target}</span><strong>{money(value.target)}</strong></div><div className="ceiling"><span>{t.ceiling}</span><strong>{money(value.ceiling)}</strong></div></div>
            : <div className="boundary-prompt"><p>{language === "zh-CN" ? "市场区间不等于你的报价边界。补充预算和已确认维修后再单独计算。" : "The market range is not your offer boundary. Add your budget and confirmed repairs before calculating it."}</p><button className="text-button" onClick={onGoNegotiate}>{language === "zh-CN" ? "前往谈价页计算" : "Calculate in negotiation"} →</button></div>}
        </>
      ) : <div className="empty-state compact">{t.amountUnavailable}<small>{value.sample_count} {language === "zh-CN" ? "条可比车源" : "comparable listings"}</small></div>}
    </section>
  );
}

function EvidenceView({ record, language, t, onRefresh, isDemo, notify, setConnected }: { record: CaseRecord; language: Language; t: typeof copy[Language]; onRefresh: () => void; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void }) {
  return (
    <div className="dashboard-grid">
      <section className="card span-2">
        <div className="card-heading"><div><h2>{language === "zh-CN" ? "材料与证据账本" : "Documents and evidence ledger"}</h2><p>{language === "zh-CN" ? "每项结论都应能回到一份材料、照片、扫描或检查记录。" : "Every conclusion should trace back to a document, photo, scan, or inspection record."}</p></div><span className="source-stamp">{record.evidence.length} {language === "zh-CN" ? "项材料" : "sources"} · {Math.round(record.coverage_percent)}%</span></div>
        <div className="evidence-table" role="table">
          <div className="table-head" role="row"><span>{language === "zh-CN" ? "材料" : "Document"}</span><span>{language === "zh-CN" ? "引用位置" : "Reference"}</span><span>{language === "zh-CN" ? "核验状态" : "Status"}</span><span>{language === "zh-CN" ? "日期" : "Date"}</span></div>
          {record.evidence.map((item) => <div className="table-row" role="row" key={item.id}><div><strong>{item.label}</strong><small>{item.source}</small></div><span>{item.reference || "—"}</span><span className={`evidence-status ${item.status}`}>{item.status === "verified" ? language === "zh-CN" ? "已核验" : "Verified" : item.status === "conflict" ? language === "zh-CN" ? "有冲突" : "Conflict" : language === "zh-CN" ? "待核验" : "Unverified"}</span><span>{item.captured_at.slice(0, 10)}</span></div>)}
          {record.evidence.length === 0 && <div className="empty-state">{language === "zh-CN" ? "还没有证据。导入车源、可选的车辆历史报告或检查记录。" : "No evidence yet. Import a listing, optional vehicle-history report, or inspection."}</div>}
        </div>
      </section>
      <ArtifactUploader record={record} language={language} onRefresh={onRefresh} isDemo={isDemo} notify={notify} setConnected={setConnected} />
      <section className="card span-2">
        <div className="card-heading"><div><h2>{language === "zh-CN" ? "结论依据" : "Finding traceability"}</h2><p>{language === "zh-CN" ? "“未知”表示还没有检查，不代表正常。" : "Unknown means not checked; it does not mean normal."}</p></div></div>
        <div className="finding-detail-grid">
          {record.findings.map((finding) => <article key={finding.id}><div className="finding-title"><span className={`severity ${finding.level}`} /><h3>{finding.title}</h3><span className="finding-state">{finding.status === "confirmed" ? language === "zh-CN" ? "已确认" : "Confirmed" : finding.status === "possible" ? language === "zh-CN" ? "待确认" : "Possible" : finding.status === "cleared" ? language === "zh-CN" ? "已排除" : "Cleared" : t.unknown}</span></div><p>{finding.summary}</p><dl><div><dt>{language === "zh-CN" ? "关联证据" : "Evidence"}</dt><dd>{finding.evidence_ids.length ? finding.evidence_ids.join(", ") : t.unknown}</dd></div><div><dt>{language === "zh-CN" ? "下一项检查" : "Next check"}</dt><dd>{finding.next_check || "—"}</dd></div></dl></article>)}
        </div>
      </section>
    </div>
  );
}

async function fileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("File read failed"));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(file);
  });
}

function ArtifactUploader({ record, language, onRefresh, isDemo, notify, setConnected }: { record: CaseRecord; language: Language; onRefresh: () => void; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState("history_report");
  const [label, setLabel] = useState("");
  const [plainText, setPlainText] = useState("");
  const [titleOwnerName, setTitleOwnerName] = useState("");
  const [sellerLegalName, setSellerLegalName] = useState("");
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (isDemo) return;
    if (!file && !plainText.trim()) {
      notify(language === "zh-CN" ? "请选择文件或粘贴文字" : "Choose a file or paste text");
      return;
    }
    if (kind === "title" && Boolean(titleOwnerName.trim()) !== Boolean(sellerLegalName.trim())) {
      notify(language === "zh-CN" ? "请同时填写 title 车主姓名和卖家证件姓名" : "Enter both the titled owner and seller legal names");
      return;
    }
    setBusy(true);
    try {
      await api.uploadArtifact(record.id, {
        filename: file?.name || `${kind}.txt`,
        kind,
        media_type: file?.type || "text/plain",
        label: label || file?.name || kind,
        ...(kind === "title" && titleOwnerName.trim() && sellerLegalName.trim() ? {
          title_owner_name: titleOwnerName.trim(),
          seller_legal_name: sellerLegalName.trim(),
        } : {}),
        ...(file ? { content_base64: await fileAsBase64(file) } : { text: plainText }),
      }, caseAccessFor(record.id));
      setConnected(true);
      setFile(undefined);
      setPlainText("");
      setLabel("");
      setTitleOwnerName("");
      setSellerLegalName("");
      onRefresh();
      notify(language === "zh-CN" ? "材料已上传并加入证据账本" : "Artifact uploaded to the evidence ledger");
    } catch (error) {
      setConnected(!isApiConnectionFailure(error));
      notify(apiErrorMessage(error, language, language === "zh-CN" ? "材料上传失败" : "Artifact upload failed"));
    } finally {
      setBusy(false);
    }
  }

  const evidenceText = record.evidence.map((item) => `${item.kind || ""} ${item.label}`.toLowerCase()).join(" ");
  const suggested = [
    { match: /title/, zh: "原始 title 照片", en: "Original title photos" },
    { match: /ppi|inspection/, zh: "独立 PPI 报告", en: "Independent PPI report" },
    { match: /receipt|invoice|维修|发票/, zh: "近期维修发票", en: "Recent repair receipts" },
  ].filter((item) => !item.match.test(evidenceText));

  return <section className="card span-2 evidence-uploader">
    <div className="card-heading"><div><h2>{language === "zh-CN" ? "补充关键材料" : "Add key documents"}</h2><p>{language === "zh-CN" ? `已收到 ${record.evidence.length} 项材料${suggested.length ? `，建议继续补充 ${suggested.length} 类` : ""}。` : `${record.evidence.length} documents received${suggested.length ? `; ${suggested.length} categories still suggested` : ""}.`}</p></div><button className="button ghost" type="button" onClick={() => setOpen((value) => !value)}><Upload aria-hidden="true" size={17} />{open ? language === "zh-CN" ? "收起" : "Close" : language === "zh-CN" ? "添加材料" : "Add document"}</button></div>
    {!open && suggested.length > 0 && <div className="missing-evidence-list"><span>{language === "zh-CN" ? "建议下一步补充" : "Suggested next documents"}</span>{suggested.map((item) => <strong key={item.en}><FileStack aria-hidden="true" size={16} />{language === "zh-CN" ? item.zh : item.en}</strong>)}</div>}
    {open && <form className="artifact-form" onSubmit={submit}>
      <div className="form-pair"><label>{language === "zh-CN" ? "材料类型" : "Document type"}<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="history_report">{language === "zh-CN" ? "车辆历史报告（可选）" : "Vehicle-history report (optional)"}</option><option value="title">Title</option><option value="lien_release">{language === "zh-CN" ? "解除抵押证明" : "Lien release"}</option><option value="receipt">{language === "zh-CN" ? "维修发票" : "Repair receipt"}</option><option value="state_inspection">{language === "zh-CN" ? "州验车记录" : "State inspection"}</option><option value="seller_message">{language === "zh-CN" ? "卖家聊天" : "Seller message"}</option><option value="photo">{language === "zh-CN" ? "照片或截图" : "Photo or screenshot"}</option><option value="ppi">{language === "zh-CN" ? "独立购前检查（PPI）" : "Independent PPI"}</option><option value="other">{language === "zh-CN" ? "其他" : "Other"}</option></select></label><label>{language === "zh-CN" ? "材料名称" : "Document label"}<input value={label} onChange={(event) => setLabel(event.target.value)} placeholder={language === "zh-CN" ? "例如：历史报告第 1–5 页" : "e.g. history report pages 1–5"} /></label></div>
      {kind === "title" && <>
        <div className="form-pair">
          <label>{language === "zh-CN" ? "Title 上的车主姓名" : "Titled owner legal name"}<input autoComplete="off" value={titleOwnerName} onChange={(event) => setTitleOwnerName(event.target.value)} /></label>
          <label>{language === "zh-CN" ? "卖家证件姓名" : "Seller ID legal name"}<input autoComplete="off" value={sellerLegalName} onChange={(event) => setSellerLegalName(event.target.value)} /></label>
        </div>
        <small>{language === "zh-CN" ? "仅在服务器内即时做规范化精确比对；案件只保存 MATCH/MISMATCH，不保存姓名。仍须当面核对原件。" : "Compared transiently with conservative exact normalization; only MATCH/MISMATCH is retained. Verify the originals in person."}</small>
      </>}
      <label>{language === "zh-CN" ? "选择文件" : "Choose file"}<input type="file" accept="application/pdf,image/*,text/plain,application/json,text/csv" onChange={(event) => setFile(event.target.files?.[0])} /></label>
      <div className="or-divider">{language === "zh-CN" ? "或粘贴文字" : "or paste text"}</div>
      <label>{language === "zh-CN" ? "文字内容" : "Text content"}<textarea rows={4} value={plainText} onChange={(event) => setPlainText(event.target.value)} placeholder={language === "zh-CN" ? "卖家聊天、维修记录或报告摘录" : "Seller chat, maintenance record, or report excerpt"} /></label>
      <button className="button primary" disabled={busy || isDemo}>{busy ? (language === "zh-CN" ? "正在上传…" : "Uploading…") : language === "zh-CN" ? "上传材料" : "Upload document"}</button>
    </form>}
  </section>;
}

function InspectionView({ record, language, t, patchCase, notify, setConnected, isDemo, onRefresh }: { record: CaseRecord; language: Language; t: typeof copy[Language]; patchCase: (updater: (item: CaseRecord) => CaseRecord) => void; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean; onRefresh: () => void }) {
  const [activeStage, setActiveStage] = useState(record.inspections[0]?.id || "before");
  const stage = record.inspections.find((item) => item.id === activeStage) || record.inspections[0];

  function setCheckStatus(checkId: string, status: CheckStatus) {
    patchCase((item) => ({ ...item, inspections: item.inspections.map((section) => section.id !== activeStage ? section : { ...section, checks: section.checks.map((check) => check.id === checkId ? { ...check, status } : check) }) }));
  }

  function updateCheck(checkId: string, change: { note?: string; evidence_ids?: string[] }) {
    patchCase((item) => ({
      ...item,
      inspections: item.inspections.map((section) => section.id !== activeStage ? section : {
        ...section,
        checks: section.checks.map((check) => check.id === checkId ? { ...check, ...change } : check),
      }),
    }));
  }

  function updateInspector(inspector: string) {
    patchCase((item) => ({
      ...item,
      inspections: item.inspections.map((section) => section.id === "ppi" ? { ...section, inspector } : section),
    }));
  }

  async function saveStage() {
    if (isDemo) {
      notify(language === "zh-CN" ? "演示模式只在页面预览，不写入 API" : "Demo changes are preview-only and not saved");
      return;
    }
    if (stage.id === "ppi" && !stage.inspector?.trim()) {
      notify(language === "zh-CN" ? "保存 PPI 前请填写独立修理厂或技师角色（不要填写个人姓名）" : "Enter the independent shop or inspector role before saving the PPI (do not enter a person's name)");
      return;
    }
    try { await api.saveInspection(record.id, stage, caseAccessFor(record.id)); setConnected(true); onRefresh(); notify(language === "zh-CN" ? "检查已保存" : "Inspection saved"); }
    catch (error) { setConnected(!isApiConnectionFailure(error)); notify(apiErrorMessage(error, language, language === "zh-CN" ? "检查保存失败" : "Inspection save failed")); }
  }

  return (
    <section className="card inspection-shell">
      <div className="card-heading"><div><h2>{language === "zh-CN" ? "现场验车清单" : "On-site inspection checklist"}</h2><p>{language === "zh-CN" ? "未实际检查的项目保持“未检查”；只有需复查或不通过时才要求补充备注。" : "Leave anything not inspected as Not checked. Notes are requested only for Review or Fail."}</p></div><span className="source-stamp">{record.inspections.reduce((count, item) => count + item.checks.filter((check) => check.status !== "unknown").length, 0)} / {record.inspections.reduce((count, item) => count + item.checks.length, 0)} {language === "zh-CN" ? "已检查" : "checked"}</span></div>
      <div className="inspection-layout">
        <div className="stage-list">{record.inspections.map((item, index) => {
          const complete = item.checks.filter((check) => check.status !== "unknown").length;
          return <button className={item.id === activeStage ? "active" : ""} aria-current={item.id === activeStage ? "step" : undefined} key={item.id} onClick={() => setActiveStage(item.id)}><span>{index + 1}</span><div><strong>{localizedDualLabel(item.title, language)}</strong><small>{complete}/{item.checks.length} {language === "zh-CN" ? "已检查" : "checked"}</small></div></button>;
        })}</div>
        <div className="checklist">
          <h3>{localizedDualLabel(stage.title, language)}</h3>
          <p>{language === "zh-CN" ? "未实际检查的项目必须保持“未知”。可为每项添加备注并关联已上传证据。" : "Leave anything not actually checked as Unknown. Notes and uploaded evidence can be linked to each check."}</p>
          {stage.id === "ppi" && <label className="ppi-inspector-field"><span>{language === "zh-CN" ? "独立检查方（必填）" : "Independent inspector (required)"}</span><input value={stage.inspector || ""} onChange={(event) => updateInspector(event.target.value)} placeholder={language === "zh-CN" ? "例如：独立 MINI 专修店（不要填个人姓名）" : "e.g. Independent MINI specialist (no personal name)"} /></label>}
          {stage.checks.map((check) => <div className="check-row" key={check.id}>
            <div className="check-main">
              <span className="check-label">{localizedDualLabel(check.label, language)}</span>
              <label className="check-status-control"><span className="visually-hidden">{language === "zh-CN" ? "检查状态" : "Check status"}</span><select className={check.status} aria-label={`${localizedDualLabel(check.label, language)}: ${statusLabel(language, check.status)}`} value={check.status} onChange={(event) => setCheckStatus(check.id, event.target.value as CheckStatus)}><option value="unknown">{statusLabel(language, "unknown")}</option><option value="pass">{statusLabel(language, "pass")}</option><option value="warn">{statusLabel(language, "warn")}</option><option value="fail">{statusLabel(language, "fail")}</option></select></label>
            </div>
            {(check.status === "warn" || check.status === "fail" || Boolean(check.note) || Boolean(check.evidence_ids?.length)) && <div className="check-fields">
                <label><span>{language === "zh-CN" ? "备注" : "Notes"}</span><input value={check.note || ""} onChange={(event) => updateCheck(check.id, { note: event.target.value })} placeholder={language === "zh-CN" ? "仅记录实际观察" : "Record observed facts only"} /></label>
                <label><span>{language === "zh-CN" ? "证据" : "Evidence"}</span><select value={check.evidence_ids?.[0] || ""} onChange={(event) => updateCheck(check.id, { evidence_ids: event.target.value ? [event.target.value] : [] })}><option value="">{language === "zh-CN" ? "未关联" : "Not linked"}</option>{record.evidence.map((evidence) => <option key={evidence.id} value={evidence.id}>{evidence.label}</option>)}</select></label>
              </div>}
          </div>)}
          <button className="button primary save-stage" onClick={saveStage}>{t.save}</button>
        </div>
      </div>
    </section>
  );
}

function NegotiationView({ record, language, t, notify, setConnected, isDemo }: { record: CaseRecord; language: Language; t: typeof copy[Language]; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [phase, setPhase] = useState<"initial_contact" | "conditional_offer" | "post_ppi" | "walk_away">("initial_contact");
  const [budget, setBudget] = useState(record.all_in_budget ? String(record.all_in_budget) : "");
  const [mandatoryCosts, setMandatoryCosts] = useState("");
  const [sellerFloor, setSellerFloor] = useState("");
  const [result, setResult] = useState<NegotiationResponse>();
  const [draftMessage, setDraftMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [excludedFindingIds, setExcludedFindingIds] = useState<Set<string>>(() => new Set());
  const eligibleAdjustments = useMemo(() => eligibleNegotiationAdjustments(record), [record]);
  const adjustments = eligibleAdjustments.filter((item) => !item.finding_id || !excludedFindingIds.has(item.finding_id));
  const inspectionOnlyFindings = record.findings.filter((finding) => finding.status === "possible");
  const showArithmetic = shouldShowNegotiationArithmetic(phase);

  function toggleAdjustment(findingId: string) {
    setExcludedFindingIds((current) => {
      const next = new Set(current);
      if (next.has(findingId)) next.delete(findingId);
      else next.add(findingId);
      return next;
    });
    setResult(undefined);
  }

  async function generate() {
    const askingPrice = record.listing.asking_price;
    const marketBaseline = record.valuation.market_median;
    if (phase !== "initial_contact" && (askingPrice === undefined || marketBaseline === undefined)) {
      notify(language === "zh-CN" ? "先导入目标车源价格和足够的可比车，再生成价格边界。" : "Import the target asking price and enough comparable listings before generating a price boundary.");
      return;
    }
    const budgetValue = Number(budget);
    const mandatoryCostsValue = Number(mandatoryCosts);
    if (phase !== "initial_contact" && (
      !budget
      || !mandatoryCosts
      || !Number.isFinite(budgetValue)
      || budgetValue <= 0
      || !Number.isFinite(mandatoryCostsValue)
      || mandatoryCostsValue < 0
    )) {
      notify(language === "zh-CN" ? "请先确认总预算，以及税费、登记和合法运输等买家固有成本；系统不会使用隐藏默认值。" : "Confirm the all-in budget and buyer-side tax, registration, and legal-transport costs first; the system uses no hidden defaults.");
      return;
    }
    const request: NegotiationRequest = phase === "initial_contact"
      ? { phase, language, evidence_coverage: record.coverage_percent, adjustments: [] }
      : { phase, language, asking_price: askingPrice, market_baseline: marketBaseline, all_in_budget: budgetValue, evidence_coverage: record.coverage_percent, adjustments, buyer_mandatory_costs: mandatoryCostsValue, seller_floor: sellerFloor ? Number(sellerFloor) : undefined };
    setBusy(true);
    try {
      const response = isDemo ? calculateNegotiation(request) : await api.draftNegotiation(record.id, request, caseAccessFor(record.id));
      setResult(response);
      setDraftMessage(response.message);
      if (!isDemo) setConnected(true);
    }
    catch (error) { setConnected(!isApiConnectionFailure(error)); setResult(undefined); notify(negotiationErrorMessage(error, language)); }
    finally { setBusy(false); }
  }

  async function copyMessage() {
    if (!result || !draftMessage) return;
    await navigator.clipboard.writeText(draftMessage);
    notify(t.copied);
  }

  return (
    <div className="negotiation-layout">
      <section className="card negotiation-form"><div className="card-heading"><div><h2>{language === "zh-CN" ? "谈价准备" : "Offer preparation"}</h2><p>{language === "zh-CN" ? "只使用已核实材料计算边界；未知项目不会被当作确定故障扣价。" : "Only verified evidence is used in the boundary. Unknowns are never priced as confirmed faults."}</p></div></div><label>{language === "zh-CN" ? "当前谈价阶段" : "Negotiation stage"}<select value={phase} onChange={(event) => { setPhase(event.target.value as typeof phase); setResult(undefined); setDraftMessage(""); }}><option value="initial_contact">{language === "zh-CN" ? "第一次联系" : "Initial contact"}</option><option value="conditional_offer">{language === "zh-CN" ? "看车前有条件报价" : "Conditional pre-visit offer"}</option><option value="post_ppi">{language === "zh-CN" ? "PPI 后重新报价" : "Post-PPI offer"}</option><option value="walk_away">{language === "zh-CN" ? "礼貌退出或等待" : "Walk away or wait"}</option></select></label>{phase === "initial_contact" ? <div className="privacy-callout">{language === "zh-CN" ? "初次联系只生成 VIN、title、保养、当前故障和 PPI 问题；不需要估值，也不会生成报价。" : "Initial contact asks for the VIN, title, maintenance, current issues, and PPI permission. It does not need a valuation or generate an offer."}</div> : <><div className="form-pair"><label>{language === "zh-CN" ? "总预算（美元）" : "All-in budget (USD)"}<input required min="1" type="number" value={budget} onChange={(event) => setBudget(event.target.value)} /></label><label>{language === "zh-CN" ? "卖家底价（可选）" : "Seller floor (optional)"}<input min="0" type="number" value={sellerFloor} onChange={(event) => setSellerFloor(event.target.value)} /></label></div><label>{language === "zh-CN" ? "买家固有成本：税、登记、合法运输等（美元）" : "Buyer-side tax, registration, legal transport, etc. (USD)"}<input required min="0" type="number" value={mandatoryCosts} onChange={(event) => setMandatoryCosts(event.target.value)} /></label><div className="privacy-callout">{language === "zh-CN" ? "这些成本只限制你的 all-in 最高价，不会被伪装成车辆缺陷向卖家压价。请填 0 或你的实际估算，不能留空。" : "These costs constrain your all-in ceiling; they are never presented to the seller as vehicle defects. Enter 0 or your reviewed estimate—do not leave it blank."}</div><div className="deductions"><h3>{language === "zh-CN" ? "有证据的调整" : "Evidence-backed adjustments"}</h3>{eligibleAdjustments.length ? eligibleAdjustments.map((item) => <div className="negotiation-adjustment-row" key={item.finding_id || item.label}><label><input type="checkbox" checked={!item.finding_id || !excludedFindingIds.has(item.finding_id)} onChange={() => item.finding_id && toggleAdjustment(item.finding_id)} /><span>{item.label}</span></label><strong>{!item.finding_id || !excludedFindingIds.has(item.finding_id) ? `−${money(item.amount)}` : language === "zh-CN" ? "未计入" : "Excluded"}</strong></div>) : <div><span>{language === "zh-CN" ? "尚无可扣除的确认项目" : "No documented adjustments yet"}</span><strong>—</strong></div>}{inspectionOnlyFindings.length > 0 && <div className="inspection-only-note"><span>{language === "zh-CN" ? `待检查（不扣款）：${inspectionOnlyFindings.map((item) => item.title).join("；")}` : `Needs inspection (not deducted): ${inspectionOnlyFindings.map((item) => item.title).join("; ")}`}</span><strong>{language === "zh-CN" ? "待确认" : "Unconfirmed"}</strong></div>}<div><span>{language === "zh-CN" ? "证据准备金" : "Evidence reserve"}</span><strong>{Math.round(record.coverage_percent)}% {language === "zh-CN" ? "覆盖" : "coverage"}</strong></div></div></>}<button className="button primary full" onClick={generate} disabled={busy}>{busy ? language === "zh-CN" ? "正在生成…" : "Generating…" : t.generate}</button></section>
      <section className="card message-preview"><div className="card-heading"><div><h2>{language === "zh-CN" ? "卖家消息" : "Seller message"}</h2><p>{language === "zh-CN" ? "发送前可以自行编辑；系统不会自动点击发送。" : "Edit before copying; the system never sends automatically."}</p></div>{result && showArithmetic && <span className={`decision mini ${result.decision.toLowerCase()}`}>{language === "zh-CN" ? decisionCopy[result.decision].zh : decisionCopy[result.decision].en}</span>}</div>{result ? <>{showArithmetic && <div className="boundary-grid"><div><span>{t.opening}</span><strong>{money(result.opening)}</strong></div><div><span>{t.target}</span><strong>{money(result.target)}</strong></div><div><span>{t.ceiling}</span><strong>{money(result.ceiling)}</strong></div></div>}<textarea className="message-box message-editor" rows={10} value={draftMessage} onChange={(event) => setDraftMessage(event.target.value)} aria-label={language === "zh-CN" ? "可编辑卖家消息" : "Editable seller message"} /><button className="button ghost" onClick={copyMessage}>{t.copy}</button>{showArithmetic && <details className="trace"><summary>{language === "zh-CN" ? "价格是怎样计算的" : "How the price was calculated"}</summary>{result.trace.map((item, index) => <span key={`${item.label}-${index}`}>{item.label || item.explanation}<b>{item.amount !== undefined ? money(item.amount) : ""}</b></span>)}</details>}</> : <div className="empty-state tall">{phase === "initial_contact" ? language === "zh-CN" ? "生成一条不含报价的初次筛选消息。" : "Generate an initial screening message without a price offer." : language === "zh-CN" ? "先生成价格边界和消息。证据覆盖低于 40% 时不会给出最终最高价。" : "Generate a price boundary and message. Below 40% evidence coverage, no final ceiling is produced."}</div>}</section>
    </div>
  );
}

function TriStateField({ label, value, language, onChange }: { label: string; value: boolean | null; language: Language; onChange: (value: boolean | null) => void }) {
  const serialized = value === null ? "unknown" : value ? "yes" : "no";
  return (
    <label>{label}
      <select
        value={serialized}
        onChange={(event) => onChange(event.target.value === "unknown" ? null : event.target.value === "yes")}
      >
        <option value="unknown">{language === "zh-CN" ? "未知 / 尚未询问" : "Unknown / not asked"}</option>
        <option value="yes">{language === "zh-CN" ? "是" : "Yes"}</option>
        <option value="no">{language === "zh-CN" ? "否 — 卖家拒绝" : "No — seller refused"}</option>
      </select>
    </label>
  );
}

function MatchStatusField({ label, value, language, onChange }: { label: string; value: TransactionContextInput["identity_title_match"]; language: Language; onChange: (value: TransactionContextInput["identity_title_match"]) => void }) {
  return (
    <label>{label}
      <select value={value} onChange={(event) => onChange(event.target.value as TransactionContextInput["identity_title_match"])}>
        <option value="UNKNOWN">{language === "zh-CN" ? "未知 / 尚未核对" : "Unknown / not checked"}</option>
        <option value="MATCH">{language === "zh-CN" ? "完全一致" : "Match"}</option>
        <option value="MISMATCH">{language === "zh-CN" ? "不一致 — 停止交易" : "Mismatch — stop"}</option>
      </select>
    </label>
  );
}

function TransactionView({ record, language, t, notify, setConnected, isDemo }: { record: CaseRecord; language: Language; t: typeof copy[Language]; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [context, setContext] = useState<TransactionContextInput>({ purchase_date: new Date().toISOString().slice(0, 10), buyer_residence_state: "NJ", buyer_license_state: "NJ", garaging_state: "CT", registration_state: "NJ", sale_state: "NY", title_state: "NY", seller_type: "private", title_status: "UNKNOWN", identity_title_match: "UNKNOWN", vin_match: "UNKNOWN", seller_allows_ppi: null, seller_allows_bill_of_sale: null, seller_discloses_odometer: null, lien_status: "unknown", insurance_active_for_vin: false, legal_transport: "none" });
  const [plan, setPlan] = useState<TransactionPlan>(record.transaction_plan);
  const stateFields = ["buyer_residence_state", "buyer_license_state", "garaging_state", "registration_state", "sale_state", "title_state"] as const;
  type StateField = typeof stateFields[number];
  type SupportedState = TransactionContextInput[StateField];
  const [stateSelections, setStateSelections] = useState<Record<StateField, SupportedState | "">>({ buyer_residence_state: "", buyer_license_state: "", garaging_state: "", registration_state: "", sale_state: "", title_state: "" });
  const stateLabels: Record<StateField, { en: string; zh: string }> = {
    buyer_residence_state: { en: "Buyer residence state", zh: "买家居住州" },
    buyer_license_state: { en: "Driver license state", zh: "驾照签发州" },
    garaging_state: { en: "Garaging state", zh: "车辆主要停放州" },
    registration_state: { en: "Registration state", zh: "计划注册州" },
    sale_state: { en: "Sale state", zh: "成交州" },
    title_state: { en: "Current title state", zh: "现有 title 州" },
  };

  async function generatePlan() {
    if (stateFields.some((field) => !stateSelections[field])) {
      notify(language === "zh-CN" ? "请先明确选择全部六个州信息；系统不会替你猜。" : "Select all six state fields first; the system will not guess them for you.");
      return;
    }
    const requestContext = { ...context, ...stateSelections } as TransactionContextInput;
    if (isDemo) {
      setPlan(buildLocalTransactionPlan(requestContext, language));
      notify(language === "zh-CN" ? "演示模式：使用页面内安全规则" : "Demo mode: generated with in-page safety rules");
      return;
    }
    try { setPlan(await api.transactionPlan(record.id, requestContext, record.vehicle, caseAccessFor(record.id))); setConnected(true); }
    catch (error) { setConnected(!isApiConnectionFailure(error)); notify(apiErrorMessage(error, language, language === "zh-CN" ? "交易计划生成失败" : "Transaction plan failed")); }
  }

  return (
    <div className="transaction-layout">
      <section className="card transaction-form">
        <div className="card-heading"><div><h2>{language === "zh-CN" ? "购买与过户情况" : "Purchase and title-transfer facts"}</h2><p>{language === "zh-CN" ? "请填写真实情况。系统不会替你猜州、title 或合法运车路径。" : "Enter the actual facts. The system will not guess states, title status, or a legal transport route."}</p></div></div>
        <div className="form-pair"><label>{language === "zh-CN" ? "计划成交日期" : "Planned purchase date"}<input type="date" value={context.purchase_date} onChange={(event) => setContext({ ...context, purchase_date: event.target.value })} /></label><label>{language === "zh-CN" ? "卖家类型" : "Seller type"}<select value={context.seller_type} onChange={(event) => setContext({ ...context, seller_type: event.target.value as TransactionContextInput["seller_type"] })}><option value="private">{language === "zh-CN" ? "私人卖家" : "Private seller"}</option><option value="dealer">{language === "zh-CN" ? "经销商" : "Dealer"}</option></select></label></div>
        <div className="privacy-callout">{language === "zh-CN" ? "州信息决定 title、税费、临牌和登记路径。请逐项选择真实情况；这里没有预设答案。" : "These states control title, tax, permit, and registration steps. Select the real facts; no answer is preselected."}</div>
        <div className="state-grid">{stateFields.map((field) => <label key={field}>{language === "zh-CN" ? stateLabels[field].zh : stateLabels[field].en}<select required value={stateSelections[field]} onChange={(event) => setStateSelections({ ...stateSelections, [field]: event.target.value as SupportedState | "" })}><option value="">{language === "zh-CN" ? "请选择…" : "Select…"}</option><option value="NJ">NJ</option><option value="NY">NY</option><option value="CT">CT</option></select></label>)}</div>
        <div className="gate-inputs">
          <label>{language === "zh-CN" ? "Title 文件状态" : "Title document status"}<select value={context.title_status} onChange={(event) => setContext({ ...context, title_status: event.target.value as TransactionContextInput["title_status"] })}><option value="UNKNOWN">{language === "zh-CN" ? "未知 / 尚未看原件" : "Unknown / original not inspected"}</option><option value="ORIGINAL">{language === "zh-CN" ? "原始、可转让" : "Original and transferable"}</option><option value="MISSING">{language === "zh-CN" ? "缺失 — 停止交易" : "Missing — stop"}</option><option value="ALTERED">{language === "zh-CN" ? "涂改 — 停止交易" : "Altered — stop"}</option><option value="ALREADY_ASSIGNED">{language === "zh-CN" ? "已签给他人 — 停止交易" : "Already assigned — stop"}</option><option value="BRANDED">{language === "zh-CN" ? "Branded / 重建等" : "Branded / rebuilt, etc."}</option></select></label>
          <MatchStatusField label={language === "zh-CN" ? "卖家身份证姓名与 title" : "Seller ID vs titled owner"} value={context.identity_title_match} language={language} onChange={(value) => setContext({ ...context, identity_title_match: value })} />
          <MatchStatusField label={language === "zh-CN" ? "Title、车身、报告 VIN" : "VIN across title, vehicle, and report"} value={context.vin_match} language={language} onChange={(value) => setContext({ ...context, vin_match: value })} />
          <TriStateField language={language} label={language === "zh-CN" ? "卖家允许独立 PPI" : "Seller allows independent PPI"} value={context.seller_allows_ppi} onChange={(value) => setContext({ ...context, seller_allows_ppi: value })} />
          <TriStateField language={language} label={language === "zh-CN" ? "卖家愿意签署 bill of sale" : "Seller will sign bill of sale"} value={context.seller_allows_bill_of_sale} onChange={(value) => setContext({ ...context, seller_allows_bill_of_sale: value })} />
          <TriStateField language={language} label={language === "zh-CN" ? "卖家愿意披露里程" : "Seller discloses odometer"} value={context.seller_discloses_odometer} onChange={(value) => setContext({ ...context, seller_discloses_odometer: value })} />
          <label><input type="checkbox" checked={context.insurance_active_for_vin} onChange={(event) => setContext({ ...context, insurance_active_for_vin: event.target.checked })} />{language === "zh-CN" ? "已为该 VIN 购买生效保险" : "Insurance active for this VIN"}</label>
          <label>{language === "zh-CN" ? "抵押权状态" : "Lien status"}<select value={context.lien_status} onChange={(event) => setContext({ ...context, lien_status: event.target.value as TransactionContextInput["lien_status"] })}><option value="unknown">{language === "zh-CN" ? "未知" : "Unknown"}</option><option value="none">{language === "zh-CN" ? "无抵押" : "None"}</option><option value="released">{language === "zh-CN" ? "已解除" : "Released"}</option><option value="unresolved">{language === "zh-CN" ? "未解除" : "Unresolved"}</option></select></label>
          <label>{language === "zh-CN" ? "合法运车方式" : "Legal transport"}<select value={context.legal_transport} onChange={(event) => setContext({ ...context, legal_transport: event.target.value as TransactionContextInput["legal_transport"] })}><option value="none">{language === "zh-CN" ? "尚未安排" : "Not arranged"}</option><option value="temporary_permit">{language === "zh-CN" ? "合法临时许可" : "Temporary permit"}</option><option value="registered_plate">{language === "zh-CN" ? "已登记车牌" : "Registered plate"}</option><option value="tow">{language === "zh-CN" ? "拖车 / 平板车" : "Tow / trailer"}</option></select></label>
        </div>
        <button className="button primary full" onClick={generatePlan}>{t.transactionPlan}</button>
      </section>
      <section className="card plan-view">
        <div className="card-heading"><div><span className="section-kicker">{language === "zh-CN" ? `规则核验日期 ${plan.verified_as_of}` : `Rules verified ${plan.verified_as_of}`}</span><h2>{language === "zh-CN" ? decisionCopy[plan.decision].zh : decisionCopy[plan.decision].en}</h2></div><span className={`decision mini ${plan.decision.toLowerCase()}`}>{language === "zh-CN" ? decisionCopy[plan.decision].zh : decisionCopy[plan.decision].en}</span></div>
        <h3 className="section-label">{t.hardGates}</h3>
        <div className="task-list">{plan.hard_gates.map((task) => <article className={task.status} key={task.id}><span>{task.status === "blocked" ? "×" : "!"}</span><div><strong>{task.title}</strong><p>{task.detail}</p></div></article>)}</div>
        <h3 className="section-label">{t.tasks}</h3>
        <div className="task-list numbered">{plan.tasks.map((task, index) => <article key={task.id}><span>{index + 1}</span><div><strong>{task.title}</strong><p>{task.detail}</p>{task.official_url && <a href={task.official_url} target="_blank" rel="noreferrer">{t.official} ↗</a>}</div></article>)}</div>
      </section>
    </div>
  );
}

function CompareView({ cases, language, t, isDemo, notify: _notify }: { cases: CaseRecord[]; language: Language; t: typeof copy[Language]; isDemo: boolean; notify: (text: string) => void }) {
  const [ranking, setRanking] = useState<ComparisonRow[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string>();
  const caseIds = cases.map((item) => item.id).join("|");

  useEffect(() => {
    if (cases.length < 2) {
      setRanking([]);
      setState("idle");
      return;
    }
    if (isDemo) {
      const order = { BUY_CANDIDATE: 0, NEGOTIATE: 1, INSPECT: 2, STOP: 3 };
      const riskOrder: Record<ComparisonRisk, number> = { INFO: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4, UNKNOWN: 5 };
      const rows = cases.map((item): ComparisonRow => {
        const mechanicalRisk = comparisonRiskFromLevel(item.risk_axes.find((axis) => axis.id === "mechanical")?.level || "unknown");
        const titleRisk = comparisonRiskFromLevel(item.risk_axes.find((axis) => axis.id === "title")?.level || "unknown");
        return {
          caseId: item.id,
          rank: 1,
          decision: item.decision,
          askingPrice: item.listing.asking_price,
          mechanicalRisk,
          titleRisk,
          coveragePercent: item.coverage_percent,
          unresolvedPlanningExposure: item.unresolved_planning_exposure ? {
            low: item.unresolved_planning_exposure[0],
            likely: (item.unresolved_planning_exposure[0] + item.unresolved_planning_exposure[1]) / 2,
            high: item.unresolved_planning_exposure[1],
            currency: "USD",
          } : null,
          reason: "Demo comparison",
        };
      }).sort((a, b) => order[a.decision] - order[b.decision]
        || riskOrder[a.titleRisk] - riskOrder[b.titleRisk]
        || riskOrder[a.mechanicalRisk] - riskOrder[b.mechanicalRisk]
        || b.coveragePercent - a.coveragePercent);
      rows.forEach((row, index) => { row.rank = index + 1; });
      setRanking(rows);
      setState("ready");
      return;
    }
    let cancelled = false;
    setState("loading");
    setError(undefined);
    api.compare(cases.map((item) => item.id), accessTokenMap(cases.map((item) => item.id))).then((response) => {
      if (cancelled) return;
      setRanking(response.ranked);
      setState("ready");
    }).catch((reason) => {
      if (cancelled) return;
      setError(apiErrorMessage(reason, language, language === "zh-CN" ? "车辆比较失败" : "Comparison failed"));
      setState("error");
    });
    return () => { cancelled = true; };
    // caseIds is a stable content fingerprint; depending on cases directly
    // would repeat the request whenever a parent array is replaced.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseIds, isDemo]);

  const ranked = ranking.flatMap((row) => {
    const record = cases.find((item) => item.id === row.caseId);
    return record ? [{ row, record }] : [];
  });
  const riskLabel = (risk: ComparisonRisk) => language === "zh-CN" && risk === "UNKNOWN" ? "未知" : risk;
  return <section className="card compare-card">
    <div className="card-heading">
      <div><h2>{t.compareTitle}</h2><p>{language === "zh-CN" ? "优先显示值得继续核实的车辆；证据不足的车辆不会得到虚假的精确排名。" : "Prioritizes vehicles worth further review; evidence-poor vehicles do not receive false precision."}</p></div>
      <span className="source-stamp">{isDemo ? language === "zh-CN" ? "演示比较" : "Demo comparison" : language === "zh-CN" ? "规则比较" : "Rules-based comparison"}</span>
    </div>
    {cases.length < 2
      ? <div className="empty-state">{language === "zh-CN" ? "至少建立两个案件才能比较。" : "Create at least two cases to compare."}</div>
      : state === "loading"
        ? <div className="empty-state">{language === "zh-CN" ? "正在运行确定性比较…" : "Running deterministic comparison…"}</div>
        : state === "error"
          ? <div className="empty-state error-state">{error}</div>
          : <>
            <div className="comparison" aria-label={language === "zh-CN" ? "候选车辆比较" : "Candidate vehicle comparison"}>
              <div className="comparison-head" aria-hidden="true">
                <span>#</span><span>Vehicle</span><span>{t.decision}</span>
                <span>{language === "zh-CN" ? "机械" : "Mechanical"}</span>
                <span>{language === "zh-CN" ? "产权" : "Title"}</span>
                <span>{t.asking}</span><span>{t.coverage}</span><span>{t.planningExposure}</span>
              </div>
              {ranked.map(({ row, record }) => <article className="comparison-row" key={record.id} aria-label={`${language === "zh-CN" ? "排名" : "Rank"} ${row.rank}: ${record.name.replace(/^Synthetic demo · /, "")}`}>
                <strong className="comparison-rank" aria-label={`${language === "zh-CN" ? "排名" : "Rank"} ${row.rank}`}>#{row.rank}</strong>
                <div className="comparison-vehicle"><b>{record.name.replace(/^Synthetic demo · /, "")}</b><small>{record.vehicle.generation || "—"} · {mileage(record.listing.mileage)}</small></div>
                <div className="comparison-field"><span className="mobile-label">{t.decision}</span><span className={`decision mini ${row.decision.toLowerCase()}`}>{language === "zh-CN" ? decisionCopy[row.decision].zh : decisionCopy[row.decision].en}</span></div>
                <div className="comparison-field"><span className="mobile-label">{language === "zh-CN" ? "机械风险" : "Mechanical risk"}</span><span className={comparisonRiskClass(row.mechanicalRisk)}>{riskLabel(row.mechanicalRisk)}</span></div>
                <div className="comparison-field"><span className="mobile-label">{language === "zh-CN" ? "产权风险" : "Title risk"}</span><span className={comparisonRiskClass(row.titleRisk)}>{riskLabel(row.titleRisk)}</span></div>
                <div className="comparison-field"><span className="mobile-label">{t.asking}</span><strong>{money(row.askingPrice ?? record.listing.asking_price)}</strong></div>
                <div className="comparison-field mini-coverage"><span className="mobile-label">{t.coverage}</span><span>{row.coveragePercent}%</span><i aria-hidden="true"><b style={{ width: `${row.coveragePercent}%` }} /></i></div>
                <div className="comparison-field"><span className="mobile-label">{t.planningExposure}</span><span>{row.unresolvedPlanningExposure ? `${money(row.unresolvedPlanningExposure.low)}–${money(row.unresolvedPlanningExposure.high)}` : "—"}</span></div>
              </article>)}
            </div>
            <div className="compare-footnote">
              {language === "zh-CN"
                ? "UNKNOWN 表示尚未完成对应核验，并以灰色显示；排序不会把它当作低风险。未解决维修规划暴露只合计已确认或疑似但尚未解决的最可能维修分支，用于案件比较，不是未来 12 个月的预计维修费。"
                : "UNKNOWN means that axis has not been verified, is shown in gray, and never receives a low-risk ranking advantage. Unresolved repair planning exposure sums the most-likely branches for confirmed or suspected unresolved findings; it is a comparison aid, not a 12-month expected-cost forecast."}
            </div>
          </>}
  </section>;
}

function ImportModal({ record, language, onClose, patchCase, notify, setConnected, isDemo, onRefresh }: { record: CaseRecord; language: Language; onClose: () => void; patchCase: (updater: (item: CaseRecord) => CaseRecord) => void; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean; onRefresh: () => void }) {
  const [form, setForm] = useState<ListingImportForm>(() => targetListingImportForm(record));
  const [busy, setBusy] = useState(false);
  const [decodeBusy, setDecodeBusy] = useState(false);
  const [decodeError, setDecodeError] = useState<string>();
  const [decodeStatus, setDecodeStatus] = useState<string>();
  const zh = language === "zh-CN";
  useModalEscape(onClose, busy || decodeBusy);
  function switchRole(role: ListingRole) {
    setForm(role === "target" ? targetListingImportForm(record) : comparableListingImportForm(record));
    setDecodeError(undefined);
    setDecodeStatus(undefined);
  }
  function update<K extends keyof ListingImportForm>(key: K, value: ListingImportForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  function updateVin(value: string) {
    update("vin", normalizeVinInput(value));
    setDecodeError(undefined);
    setDecodeStatus(undefined);
  }
  async function decodeListingVin() {
    const vin = normalizeVinInput(form.vin);
    setDecodeError(undefined);
    setDecodeStatus(undefined);
    if (!isValidModernVin(vin)) {
      setDecodeError(zh ? "请输入 17 位 VIN（不能含 I、O、Q），或留空后手工填写配置。" : "Enter a 17-character VIN without I, O, or Q, or leave it blank and enter the configuration manually.");
      return;
    }
    setDecodeBusy(true);
    try {
      const decoded = await api.decodeVin(vin, form.year ? Number(form.year) : undefined);
      if (!decoded.decodeValid) {
        setDecodeError(zh
          ? `NHTSA 无法确认这个 VIN${decoded.errorText ? `：${decoded.errorText}` : ""}。请核对字符，并手工填写可验证的配置。`
          : `NHTSA could not validate this VIN${decoded.errorText ? `: ${decoded.errorText}` : ""}. Check every character and enter only verifiable configuration manually.`);
        return;
      }
      setForm((current) => ({
        ...applyDecodedVehicleToForm(current, decoded.vehicle),
        generation: decoded.vehicle.generation || current.generation,
        platform: decoded.vehicle.platform || current.platform,
        production_date: decoded.vehicle.production_date || current.production_date,
      }));
      setConnected(true);
      setDecodeStatus(zh ? "NHTSA 解码完成；请与车身铭牌和 title 逐项核对。" : "NHTSA decode complete. Verify every field against the VIN label and title.");
    } catch (error) {
      setConnected(!isApiConnectionFailure(error));
      setDecodeError(apiErrorMessage(error, language, zh ? "VIN 解码失败；仍可手工填写。" : "VIN decode failed; manual entry remains available."));
    } finally {
      setDecodeBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.vin && !isValidModernVin(form.vin)) {
      setDecodeError(zh ? "VIN 必须为 17 位且不能含 I、O、Q；请修正或清空。" : "VIN must be 17 characters without I, O, or Q. Correct it or clear the field.");
      return;
    }
    const listing = listingImportPayload(form);
    setBusy(true);
    try {
      if (isDemo) {
        const now = new Date().toISOString();
        const snapshot = { ...listing, id: `demo-listing-${Date.now()}`, captured_at: now };
        if (listing.is_target) {
          patchCase((item) => ({
            ...item,
            name: listing.title || item.name,
            listing: { ...item.listing, ...snapshot },
            vehicle: { ...item.vehicle, ...listingImportVehicle(listing) },
            updated_at: now,
          }));
        } else {
          patchCase((item) => ({
            ...item,
            comparable_listings: [...(item.comparable_listings || []), snapshot],
            evidence: [...item.evidence, {
              id: `demo-comparable-${Date.now()}`,
              label: listing.title,
              source: listing.channel,
              captured_at: now,
              status: "unverified",
            }],
            updated_at: now,
          }));
        }
      } else {
        await api.importListings(record.id, [listing], caseAccessFor(record.id));
        setConnected(true);
        onRefresh();
      }
      notify(listing.is_target
        ? zh ? "目标车源已导入并保存快照" : "Target listing imported and snapshotted"
        : zh ? "可比车源已导入；重新分析后才会判断是否纳入估值" : "Comparable imported; re-analysis will decide whether it is admitted");
      onClose();
    } catch (error) {
      setConnected(!isApiConnectionFailure(error));
      notify(apiErrorMessage(error, language, language === "zh-CN" ? "车源导入失败" : "Listing import failed"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="modal listing-import-modal" role="dialog" aria-modal="true" aria-labelledby="listing-import-title" aria-busy={busy || decodeBusy} onSubmit={submit}>
        <div className="modal-head">
          <div><h2 id="listing-import-title">{zh ? "添加目标车或可比车" : "Add a target or comparable vehicle"}</h2></div>
          <button type="button" onClick={onClose} aria-label={zh ? "关闭" : "Close"}><X size={18} /></button>
        </div>
        <p>{zh
          ? "目标车用于定义案件；可比车只在配置、渠道、日期和距离满足确定性规则时才会进入估值。"
          : "The target defines the case. A comparable enters valuation only when its verified configuration, channel, date, and distance pass deterministic rules."}</p>

        <fieldset className="listing-role" aria-label={zh ? "车源用途" : "Listing role"}>
          <legend>{zh ? "这条车源是" : "This listing is"}</legend>
          <label className={form.role === "target" ? "active" : ""}>
            <input type="radio" name="listing-role" value="target" checked={form.role === "target"} onChange={() => switchRole("target")} />
            <span><strong>{zh ? "目标车辆" : "Target vehicle"}</strong><small>{zh ? "更新当前案件的目标车快照" : "Update the case target snapshot"}</small></span>
          </label>
          <label className={form.role === "comparable" ? "active" : ""}>
            <input type="radio" name="listing-role" value="comparable" checked={form.role === "comparable"} onChange={() => switchRole("comparable")} />
            <span><strong>{zh ? "市场可比车" : "Market comparable"}</strong><small>{zh ? "作为相似车候选，重新分析后筛选" : "Screened for valuation after re-analysis"}</small></span>
          </label>
        </fieldset>

        <div className="listing-evidence-help" id="listing-evidence-help">
          {form.role === "target"
            ? zh ? "已从案件预填目标车资料。请按当前车源核对，不要把旧案件资料当作这张车源的新证据。" : "Target details are prefilled from the case. Verify them against this listing; old case data is not new listing evidence."
            : zh ? "只填写你能在这条车源中核实的事实。缺少配置、日期或距离不会被自动当作匹配，该车源可能被估值引擎排除。" : "Enter only facts verified in this listing. Missing configuration, date, or distance is never assumed to match and may exclude it from valuation."}
        </div>

        <section className="listing-form-section" aria-labelledby="listing-source-heading">
          <h3 id="listing-source-heading">{zh ? "车源与价格" : "Source & price"}</h3>
          <label>{zh ? "车源链接" : "Listing URL"}<input type="url" value={form.source_url} onChange={(event) => update("source_url", event.target.value)} placeholder="https://…" /></label>
          <label>{zh ? "车源标题" : "Listing title"}<input required value={form.title} onChange={(event) => update("title", event.target.value)} placeholder={zh ? "例如：2017 Toyota Corolla LE" : "e.g. 2017 Toyota Corolla LE"} /></label>
          <div className="form-pair">
            <label>{zh ? "价格 / 参考值（美元）" : "Price / reference value (USD)"}<input required type="number" min="0" step="1" value={form.asking_price} onChange={(event) => update("asking_price", event.target.value)} /></label>
            <label>{zh ? "价格来源类型" : "Reference kind"}<select value={form.reference_kind} onChange={(event) => update("reference_kind", event.target.value as ListingImportForm["reference_kind"])}><option value="asking">{zh ? "挂牌价 Asking" : "Asking price"}</option><option value="sold">{zh ? "已成交 Sold" : "Sold price"}</option><option value="reference">{zh ? "外部参考值 External" : "External reference value"}</option></select></label>
          </div>
          <div className="form-pair">
            <label>{zh ? "里程（miles）" : "Mileage (miles)"}<input type="number" min="0" step="1" value={form.mileage} onChange={(event) => update("mileage", event.target.value)} /></label>
            <label>{zh ? "挂牌日期" : "Date listed"}<input type="date" value={form.listed_date} onChange={(event) => update("listed_date", event.target.value)} /></label>
          </div>
          <div className="form-pair">
            <label>{zh ? "地点" : "Location"}<input value={form.location} onChange={(event) => update("location", event.target.value)} placeholder={zh ? "城市，州" : "City, state"} /></label>
            {form.role === "comparable"
              ? <label>{zh ? "距目标车（miles）" : "Distance from target (miles)"}<input type="number" min="0" step="0.1" value={form.distance_miles} onChange={(event) => update("distance_miles", event.target.value)} /></label>
              : <div className="target-distance-note">{zh ? "目标车不需要填写距离。" : "Distance is not used for the target."}</div>}
          </div>
          <div className="form-pair">
            <label>{zh ? "渠道" : "Channel"}<select value={form.channel} onChange={(event) => update("channel", event.target.value)}><option value="facebook_marketplace">Facebook Marketplace</option><option value="craigslist">Craigslist</option><option value="cars_com">Cars.com</option><option value="autotrader">Autotrader</option><option value="dealer">{zh ? "经销商网站" : "Dealer site"}</option><option value="user_entry">{zh ? "手工录入" : "Manual entry"}</option><option value="other">{zh ? "其他" : "Other"}</option></select></label>
            <label>{zh ? "卖家类型" : "Seller type"}<select value={form.seller_type} onChange={(event) => update("seller_type", event.target.value as ListingImportForm["seller_type"])}><option value="private">{zh ? "私人卖家" : "Private party"}</option><option value="dealer">{zh ? "经销商" : "Dealer"}</option><option value="unknown">{zh ? "未知" : "Unknown"}</option></select></label>
          </div>
        </section>

        <section className="listing-form-section" aria-labelledby="listing-config-heading">
          <div className="listing-section-heading">
            <div><h3 id="listing-config-heading">{zh ? "精确车型配置" : "Exact vehicle configuration"}</h3><small>{zh ? "这些字段决定可比车是否能进入估值" : "These fields determine comparable admission"}</small></div>
            {form.role === "comparable" && <button className="text-button config-copy-button" type="button" onClick={() => setForm((current) => copyResolvedTargetConfiguration(current, record.vehicle))}>{zh ? "复制目标配置（需逐项核实）" : "Copy target config (verify each field)"}</button>}
          </div>
          {form.copied_configuration && <div className="copied-config-warning" role="status">{zh ? "已复制案件中的目标配置。这只是便捷输入；提交前必须与可比车源逐项核实。" : "Copied from the case target for convenience. Verify every field against the comparable before submitting."}</div>}
          <div className="vin-decode-row">
            <label>VIN<input value={form.vin} maxLength={17} onChange={(event) => updateVin(event.target.value)} placeholder="17 characters" /></label>
            <button className="button ghost" type="button" onClick={decodeListingVin} disabled={decodeBusy || busy}>{decodeBusy ? "…" : zh ? "免费 NHTSA 解码" : "Free NHTSA decode"}</button>
          </div>
          {decodeError && <div className="form-error" role="alert">{decodeError}</div>}
          {decodeStatus && <div className="form-success" role="status">{decodeStatus}</div>}
          <div className="privacy-callout">{zh ? "仅在你点击解码时，VIN 会由当前配置的 API 发送给免费的美国 NHTSA vPIC 服务；不需要账号或 API key。解码结果是待核对的规格，不证明 title 或车况。" : "Only when you click decode, the configured API sends the VIN to the free U.S. NHTSA vPIC service. No account or API key is needed. Decoded specs require review and do not prove title or condition."}</div>
          <div className="form-triple">
            <label>{zh ? "年款" : "Year"}<input type="number" min="1981" max="2100" value={form.year} onChange={(event) => update("year", event.target.value)} /></label>
            <label>{zh ? "品牌" : "Make"}<input value={form.make} onChange={(event) => update("make", event.target.value)} /></label>
            <label>{zh ? "车型" : "Model"}<input value={form.model} onChange={(event) => update("model", event.target.value)} /></label>
          </div>
          <div className="form-triple">
            <label>{zh ? "配置 / Trim" : "Trim"}<input value={form.trim} onChange={(event) => update("trim", event.target.value)} /></label>
            <label>{zh ? "代际" : "Generation"}<input value={form.generation} onChange={(event) => update("generation", event.target.value)} /></label>
            <label>{zh ? "平台代号" : "Platform"}<input value={form.platform} onChange={(event) => update("platform", event.target.value)} /></label>
          </div>
          <div className="form-pair">
            <label>{zh ? "发动机" : "Engine"}<input value={form.engine} onChange={(event) => update("engine", event.target.value)} placeholder="1.8L 2ZR-FE I4" /></label>
            <label>{zh ? "变速箱" : "Transmission"}<input value={form.transmission} onChange={(event) => update("transmission", event.target.value)} placeholder="CVT / 6-speed manual" /></label>
          </div>
          <div className="form-triple">
            <label>{zh ? "驱动形式" : "Drivetrain"}<input value={form.drivetrain} onChange={(event) => update("drivetrain", event.target.value)} placeholder="FWD / AWD / RWD" /></label>
            <label>{zh ? "生产日期" : "Production date"}<input type="date" value={form.production_date} onChange={(event) => update("production_date", event.target.value)} /></label>
            <label>{zh ? "燃料类型" : "Fuel type"}<select value={form.fuel_type} onChange={(event) => update("fuel_type", event.target.value)}><option value="unknown">{zh ? "未知" : "Unknown"}</option><option value="gasoline">{zh ? "汽油" : "Gasoline"}</option><option value="diesel">{zh ? "柴油" : "Diesel"}</option><option value="hybrid">{zh ? "混动" : "Hybrid"}</option><option value="plug_in_hybrid">{zh ? "插电混动" : "Plug-in hybrid"}</option><option value="electric">{zh ? "纯电" : "Electric"}</option></select></label>
          </div>
          <label>{zh ? "车身形式" : "Body style"}<input value={form.body_style} onChange={(event) => update("body_style", event.target.value)} placeholder={zh ? "例如：hatchback / sedan / SUV" : "e.g. hatchback / sedan / SUV"} /></label>
        </section>

        <div className="privacy-callout">{zh ? "不会导入 Cookie、登录令牌或私聊正文。提交的字段会作为用户提供的结构化车源证据保存。" : "No cookies, session tokens, or private-message text are imported. Submitted fields are stored as user-provided structured listing evidence."}</div>
        <button className="button primary full" disabled={busy || decodeBusy}>{busy ? "…" : form.role === "target" ? zh ? "导入目标车" : "Import target" : zh ? "导入可比车" : "Import comparable"}</button>
      </form>
    </div>
  );
}

function CaseArchiveModal({ activeCase, dataMode, deploymentMode, language, onClose, onImported, onDeleted }: {
  activeCase?: CaseRecord;
  dataMode: DataMode;
  deploymentMode: DeploymentMode;
  language: Language;
  onClose: () => void;
  onImported: (record: CaseRecord) => void;
  onDeleted: (caseId: string) => void;
}) {
  const [exportPassphrase, setExportPassphrase] = useState("");
  const [importPassphrase, setImportPassphrase] = useState("");
  const [archiveFile, setArchiveFile] = useState<File>();
  const [exportBusy, setExportBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [exportError, setExportError] = useState<string>();
  const [importError, setImportError] = useState<string>();
  const [exportStatus, setExportStatus] = useState<string>();
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string>();
  const isBusy = exportBusy || importBusy || deleteBusy;
  const canExport = Boolean(activeCase && dataMode === "api");
  useModalEscape(onClose, isBusy);

  async function exportArchive(event: FormEvent) {
    event.preventDefault();
    setExportError(undefined);
    setExportStatus(undefined);
    const validationError = ocddPassphraseError(exportPassphrase, language);
    if (validationError) {
      setExportError(validationError);
      return;
    }
    if (!activeCase || dataMode !== "api") {
      setExportError(language === "zh-CN" ? "只能导出已连接 API 的真实案件。" : "Only a real API-connected case can be exported.");
      return;
    }
    setExportBusy(true);
    try {
      const archive = await api.exportCase(
        activeCase.id,
        normalizeOcddPassphrase(exportPassphrase),
        caseAccessFor(activeCase.id),
      );
      const objectUrl = URL.createObjectURL(archive);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = ocddDownloadName(activeCase.id);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setExportStatus(language === "zh-CN" ? "加密 .ocdd 文件已生成。请妥善保存口令。" : "Encrypted .ocdd file created. Keep the passphrase safe.");
    } catch (reason) {
      setExportError(apiErrorMessage(reason, language, language === "zh-CN" ? "案件导出失败。" : "Case export failed."));
    } finally {
      setExportBusy(false);
    }
  }

  async function importArchive(event: FormEvent) {
    event.preventDefault();
    setImportError(undefined);
    const passphraseValidation = ocddPassphraseError(importPassphrase, language);
    const fileValidation = ocddFileError(archiveFile?.name, language);
    if (passphraseValidation || fileValidation) {
      setImportError(passphraseValidation || fileValidation);
      return;
    }
    if (!archiveFile) return;
    setImportBusy(true);
    try {
      const contentBase64 = await blobToBase64(archiveFile);
      const imported = await api.importCase(
        contentBase64,
        normalizeOcddPassphrase(importPassphrase),
      );
      // The API client already stores this one-time cloud capability in
      // sessionStorage. Remember it explicitly here as a defensive boundary
      // before the immediate case fetch; it is never added to a URL.
      rememberCaseAccess(imported.caseId, imported.accessToken);
      const record = await api.getCase(
        imported.caseId,
        imported.accessToken ? { accessToken: imported.accessToken } : undefined,
      );
      onImported(record);
    } catch (reason) {
      setImportError(apiErrorMessage(reason, language, language === "zh-CN" ? "案件导入失败。请检查文件和口令。" : "Case import failed. Check the file and passphrase."));
    } finally {
      setImportBusy(false);
    }
  }

  async function deleteCurrentCase(event: FormEvent) {
    event.preventDefault();
    setDeleteError(undefined);
    if (!activeCase || dataMode !== "api") {
      setDeleteError(language === "zh-CN" ? "只能删除已连接 API 的真实案件。" : "Only a real API-connected case can be deleted here.");
      return;
    }
    if (deleteConfirmation !== "DELETE") {
      setDeleteError(language === "zh-CN" ? "请输入 DELETE 以确认删除案件数据。" : "Type DELETE to confirm case-data deletion.");
      return;
    }
    setDeleteBusy(true);
    try {
      await api.deleteCase(activeCase.id, caseAccessFor(activeCase.id));
      onDeleted(activeCase.id);
    } catch (reason) {
      setDeleteError(apiErrorMessage(reason, language, language === "zh-CN" ? "案件删除失败。" : "Case deletion failed."));
      setDeleteBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !isBusy && onClose()}>
      <section className="modal archive-modal" role="dialog" aria-modal="true" aria-labelledby="archive-modal-title" aria-busy={isBusy}>
        <div className="modal-head">
          <div><h2 id="archive-modal-title">{language === "zh-CN" ? ".ocdd 加密案件文件" : "Encrypted .ocdd case file"}</h2></div>
          <button type="button" disabled={isBusy} onClick={onClose} aria-label={language === "zh-CN" ? "关闭" : "Close"}><X size={18} /></button>
        </div>
        <p>{language === "zh-CN" ? ".ocdd 保存结构化案件；敏感原件默认不包含。口令不会保存到浏览器，遗失后无法恢复。" : ".ocdd stores the structured case; sensitive originals are excluded by default. The passphrase is not saved in the browser and cannot be recovered."}</p>
        <div className="archive-grid">
          <form className="archive-pane" onSubmit={exportArchive}>
            <div><h3>{language === "zh-CN" ? "导出当前案件" : "Export current case"}</h3></div>
            {canExport ? <p>{activeCase?.name}</p> : <div className="archive-unavailable">{language === "zh-CN" ? "当前没有可导出的真实 API 案件；演示数据不会写入案件文件。" : "No real API case is available to export; demo data is never written to an archive."}</div>}
            <label>{language === "zh-CN" ? "加密口令（至少 8 字符）" : "Encryption passphrase (8+ characters)"}<input type="password" minLength={8} autoComplete="new-password" value={exportPassphrase} onChange={(event) => setExportPassphrase(event.target.value)} disabled={!canExport || exportBusy} /></label>
            {exportError && <div className="form-error" role="alert">{exportError}</div>}
            {exportStatus && <div className="form-success" role="status">{exportStatus}</div>}
            <button className="button primary full" disabled={!canExport || exportBusy || importBusy}>{exportBusy ? "…" : language === "zh-CN" ? "生成加密文件" : "Create encrypted file"}</button>
          </form>
          <form className="archive-pane" onSubmit={importArchive}>
            <div><h3>{language === "zh-CN" ? "导入已有案件" : "Import an existing case"}</h3></div>
            <label>{language === "zh-CN" ? ".ocdd 文件" : ".ocdd file"}<input type="file" accept=".ocdd,application/octet-stream" onChange={(event) => setArchiveFile(event.target.files?.[0])} disabled={importBusy} /></label>
            <label>{language === "zh-CN" ? "解密口令（至少 8 字符）" : "Decryption passphrase (8+ characters)"}<input type="password" minLength={8} autoComplete="current-password" value={importPassphrase} onChange={(event) => setImportPassphrase(event.target.value)} disabled={importBusy} /></label>
            {importError && <div className="form-error" role="alert">{importError}</div>}
            <div className="privacy-callout">{language === "zh-CN" ? "云端 capability 只保存在当前会话；单案件请求通过请求头，多案件比较通过 HTTPS 请求正文发送，绝不会放进 URL。" : "Cloud capabilities stay in this session only: single-case requests use a header, while multi-case comparison uses the HTTPS request body. They are never placed in a URL."}</div>
            <button className="button primary full" disabled={importBusy || exportBusy}>{importBusy ? "…" : language === "zh-CN" ? "解密并导入" : "Decrypt and import"}</button>
          </form>
        </div>
        <form className="case-delete-zone" onSubmit={deleteCurrentCase}>
          <div><h3>{language === "zh-CN" ? "删除当前案件与已存储附件" : "Delete this case and stored artifacts"}</h3><p>{language === "zh-CN" ? "删除结构化案件、已存储附件和当前会话访问凭证；不会影响其他案件。此操作不可撤销。" : "Deletes this structured case, stored artifacts, and its session capability without touching other cases. This cannot be undone."}{deploymentMode === "cloud" && <> {language === "zh-CN" ? "这不代表立即完成全系统擦除；短暂的加密处理信封仍受部署方披露的保留边界约束。" : "This does not claim immediate whole-system erasure; transient encrypted processing envelopes remain subject to the deployment's disclosed retention boundary."}</>}</p></div>
          <label>{language === "zh-CN" ? "输入 DELETE 确认" : "Type DELETE to confirm"}<input value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} disabled={!canExport || isBusy} autoComplete="off" /></label>
          {deleteError && <div className="form-error" role="alert">{deleteError}</div>}
          <button className="button danger" disabled={!canExport || isBusy || deleteConfirmation !== "DELETE"}>{deleteBusy ? "…" : language === "zh-CN" ? "删除案件数据" : "Delete case data"}</button>
        </form>
      </section>
    </div>
  );
}

function NewCaseModal({ language, onClose, onCreate, setConnected, isDemo }: { language: Language; onClose: () => void; onCreate: (record: CaseRecord) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [form, setForm] = useState({ vin: "", year: "", make: "", model: "", trim: "", engine: "", transmission: "", drivetrain: "", fuel_type: "", body_style: "", budget: "" });
  const [decodedVehicle, setDecodedVehicle] = useState<VehicleSpec>();
  const [decodeBusy, setDecodeBusy] = useState(false);
  const [decodeError, setDecodeError] = useState<string>();
  const [decodeStatus, setDecodeStatus] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  function updateVin(value: string) {
    const vin = normalizeVinInput(value);
    setForm((current) => ({ ...current, vin }));
    if (normalizeVinInput(decodedVehicle?.vin || "") !== vin) setDecodedVehicle(undefined);
    setDecodeError(undefined);
    setDecodeStatus(undefined);
  }

  async function decodeVin() {
    const vin = normalizeVinInput(form.vin);
    setDecodeError(undefined);
    setDecodeStatus(undefined);
    if (!isValidModernVin(vin)) {
      setDecodeError(language === "zh-CN" ? "请输入 17 位 VIN；VIN 不能包含 I、O 或 Q。你也可以跳过解码，直接手工填写车辆信息。" : "Enter a 17-character VIN without I, O, or Q. You can also skip decoding and enter the vehicle manually.");
      return;
    }

    setDecodeBusy(true);
    try {
      const year = Number(form.year);
      const response = await api.decodeVin(vin, Number.isInteger(year) && year >= 1981 && year <= 2100 ? year : undefined);
      if (!response.decodeValid) {
        setDecodedVehicle(undefined);
        setDecodeError(language === "zh-CN" ? `NHTSA 未能确认这个 VIN${response.errorText ? `：${response.errorText}` : ""}。请核对 VIN，或继续手工填写。` : `NHTSA could not validate this VIN${response.errorText ? `: ${response.errorText}` : ""}. Check the VIN or continue with manual entry.`);
        return;
      }
      const vehicle = { ...response.vehicle, vin: response.vehicle.vin || vin };
      setDecodedVehicle(vehicle);
      setForm((current) => applyDecodedVehicleToForm(current, vehicle));
      setDecodeStatus(language === "zh-CN" ? "已用 NHTSA 官方数据填入可识别字段；空白或不准确的字段仍可手工修改。" : "Recognized fields were filled from official NHTSA data. Blank or inaccurate fields can still be edited manually.");
    } catch (reason) {
      setDecodeError(apiErrorMessage(reason, language, language === "zh-CN" ? "当前配置的 API 无法联系 NHTSA。请检查网络和服务，或继续手工填写。" : "The configured API could not reach NHTSA. Check the service and internet connection, or continue with manual entry."));
    } finally {
      setDecodeBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.vin && !isValidModernVin(form.vin)) {
      setError(language === "zh-CN" ? "VIN 必须留空，或填写不含 I、O、Q 的完整 17 位 VIN。" : "Leave VIN blank or enter a complete 17-character VIN without I, O, or Q.");
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const vehicle = vehicleSpecForCase(form, decodedVehicle);
      if (isDemo) {
        const seed = structuredClone(demoCases[1]);
        seed.id = `demo-${Date.now()}`;
        seed.name = `${form.year} ${form.make} ${form.model}`.trim() || "Untitled vehicle";
        seed.vehicle = vehicle;
        seed.listing = { ...seed.listing, id: `listing-${seed.id}`, title: seed.name, asking_price: 0, mileage: undefined, captured_at: new Date().toISOString() };
        onCreate(seed);
      } else {
        const created = await api.createCase({ language, all_in_budget: form.budget ? Number(form.budget) : undefined, vehicle });
        rememberCaseAccess(created.case.id, created.accessToken);
        setConnected(true);
        onCreate(created.case);
      }
    } catch (reason) {
      setConnected(!isApiConnectionFailure(reason));
      setError(apiErrorMessage(reason, language, language === "zh-CN" ? "案件创建失败" : "Case creation failed"));
    } finally {
      setBusy(false);
    }
  }
  const isBusy = busy || decodeBusy;
  useModalEscape(onClose, isBusy);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !isBusy && onClose()}>
      <form className="modal small" role="dialog" aria-modal="true" aria-labelledby="new-case-title" onSubmit={submit} aria-busy={isBusy}>
        <div className="modal-head">
          <div><h2 id="new-case-title">{language === "zh-CN" ? "添加候选车辆" : "Add a candidate vehicle"}</h2></div>
          <button type="button" onClick={onClose} disabled={isBusy} aria-label={language === "zh-CN" ? "关闭" : "Close"}><X size={18} /></button>
        </div>
        <div className="vin-decode-row">
          <label>VIN<input value={form.vin} maxLength={32} autoCapitalize="characters" autoComplete="off" spellCheck={false} disabled={isBusy} aria-describedby="vin-decode-disclosure" onChange={(event) => updateVin(event.target.value)} placeholder="17-character VIN" /></label>
          <button className="button ghost" type="button" onClick={() => void decodeVin()} disabled={isBusy || !form.vin} aria-describedby="vin-decode-disclosure">{decodeBusy ? (language === "zh-CN" ? "解码中…" : "Decoding…") : language === "zh-CN" ? "免费 NHTSA 解码" : "Free NHTSA decode"}</button>
        </div>
        <div className="privacy-callout" id="vin-decode-disclosure">{language === "zh-CN" ? "只有点击解码后，VIN 才会经当前配置的 API 发送到美国 NHTSA 官方 vPIC。需要联网；无需账户、API key 或费用。请逐项复核下方自动填入字段；创建后它们作为你审核过的车辆资料保存，不会冒充独立证据。交易前仍须逐字比对车身和原始 title 上的 VIN。" : "Only after you click decode is the VIN sent through the configured API to official NHTSA vPIC. Internet is required; no account, API key, or fee is required. Review every filled field below: after creation it is saved as your reviewed vehicle specification, not as independent evidence. Compare the physical vehicle VIN and original title character by character before purchase."}</div>
        {decodeError && <div className="form-error" role="alert">{decodeError}</div>}
        {decodeStatus && <div className="form-success" role="status">{decodeStatus}</div>}
        <div className="form-pair"><label>{language === "zh-CN" ? "年款" : "Year"}<input type="number" value={form.year} disabled={isBusy} onChange={(event) => setForm({ ...form, year: event.target.value })} /></label><label>{language === "zh-CN" ? "品牌" : "Make"}<input required value={form.make} disabled={isBusy} onChange={(event) => setForm({ ...form, make: event.target.value })} /></label></div>
        <div className="form-pair"><label>{language === "zh-CN" ? "车型" : "Model"}<input required value={form.model} disabled={isBusy} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label><label>{language === "zh-CN" ? "配置版本" : "Trim"}<input value={form.trim} disabled={isBusy} onChange={(event) => setForm({ ...form, trim: event.target.value })} /></label></div>
        <details className="advanced-fields">
          <summary>{language === "zh-CN" ? "补充精确机械配置" : "Add exact mechanical configuration"}</summary>
          <div className="form-pair"><label>{language === "zh-CN" ? "发动机（请复核）" : "Engine (review)"}<input value={form.engine} disabled={isBusy} onChange={(event) => setForm({ ...form, engine: event.target.value })} /></label><label>{language === "zh-CN" ? "变速箱（请复核）" : "Transmission (review)"}<input value={form.transmission} disabled={isBusy} onChange={(event) => setForm({ ...form, transmission: event.target.value })} /></label></div>
          <div className="form-pair"><label>{language === "zh-CN" ? "驱动形式（请复核）" : "Drivetrain (review)"}<input value={form.drivetrain} disabled={isBusy} onChange={(event) => setForm({ ...form, drivetrain: event.target.value })} /></label><label>{language === "zh-CN" ? "燃料类型（请复核）" : "Fuel type (review)"}<select value={form.fuel_type || "unknown"} disabled={isBusy} onChange={(event) => setForm({ ...form, fuel_type: event.target.value })}><option value="unknown">{language === "zh-CN" ? "未知" : "Unknown"}</option><option value="gasoline">{language === "zh-CN" ? "汽油" : "Gasoline"}</option><option value="diesel">{language === "zh-CN" ? "柴油" : "Diesel"}</option><option value="hybrid">{language === "zh-CN" ? "油电混动" : "Hybrid"}</option><option value="plug_in_hybrid">{language === "zh-CN" ? "插电混动" : "Plug-in hybrid"}</option><option value="electric">{language === "zh-CN" ? "纯电" : "Electric"}</option><option value="other">{language === "zh-CN" ? "其他" : "Other"}</option></select></label></div>
          <label>{language === "zh-CN" ? "车身形式（请复核）" : "Body style (review)"}<input value={form.body_style} disabled={isBusy} onChange={(event) => setForm({ ...form, body_style: event.target.value })} /></label>
        </details>
        <label>{language === "zh-CN" ? "总预算（含税费与登记）" : "All-in budget"}<input type="number" value={form.budget} disabled={isBusy} onChange={(event) => setForm({ ...form, budget: event.target.value })} /></label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button primary full" disabled={isBusy}>{busy ? language === "zh-CN" ? "正在创建…" : "Creating…" : language === "zh-CN" ? "创建车辆案件" : "Create vehicle case"}</button>
      </form>
    </div>
  );
}
