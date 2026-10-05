import { Fragment, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { QAResult } from "../api/types";
import { Card, ErrorBanner, FieldMessage, PageHeader, Spinner, issueClass } from "../components/ui";
import { checkText } from "../lib/validation";

const EXAMPLES = [
  "What sintering temperature window gave the lowest ASR?",
  "How does coating thickness affect chromium poisoning and degradation?",
  "What are the FY26 cell-level performance targets?",
  "Have we tested LSCF-GDC cathodes with electrolytes thinner than 6 µm?",
];

interface Turn {
  question: string;
  result: QAResult;
}

/** Render [S1] markers as superscript links to the citation list. */
function AnswerText({ text, turn }: { text: string; turn: number }) {
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <p className="leading-relaxed">
      {parts.map((p, i) => {
        const m = p.match(/^\[(S\d+)\]$/);
        return m ? (
          <a key={i} href={`#t${turn}-${m[1]}`} className="mx-0.5 align-super text-[11px] font-semibold text-[var(--accent)]">
            {m[1]}
          </a>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        );
      })}
    </p>
  );
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const [attempted, setAttempted] = useState(false);
  const questionIssue = checkText(question, { label: "Question", min: 3, max: 2000, required: true });
  // Don't nag about an empty box until the user has tried to submit it.
  const shownIssue = question.trim() || attempted ? questionIssue : null;

  const ask = async (q: string) => {
    if (checkText(q, { label: "Question", min: 3, max: 2000, required: true })) return;
    q = q.trim();
    setBusy(true);
    setError(null);
    try {
      const result = await api.ask(q);
      setTurns((t) => [{ question: q, result }, ...t]);
      setQuestion("");
      setAttempted(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Program"
        title="Ask the program"
        subtitle="Answers draw only on approved experiments and internal reports, with a citation for every statement. When the record has no support, CellLoop says so rather than guessing."
      />
      <Card className="mb-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setAttempted(true);
            void ask(question);
          }}
          noValidate
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              className={`input ${issueClass(shownIssue)}`}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Have we tried this before? What happened?"
              aria-label="Question"
              aria-invalid={!!shownIssue || undefined}
              aria-describedby="question-msg"
            />
            <button className="btn btn-primary" disabled={busy || (attempted && !!questionIssue)}>
              Ask
            </button>
          </div>
          <div className="flex">
            <FieldMessage id="question-msg" issue={shownIssue} />
            {question.length > 1500 && <span className="muted mt-1 ml-auto text-xs tabular-nums">{question.length}/2000</span>}
          </div>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="btn btn-sm h-auto min-h-[26px] py-1 text-left whitespace-normal" onClick={() => ask(ex)} disabled={busy}>
              {ex}
            </button>
          ))}
        </div>
      </Card>
      <ErrorBanner error={error} />
      {busy && <Spinner label="Searching the program record…" />}
      <div className="space-y-4">
        {turns.map((t, ti) => {
          const turn = turns.length - ti;
          return (
            <Card key={turn}>
              <p className="mb-2 font-semibold">{t.question}</p>
              {t.result.answered ? (
                <>
                  <AnswerText text={t.result.answer} turn={turn} />
                  <h3 className="eyebrow mt-6 mb-2">Sources</h3>
                  <ol className="space-y-2">
                    {t.result.citations.map((c) => (
                      <li key={c.id} id={`t${turn}-${c.id}`} className="rounded-lg border border-[var(--border)] p-3 text-[13px]">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold text-[var(--accent)]">{c.id}</span>
                          {c.experiment_id ? (
                            <Link className="link" to={`/experiments/${c.experiment_id}`}>
                              {c.label}
                            </Link>
                          ) : (
                            <span>{c.label}</span>
                          )}
                          <span className="muted text-xs">relevance {c.similarity.toFixed(2)}</span>
                        </div>
                        <p className="muted mt-1 line-clamp-3 text-xs">{c.snippet}</p>
                      </li>
                    ))}
                  </ol>
                </>
              ) : (
                <div className="note note-warn">
                  <span aria-hidden>⚠ </span>
                  {t.result.answer}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </>
  );
}
