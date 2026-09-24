import { useState } from "react";
import { EmptyStage } from "./EmptyStage";
import { mascotLine } from "../lib/mascotCopy";
import { fetchNovelAudit } from "../api/projects";
import {
  chapterBrief,
  submissionPreflight,
  type PreflightReport,
} from "../lib/submissionPreflight";
import type { SubmissionOptions } from "../api/projects";
import type { VnProject } from "../types/vn";
import styles from "./StudioApp.module.css";

type Props = {
  /** 当前作品：投稿前自检需要它（章节、元信息） */
  project: VnProject;
  rpyPreview: string | null;
  rpyStale: boolean;
  onGenerateRpy: () => void;
  onDownloadRpy: () => void;
  onDownloadJson: () => void;
  onDownloadMarkdown: () => void;
  onDownloadDocx: () => void;
  onDownloadBundle: () => void;
  bundleBusy: boolean;
  /** 投稿包导出（单篇或分章包）；父组件负责取 blob 与下载 */
  onDownloadSubmission: (opts: SubmissionOptions) => void;
  submissionBusy: boolean;
};

/**
 * 项目 → 导出 sub-tab: generate/download .rpy, download project JSON,
 * submission exports (Markdown / Word), download full Ren'Py project zip.
 * Pure presentational — export/status logic stays in StudioApp.
 */
