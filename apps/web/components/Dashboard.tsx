"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ComparisonRisk, ComparisonRow } from "@ocdd/contracts";
import { api, apiErrorMessage, isApiConnectionFailure, isApiError } from "@/lib/api";
import { accessTokenMap, caseAccessFor, forgetCaseAccess, knownCaseAccesses, rememberCaseAccess } from "@/lib/case-access";
import { explicitDemoCases } from "@/lib/case-record";
import { comparisonRiskClass, comparisonRiskFromLevel } from "@/lib/compare";
import { demoCases } from "@/lib/demo";
import { mobileCaseLabel } from "@/lib/mobile-case-label";
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
  NegotiationResponse,
  RiskLevel,
  TransactionContextInput,
  TransactionPlan,
} from "@/lib/types";
import { ServiceWorkerRegister } from "./ServiceWorkerRegister";

type Tab = "overview" | "evidence" | "inspection" | "negotiate" | "transaction" | "compare";

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
    analyze: "重新分析",
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
    localMode: "本地演示数据",
    apiMode: "API 已连接",
    offlineMode: "API 未连接",
    loading: "正在连接 OpenCarDueDiligence API…",
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
    analyze: "Re-analyze",
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
    localMode: "Local demo data",
    apiMode: "API connected",
    offlineMode: "API disconnected",
    loading: "Connecting to the OpenCarDueDiligence API…",
    empty: "No cases yet. Create one, then import a listing, report, or OBD scan.",
    retry: "Reconnect",
    refresh: "Refresh",
    amountUnavailable: "Insufficient evidence — no point estimate",
  },
} as const;

