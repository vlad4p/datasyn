type Layer = "bronze" | "silver" | "gold" | "other";

type Props = { layer: Layer; label?: string };

const LABELS: Record<Layer, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
  other: "Other",
};

export function LayerBadge({ layer, label }: Props) {
  return (
    <span className={`layer-badge ${layer}`}>{label ?? LABELS[layer]}</span>
  );
}
