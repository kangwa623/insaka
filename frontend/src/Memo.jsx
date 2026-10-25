import { Fragment, useState } from "react";

const PLACEHOLDER = /\{\{\s*([a-z_:]+)\s*\}\}/g;

// The memo, section by section. The model wrote the words; every figure was inserted by
// code and is a button that opens the statement lines it was computed from.
export default function Memo({ c, me, busy, act, open }) {
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState("");
  if (!c.memo) return <p className="muted">No memo: the agent stopped this case.</p>;
  const canEdit = c.status === "awaiting_rm" && me?.roles.includes("rm");

  const openFigure = (span) => {
    const fig = c.figures[span.figure] || {};
    open({ title: span.text, label: fig.label, source: span.source, rows: span.rows,
           detail: fig.detail, figure: span.figure, score: c.score });
  };

  return (
    <article className="memo card">
      <div className="memo-head">
        <span className="muted">Drafted by Insaka ({c.memo.written_by.replace("llm:", "")}). The RM reviews; an approver decides.</span>
      </div>
      {c.escalations.length > 0 && (
        <div className="escalations">
          {c.escalations.map((e, i) => (
            <div key={i} className={`escalation ${e.stop ? "stop" : ""}`}>
              <b>{e.stop ? "Stopped for a person" : "Flagged for the RM"} ({e.kind.replace("_", " ")}):</b> {e.reason}
            </div>
          ))}
        </div>
      )}
      {c.memo.sections.map((s) => (
        <section key={s.title} className="memo-section">
          <h2>
            {s.title}
            {canEdit && editing !== s.title && (
              <button className="link" onClick={() => { setEditing(s.title); setDraft(s.text); }}>Edit</button>
            )}
          </h2>
          {editing === s.title ? (
            <div className="editor">
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} />
              <div className="buttons">
                <button className="primary" disabled={busy}
                        onClick={() => act("edit", { section: s.title, text: draft }, "Edit saved and logged").then(() => setEditing(null))}>
                  Save edit
                </button>
                <button className="secondary" onClick={() => setEditing(null)}>Cancel</button>
              </div>
            </div>
          ) : s.edited_by ? (
            <p>{s.text} <span className="edited">Edited by {s.edited_by}; figures in an edited section are no longer linked</span></p>
          ) : (
            <p><Linked section={s} openFigure={openFigure} /></p>
          )}
        </section>
      ))}
      <footer className="memo-foot">
        {countFigures(c.memo.sections)} figures in this memo, each linked to its source; 0 numbers without a source.
      </footer>
    </article>
  );
}

function Linked({ section, openFigure }) {
  const parts = section.template.split(PLACEHOLDER);
  let i = 0;
  return parts.map((part, k) => {
    if (k % 2 === 0) return <Fragment key={k}>{part}</Fragment>;
    const span = section.figures[i++];
    return (
      <button key={k} className="figure" title={`Show the source of ${span.text}`} onClick={() => openFigure(span)}>
        {span.text}
      </button>
    );
  });
}

function countFigures(sections) {
  return new Set(sections.flatMap((s) => s.figures.map((f) => f.figure))).size;
}