export function ProjectExportPanel({
  project,
  rpyPreview,
  rpyStale,
  onGenerateRpy,
  onDownloadRpy,
  onDownloadJson,
  onDownloadMarkdown,
  onDownloadDocx,
  onDownloadBundle,
  bundleBusy,
  onDownloadSubmission,
  submissionBusy,
}: Props) {
  const [sub, setSub] = useState<SubmissionOptions>({
    indent: true,
    pageBreak: true,
    counts: true,
    synopsis: false,
    author: "",
    contact: "",
  });
  /** 投稿前自检结果（点了才跑：它会调一次离线体检接口） */
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  const [preflightError, setPreflightError] = useState("");

  async function runPreflight() {
    setPreflightBusy(true);
    setPreflightError("");
    try {
      // 体检本身是离线的（不调模型、不占配额），所以这里可以随时跑
      const audit = await fetchNovelAudit(project.id, { parts: "consistency" });
      const issues = audit.consistency?.issues ?? [];
      setPreflight(
        submissionPreflight({
          title: project.title ?? "",
          genre: project.genre,
          logline: project.logline,
          chapters: (project.chapters ?? []).map(chapterBrief),
          auditErrorCount: issues.filter((i) => i.severity === "error").length,
          quoteUnbalancedCount: issues.filter((i) => i.code === "quote_unbalanced").length,
          chapterGoal: project.writingGoals?.chapter ?? null,
        })
      );
    } catch (e) {
      setPreflightError(e instanceof Error ? e.message : "自检失败");
    } finally {
      setPreflightBusy(false);
    }
  }
  return (
    <>
      <div className={styles.toolbar}>
        <span>
          按你的目的选：投稿 / 交稿 → 「下载 Word」或「下载 Markdown」；想在电脑上运行试玩
          → 「下载 Ren'Py 项目包（zip）」（Ren'Py 是免费的文字冒险游戏制作软件，用它打开即可运行）。
          「生成 .rpy / 下载 .rpy」是给想在 Ren'Py 里继续改脚本的进阶用法；「下载工程 .json」是整份作品的备份文件。
        </span>
        <div className={styles.aiQuick}>
          <button type="button" className={styles.primary} onClick={onGenerateRpy}>
            生成 .rpy
          </button>
          <button
            type="button"
            disabled={!rpyPreview || rpyStale}
            onClick={onDownloadRpy}
            title={
              !rpyPreview
                ? "请先生成"
                : rpyStale
                  ? "剧本已改动，请重新生成"
                  : "下载预览中的 .rpy"
            }
          >
            下载 .rpy
          </button>
          <button type="button" onClick={onDownloadMarkdown} title="投稿用 Markdown 稿">
            下载 Markdown
          </button>
          <button type="button" onClick={onDownloadDocx} title="投稿用 Word 稿（.docx）">
            下载 Word
          </button>
          <button type="button" onClick={onDownloadJson} title="整份作品的备份文件，以后可导入恢复">
            下载工程备份 (.json)
          </button>
          <button
            type="button"
            disabled={bundleBusy}
            onClick={onDownloadBundle}
            title="下载一个 zip，内含可直接运行的完整工程文件，用免费的 Ren'Py 引擎打开即可试玩"
          >
            {bundleBusy ? "打包中…" : "下载 Ren'Py 项目包"}
          </button>
        </div>
      </div>
      {/* 投稿包：与上面「下载 Word」的区别是它按投稿方的格式要求来。
          默认不带章节梗概——那是写给自己看的备注，混进稿子里会被编辑当正文。 */}
      <div className={styles.toolbar}>
        <div>
          <strong>投稿包</strong>
          <p className={styles.hint}>
            按投稿方的格式要求排版：正文首行缩进 2 字符、每章另起一页、文末标字数、
            开头一页投稿信息。很多渠道要求<strong>一章一个文件</strong>，那就选「分章打包」。
          </p>
        </div>
        <div className={styles.aiQuick}>
          <label className={styles.inlineLabel}>
            <input
              type="checkbox"
              checked={sub.indent !== false}
              onChange={(e) => setSub((s) => ({ ...s, indent: e.target.checked }))}
            />
            首行缩进
          </label>
          <label className={styles.inlineLabel}>
            <input
              type="checkbox"
              checked={sub.pageBreak !== false}
              onChange={(e) => setSub((s) => ({ ...s, pageBreak: e.target.checked }))}
            />
            每章分页
          </label>
          <label className={styles.inlineLabel}>
            <input
              type="checkbox"
              checked={sub.counts !== false}
              onChange={(e) => setSub((s) => ({ ...s, counts: e.target.checked }))}
            />
            标注字数
          </label>
          <label
            className={styles.inlineLabel}
            title="章节梗概是写给你自己的备注，投稿稿里默认不带"
          >
            <input
              type="checkbox"
              checked={Boolean(sub.synopsis)}
              onChange={(e) => setSub((s) => ({ ...s, synopsis: e.target.checked }))}
            />
            带上梗概
          </label>
          <label className={styles.inlineLabel}>
            作者名
            <input
              value={sub.author ?? ""}
              placeholder="可留空"
              onChange={(e) => setSub((s) => ({ ...s, author: e.target.value }))}
            />
          </label>
          <label className={styles.inlineLabel}>
            联系方式
            <input
              value={sub.contact ?? ""}
              placeholder="可留空"
              onChange={(e) => setSub((s) => ({ ...s, contact: e.target.value }))}
            />
          </label>
          <button
            type="button"
            disabled={submissionBusy}
            data-testid="download-submission-docx"
            onClick={() => onDownloadSubmission(sub)}
          >
            {submissionBusy ? "导出中…" : "下载投稿稿 (.docx)"}
          </button>
          <button
            type="button"
            disabled={submissionBusy}
            data-testid="download-submission-zip"
            onClick={() => onDownloadSubmission({ ...sub, split: true })}
          >
            {submissionBusy ? "打包中…" : "分章打包 (.zip)"}
          </button>
          <button
            type="button"
            disabled={preflightBusy}
            data-testid="run-preflight"
            title="导出前检查一遍：空章、重复标题、引号不配对（会让导出吞台词）、元信息是否齐"
            onClick={() => void runPreflight()}
          >
            {preflightBusy ? "检查中…" : "投稿前自检"}
          </button>
        </div>
      </div>

      {/* 投稿前自检：检查的是"我们写明的默认值 + 你这本书的状态"，不是某个平台的规范
          （平台要求各不相同、也查不到权威来源，所以不假装对齐）。 */}
      {preflightError ? <p className={styles.hint}>{preflightError}</p> : null}
      {preflight ? (
        <div className={styles.toolbar} data-testid="preflight-result">
          <div>
            <strong>
              {preflight.okToSubmit
                ? "自检通过：没有会破坏阅读的问题"
                : `有 ${preflight.blockers} 项必须先处理`}
            </strong>
            <ul className={styles.hint}>
              {preflight.checks.map((c) => (
                <li key={c.id}>
                  {c.level === "blocker" ? "⛔ " : c.level === "warn" ? "⚠️ " : "· "}
                  <strong>{c.title}</strong>：{c.detail}
                  {c.fix ? ` — ${c.fix}` : ""}
                </li>
              ))}
            </ul>
            <p className={styles.hint}>
              自检只覆盖"交出去会出问题"的那几类。更多细节（标点/人名/注音/钩子）在
              「项目 → 稿件体检」。
            </p>
          </div>
        </div>
      ) : null}
      <details className={styles.hint}>
        <summary>下载了 Ren'Py 项目包之后怎么跑？（三步）</summary>
        <ol>
          <li>
            去{" "}
            <a href="https://www.renpy.org/latest.html" target="_blank" rel="noreferrer">
              官网
            </a>{" "}
            下载安装免费的 Ren'Py（Windows / macOS / Linux 都有）。
          </li>
          <li>
            打开 Ren'Py，在「preferences」里把 Projects Directory 指向你解压出的工程文件夹的
            <strong>上一级目录</strong>——Ren'Py 会把工程列出来。
          </li>
          <li>在列表里选中你的工程，点「Launch Project」就能试玩。</li>
        </ol>
        <p>想让朋友也玩到：把解压后的整个文件夹发给他，他照上面三步做即可（不用注册本站）。</p>
      </details>
      {rpyStale && rpyPreview && (
        <p className={styles.hint}>
          剧本已修改，预览已过期 — 请重新点击「生成 .rpy」。
        </p>
      )}
      {!rpyPreview ? (
        <EmptyStage stamp="EXP" title="尚无导出预览" line={mascotLine("emptyExport")}>
          <button type="button" className={styles.primary} onClick={onGenerateRpy}>
            生成 .rpy
          </button>
        </EmptyStage>
      ) : (
        <pre className={styles.pre}>{rpyPreview}</pre>
      )}
    </>
  );
}
