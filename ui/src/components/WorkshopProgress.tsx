import { Check } from "lucide-react";

type WorkshopStage = "retrieve" | "rank" | "reason";

const stages: Array<{
  id: WorkshopStage;
  label: string;
  outcome: string;
}> = [
  { id: "retrieve", label: "Retrieve", outcome: "Candidate universe" },
  { id: "rank", label: "Rank", outcome: "Explainable order" },
  { id: "reason", label: "Reason", outcome: "Grounded answer" },
];

export function WorkshopProgress({
  active,
}: {
  active: WorkshopStage;
}) {
  const activeIndex = stages.findIndex((stage) => stage.id === active);

  return (
    <nav className="workshop-progress" aria-label="Retrieve, rank, reason progress">
      <ol>
        {stages.map((stage, index) => {
          const state = index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending";
          return (
            <li className={state} key={stage.id} aria-current={state === "active" ? "step" : undefined}>
              <span aria-hidden="true">
                {state === "complete" ? <Check size={13} /> : index + 1}
              </span>
              <div>
                <strong>{stage.label}</strong>
                <small>{stage.outcome}</small>
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