const tabs: Array<{ id: Tab; icon: string }> = [
  { id: "overview", icon: "⌂" },
  { id: "evidence", icon: "▤" },
  { id: "inspection", icon: "✓" },
  { id: "negotiate", icon: "↔" },
  { id: "transaction", icon: "§" },
  { id: "compare", icon: "≋" },
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

function nextCheckStatus(status: CheckStatus): CheckStatus {
  if (status === "unknown") return "pass";
  if (status === "pass") return "warn";
  if (status === "warn") return "fail";
  return "unknown";
}

export function Dashboard() {
  const [language, setLanguage] = useState<Language>("zh-CN");
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [activeCaseId, setActiveCaseId] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [newCaseOpen, setNewCaseOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [dataMode, setDataMode] = useState<"api" | "demo" | "offline">("offline");
  const [loadError, setLoadError] = useState<string>();
  const [toast, setToast] = useState<string>();
  const t = copy[language];
  const activeCase = cases.find((item) => item.id === activeCaseId) || cases[0];
  const demoEnabled = process.env.NEXT_PUBLIC_OCDD_ENABLE_DEMO === "true";

  useEffect(() => {
    const storedLanguage = window.localStorage.getItem("ocdd-language") as Language | null;
    if (storedLanguage === "en" || storedLanguage === "zh-CN") setLanguage(storedLanguage);
    void loadCases();
    // This is intentionally a one-time boot connection. User-driven refreshes
    // call loadCases directly and never substitute demo data in API mode.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadCases() {
    setLoadState("loading");
    setLoadError(undefined);
    try {
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
        setLoadState("ready");
        setLoadError(undefined);
        return;
      }
      setCases([]);
      setActiveCaseId("");
      setDataMode(isApiConnectionFailure(error) ? "offline" : "api");
      setLoadState("error");
      setLoadError(apiErrorMessage(error, language));
    }
  }

  function updateLanguage(value: Language) {
    setLanguage(value);
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

  return (
    <div className="app-shell">
      <ServiceWorkerRegister />
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">OC</div>
          <div><strong>OpenCar</strong><span>Due Diligence</span></div>
        </div>

        <div className="workspace-label"><span>{t.workspace}</span><small>{dataMode === "api" ? t.apiMode : dataMode === "demo" ? t.localMode : t.offlineMode}</small></div>
        <nav className="side-nav" aria-label="Primary navigation">
          {tabs.map((item) => (
            <button
              key={item.id}
              className={activeTab === item.id ? "active" : ""}
              onClick={() => setActiveTab(item.id)}
            >
              <span aria-hidden="true">{item.icon}</span>{t[item.id]}
            </button>
          ))}
        </nav>

        <div className="watchlist-heading"><span>{t.watchlist}</span><button onClick={() => setNewCaseOpen(true)} aria-label={t.newCase}>＋</button></div>
        <div className="case-list">
          {cases.map((item) => (
            <button key={item.id} className={item.id === activeCase?.id ? "case-row active" : "case-row"} onClick={() => void selectCase(item.id)}>
              <span className={`case-dot ${item.decision.toLowerCase()}`} />
              <span><strong>{item.name}</strong><small>{money(item.listing.asking_price)} · {mileage(item.listing.mileage)}</small></span>
            </button>
          ))}
        </div>
        <div className="privacy-note"><span aria-hidden="true">⌁</span><p><strong>Local-first</strong><br />Sensitive originals stay on your device by default.</p></div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb">{activeCase?.name || "OpenCarDueDiligence"}<span>/</span>{t[activeTab]}</div>
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
            <button className="mobile-new-case" type="button" onClick={() => setNewCaseOpen(true)} aria-label={t.newCase}><span aria-hidden="true">＋</span>{t.newCase}</button>
          </div>
          <div className="top-actions">
            <div className="language-toggle" role="group" aria-label="Language">
              <button className={language === "zh-CN" ? "active" : ""} onClick={() => updateLanguage("zh-CN")}>中文</button>
              <button className={language === "en" ? "active" : ""} onClick={() => updateLanguage("en")}>EN</button>
            </div>
            <button className="button ghost archive-button" onClick={() => setArchiveOpen(true)}>{language === "zh-CN" ? "案件文件" : "Case file"}</button>
            {activeCase && <button className="button ghost" disabled={busy || dataMode === "demo"} onClick={() => void refreshActiveCase()}>{t.refresh}</button>}
            {activeCase && <button className="button ghost print-button" disabled={pdfBusy} onClick={handlePdf}>{pdfBusy ? "…" : language === "zh-CN" ? "报告 PDF" : "Report PDF"}</button>}
            {activeCase && <button className="button ghost" onClick={() => setImportOpen(true)}>＋ {t.import}</button>}
            {activeCase && <button className="button primary" disabled={busy} onClick={handleAnalyze}>{busy ? "…" : t.analyze}</button>}
          </div>
        </header>

        <div className="content">
          {loadState === "loading" && <WorkspaceState title={t.loading} detail="GET /v1/cases" />}
          {loadState === "error" && <WorkspaceState title={dataMode === "offline" ? t.offlineMode : language === "zh-CN" ? "API 请求失败" : "API request failed"} detail={loadError || (language === "zh-CN" ? "无法完成请求" : "The request could not be completed")} action={t.retry} onAction={() => void loadCases()} />}
          {loadState === "ready" && !activeCase && <WorkspaceState title={t.empty} action={t.newCase} onAction={() => setNewCaseOpen(true)} />}
          {loadState === "ready" && activeCase && <>
            <CaseHero record={activeCase} language={language} t={t} />
            {activeTab === "overview" && <Overview key={activeCase.id} record={activeCase} language={language} t={t} onGoEvidence={() => setActiveTab("evidence")} onRefresh={() => void refreshActiveCase(true)} isDemo={dataMode === "demo"} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} />}
            {activeTab === "evidence" && <EvidenceView key={activeCase.id} record={activeCase} language={language} t={t} onRefresh={() => void refreshActiveCase(true)} isDemo={dataMode === "demo"} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} />}
            {activeTab === "inspection" && <InspectionView key={activeCase.id} record={activeCase} language={language} t={t} patchCase={patchActiveCase} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} onRefresh={() => void refreshActiveCase(true)} />}
            {activeTab === "negotiate" && <NegotiationView key={activeCase.id} record={activeCase} language={language} t={t} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
            {activeTab === "transaction" && <TransactionView key={activeCase.id} record={activeCase} language={language} t={t} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
            {activeTab === "compare" && <CompareView cases={cases} language={language} t={t} isDemo={dataMode === "demo"} notify={notify} />}
          </>}
        </div>
      </main>

      {importOpen && activeCase && <ImportModal record={activeCase} language={language} onClose={() => setImportOpen(false)} patchCase={patchActiveCase} notify={notify} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} onRefresh={() => void refreshActiveCase(true)} />}
      {archiveOpen && <CaseArchiveModal activeCase={activeCase} dataMode={dataMode} language={language} onClose={() => setArchiveOpen(false)} onImported={(record) => { setCases((items) => [record, ...items.filter((item) => item.id !== record.id)]); setActiveCaseId(record.id); setActiveTab("overview"); setDataMode("api"); setLoadState("ready"); setArchiveOpen(false); notify(language === "zh-CN" ? "加密案件已导入" : "Encrypted case imported"); }} />}
      {newCaseOpen && <NewCaseModal language={language} onClose={() => setNewCaseOpen(false)} onCreate={(record) => { setCases((items) => [...items, record]); setActiveCaseId(record.id); setNewCaseOpen(false); setLoadState("ready"); }} setConnected={(value) => setDataMode(value ? "api" : "offline")} isDemo={dataMode === "demo"} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

function WorkspaceState({ title, detail, action, onAction }: { title: string; detail?: string; action?: string; onAction?: () => void }) {
  return <section className="card workspace-state"><div><span className="eyebrow">WORKSPACE</span><h2>{title}</h2>{detail && <p>{detail}</p>}{action && onAction && <button className="button primary" onClick={onAction}>{action}</button>}</div></section>;
}

function CaseHero({ record, language, t }: { record: CaseRecord; language: Language; t: typeof copy[Language] }) {
  const spec = [record.vehicle.generation, record.vehicle.engine, record.vehicle.transmission, record.vehicle.drivetrain].filter(Boolean).join(" · ");
  return (
    <section className="case-hero">
      <div>
        <div className="eyebrow">CASE {record.id.replace("demo-", "").toUpperCase()}</div>
        <h1>{record.name}</h1>
        <p>{spec}</p>
        <div className="vehicle-meta"><span>{mileage(record.listing.mileage)}</span><span>{record.listing.location || "—"}</span><span>{record.listing.seller_type}</span></div>
      </div>
      <div className="hero-status">
        <span>{t.decision}</span>
        <strong className={`decision ${record.decision.toLowerCase()}`}>{language === "zh-CN" ? decisionCopy[record.decision].zh : decisionCopy[record.decision].en}</strong>
        <div className="coverage"><span>{t.coverage}</span><b>{record.coverage_percent}%</b><div><i style={{ width: `${record.coverage_percent}%` }} /></div></div>
      </div>
    </section>
  );
}

function Overview({ record, language, t, onGoEvidence, onRefresh, isDemo, notify, setConnected }: { record: CaseRecord; language: Language; t: typeof copy[Language]; onGoEvidence: () => void; onRefresh: () => void; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void }) {
  return (
    <div className="dashboard-grid">
      <section className="card span-2">
        <div className="card-heading"><div><span className="eyebrow">01 / SCREEN</span><h2>{t.riskAxes}</h2></div><span className="source-stamp">Evidence-led · no composite score</span></div>
        <div className="risk-grid">
          {record.risk_axes.map((axis) => (
            <article className={`risk-card ${axis.level}`} key={axis.id}>
              <div><span>{axis.label}</span><strong>{language === "zh-CN" ? riskCopy[axis.level].zh : riskCopy[axis.level].en}</strong></div>
              <p>{axis.note}</p>
            </article>
          ))}
        </div>
      </section>

      <ValuationCard record={record} t={t} />

      <section className="card findings-card">
        <div className="card-heading"><div><span className="eyebrow">03 / FINDINGS</span><h2>{t.findings}</h2></div><button className="text-button" onClick={onGoEvidence}>{t.viewEvidence} →</button></div>
        <div className="finding-list">
          {record.findings.length === 0 && <div className="empty-state">{language === "zh-CN" ? "尚无结论。先导入历史报告和检查结果。" : "No findings yet. Import history and inspection evidence first."}</div>}
          {record.findings.map((finding) => (
            <article key={finding.id}>
              <span className={`severity ${finding.level}`} />
              <div><h3>{finding.title}</h3><p>{finding.summary}</p><small>Next: {finding.next_check || "—"}</small></div>
              <div className="exposure">{finding.exposure_high ? `${money(finding.exposure_low)}–${money(finding.exposure_high)}` : "—"}</div>
            </article>
          ))}
        </div>
      </section>

      <section className="card span-2 obd-card">
        <div className="card-heading"><div><span className="eyebrow">04 / DIAGNOSTICS</span><h2>{t.obd}</h2></div><span className={`readiness ${record.diagnostics.readiness}`}>{record.diagnostics.readiness.replace("_", " ")}</span></div>
        <div className="obd-layout">
          <div><h3>{language === "zh-CN" ? "本次扫描覆盖" : "Covered by this scan"}</h3>{record.diagnostics.coverage.length ? record.diagnostics.coverage.map((item) => <span className="token pass" key={item}>✓ {item}</span>) : <span className="token unknown">— {t.unknown}</span>}<h3 className="token-heading">DTC</h3>{record.diagnostics.codes.length ? record.diagnostics.codes.map((item) => <span className="token warn" key={item}>! {item}</span>) : <span className="token unknown">— none reported</span>}</div>
          <div><h3>{language === "zh-CN" ? "没有覆盖" : "Not covered"}</h3>{record.diagnostics.not_covered.map((item) => <span className="token unknown" key={item}>? {item}</span>)}</div>
          <div className="obd-warning"><strong>Important</strong><p>{t.noCodeWarning}</p></div>
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
    <button className="button ghost" onClick={() => setOpen((value) => !value)}>{open ? "−" : "+"} {language === "zh-CN" ? "手工录入普通 OBD" : "Enter generic OBD scan"}</button>
    {open && <form className="inline-form" onSubmit={submit}>
      <div className="form-pair"><label>Scanner<input value={form.scanner} onChange={(event) => setForm({ ...form, scanner: event.target.value })} /></label><label>DTCs<input value={form.codes} onChange={(event) => setForm({ ...form, codes: event.target.value })} placeholder="P0301, P0420" /></label></div>
      <div className="form-pair"><label>Readiness<select value={form.readiness} onChange={(event) => setForm({ ...form, readiness: event.target.value })}><option value="UNKNOWN">Unknown</option><option value="READY">All declared monitors ready</option><option value="NOT_READY">One or more not ready</option></select></label><label>MIL<select value={form.mil} onChange={(event) => setForm({ ...form, mil: event.target.value })}><option value="unknown">Unknown</option><option value="off">Off</option><option value="on">On</option></select></label></div>
      <label>Notes<textarea rows={2} value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
      <button className="button primary" disabled={busy || isDemo}>{busy ? "…" : language === "zh-CN" ? "保存只读扫描" : "Save read-only scan"}</button>
    </form>}
  </div>;
}

function ValuationCard({ record, t }: { record: CaseRecord; t: typeof copy[Language] }) {
  const value = record.valuation;
  const hasMarket = value.market_median !== undefined;
  return (
    <section className="card valuation-card">
      <div className="card-heading"><div><span className="eyebrow">02 / VALUE</span><h2>{t.valuation}</h2></div><span className={`confidence ${value.confidence}`}>{value.confidence} confidence</span></div>
      <div className="valuation-main"><span>{t.asking}</span><strong>{money(value.asking_price)}</strong></div>
      {hasMarket ? (
        <>
          <div className="range-label"><span>{value.market_label}</span><b>{money(value.q1)} — {money(value.q3)}</b></div>
          <div className="price-track"><i className="range" style={{ left: "22%", width: "50%" }} /><i className="asking-pin" style={{ left: "42%" }} /><i className="ceiling-pin" style={{ left: "31%" }} /></div>
          <div className="price-legend"><span><i className="dot dark" />Asking</span><span><i className="dot gold" />Ceiling</span><span>{value.sample_count} comps</span></div>
          <div className="offer-grid"><div><span>{t.opening}</span><strong>{money(value.opening)}</strong></div><div><span>{t.target}</span><strong>{money(value.target)}</strong></div><div className="ceiling"><span>{t.ceiling}</span><strong>{money(value.ceiling)}</strong></div></div>
        </>
      ) : <div className="empty-state compact">{t.amountUnavailable}<small>{value.sample_count} comparable listings</small></div>}
    </section>
  );
}

function EvidenceView({ record, language, t, onRefresh, isDemo, notify, setConnected }: { record: CaseRecord; language: Language; t: typeof copy[Language]; onRefresh: () => void; isDemo: boolean; notify: (text: string) => void; setConnected: (value: boolean) => void }) {
  return (
    <div className="dashboard-grid">
      <section className="card span-2">
        <div className="card-heading"><div><span className="eyebrow">EVIDENCE LEDGER</span><h2>{t.evidence}</h2></div><span className="source-stamp">{record.evidence.length} sources · {record.coverage_percent}% coverage</span></div>
        <div className="evidence-table" role="table">
          <div className="table-head" role="row"><span>Source</span><span>{language === "zh-CN" ? "引用" : "Reference"}</span><span>Status</span><span>Date</span></div>
          {record.evidence.map((item) => <div className="table-row" role="row" key={item.id}><div><strong>{item.label}</strong><small>{item.source}</small></div><span>{item.reference || "—"}</span><span className={`evidence-status ${item.status}`}>{item.status}</span><span>{item.captured_at.slice(0, 10)}</span></div>)}
          {record.evidence.length === 0 && <div className="empty-state">{language === "zh-CN" ? "还没有证据。导入 listing、CARFAX 或检查记录。" : "No evidence yet. Import a listing, history report, or inspection."}</div>}
        </div>
      </section>
      <ArtifactUploader record={record} language={language} onRefresh={onRefresh} isDemo={isDemo} notify={notify} setConnected={setConnected} />
      <section className="card span-2">
        <div className="card-heading"><div><span className="eyebrow">TRACEABILITY</span><h2>{t.findings}</h2></div></div>
        <div className="finding-detail-grid">
          {record.findings.map((finding) => <article key={finding.id}><div className="finding-title"><span className={`severity ${finding.level}`} /><h3>{finding.title}</h3><span className="finding-state">{finding.status}</span></div><p>{finding.summary}</p><dl><div><dt>Evidence</dt><dd>{finding.evidence_ids.length ? finding.evidence_ids.join(", ") : t.unknown}</dd></div><div><dt>Next check</dt><dd>{finding.next_check || "—"}</dd></div></dl></article>)}
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

  return <section className="card span-2 evidence-uploader">
    <div className="card-heading"><div><span className="eyebrow">ARTIFACT INGEST</span><h2>{language === "zh-CN" ? "上传报告、title、发票或聊天" : "Upload report, title, receipt, or chat"}</h2></div><span className="source-stamp">PDF text first · OCR fallback</span></div>
    <form className="artifact-form" onSubmit={submit}>
      <div className="form-pair"><label>Kind<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="history_report">CARFAX / history report</option><option value="title">Title</option><option value="lien_release">Lien release</option><option value="receipt">Repair receipt</option><option value="state_inspection">State inspection</option><option value="seller_message">Seller message</option><option value="photo">Photo / screenshot</option><option value="ppi">PPI</option><option value="other">Other</option></select></label><label>Label<input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="CARFAX page set" /></label></div>
      {kind === "title" && <>
        <div className="form-pair">
          <label>{language === "zh-CN" ? "Title 上的车主姓名" : "Titled owner legal name"}<input autoComplete="off" value={titleOwnerName} onChange={(event) => setTitleOwnerName(event.target.value)} /></label>
          <label>{language === "zh-CN" ? "卖家证件姓名" : "Seller ID legal name"}<input autoComplete="off" value={sellerLegalName} onChange={(event) => setSellerLegalName(event.target.value)} /></label>
        </div>
        <small>{language === "zh-CN" ? "仅在服务器内即时做规范化精确比对；案件只保存 MATCH/MISMATCH，不保存姓名。仍须当面核对原件。" : "Compared transiently with conservative exact normalization; only MATCH/MISMATCH is retained. Verify the originals in person."}</small>
      </>}
      <label>File<input type="file" accept="application/pdf,image/*,text/plain,application/json,text/csv" onChange={(event) => setFile(event.target.files?.[0])} /></label>
      <div className="or-divider">{language === "zh-CN" ? "或粘贴文字" : "or paste text"}</div>
      <label>Text<textarea rows={4} value={plainText} onChange={(event) => setPlainText(event.target.value)} placeholder={language === "zh-CN" ? "卖家聊天、维修记录或报告摘录" : "Seller chat, maintenance record, or report excerpt"} /></label>
      <button className="button primary" disabled={busy || isDemo}>{busy ? "…" : language === "zh-CN" ? "上传材料" : "Upload artifact"}</button>
    </form>
  </section>;
}

function InspectionView({ record, language, t, patchCase, notify, setConnected, isDemo, onRefresh }: { record: CaseRecord; language: Language; t: typeof copy[Language]; patchCase: (updater: (item: CaseRecord) => CaseRecord) => void; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean; onRefresh: () => void }) {
  const [activeStage, setActiveStage] = useState(record.inspections[0]?.id || "before");
  const stage = record.inspections.find((item) => item.id === activeStage) || record.inspections[0];

  function cycle(checkId: string) {
    patchCase((item) => ({ ...item, inspections: item.inspections.map((section) => section.id !== activeStage ? section : { ...section, checks: section.checks.map((check) => check.id === checkId ? { ...check, status: nextCheckStatus(check.status) } : check) }) }));
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
      <div className="card-heading"><div><span className="eyebrow">5-STAGE · 41 CHECKS</span><h2>{t.inspection}</h2></div><span className="source-stamp">{language === "zh-CN" ? "点击状态切换：未知 → 通过 → 需复查 → 失败" : "Tap status: unknown → pass → review → fail"}</span></div>
      <div className="inspection-layout">
        <div className="stage-list">{record.inspections.map((item, index) => {
          const complete = item.checks.filter((check) => check.status !== "unknown").length;
          return <button className={item.id === activeStage ? "active" : ""} key={item.id} onClick={() => setActiveStage(item.id)}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.title}</strong><small>{complete}/{item.checks.length} checked</small></div></button>;
        })}</div>
        <div className="checklist">
          <h3>{stage.title}</h3>
          <p>{language === "zh-CN" ? "未实际检查的项目必须保持“未知”。可为每项添加备注并关联已上传证据。" : "Leave anything not actually checked as Unknown. Notes and uploaded evidence can be linked to each check."}</p>
          {stage.id === "ppi" && <label className="ppi-inspector-field"><span>{language === "zh-CN" ? "独立检查方（必填）" : "Independent inspector (required)"}</span><input value={stage.inspector || ""} onChange={(event) => updateInspector(event.target.value)} placeholder={language === "zh-CN" ? "例如：独立 MINI 专修店（不要填个人姓名）" : "e.g. Independent MINI specialist (no personal name)"} /></label>}
          {stage.checks.map((check) => <div className="check-row" key={check.id}>
            <button className="check-status-button" type="button" onClick={() => cycle(check.id)} aria-label={`${check.label}: ${statusLabel(language, check.status)}`}>
              <span className={`check-icon ${check.status}`}>{check.status === "pass" ? "✓" : check.status === "warn" ? "!" : check.status === "fail" ? "×" : "?"}</span>
              <b className={check.status}>{statusLabel(language, check.status)}</b>
            </button>
            <div className="check-content">
              <span className="check-label">{check.label}</span>
              <div className="check-fields">
                <label><span>{language === "zh-CN" ? "备注" : "Notes"}</span><input value={check.note || ""} onChange={(event) => updateCheck(check.id, { note: event.target.value })} placeholder={language === "zh-CN" ? "仅记录实际观察" : "Record observed facts only"} /></label>
                <label><span>{language === "zh-CN" ? "证据" : "Evidence"}</span><select value={check.evidence_ids?.[0] || ""} onChange={(event) => updateCheck(check.id, { evidence_ids: event.target.value ? [event.target.value] : [] })}><option value="">{language === "zh-CN" ? "未关联" : "Not linked"}</option>{record.evidence.map((evidence) => <option key={evidence.id} value={evidence.id}>{evidence.label}</option>)}</select></label>
              </div>
            </div>
          </div>)}
          <button className="button primary save-stage" onClick={saveStage}>{t.save}</button>
        </div>
      </div>
    </section>
  );
}

function NegotiationView({ record, language, t, notify, setConnected, isDemo }: { record: CaseRecord; language: Language; t: typeof copy[Language]; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [phase, setPhase] = useState<"initial_contact" | "conditional_offer" | "post_ppi" | "walk_away">("initial_contact");
  const [budget, setBudget] = useState(6500);
  const [sellerFloor, setSellerFloor] = useState(record.valuation.ceiling || 0);
  const [result, setResult] = useState<NegotiationResponse>();
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
    const request = { phase, language, asking_price: record.listing.asking_price, market_baseline: record.valuation.market_median || record.listing.asking_price, all_in_budget: budget, evidence_coverage: record.coverage_percent, adjustments, buyer_mandatory_costs: 500, seller_floor: sellerFloor || undefined };
    setBusy(true);
    try {
      if (isDemo) setResult(calculateNegotiation(request));
      else { setResult(await api.draftNegotiation(record.id, request, caseAccessFor(record.id))); setConnected(true); }
    }
    catch (error) { setConnected(!isApiConnectionFailure(error)); setResult(undefined); notify(negotiationErrorMessage(error, language)); }
    finally { setBusy(false); }
  }

  async function copyMessage() {
    if (!result) return;
    await navigator.clipboard.writeText(result.message);
    notify(t.copied);
  }

  return (
    <div className="negotiation-layout">
      <section className="card negotiation-form"><div className="card-heading"><div><span className="eyebrow">DETERMINISTIC BOUNDARY</span><h2>{t.negotiate}</h2></div></div><label>Phase<select value={phase} onChange={(event) => { setPhase(event.target.value as typeof phase); setResult(undefined); }}><option value="initial_contact">Initial contact</option><option value="conditional_offer">Conditional offer</option><option value="post_ppi">Post-PPI</option><option value="walk_away">Walk away / wait</option></select></label>{phase === "initial_contact" ? <div className="privacy-callout">{language === "zh-CN" ? "初次联系只生成 VIN、title、保养、当前故障和 PPI 问题；不需要估值，也不会生成报价。" : "Initial contact asks for the VIN, title, maintenance, current issues, and PPI permission. It does not need a valuation or generate an offer."}</div> : <><div className="form-pair"><label>All-in budget<input type="number" value={budget} onChange={(event) => setBudget(Number(event.target.value))} /></label><label>Seller floor<input type="number" value={sellerFloor} onChange={(event) => setSellerFloor(Number(event.target.value))} /></label></div><div className="deductions"><h3>{language === "zh-CN" ? "有证据的调整" : "Evidence-backed adjustments"}</h3>{eligibleAdjustments.length ? eligibleAdjustments.map((item) => <div className="negotiation-adjustment-row" key={item.finding_id || item.label}><label><input type="checkbox" checked={!item.finding_id || !excludedFindingIds.has(item.finding_id)} onChange={() => item.finding_id && toggleAdjustment(item.finding_id)} /><span>{item.label}</span></label><strong>{!item.finding_id || !excludedFindingIds.has(item.finding_id) ? `−${money(item.amount)}` : language === "zh-CN" ? "未计入" : "Excluded"}</strong></div>) : <div><span>{language === "zh-CN" ? "尚无可扣除的确认项目" : "No documented adjustments yet"}</span><strong>—</strong></div>}{inspectionOnlyFindings.length > 0 && <div className="inspection-only-note"><span>{language === "zh-CN" ? `待检查（不扣款）：${inspectionOnlyFindings.map((item) => item.title).join("；")}` : `Needs inspection (not deducted): ${inspectionOnlyFindings.map((item) => item.title).join("; ")}`}</span><strong>{language === "zh-CN" ? "待确认" : "Unconfirmed"}</strong></div>}<div><span>{language === "zh-CN" ? "证据准备金" : "Evidence reserve"}</span><strong>{record.coverage_percent}% coverage</strong></div></div></>}<button className="button primary full" onClick={generate} disabled={busy}>{busy ? "…" : t.generate}</button></section>
      <section className="card message-preview"><div className="card-heading"><div><span className="eyebrow">MESSAGE PREVIEW</span><h2>{language === "zh-CN" ? "卖家消息" : "Seller message"}</h2></div>{result && showArithmetic && <span className={`decision mini ${result.decision.toLowerCase()}`}>{result.decision}</span>}</div>{result ? <>{showArithmetic && <div className="boundary-grid"><div><span>{t.opening}</span><strong>{money(result.opening)}</strong></div><div><span>{t.target}</span><strong>{money(result.target)}</strong></div><div><span>{t.ceiling}</span><strong>{money(result.ceiling)}</strong></div></div>}<div className="message-box">{result.message}</div><button className="button ghost" onClick={copyMessage}>{t.copy}</button>{showArithmetic && <div className="trace"><strong>Calculation trace</strong>{result.trace.map((item, index) => <span key={`${item.label}-${index}`}>{item.label || item.explanation}<b>{item.amount !== undefined ? money(item.amount) : ""}</b></span>)}</div>}</> : <div className="empty-state tall">{phase === "initial_contact" ? language === "zh-CN" ? "生成一条不含报价的初次筛选消息。" : "Generate an initial screening message without a price offer." : language === "zh-CN" ? "先生成价格边界和消息。低于 40% 证据覆盖时不会给出最终最高价。" : "Generate a price boundary and message. Below 40% evidence coverage, no final ceiling is produced."}</div>}</section>
    </div>
  );
}

function TriStateField({ label, value, onChange }: { label: string; value: boolean | null; onChange: (value: boolean | null) => void }) {
  const serialized = value === null ? "unknown" : value ? "yes" : "no";
  return (
    <label>{label}
      <select
        value={serialized}
        onChange={(event) => onChange(event.target.value === "unknown" ? null : event.target.value === "yes")}
      >
        <option value="unknown">Unknown / not asked</option>
        <option value="yes">Yes</option>
        <option value="no">No — seller refused</option>
      </select>
    </label>
  );
}

function TransactionView({ record, language, t, notify, setConnected, isDemo }: { record: CaseRecord; language: Language; t: typeof copy[Language]; notify: (text: string) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [context, setContext] = useState<TransactionContextInput>({ purchase_date: new Date().toISOString().slice(0, 10), buyer_residence_state: "NJ", buyer_license_state: "NJ", garaging_state: "CT", registration_state: "NJ", sale_state: "NY", title_state: "NY", seller_type: "private", title_name_matches: false, vin_matches: false, original_title_present: false, seller_allows_ppi: null, seller_allows_bill_of_sale: null, seller_discloses_odometer: null, lien_status: "unknown", insurance_active_for_vin: false, legal_transport: "none" });
  const [plan, setPlan] = useState<TransactionPlan>(record.transaction_plan);
  const stateFields = ["buyer_residence_state", "buyer_license_state", "garaging_state", "registration_state", "sale_state", "title_state"] as const;

  async function generatePlan() {
    if (isDemo) {
      setPlan(buildLocalTransactionPlan(context, language));
      notify(language === "zh-CN" ? "演示模式：使用页面内安全规则" : "Demo mode: generated with in-page safety rules");
      return;
    }
    try { setPlan(await api.transactionPlan(record.id, context, record.vehicle, caseAccessFor(record.id))); setConnected(true); }
    catch (error) { setConnected(!isApiConnectionFailure(error)); notify(apiErrorMessage(error, language, language === "zh-CN" ? "交易计划生成失败" : "Transaction plan failed")); }
  }

  return (
    <div className="transaction-layout">
      <section className="card transaction-form">
        <div className="card-heading"><div><span className="eyebrow">STATE-AWARE</span><h2>{t.transaction}</h2></div></div>
        <div className="state-grid">{stateFields.map((field) => <label key={field}>{field.replaceAll("_", " ")}<select value={context[field]} onChange={(event) => setContext({ ...context, [field]: event.target.value })}><option>NJ</option><option>NY</option><option>CT</option></select></label>)}</div>
        <div className="gate-inputs">
          <label><input type="checkbox" checked={context.original_title_present} onChange={(event) => setContext({ ...context, original_title_present: event.target.checked })} />Original title present</label>
          <label><input type="checkbox" checked={context.title_name_matches} onChange={(event) => setContext({ ...context, title_name_matches: event.target.checked })} />Seller ID matches title</label>
          <label><input type="checkbox" checked={context.vin_matches} onChange={(event) => setContext({ ...context, vin_matches: event.target.checked })} />VIN matches title, vehicle, and report</label>
          <TriStateField label="Seller allows independent PPI" value={context.seller_allows_ppi} onChange={(value) => setContext({ ...context, seller_allows_ppi: value })} />
          <TriStateField label="Seller will sign bill of sale" value={context.seller_allows_bill_of_sale} onChange={(value) => setContext({ ...context, seller_allows_bill_of_sale: value })} />
          <TriStateField label="Seller discloses odometer" value={context.seller_discloses_odometer} onChange={(value) => setContext({ ...context, seller_discloses_odometer: value })} />
          <label><input type="checkbox" checked={context.insurance_active_for_vin} onChange={(event) => setContext({ ...context, insurance_active_for_vin: event.target.checked })} />Insurance active for VIN</label>
          <label>Lien status<select value={context.lien_status} onChange={(event) => setContext({ ...context, lien_status: event.target.value as TransactionContextInput["lien_status"] })}><option value="unknown">Unknown</option><option value="none">None</option><option value="released">Released</option><option value="unresolved">Unresolved</option></select></label>
          <label>Transport<select value={context.legal_transport} onChange={(event) => setContext({ ...context, legal_transport: event.target.value as TransactionContextInput["legal_transport"] })}><option value="none">None yet</option><option value="temporary_permit">Temporary permit</option><option value="registered_plate">Registered plate</option><option value="tow">Tow / trailer</option></select></label>
        </div>
        <button className="button primary full" onClick={generatePlan}>{t.transactionPlan}</button>
      </section>
      <section className="card plan-view">
        <div className="card-heading"><div><span className="eyebrow">VERIFIED AS OF {plan.verified_as_of}</span><h2>{language === "zh-CN" ? decisionCopy[plan.decision].zh : decisionCopy[plan.decision].en}</h2></div><span className={`decision mini ${plan.decision.toLowerCase()}`}>{plan.decision}</span></div>
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
      <div><span className="eyebrow">SHORTLIST</span><h2>{t.compareTitle}</h2></div>
      <span className="source-stamp">{isDemo ? "Demo ranking" : "POST /v1/compare"}</span>
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
              {ranked.map(({ row, record }) => <article className="comparison-row" key={record.id} aria-label={`${language === "zh-CN" ? "排名" : "Rank"} ${row.rank}: ${record.name}`}>
                <strong className="comparison-rank" aria-label={`${language === "zh-CN" ? "排名" : "Rank"} ${row.rank}`}>#{row.rank}</strong>
                <div className="comparison-vehicle"><b>{record.name}</b><small>{record.vehicle.generation || "—"} · {mileage(record.listing.mileage)}</small></div>
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
  const zh = language === "zh-CN";
  function switchRole(role: ListingRole) {
    setForm(role === "target" ? targetListingImportForm(record) : comparableListingImportForm(record));
  }
  function update<K extends keyof ListingImportForm>(key: K, value: ListingImportForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
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
      <form className="modal listing-import-modal" onSubmit={submit}>
        <div className="modal-head">
          <div><span className="eyebrow">LISTING SNAPSHOT</span><h2>{zh ? "导入目标车或可比车" : "Import target or comparable"}</h2></div>
          <button type="button" onClick={onClose} aria-label="Close">×</button>
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
            <span><strong>{zh ? "市场可比车" : "Market comparable"}</strong><small>{zh ? "is_target=false；供重新分析筛选" : "is_target=false; screened on re-analysis"}</small></span>
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
        <button className="button primary full" disabled={busy}>{busy ? "…" : form.role === "target" ? zh ? "导入目标车" : "Import target" : zh ? "导入可比车" : "Import comparable"}</button>
      </form>
    </div>
  );
}

function CaseArchiveModal({ activeCase, dataMode, language, onClose, onImported }: {
  activeCase?: CaseRecord;
  dataMode: "api" | "demo" | "offline";
  language: Language;
  onClose: () => void;
  onImported: (record: CaseRecord) => void;
}) {
  const [exportPassphrase, setExportPassphrase] = useState("");
  const [importPassphrase, setImportPassphrase] = useState("");
  const [archiveFile, setArchiveFile] = useState<File>();
  const [exportBusy, setExportBusy] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [exportError, setExportError] = useState<string>();
  const [importError, setImportError] = useState<string>();
  const [exportStatus, setExportStatus] = useState<string>();
  const isBusy = exportBusy || importBusy;
  const canExport = Boolean(activeCase && dataMode === "api");

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

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !isBusy && onClose()}>
      <section className="modal archive-modal" role="dialog" aria-modal="true" aria-labelledby="archive-modal-title" aria-busy={isBusy}>
        <div className="modal-head">
          <div><span className="eyebrow">ENCRYPTED CASE FILE</span><h2 id="archive-modal-title">{language === "zh-CN" ? ".ocdd 加密导入与导出" : "Encrypted .ocdd import and export"}</h2></div>
          <button type="button" disabled={isBusy} onClick={onClose} aria-label={language === "zh-CN" ? "关闭" : "Close"}>×</button>
        </div>
        <p>{language === "zh-CN" ? ".ocdd 保存结构化案件；敏感原件默认不包含。口令不会保存到浏览器，遗失后无法恢复。" : ".ocdd stores the structured case; sensitive originals are excluded by default. The passphrase is not saved in the browser and cannot be recovered."}</p>
        <div className="archive-grid">
          <form className="archive-pane" onSubmit={exportArchive}>
            <div><span className="eyebrow">EXPORT</span><h3>{language === "zh-CN" ? "导出当前案件" : "Export current case"}</h3></div>
            {canExport ? <p>{activeCase?.name}</p> : <div className="archive-unavailable">{language === "zh-CN" ? "当前没有可导出的真实 API 案件；演示数据不会写入案件文件。" : "No real API case is available to export; demo data is never written to an archive."}</div>}
            <label>{language === "zh-CN" ? "加密口令（至少 8 字符）" : "Encryption passphrase (8+ characters)"}<input type="password" minLength={8} autoComplete="new-password" value={exportPassphrase} onChange={(event) => setExportPassphrase(event.target.value)} disabled={!canExport || exportBusy} /></label>
            {exportError && <div className="form-error" role="alert">{exportError}</div>}
            {exportStatus && <div className="form-success" role="status">{exportStatus}</div>}
            <button className="button primary full" disabled={!canExport || exportBusy || importBusy}>{exportBusy ? "…" : language === "zh-CN" ? "生成加密文件" : "Create encrypted file"}</button>
          </form>
          <form className="archive-pane" onSubmit={importArchive}>
            <div><span className="eyebrow">IMPORT</span><h3>{language === "zh-CN" ? "导入已有案件" : "Import an existing case"}</h3></div>
            <label>{language === "zh-CN" ? ".ocdd 文件" : ".ocdd file"}<input type="file" accept=".ocdd,application/octet-stream" onChange={(event) => setArchiveFile(event.target.files?.[0])} disabled={importBusy} /></label>
            <label>{language === "zh-CN" ? "解密口令（至少 8 字符）" : "Decryption passphrase (8+ characters)"}<input type="password" minLength={8} autoComplete="current-password" value={importPassphrase} onChange={(event) => setImportPassphrase(event.target.value)} disabled={importBusy} /></label>
            {importError && <div className="form-error" role="alert">{importError}</div>}
            <div className="privacy-callout">{language === "zh-CN" ? "云端 capability 只保存在当前会话并通过请求头发送，绝不会放进 URL。" : "Cloud capability is kept only for this session and sent in a request header, never in a URL."}</div>
            <button className="button primary full" disabled={importBusy || exportBusy}>{importBusy ? "…" : language === "zh-CN" ? "解密并导入" : "Decrypt and import"}</button>
          </form>
        </div>
      </section>
    </div>
  );
}

function NewCaseModal({ language, onClose, onCreate, setConnected, isDemo }: { language: Language; onClose: () => void; onCreate: (record: CaseRecord) => void; setConnected: (value: boolean) => void; isDemo: boolean }) {
  const [form, setForm] = useState({ year: "", make: "", model: "", trim: "", budget: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      if (isDemo) {
        const seed = structuredClone(demoCases[1]);
        seed.id = `demo-${Date.now()}`;
        seed.name = `${form.year} ${form.make} ${form.model}`.trim() || "Untitled vehicle";
        seed.vehicle = { year: form.year ? Number(form.year) : undefined, make: form.make, model: form.model, trim: form.trim };
        seed.listing = { ...seed.listing, id: `listing-${seed.id}`, title: seed.name, asking_price: 0, mileage: undefined, captured_at: new Date().toISOString() };
        onCreate(seed);
      } else {
        const created = await api.createCase({ language, all_in_budget: form.budget ? Number(form.budget) : undefined, vehicle: { year: form.year ? Number(form.year) : undefined, make: form.make, model: form.model, trim: form.trim } });
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
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><form className="modal small" onSubmit={submit}><div className="modal-head"><div><span className="eyebrow">NEW CASE</span><h2>{language === "zh-CN" ? "建立候选车辆" : "Create vehicle case"}</h2></div><button type="button" onClick={onClose}>×</button></div><div className="form-pair"><label>Year<input type="number" value={form.year} onChange={(event) => setForm({ ...form, year: event.target.value })} /></label><label>Make<input required value={form.make} onChange={(event) => setForm({ ...form, make: event.target.value })} /></label></div><div className="form-pair"><label>Model<input required value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label><label>Trim<input value={form.trim} onChange={(event) => setForm({ ...form, trim: event.target.value })} /></label></div><label>All-in budget<input type="number" value={form.budget} onChange={(event) => setForm({ ...form, budget: event.target.value })} /></label>{error && <div className="form-error" role="alert">{error}</div>}<button className="button primary full" disabled={busy}>{busy ? "…" : language === "zh-CN" ? "创建案件" : "Create case"}</button></form></div>;
}
