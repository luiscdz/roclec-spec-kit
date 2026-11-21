import { STAGE_LABEL } from "../labels";
import { STAGES, type Stage } from "../types";

interface Props { counts: Record<Stage, number>; total: number; selected: Stage | null; onSelect: (stage: Stage | null) => void }

/** Stacked bar with visible counts, keyboard-focusable segments and an equivalent table. */
export function StageBar({ counts, total, selected, onSelect }: Props) {
  const present = STAGES.filter((s) => counts[s] > 0);
  const toggle = (stage: Stage) => onSelect(selected === stage ? null : stage);
  return (
    <div>
      {total === 0 ? (
        <div className="stagebar empty-bar" role="img" aria-label="Sin miembros">Esta release aún no tiene cambios asignados</div>
      ) : (
        <div className="stagebar" role="group" aria-label="Miembros por etapa">
          {present.map((stage) => (
            <button key={stage} type="button" className={`s-${stage}`} style={{ flex: counts[stage] }} aria-pressed={selected === stage}
              aria-label={`${STAGE_LABEL[stage]}: ${counts[stage]} de ${total}. Filtrar la tabla`} onClick={() => toggle(stage)}>
              {counts[stage]}
            </button>
          ))}
        </div>
      )}
      <div className="table-scroll legend" style={{ marginTop: 12 }}>
        <table>
          <caption className="visually-hidden">Conteo de miembros por etapa</caption>
          <thead><tr><th>Etapa</th><th className="num">Miembros</th><th className="num">Parte</th><th><span className="visually-hidden">Filtro</span></th></tr></thead>
          <tbody>
            {STAGES.filter((s) => counts[s] > 0 || ["approved", "in-progress", "verified", "integrated"].includes(s)).map((stage) => (
              <tr key={stage}>
                <td><span className={`swatch s-${stage}`} aria-hidden="true" />{STAGE_LABEL[stage]}</td>
                <td className="num">{counts[stage]}</td>
                <td className="num">{total ? Math.round((100 * counts[stage]) / total) : 0}%</td>
                <td>{counts[stage] > 0 ? <button type="button" aria-pressed={selected === stage} onClick={() => toggle(stage)}>{selected === stage ? "Quitar filtro" : "Filtrar"}</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
